import asyncio
import collections
import copy
import json
import os
import re
import shutil
import time

import decky

import xone_installer as installer
import xone_sysfs as xone

POLL_INTERVAL = 1.5
RELEASE_CACHE_SECONDS = 600
# An adapter (dongle) whose firmware was restarted without losing power, e.g. by
# reloading xone, can get stuck announcing clients that never finish connecting
# until every slot is taken. Only unplugging it clears that, so flag it when this
# many slots have been connecting for this long; a real connection takes seconds.
STUCK_CONNECTING = 4
STUCK_SECONDS = 20
# only release tags, never arbitrary git refs
RELEASE_TAG_RE = re.compile(r"^v\d+(\.\d+)*$")

DEFAULT_SETTINGS = {
    "notify_connect": True,
    "notify_low_battery": True,
    # per controller, keyed by client "key": {"brightness": int, "mode": int}
    "leds": {},
}


def _settings_path():
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")


def _attachment_label(client):
    return {"chatpad": "Chatpad", "headset": "Headset"}.get(client["kind"], "Accessory")


def _result(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        return {"ok": True}
    except (xone.XoneError, ValueError) as e:
        decky.logger.warning(str(e))
        return {"ok": False, "error": str(e)}


class Plugin:
    async def get_state(self):
        return self._snapshot()

    async def get_settings(self):
        return self.settings

    async def set_setting(self, key, value):
        if key not in DEFAULT_SETTINGS:
            return {"ok": False, "error": f"unknown setting {key}"}
        self.settings[key] = value
        self._save_settings()
        return {"ok": True}

    async def set_pairing(self, dongle_id, enabled):
        result = _result(xone.set_pairing, dongle_id, enabled)
        await self._poll()
        return result

    async def power_off(self, dongle_id, slot):
        result = _result(xone.power_off, dongle_id, slot)
        await self._poll()
        return result

    async def set_led(self, client_id, brightness=None, mode=None):
        """Apply to one controller and remember it for when that controller reconnects."""
        client = self._client(client_id)
        if not client or not client["led"]:
            return {"ok": False, "error": f"{client_id} has no LED"}
        if client["key"]:
            saved = self.settings["leds"].setdefault(client["key"], {})
            if brightness is not None:
                saved["brightness"] = int(brightness)
            if mode is not None:
                saved["mode"] = int(mode)
            self._save_settings()
        result = _result(xone.set_led, client["led"]["name"], brightness, mode)
        await self._poll()
        return result

    async def reset_led(self, client_id):
        """Forget the controller's LED setting and put it back to xone's default now."""
        client = self._client(client_id)
        if not client or not client["led"]:
            return {"ok": False, "error": f"{client_id} has no LED"}
        if self.settings["leds"].pop(client["key"], None) is not None:
            self._save_settings()
        result = _result(xone.set_led, client["led"]["name"], xone.LED_DEFAULT_BRIGHTNESS, xone.LED_DEFAULT_MODE)
        await self._poll()
        return result

    async def get_driver_status(self):
        status = await installer.status(installer.Runner(lambda _: None))
        return {**status, "latest": await self._latest_release(), "install": self._install_info()}

    async def check_for_updates(self):
        await self._latest_release(refresh=True)
        return await self.get_driver_status()

    async def start_install(self, tag=None):
        """Install `tag` (e.g. "v0.5.8" to reinstall), or the latest release."""
        if self._installing():
            return {"ok": False, "error": "An install is already running"}
        if tag is not None and not RELEASE_TAG_RE.match(tag):
            return {"ok": False, "error": f"Invalid xone version {tag}"}
        tag = tag or await self._latest_release(refresh=True)
        if not tag:
            return {"ok": False, "error": "Couldn't reach GitHub to find the latest xone release"}
        self.install_task = asyncio.get_event_loop().create_task(self._run_install(tag))
        return {"ok": True}

    async def _main(self):
        self.install_task = None
        self.install = None
        self.install_log = collections.deque(maxlen=300)
        self.release_cache = (0, None)
        self.settings = self._load_settings()
        self.state = None
        self.pairing_started = {}
        # (dongle id, adapter) -> when it was first seen still connecting
        self.connecting_since = {}
        self.snapshot_json = None
        self.poll_lock = asyncio.Lock()
        decky.logger.info("Xbox Wireless plugin started, xone driver loaded: %s", xone.driver_loaded())
        while True:
            try:
                await self._poll()
            except Exception:
                decky.logger.exception("poll failed")
            await asyncio.sleep(POLL_INTERVAL)

    async def _latest_release(self, refresh=False):
        fetched_at, tag = self.release_cache
        if refresh or not tag or time.time() - fetched_at > RELEASE_CACHE_SECONDS:
            try:
                tag = await asyncio.get_event_loop().run_in_executor(None, installer.fetch_latest_release)
                self.release_cache = (time.time(), tag)
            except Exception as e:
                decky.logger.warning("latest release lookup failed: %s", e)
        return tag

    def _installing(self):
        return self.install_task is not None and not self.install_task.done()

    def _install_info(self):
        return {**self.install, "log": list(self.install_log)} if self.install else None

    async def _run_install(self, tag):
        os.makedirs(decky.DECKY_PLUGIN_LOG_DIR, exist_ok=True)
        log_path = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, time.strftime("install-%Y%m%d-%H%M%S.log"))
        self.install_log.clear()
        self.install = {"tag": tag, "running": True, "error": None, "started": time.time(),
                        "finished": None, "log_file": log_path}
        await decky.emit("install_state", self._install_info())
        loop = asyncio.get_event_loop()

        with open(log_path, "w") as log_file:
            def log(line):
                self.install_log.append(line)
                log_file.write(line + "\n")
                log_file.flush()
                loop.create_task(decky.emit("install_log", line))

            workdir = decky.DECKY_PLUGIN_RUNTIME_DIR
            try:
                os.makedirs(workdir, exist_ok=True)
                shutil.chown(workdir, decky.DECKY_USER, decky.DECKY_USER)
                await installer.install(installer.Runner(log), tag, workdir, decky.DECKY_USER)
            except Exception as e:
                if not isinstance(e, installer.InstallError):
                    decky.logger.exception("install failed")
                log(f"Install failed: {e}")
                self.install["error"] = str(e)

        self.install["running"] = False
        self.install["finished"] = time.time()
        await decky.emit("install_state", self._install_info())
        if self.install["error"]:
            await self._notify("xone install failed", self.install["error"])
        else:
            await self._notify("xone installed", f"{tag} is ready")

    async def _unload(self):
        decky.logger.info("Xbox Wireless plugin unloaded")

    async def _poll(self):
        async with self.poll_lock:
            await self._poll_locked()

    async def _poll_locked(self):
        state = xone.read_state()
        self._mark_stuck(state)
        prev = self.state
        self.state = state
        if prev is not None:
            await self._handle_changes(prev, state)
        else:
            self._apply_led(self._led_clients(state))

        for dongle in state["dongles"]:
            if dongle["pairing"]:
                self.pairing_started.setdefault(dongle["id"], time.time())
            else:
                self.pairing_started.pop(dongle["id"], None)

        snapshot = self._snapshot()
        encoded = json.dumps(snapshot, sort_keys=True)
        if encoded != self.snapshot_json:
            self.snapshot_json = encoded
            await decky.emit("state", snapshot)

    def _mark_stuck(self, state):
        now = time.time()
        seen = {}
        for dongle in state["dongles"]:
            connecting = [d["adapter"] for d in dongle["devices"] if d["connecting"]]
            for adapter in connecting:
                key = (dongle["id"], adapter)
                seen[key] = self.connecting_since.get(key, now)
            stale = [a for a in connecting if now - seen[(dongle["id"], a)] >= STUCK_SECONDS]
            dongle["stuck"] = len(stale) >= STUCK_CONNECTING
        self.connecting_since = seen

    def _snapshot(self):
        return {
            **(self.state or xone.read_state()),
            "pairing_started": self.pairing_started,
            "pairing_timeout": xone.PAIRING_TIMEOUT,
        }

    async def _handle_changes(self, prev, state):
        old_devices = self._devices(prev)
        new_devices = self._devices(state)

        # reinstalling is the usual cause of this, so tell the user even mid-install
        was_stuck = {d["id"] for d in prev["dongles"] if d.get("stuck")}
        for dongle in state["dongles"]:
            if dongle["stuck"] and dongle["id"] not in was_stuck:
                await self._notify(f"{dongle['model']} stopped responding",
                                   "Unplug it, wait 10 seconds and plug it back in.")

        # reinstalling unloads the driver, which would look like every device leaving
        notify = not self._installing()

        if notify and self.settings["notify_connect"]:
            for key, device in new_devices.items():
                if key not in old_devices:
                    await self._notify("Controller connected", device["clients"][0]["name"])
            for key, device in old_devices.items():
                if key not in new_devices:
                    await self._notify("Controller disconnected", device["clients"][0]["name"])
            # chatpads/headsets plugged into or out of a controller that stays connected
            for key, device in new_devices.items():
                if key not in old_devices:
                    continue
                before, after = self._attachments(old_devices[key]), self._attachments(device)
                owner = device["clients"][0]["name"]
                for client_id in after.keys() - before.keys():
                    await self._notify(f"{_attachment_label(after[client_id])} connected", owner)
                for client_id in before.keys() - after.keys():
                    await self._notify(f"{_attachment_label(before[client_id])} disconnected", owner)

        if notify and self.settings["notify_low_battery"]:
            old_levels = self._battery_levels(prev)
            for client_id, (name, level) in self._battery_levels(state).items():
                if level == "Low" and old_levels.get(client_id, (None, None))[1] != "Low":
                    await self._notify("Battery low", name)

        old_leds = {c["led"]["name"] for c in self._led_clients(prev)}
        self._apply_led([c for c in self._led_clients(state) if c["led"]["name"] not in old_leds])

    def _apply_led(self, clients):
        for client in clients:
            saved = self.settings["leds"].get(client["key"])
            if saved:
                _result(xone.set_led, client["led"]["name"], saved.get("brightness"), saved.get("mode"))

    async def _notify(self, title, body):
        await decky.emit("notify", title, body)

    @staticmethod
    def _all_devices(state):
        for dongle in state["dongles"]:
            for device in dongle["devices"]:
                yield dongle["id"], device
        for device in state["wired"]:
            yield device["interface"], device

    @classmethod
    def _devices(cls, state):
        """Fully connected devices, keyed so a reused adapter ID still counts as new."""
        return {
            (parent, d["adapter"], d["clients"][0]["id"]): d
            for parent, d in cls._all_devices(state)
            if d["clients"] and not d["partial"]
        }

    @staticmethod
    def _attachments(device):
        """Real (non-phantom) attachments of a device, by client id."""
        return {c["id"]: c for c in device["clients"][1:] if not c["phantom"]}

    @classmethod
    def _battery_levels(cls, state):
        return {
            c["id"]: (c["name"], c["battery"]["level"])
            for _, d in cls._all_devices(state)
            for c in d["clients"]
            if c["battery"]
        }

    @classmethod
    def _led_clients(cls, state):
        return [c for _, d in cls._all_devices(state) for c in d["clients"] if c["led"]]

    def _client(self, client_id):
        for _, device in self._all_devices(self.state or xone.read_state()):
            for client in device["clients"]:
                if client["id"] == client_id:
                    return client
        return None

    def _load_settings(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        try:
            with open(_settings_path()) as f:
                settings.update({k: v for k, v in json.load(f).items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError):
            pass
        return settings

    def _save_settings(self):
        try:
            os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
            with open(_settings_path(), "w") as f:
                json.dump(self.settings, f, indent=2)
        except OSError:
            decky.logger.exception("failed to save settings")

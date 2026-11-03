"""
Game/chat balance for headsets with a dial (patches/xone-chat-mix.patch).

xone reports the dial in sysfs as 0-100; this turns it into stream volumes on the
headset's PipeWire sink, like an Xbox does: towards one end chat apps fade out,
towards the other everything else does.

PipeWire saves stream volumes per app, so a faded-out Discord would come back
faded out next time. The volume each app had before fading is kept on disk and
put back once it plays somewhere else, or the dial or plugin is turned off.

This module has no decky dependency so it can be tested against a fake pactl.
"""

import asyncio
import json
import os
import pwd
import select
import threading

# the dial turned forward (0) is all game, back (100) all chat
DIAL_CENTER = 50
# how far the faded side drops just before the end of the dial, which mutes it.
# Even steps in dB sound even; pactl volumes are cubic, so a straight line in
# them is near silent for the last third.
FADE_DB = 30

# matched against the app's name and binary, lower case
CHAT_APPS = (
    "discord",
    "vesktop",
    "webcord",
    "legcord",
    "armcord",
    "teamspeak",
    "ts3client",
    "mumble",
    "webrtc voiceengine",
)
# voice chat in the Steam client; exact, as games' names can contain "steam".
# Not steamwebhelper: that's the Steam UI's own sounds.
CHAT_BINARIES = ("steam",)
CHAT_ROLES = ("communication", "phone")

# volumes pactl reads back can be off by a little from what was set
VOLUME_SLACK = 700
# PA_VOLUME_NORM, 100%
FULL_VOLUME = 65536


def mix(dial):
    """(game, chat) volume factors for a dial position."""
    dial = max(0, min(int(dial), 100))
    if dial <= DIAL_CENTER:
        return 1.0, _fade((DIAL_CENTER - dial) / DIAL_CENTER)
    return _fade((dial - DIAL_CENTER) / (100 - DIAL_CENTER)), 1.0


def _fade(amount):
    """Volume factor for fading `amount` (0-1) of the way to the end."""
    if amount >= 1:
        return 0.0
    # pactl volume = amplitude ** (1/3), so dB = 60 * log10(volume)
    return 10 ** (-FADE_DB * amount / 60)


def is_chat(props):
    if props.get("media.role", "").lower() in CHAT_ROLES:
        return True
    binary = props.get("application.process.binary", "").lower()
    if binary in CHAT_BINARIES:
        return True
    names = (props.get("application.name", "").lower(), binary)
    return any(app in name for name in names for app in CHAT_APPS)


def _volume(stream):
    values = [ch["value"] for ch in (stream.get("volume") or {}).values()]
    return max(values) if values else None


def _close(a, b):
    return abs(a - b) <= VOLUME_SLACK


class Pactl:
    """Runs pactl as the desktop user, against their PipeWire."""

    def __init__(self, user):
        info = pwd.getpwnam(user)
        self.uid, self.gid = info.pw_uid, info.pw_gid
        # a clean env: decky's own LD_LIBRARY_PATH breaks system binaries
        self.env = {
            "HOME": info.pw_dir,
            "PATH": "/usr/bin:/bin",
            "XDG_RUNTIME_DIR": f"/run/user/{info.pw_uid}",
        }

    def _spawn(self, *args, **kwargs):
        return asyncio.create_subprocess_exec(
            "pactl", *args, env=self.env, user=self.uid, group=self.gid,
            stdin=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **kwargs,
        )

    async def run(self, *args):
        proc = await self._spawn(*args, stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        if proc.returncode:
            raise OSError(f"pactl {args[0]} failed ({proc.returncode})")
        return out.decode()

    async def list(self, kind):
        return json.loads(await self.run("-f", "json", "list", kind) or "[]")

    async def set_volume(self, index, volume):
        await self.run("set-sink-input-volume", str(index), str(int(volume)))

    def subscribe(self):
        return self._spawn("subscribe", stdout=asyncio.subprocess.PIPE)


class ChatMixer:
    def __init__(self, pactl, saved_path, log):
        self.pactl = pactl
        self.saved_path = saved_path
        self.log = log
        # client id -> dial position, for headsets being watched
        self.dials = {}
        self.watchers = {}
        # sink-input index -> {"base": volume before fading, "set": what we set, "app": restore id}
        self.streams = {}
        # restore id -> {"base", "set"}, for apps currently faded
        self.saved = self._load()
        self.subscriber = None
        self.subscribe_task = None
        self.apply_task = None
        self.dirty = False

    def update(self, headsets):
        """Watch these {client id: chat_mix path}, and stop watching the rest."""
        for client_id in self.watchers.keys() - headsets.keys():
            self.watchers.pop(client_id).set()
            self.dials.pop(client_id, None)
            self.schedule()
        for client_id, path in headsets.items():
            if client_id not in self.watchers:
                stop = threading.Event()
                self.watchers[client_id] = stop
                loop = asyncio.get_event_loop()
                threading.Thread(target=self._watch, args=(loop, client_id, path, stop), daemon=True).start()
        if self.watchers and not self.subscribe_task:
            self.subscribe_task = asyncio.get_event_loop().create_task(self._subscribe())
        # an app faded when the plugin last stopped still needs putting back
        if self.saved and not self.watchers:
            self.schedule()

    async def stop(self):
        self.update({})
        if self.subscribe_task:
            self.subscribe_task.cancel()
        if self.subscriber and self.subscriber.returncode is None:
            self.subscriber.kill()
        while self.apply_task and not self.apply_task.done():
            await self.apply_task

    def _watch(self, loop, client_id, path, stop):
        """Thread: xone wakes poll() on the attribute when the dial moves."""
        try:
            with open(path, "rb", buffering=0) as f:
                poller = select.poll()
                poller.register(f, select.POLLPRI | select.POLLERR)
                while not stop.is_set():
                    f.seek(0)
                    value = int(f.read())
                    loop.call_soon_threadsafe(self._dial, client_id, value, stop)
                    poller.poll(1000)
        except (OSError, ValueError):
            pass

    def _dial(self, client_id, value, stop):
        if stop.is_set() or self.dials.get(client_id) == value:
            return
        self.dials[client_id] = value
        self.schedule()

    async def _subscribe(self):
        """New streams and streams moving between sinks need their volume set."""
        try:
            self.subscriber = await self.pactl.subscribe()
            async for line in self.subscriber.stdout:
                if b"sink" in line and b"'remove'" not in line:
                    self.schedule()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log.warning("pactl subscribe failed: %s", e)
        finally:
            self.subscribe_task = None
            if self.subscriber and self.subscriber.returncode is None:
                self.subscriber.kill()

    def schedule(self):
        if self.apply_task and not self.apply_task.done():
            self.dirty = True
        else:
            self.apply_task = asyncio.get_event_loop().create_task(self._apply_loop())

    async def _apply_loop(self):
        self.dirty = True
        while self.dirty:
            self.dirty = False
            try:
                await self.apply()
            except Exception as e:
                self.log.warning("chat mix failed: %s", e)

    async def apply(self):
        factors = {}
        if self.dials:
            for sink in await self.pactl.list("sinks"):
                card = sink.get("properties", {}).get("alsa.long_card_name", "")
                for client_id, dial in self.dials.items():
                    # "Microsoft Xbox Headset at gip1.0"
                    if card.endswith(f" at {client_id}"):
                        factors[sink["index"]] = mix(dial)

        live = set()
        for stream in await self.pactl.list("sink-inputs"):
            volume = _volume(stream)
            if volume is None:
                continue
            index = stream["index"]
            props = stream.get("properties", {})
            restore_id = props.get("module-stream-restore.id")
            # Vesktop and the Steam UI are both "Chromium" to PipeWire
            app = f"{restore_id}|{props.get('application.process.binary', '')}" if restore_id else None
            tracked = self.streams.get(index)
            if tracked is None and restore_id and self._restored_fade(restore_id, volume):
                # PipeWire gave a new stream a volume we faded something to: the
                # app was closed or the plugin stopped mid-fade, or another app
                # with the same name was faded
                base = self.saved.get(app, {}).get("base", FULL_VOLUME)
                tracked = {"base": base, "set": volume, "app": app}

            if stream["sink"] not in factors:
                if tracked and _close(volume, tracked["set"]):
                    await self.pactl.set_volume(index, tracked["base"])
                self.streams.pop(index, None)
                self.saved.pop(app, None)
                continue

            game, chat = factors[stream["sink"]]
            factor = chat if is_chat(props) else game
            if not tracked:
                base = volume
            elif _close(volume, tracked["set"]):
                base = tracked["base"]
            else:
                # someone changed its volume: keep what they set at this mix
                base = volume / factor if factor else volume
            target = round(base * factor)
            if not _close(volume, target):
                await self.pactl.set_volume(index, target)
            entry = {"base": round(base), "set": target, "app": app}
            self.streams[index] = entry
            live.add(index)
            if app:
                if _close(entry["base"], target):
                    self.saved.pop(app, None)
                else:
                    self.saved[app] = {"base": entry["base"], "set": target}

        for index in self.streams.keys() - live:
            del self.streams[index]
        self._save()

    def _restored_fade(self, restore_id, volume):
        return any(
            key.rpartition("|")[0] == restore_id and _close(volume, entry["set"])
            for key, entry in self.saved.items()
        )

    def _load(self):
        try:
            with open(self.saved_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            if os.path.exists(self.saved_path) or self.saved:
                os.makedirs(os.path.dirname(self.saved_path), exist_ok=True)
                with open(self.saved_path, "w") as f:
                    json.dump(self.saved, f)
        except OSError as e:
            self.log.warning("failed to save chat mix volumes: %s", e)

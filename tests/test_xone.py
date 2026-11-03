import asyncio
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
sys.path.insert(0, ROOT)

import xone_sysfs as xone  # noqa: E402

ACTIVE_CLIENTS = """Active clients: {count}
[00]{s0}\t[08]
[01]{s1}\t[09]
[02]\t[10]
[03]\t[11]
[04]\t[12]
[05]\t[13]
[06]\t[14]
[07]\t[15]
"""


class FakeSysfs:
    """Builds a tree shaped like the one xone creates under /sys."""

    def __init__(self, root):
        self.root = root
        self.usb = os.path.join(root, "devices/pci0000:00/usb1/1-2")
        self.intf = os.path.join(self.usb, "1-2:1.0")
        os.makedirs(os.path.join(root, "bus/xone-gip/devices"))
        os.makedirs(os.path.join(root, "bus/xone-gip/drivers/xone-gip-gamepad"))
        os.makedirs(os.path.join(root, "class/leds"))
        drv = os.path.join(root, "bus/usb/drivers/xone-dongle")
        os.makedirs(drv)
        os.makedirs(self.intf)
        self.write(os.path.join(drv, "bind"), "")
        os.symlink(self.intf, os.path.join(drv, "1-2:1.0"))
        self.write(os.path.join(self.usb, "idProduct"), "02fe")
        self.write(os.path.join(self.usb, "serial"), "ABC123")
        self.write(os.path.join(self.intf, "pairing"), "0")
        self.write(os.path.join(self.intf, "poweroff"), "")
        self.set_slots([])

    @staticmethod
    def write(path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def read(self, path):
        with open(os.path.join(self.root, path)) as f:
            return f.read()

    def set_slots(self, slots):
        self.write(os.path.join(self.intf, "active_clients"), ACTIVE_CLIENTS.format(
            count=len(slots),
            s0="*" if 0 in slots else "",
            s1="*" if 1 in slots else "",
        ))

    def add_client(self, adapter, client=0, gip_class="Windows.Xbox.Input.Gamepad",
                   level="Normal", status="Discharging", led=True, usb_id=None, serial=None,
                   chat_mix=None):
        name = f"gip{adapter}.{client}"
        cdir = os.path.join(self.intf, f"gip{adapter}", name)
        self.write(os.path.join(cdir, "uevent"), f"DRIVER=x\nMODALIAS=gip:{gip_class}\n")
        os.symlink(os.path.join(self.root, "bus/xone-gip/drivers/xone-gip-gamepad"),
                   os.path.join(cdir, "driver"))
        psy = os.path.join(cdir, "power_supply", name)
        self.write(os.path.join(psy, "status"), status + "\n")
        self.write(os.path.join(psy, "capacity_level"), level + "\n")
        self.write(os.path.join(psy, "model_name"), "Microsoft Xbox Controller\n")
        if usb_id:
            id_dir = os.path.join(cdir, "input", f"input{adapter}{client}", "id")
            self.write(os.path.join(id_dir, "vendor"), usb_id[0] + "\n")
            self.write(os.path.join(id_dir, "product"), usb_id[1] + "\n")
            self.write(os.path.join(id_dir, "version"), (usb_id[2] if len(usb_id) > 2 else "0101") + "\n")
            self.write(os.path.join(os.path.dirname(id_dir), "uniq"), (serial or "") + "\n")
        if chat_mix is not None:
            self.write(os.path.join(cdir, "chat_mix"), f"{chat_mix}\n")
            os.makedirs(os.path.join(self.root, "bus/xone-gip/devices"), exist_ok=True)
        if led:
            led_name = f"{name}:white:status"
            ldir = os.path.join(cdir, "leds", led_name)
            self.write(os.path.join(ldir, "brightness"), "20\n")
            self.write(os.path.join(ldir, "max_brightness"), "50\n")
            self.write(os.path.join(ldir, "mode"), "1\n")
            os.symlink(ldir, os.path.join(self.root, "class/leds", led_name))
        return name

    def remove_adapter(self, adapter):
        import shutil
        for led in os.listdir(os.path.join(self.root, "class/leds")):
            if led.startswith(f"gip{adapter}."):
                os.unlink(os.path.join(self.root, "class/leds", led))
        shutil.rmtree(os.path.join(self.intf, f"gip{adapter}"))


class SysfsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fs = FakeSysfs(self.tmp.name)
        xone.SYSFS_ROOT = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_driver(self):
        xone.SYSFS_ROOT = os.path.join(self.tmp.name, "missing")
        self.assertEqual(xone.read_state(), {"driver_loaded": False, "dongles": [], "wired": []})

    def test_empty_dongle(self):
        state = xone.read_state()
        self.assertTrue(state["driver_loaded"])
        [dongle] = state["dongles"]
        self.assertEqual(dongle["id"], "1-2:1.0")
        self.assertEqual(dongle["model"], "Xbox Wireless Adapter")
        self.assertEqual(dongle["serial"], "ABC123")
        self.assertFalse(dongle["pairing"])
        self.assertEqual(dongle["devices"], [])

    def test_devices_with_attachment(self):
        self.fs.add_client(3, level="High")
        self.fs.add_client(3, 1, gip_class="Windows.Xbox.Input.Headset", led=False)
        self.fs.add_client(5, level="Unknown", status="Not charging")
        self.fs.set_slots([0, 1])
        [dongle] = xone.read_state()["dongles"]
        self.assertEqual(dongle["active_clients"], 2)
        first, second = dongle["devices"]
        self.assertEqual((first["adapter"], first["slot"]), ("gip3", 0))
        self.assertEqual((second["adapter"], second["slot"]), ("gip5", 1))
        gamepad, headset = first["clients"]
        self.assertEqual(gamepad["kind"], "gamepad")
        self.assertEqual(gamepad["driver"], "xone-gip-gamepad")
        self.assertEqual(gamepad["battery"], {"status": "Discharging", "level": "High", "no_battery": False})
        self.assertEqual(gamepad["led"]["name"], "gip3.0:white:status")
        self.assertEqual(headset["kind"], "headset")
        self.assertIsNone(headset["led"])
        self.assertTrue(second["clients"][0]["battery"]["no_battery"])

    def test_gamepad_model_from_product_id(self):
        self.fs.add_client(1, usb_id=("045e", "0b00"))
        self.fs.add_client(2, usb_id=("045e", "ffff"))
        self.fs.add_client(3, usb_id=("0e6f", "0b00"))
        self.fs.set_slots([0, 1])
        names = [d["clients"][0]["name"] for d in xone.read_state()["dongles"][0]["devices"]]
        self.assertEqual(names, [
            "Xbox Elite Series 2 Controller",
            "Microsoft Xbox Controller",
            "Microsoft Xbox Controller",
        ])

    def test_phantom_chatpad(self):
        # IDs captured from an Elite Series 2 with a real chatpad plugged in
        self.fs.add_client(0, usb_id=("045e", "0b00", "0518"))
        self.fs.add_client(0, 1, gip_class="Windows.Xbox.Input.Chatpad", led=False, usb_id=("045e", "0b02", "0518"))
        self.fs.add_client(0, 2, gip_class="Windows.Xbox.Input.Chatpad", led=False, usb_id=("045e", "02f3", "0101"))
        self.fs.set_slots([0])
        [device] = xone.read_state()["dongles"][0]["devices"]
        self.assertEqual([c["phantom"] for c in device["clients"]], [False, True, False])

    def test_slot_mapping_withheld_when_ambiguous(self):
        self.fs.add_client(3)
        self.fs.set_slots([0, 1])
        [device] = xone.read_state()["dongles"][0]["devices"]
        self.assertIsNone(device["slot"])

    def test_connecting_adapter(self):
        os.makedirs(os.path.join(self.fs.intf, "gip7"))
        [device] = xone.read_state()["dongles"][0]["devices"]
        self.assertTrue(device["connecting"])

    def test_writes(self):
        self.fs.add_client(3)
        xone.set_pairing("1-2:1.0", True)
        self.assertEqual(self.fs.read("devices/pci0000:00/usb1/1-2/1-2:1.0/pairing"), "1")
        xone.power_off("1-2:1.0", -1)
        self.assertEqual(self.fs.read("devices/pci0000:00/usb1/1-2/1-2:1.0/poweroff"), "-1")
        xone.set_led("gip3.0:white:status", brightness=99, mode=3)
        self.assertEqual(self.fs.read("class/leds/gip3.0:white:status/brightness"), "50")
        self.assertEqual(self.fs.read("class/leds/gip3.0:white:status/mode"), "3")

    def test_rejects_bad_input(self):
        with self.assertRaises(xone.XoneError):
            xone.set_pairing("../../etc", True)
        with self.assertRaises(xone.XoneError):
            xone.power_off("1-2:1.0", 16)
        with self.assertRaises(xone.XoneError):
            xone.set_led("input0::capslock", brightness=1)
        with self.assertRaises(xone.XoneError):
            xone.set_led("gip3.0/../../x", brightness=1)


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fs = FakeSysfs(os.path.join(self.tmp.name, "sys"))
        xone.SYSFS_ROOT = self.fs.root
        self.events = []

        async def emit(event, *args):
            self.events.append((event, *args))

        import logging
        sys.modules["decky"] = types.SimpleNamespace(
            emit=emit,
            logger=logging.getLogger("test"),
            DECKY_PLUGIN_SETTINGS_DIR=os.path.join(self.tmp.name, "settings"),
        )
        self.plugin_settings_dir = os.path.join(self.tmp.name, "settings")
        import importlib
        import main
        importlib.reload(main)
        self.plugin = main.Plugin()
        self.plugin.settings = self.plugin._load_settings()
        self.plugin.state = None
        self.plugin.pairing_started = {}
        self.plugin.connecting_since = {}
        self.plugin.snapshot_json = None
        self.plugin.poll_lock = asyncio.Lock()
        self.plugin.install_task = None
        self.chat_mix_headsets = []
        self.plugin.chat_mixer = types.SimpleNamespace(update=self.chat_mix_headsets.append)

    def tearDown(self):
        self.tmp.cleanup()

    def poll(self):
        self.events.clear()
        asyncio.run(self.plugin._poll())
        return [e for e in self.events if e[0] == "notify"]

    def led(self, name, attr):
        return self.fs.read(f"class/leds/{name}:white:status/{attr}").strip()

    def test_notifications(self):
        self.assertEqual(self.poll(), [])
        self.assertEqual(self.events[0][0], "state")
        self.assertEqual(self.poll(), [])
        self.assertEqual(self.events, [], "unchanged state should not re-emit")

        self.fs.add_client(0)
        self.fs.set_slots([0])
        self.assertEqual(self.poll(), [("notify", "Controller connected", "Microsoft Xbox Controller")])

        self.fs.write(os.path.join(self.fs.intf, "gip0/gip0.0/power_supply/gip0.0/capacity_level"), "Low")
        self.assertEqual(self.poll(), [("notify", "Battery low", "Microsoft Xbox Controller")])
        self.assertEqual(self.poll(), [])

        self.fs.remove_adapter(0)
        self.fs.set_slots([])
        self.assertEqual(self.poll(), [("notify", "Controller disconnected", "Microsoft Xbox Controller")])

    def test_attachment_notifications(self):
        elite = ("045e", "0b00", "0518")
        self.fs.add_client(0, usb_id=elite)
        self.fs.add_client(0, 1, gip_class="Windows.Xbox.Input.Chatpad", led=False, usb_id=("045e", "0b02", "0518"))
        self.fs.set_slots([0])
        self.assertEqual(self.poll(), [], "first poll establishes state")
        self.assertEqual(self.poll(), [], "phantom chatpad is never announced")

        self.fs.add_client(0, 2, gip_class="Windows.Xbox.Input.Chatpad", led=False, usb_id=("045e", "02f3", "0101"))
        self.assertEqual(self.poll(), [("notify", "Chatpad connected", "Xbox Elite Series 2 Controller")])

        import shutil
        shutil.rmtree(os.path.join(self.fs.intf, "gip0/gip0.2"))
        self.assertEqual(self.poll(), [("notify", "Chatpad disconnected", "Xbox Elite Series 2 Controller")])

        self.plugin.settings["notify_connect"] = False
        self.fs.add_client(0, 2, gip_class="Windows.Xbox.Input.Chatpad", led=False, usb_id=("045e", "02f3", "0101"))
        self.assertEqual(self.poll(), [], "follows the connect/disconnect setting")

    def test_partial_removal_is_not_a_new_device(self):
        elite = ("045e", "0b00", "0518")
        self.fs.add_client(0, usb_id=elite)
        self.fs.add_client(0, 1, gip_class="Windows.Xbox.Input.Chatpad", led=False, usb_id=("045e", "0b02", "0518"))
        self.fs.set_slots([0])
        self.poll()

        # xone has removed the controller but not yet its chatpad
        import shutil
        os.unlink(os.path.join(self.fs.root, "class/leds/gip0.0:white:status"))
        shutil.rmtree(os.path.join(self.fs.intf, "gip0/gip0.0"))
        [device] = xone.read_state()["dongles"][0]["devices"]
        self.assertTrue(device["partial"])
        self.assertEqual(self.poll(), [("notify", "Controller disconnected", "Xbox Elite Series 2 Controller")])

        self.fs.remove_adapter(0)
        self.fs.set_slots([])
        self.assertEqual(self.poll(), [], "chatpad leaving must not look like another device")

    def test_led_saved_per_controller(self):
        elite = ("045e", "0b00", "0518")
        self.fs.add_client(0, usb_id=elite, serial="SERIAL-A")
        self.fs.add_client(1, usb_id=elite, serial="SERIAL-B")
        self.fs.set_slots([0, 1])
        self.poll()

        self.assertEqual(asyncio.run(self.plugin.set_led("gip0.0", 5, 3)), {"ok": True})
        self.assertEqual((self.led("gip0.0", "brightness"), self.led("gip0.0", "mode")), ("5", "3"))
        self.assertEqual(self.led("gip1.0", "brightness"), "20", "other controller untouched")
        self.assertEqual(self.plugin.settings["leds"], {"serial:SERIAL-A": {"brightness": 5, "mode": 3}})

        # controller A reconnects on a different adapter: its setting follows the serial
        self.fs.remove_adapter(0)
        self.fs.set_slots([1])
        self.poll()
        self.fs.add_client(2, usb_id=elite, serial="SERIAL-A")
        self.fs.set_slots([0, 1])
        self.poll()
        self.assertEqual((self.led("gip2.0", "brightness"), self.led("gip2.0", "mode")), ("5", "3"))
        self.assertEqual(self.led("gip1.0", "brightness"), "20")

        # reset forgets it and restores xone's default immediately
        self.assertEqual(asyncio.run(self.plugin.reset_led("gip2.0")), {"ok": True})
        self.assertEqual((self.led("gip2.0", "brightness"), self.led("gip2.0", "mode")), ("20", "1"))
        self.assertEqual(self.plugin.settings["leds"], {})

        self.assertFalse(asyncio.run(self.plugin.set_led("gip9.0", 5))["ok"])

    def test_old_global_led_settings_dropped(self):
        os.makedirs(self.plugin_settings_dir, exist_ok=True)
        with open(os.path.join(self.plugin_settings_dir, "settings.json"), "w") as f:
            f.write('{"led_brightness": 20, "led_mode": 1, "notify_connect": false}')
        settings = self.plugin._load_settings()
        self.assertNotIn("led_brightness", settings)
        self.assertEqual(settings["leds"], {})
        self.assertFalse(settings["notify_connect"])

    def test_stuck_adapter(self):
        import main
        clock = [1000.0]
        main.time = types.SimpleNamespace(time=lambda: clock[0])
        # clients announced but never finishing the handshake
        for adapter in range(main.STUCK_CONNECTING):
            os.makedirs(os.path.join(self.fs.intf, f"gip{adapter}"))
        self.assertEqual(self.poll(), [])
        clock[0] += main.STUCK_SECONDS - 1
        self.assertEqual(self.poll(), [])
        self.assertFalse(self.plugin.state["dongles"][0]["stuck"])

        clock[0] += 1
        self.assertEqual(self.poll(), [("notify", "Xbox Wireless Adapter stopped responding",
                                        "Unplug it, wait 10 seconds and plug it back in.")])
        self.assertTrue(self.plugin.state["dongles"][0]["stuck"])
        self.assertEqual(self.poll(), [], "only told once")

        # replugged: the stale adapters are gone
        for adapter in range(main.STUCK_CONNECTING):
            os.rmdir(os.path.join(self.fs.intf, f"gip{adapter}"))
        self.poll()
        self.assertFalse(self.plugin.state["dongles"][0]["stuck"])

    def test_chat_mix_headsets_watched(self):
        self.fs.set_slots([0, 1])
        self.fs.add_client(0)
        self.fs.add_client(1, gip_class="Windows.Xbox.Input.Headset", led=False, chat_mix=30)
        self.poll()
        self.assertEqual(self.plugin.state["dongles"][0]["devices"][1]["clients"][0]["chat_mix"], 30)
        self.assertIsNone(self.plugin.state["dongles"][0]["devices"][0]["clients"][0]["chat_mix"])
        self.assertEqual(self.chat_mix_headsets[-1], {"gip1.0": xone.chat_mix_path("gip1.0")})

        asyncio.run(self.plugin.set_setting("chat_mix", False))
        self.assertEqual(self.chat_mix_headsets[-1], {})

    def test_pairing_tracking(self):
        res = asyncio.run(self.plugin.set_pairing("1-2:1.0", True))
        self.assertEqual(res, {"ok": True})
        self.assertIn("1-2:1.0", self.plugin.pairing_started)
        res = asyncio.run(self.plugin.set_pairing("nope", True))
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()

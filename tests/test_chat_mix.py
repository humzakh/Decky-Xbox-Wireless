import asyncio
import logging
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py_modules"))

import chat_mix  # noqa: E402

FULL = 65536
HEADSET_SINK = 2
SPEAKERS = 1
# what the faded side gets halfway from the middle to the end
HALF_FADED = round(FULL * chat_mix.mix(75)[0])


class FakePactl:
    def __init__(self):
        self.sinks = [
            {"index": SPEAKERS, "properties": {"alsa.long_card_name": "HDA ATI HDMI at 0x60b00000 irq 73"}},
            {"index": HEADSET_SINK, "properties": {"alsa.long_card_name": "Microsoft Xbox Headset at gip1.0"}},
        ]
        self.inputs = {}

    def play(self, index, name, sink=HEADSET_SINK, volume=FULL, binary=None):
        self.inputs[index] = {
            "index": index,
            "sink": sink,
            "volume": {"front-left": {"value": volume}, "front-right": {"value": volume}},
            "properties": {
                "application.name": name,
                "application.process.binary": binary or name.lower(),
                "module-stream-restore.id": f"sink-input-by-application-name:{name}",
            },
        }

    def volume(self, index):
        return self.inputs[index]["volume"]["front-left"]["value"]

    def set(self, index, volume):
        for ch in self.inputs[index]["volume"].values():
            ch["value"] = volume

    async def list(self, kind):
        return self.sinks if kind == "sinks" else list(self.inputs.values())

    async def set_volume(self, index, volume):
        self.set(index, volume)


class ChatMixTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.path.join(self.tmp.name, "settings", "volumes.json")
        self.pactl = FakePactl()
        self.mixer = self.new_mixer()

    def tearDown(self):
        self.tmp.cleanup()

    def new_mixer(self):
        return chat_mix.ChatMixer(self.pactl, self.saved, logging.getLogger("test"))

    def dial(self, value, mixer=None):
        mixer = mixer or self.mixer
        mixer.dials = {"gip1.0": value} if value is not None else {}
        asyncio.run(mixer.apply())

    def test_mix(self):
        self.assertEqual(chat_mix.mix(50), (1.0, 1.0))
        self.assertEqual(chat_mix.mix(0), (1.0, 0.0))
        self.assertEqual(chat_mix.mix(100), (0.0, 1.0))
        game, chat = chat_mix.mix(75)
        self.assertEqual(chat, 1.0)
        self.assertAlmostEqual(game, 10 ** (-chat_mix.FADE_DB / 2 / 60))
        self.assertEqual(chat_mix.mix(25), (1.0, game))
        # still audible right before the end, not a straight line to silence
        self.assertGreater(chat_mix.mix(98)[0], 0.3)

    def test_is_chat(self):
        self.assertTrue(chat_mix.is_chat({"application.name": "Discord"}))
        self.assertTrue(chat_mix.is_chat({"application.process.binary": "steam"}))
        self.assertTrue(chat_mix.is_chat({"media.role": "Communication"}))
        self.assertFalse(chat_mix.is_chat({"application.process.binary": "steam_game_launcher"}))
        self.assertFalse(chat_mix.is_chat({"application.name": "Chromium", "application.process.binary": "steamwebhelper"}))
        self.assertFalse(chat_mix.is_chat({"application.name": "Hades"}))

    def test_fades_only_on_the_headset(self):
        self.pactl.play(1, "Hades")
        self.pactl.play(2, "Discord")
        self.pactl.play(3, "Music", sink=SPEAKERS)
        self.dial(25)
        self.assertEqual(self.pactl.volume(1), FULL)
        self.assertEqual(self.pactl.volume(2), HALF_FADED)
        self.assertEqual(self.pactl.volume(3), FULL)
        self.dial(100)
        self.assertEqual(self.pactl.volume(1), 0)
        self.assertEqual(self.pactl.volume(2), FULL)

    def test_restored_when_moved_or_headset_gone(self):
        self.pactl.play(1, "Hades")
        self.dial(75)
        self.assertEqual(self.pactl.volume(1), HALF_FADED)
        self.pactl.inputs[1]["sink"] = SPEAKERS
        self.dial(75)
        self.assertEqual(self.pactl.volume(1), FULL)

        self.pactl.inputs[1]["sink"] = HEADSET_SINK
        self.dial(75)
        self.dial(None)
        self.assertEqual(self.pactl.volume(1), FULL)

    def test_own_volume_kept(self):
        self.pactl.play(1, "Hades", volume=FULL // 2)
        self.dial(75)
        self.assertEqual(self.pactl.volume(1), round(FULL // 2 * chat_mix.mix(75)[0]))
        # someone sets it mid-fade: that's the volume at this mix
        self.pactl.set(1, FULL // 2)
        self.dial(75)
        self.assertEqual(self.pactl.volume(1), FULL // 2)
        self.dial(50)
        self.assertAlmostEqual(self.pactl.volume(1), FULL // 2 / chat_mix.mix(75)[0], delta=1)

    def test_apps_sharing_a_name_kept_apart(self):
        # Vesktop and the Steam UI both play as "Chromium"
        self.pactl.play(1, "Chromium", binary="vesktop.bin")
        self.pactl.play(2, "Chromium", binary="steamwebhelper")
        self.dial(0)
        self.assertEqual(self.pactl.volume(1), 0)
        self.assertEqual(self.pactl.volume(2), FULL)
        self.assertEqual(list(self.mixer.saved), ["sink-input-by-application-name:Chromium|vesktop.bin"])

    def test_fade_restored_onto_an_app_sharing_the_name(self):
        # PipeWire saves volumes by app name, so a new Vesktop stream gets the
        # volume the Steam UI was faded to
        self.pactl.play(1, "Chromium", binary="steamwebhelper")
        self.dial(75)
        faded = self.pactl.volume(1)
        self.assertLess(faded, FULL)
        self.pactl.play(2, "Chromium", binary="vesktop.bin", volume=faded)
        self.dial(75)
        self.assertEqual(self.pactl.volume(2), FULL)

    def test_restored_after_restart(self):
        # faded when the app closed; PipeWire restores the faded volume next time
        self.pactl.play(1, "Discord")
        self.dial(0)
        self.assertEqual(self.pactl.volume(1), 0)
        del self.pactl.inputs[1]
        self.pactl.play(7, "Discord", sink=SPEAKERS, volume=0)
        self.dial(None, mixer=self.new_mixer())
        self.assertEqual(self.pactl.volume(7), FULL)
        self.assertFalse(os.path.exists(self.saved) and self.new_mixer().saved)


if __name__ == "__main__":
    unittest.main()

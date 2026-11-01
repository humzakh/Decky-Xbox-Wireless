import asyncio
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py_modules"))

import xone_installer as installer  # noqa: E402

KERNEL = os.uname().release


class FakeRunner(installer.Runner):
    """
    Records commands; `capture` answers come from a {command prefix: (rc, out)} table.
    `fail` is a command name or prefix tuple that exits 1.
    """

    def __init__(self, answers, fail=None):
        super().__init__(lambda line: self.lines.append(line))
        self.lines = []
        self.commands = []
        self.answers = answers
        self.fail = fail

    async def run(self, cmd, cwd=None, env=None, user=None, check=True):
        self.commands.append((cmd, user, env))
        fail = self.fail if isinstance(self.fail, tuple) else (self.fail,)
        if self.fail and tuple(cmd[:len(fail)]) == fail:
            if check:
                raise installer.InstallError(f"{cmd[0]} failed (exit 1)")
            return 1
        return 0

    async def capture(self, cmd):
        for prefix, answer in self.answers.items():
            if tuple(cmd[:len(prefix)]) == prefix:
                return answer
        return 127, ""

    def ran(self):
        return [c[0] for c in self.commands]


def steamos(readonly="enabled", installed=()):
    answers = {
        ("steamos-readonly", "status"): (0 if readonly == "enabled" else 1, readonly),
        ("pacman", "-Qoq"): (0, "linux-neptune-72"),
    }
    for pkg in installed:
        answers[("pacman", "-Q", pkg)] = (0, f"{pkg} 1.0")
    return answers


ALL_PACKAGES = installer.BUILD_PACKAGES + ["linux-neptune-72-headers"]
CHARGING_PATCH = os.path.join(installer.PATCHES_DIR, "xone-charging.patch")


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        installer.FIRMWARE_GLOB = os.path.join(self.tmp.name, "xone_dongle_*.bin")
        installer.PACMAN_LOCK = os.path.join(self.tmp.name, "db.lck")

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, runner):
        asyncio.run(installer.install(runner, "v0.5.8", self.tmp.name, "deck"))

    def test_parse_dkms_status(self):
        text = (
            "xone/0.5.8, 7.2.7-valve2-2-neptune-72-g31504582a073, x86_64: installed\n"
            "xone/0.5.7, 6.11.11-valve1-1-neptune-611, x86_64: built\n"
        )
        self.assertEqual(installer.parse_dkms_status(text), [
            {"version": "0.5.8", "kernel": "7.2.7-valve2-2-neptune-72-g31504582a073", "state": "installed"},
            {"version": "0.5.7", "kernel": "6.11.11-valve1-1-neptune-611", "state": "built"},
        ])
        self.assertEqual(installer.parse_dkms_status(""), [])

    def test_fresh_steamos_install(self):
        runner = FakeRunner(steamos("enabled"))
        self.install(runner)
        src = os.path.join(self.tmp.name, "xone-v0.5.8")
        self.assertEqual(runner.ran(), [
            ["steamos-readonly", "disable"],
            ["pacman-key", "--init"],
            ["pacman-key", "--populate", "archlinux", "holo"],
            ["pacman", "-Sy", "--needed", "--noconfirm", *ALL_PACKAGES],
            ["rm", "-rf", src],
            ["git", "clone", "--depth", "1", "--branch", "v0.5.8", installer.REPO, src],
            ["git", "apply", "--check", CHARGING_PATCH],
            ["git", "apply", CHARGING_PATCH],
            ["./install.sh"],
            ["./install/firmware.sh", "--skip-disclaimer"],
            ["modprobe", "xone-dongle"],
            ["modprobe", "xone-wired"],
            ["steamos-readonly", "enable"],
        ])
        clone = next(c for c in runner.commands if c[0][0] == "git")
        self.assertEqual(clone[1], "deck")
        install_sh = next(c for c in runner.commands if c[0] == ["./install.sh"])
        self.assertEqual(install_sh[2], {"SUDO_USER": "deck"})

    def test_reinstall_skips_what_is_present(self):
        open(os.path.join(self.tmp.name, "xone_dongle_02fe.bin"), "w").close()
        runner = FakeRunner(steamos("disabled", installed=ALL_PACKAGES))
        self.install(runner)
        ran = runner.ran()
        self.assertNotIn(["steamos-readonly", "disable"], ran)
        self.assertNotIn(["steamos-readonly", "enable"], ran, "read-only was off before, keep it off")
        self.assertFalse(any(c[0] in ("pacman", "pacman-key") for c in ran))
        self.assertNotIn(["./install/firmware.sh", "--skip-disclaimer"], ran)
        self.assertIn(["./install.sh"], ran)

    def test_patch_that_no_longer_applies_is_skipped(self):
        runner = FakeRunner(steamos("enabled"), fail=("git", "apply", "--check"))
        self.install(runner)
        self.assertNotIn(["git", "apply", CHARGING_PATCH], runner.ran())
        self.assertIn(["./install.sh"], runner.ran())
        self.assertIn("Skipping xone-charging.patch: doesn't apply to xone v0.5.8", runner.lines)

    def test_readonly_restored_on_failure(self):
        runner = FakeRunner(steamos("enabled"), fail="./install.sh")
        with self.assertRaises(installer.InstallError):
            self.install(runner)
        self.assertEqual(runner.ran()[-1], ["steamos-readonly", "enable"])
        self.assertNotIn(["modprobe", "xone-dongle"], runner.ran())

    def test_pacman_lock_aborts(self):
        open(installer.PACMAN_LOCK, "w").close()
        runner = FakeRunner(steamos("enabled"))
        with self.assertRaisesRegex(installer.InstallError, "pacman is busy"):
            self.install(runner)
        self.assertEqual(runner.ran(), [["steamos-readonly", "disable"], ["steamos-readonly", "enable"]])

    def test_non_steamos_skips_readonly_and_holo(self):
        answers = steamos()
        del answers[("steamos-readonly", "status")]
        runner = FakeRunner(answers)
        self.install(runner)
        ran = runner.ran()
        self.assertFalse(any(c[0] == "steamos-readonly" for c in ran))
        self.assertIn(["pacman-key", "--populate", "archlinux"], ran)

    def test_status_detects_kernel_mismatch(self):
        runner = FakeRunner({
            ("dkms", "status"): (0, "xone/0.5.8, 6.11.0-old-kernel, x86_64: installed"),
        })
        status = asyncio.run(installer.status(runner))
        self.assertEqual(status["kernel"], KERNEL)
        self.assertIsNone(status["installed_version"])
        self.assertEqual(status["stale_versions"], ["0.5.8"])
        self.assertTrue(status["dkms_available"])
        self.assertFalse(status["steamos"])

    def test_runner_streams_output_with_clean_env(self):
        lines = []
        runner = installer.Runner(lines.append)
        os.environ["LD_LIBRARY_PATH"] = "/tmp/_MEIbogus"
        rc = asyncio.run(runner.run(
            ["sh", "-c", 'echo "ld=[${LD_LIBRARY_PATH:-}]"; printf "10%%\\r100%%\\n"; exit 3'],
            check=False,
        ))
        self.assertEqual(rc, 3)
        self.assertEqual(lines[1:], ["ld=[]", "100%"])
        with self.assertRaisesRegex(installer.InstallError, r"sh failed \(exit 3\)"):
            asyncio.run(runner.run(["sh", "-c", "exit 3"]))


if __name__ == "__main__":
    unittest.main()

"""
Install/update the xone driver the same way `sudo make install` does in a
checkout of https://github.com/dlundqvist/xone, plus the SteamOS preparation
that requires (read-only rootfs, pacman keyring, kernel headers).

SteamOS updates replace the root filesystem, which removes the DKMS module,
the build tools and the firmware, so this is expected to be re-run after each
OS update. The plugin itself lives in /home and survives.

No decky dependency; commands go through a Runner so tests can fake them.
"""

import asyncio
import glob
import json
import os
import re
import ssl
import urllib.request

REPO = "https://github.com/dlundqvist/xone"
LATEST_RELEASE_API = "https://api.github.com/repos/dlundqvist/xone/releases/latest"

# what install.sh / install/firmware.sh need besides kernel headers
BUILD_PACKAGES = ["base-devel", "dkms", "git", "curl", "libarchive"]

# Decky's bundled Python doesn't know where the system CA store is
CA_BUNDLES = [
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
]

# our fixes on top of upstream, applied in name order
PATCHES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patches")

FIRMWARE_GLOB = "/lib/firmware/xone_dongle_*.bin"
MODULES_DIR = "/sys/module"
PACMAN_LOCK = "/var/lib/pacman/db.lck"

# Decky's bundled Python sets LD_LIBRARY_PATH etc. for itself; system tools
# like pacman and git must not inherit that.
CLEAN_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin",
    "HOME": "/root",
    "LANG": "C.UTF-8",
    "TERM": "dumb",
}

_DKMS_RE = re.compile(r"^xone/([^,]+), ([^,]+), [^:]+: (\w+)", re.M)


class InstallError(Exception):
    pass


class Runner:
    """Runs commands, streaming combined output line by line to `log`."""

    def __init__(self, log):
        self.log = log

    async def run(self, cmd, cwd=None, env=None, user=None, check=True):
        name = os.path.basename(cmd[0])
        if user:
            cmd = ["sudo", "-u", user, "--"] + cmd
        self.log(f"$ {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env={**CLEAN_ENV, **(env or {})},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for raw in proc.stdout:
            # pacman/curl redraw progress with \r; keep the last state of each line
            line = raw.decode(errors="replace").rstrip("\n").split("\r")[-1].rstrip()
            if line:
                self.log(line)
        rc = await proc.wait()
        if check and rc != 0:
            raise InstallError(f"{name} failed (exit {rc})")
        return rc

    async def capture(self, cmd):
        """Run quietly and return (exit code, stdout)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=CLEAN_ENV,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return 127, ""
        out, _ = await proc.communicate()
        return proc.returncode, out.decode(errors="replace").strip()


def parse_dkms_status(text):
    return [
        {"version": v, "kernel": k, "state": s}
        for v, k, s in _DKMS_RE.findall(text or "")
    ]


def firmware_present():
    return bool(glob.glob(FIRMWARE_GLOB))


async def outdated_modules(runner):
    """
    xone modules still running from before the last install. uninstall.sh can't
    unload the headset module while PipeWire has its sound card open, and so not
    xone_gip either; only a restart (or unplugging everything) loads the new ones.
    """
    try:
        names = sorted(n for n in os.listdir(MODULES_DIR) if n.startswith("xone_"))
    except OSError:
        return []
    outdated = []
    for name in names:
        try:
            with open(os.path.join(MODULES_DIR, name, "srcversion")) as f:
                loaded = f.read().strip()
        except OSError:
            continue
        rc, built = await runner.capture(["modinfo", "-F", "srcversion", name])
        if rc == 0 and built and built != loaded:
            outdated.append(name)
    return outdated


def fetch_latest_release():
    """Tag name of the latest GitHub release, e.g. "v0.5.8". Blocking."""
    req = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "decky-xbox-wireless"},
    )
    cafile = next((path for path in CA_BUNDLES if os.path.exists(path)), None)
    context = ssl.create_default_context(cafile=cafile)
    with urllib.request.urlopen(req, timeout=10, context=context) as resp:
        return json.load(resp)["tag_name"]


async def readonly_status(runner):
    """"enabled", "disabled", or None when not on SteamOS."""
    # exits 1 when disabled, so go by the output
    _, out = await runner.capture(["steamos-readonly", "status"])
    return out if out in ("enabled", "disabled") else None


async def headers_package(runner, kernel):
    rc, out = await runner.capture(["pacman", "-Qoq", f"/usr/lib/modules/{kernel}/vmlinuz"])
    if rc != 0 or not out:
        raise InstallError(f"can't find the package that owns kernel {kernel}")
    return f"{out.splitlines()[0]}-headers"


async def missing_packages(runner, packages):
    missing = []
    for pkg in packages:
        rc, _ = await runner.capture(["pacman", "-Q", pkg])
        if rc != 0:
            missing.append(pkg)
    return missing


async def status(runner):
    kernel = os.uname().release
    rc, out = await runner.capture(["dkms", "status", "xone"])
    entries = parse_dkms_status(out) if rc == 0 else []
    current = next((e for e in entries if e["kernel"] == kernel and e["state"] == "installed"), None)
    loaded = None
    try:
        with open("/sys/module/xone_dongle/version") as f:
            loaded = f.read().strip()
    except OSError:
        pass
    return {
        "kernel": kernel,
        "steamos": await readonly_status(runner) is not None,
        "dkms_available": rc != 127,
        # version built for the running kernel, if any
        "installed_version": current["version"] if current else None,
        # installed for some other kernel only, e.g. after a kernel update
        "stale_versions": sorted({e["version"] for e in entries if e is not current}),
        "loaded_version": loaded,
        "restart_needed": bool(await outdated_modules(runner)),
        "firmware": firmware_present(),
    }


async def install(runner, tag, workdir, user):
    """
    Mirror of `git clone && sudo make install`, i.e. install.sh followed by
    install/firmware.sh, with the SteamOS prerequisites set up first.
    Returns whether a restart is needed to load it.
    """
    log = runner.log
    kernel = os.uname().release
    log(f"Installing xone {tag} for kernel {kernel}")

    readonly = await readonly_status(runner)
    if readonly == "enabled":
        await runner.run(["steamos-readonly", "disable"])
    try:
        packages = BUILD_PACKAGES + [await headers_package(runner, kernel)]
        missing = await missing_packages(runner, packages)
        if missing:
            if os.path.exists(PACMAN_LOCK):
                raise InstallError(f"pacman is busy ({PACMAN_LOCK} exists); try again when it's done")
            await runner.run(["pacman-key", "--init"])
            keyrings = ["archlinux", "holo"] if readonly is not None else ["archlinux"]
            await runner.run(["pacman-key", "--populate", *keyrings])
            # -Sy without -u: only add what's missing, never upgrade the OS image
            await runner.run(["pacman", "-Sy", "--needed", "--noconfirm", *missing])
        else:
            log("Build dependencies already installed")

        src = os.path.join(workdir, f"xone-{tag}")
        await runner.run(["rm", "-rf", src])
        # clone as the regular user: install.sh runs `sudo -u $SUDO_USER git describe`
        # to get the version, which git refuses on a repo owned by someone else
        await runner.run(["git", "clone", "--depth", "1", "--branch", tag, REPO, src], user=user)
        for patch in sorted(glob.glob(os.path.join(PATCHES_DIR, "*.patch"))):
            # a newer xone may have fixed it or moved the code; build it unpatched then
            if await runner.run(["git", "apply", "--check", patch], cwd=src, user=user, check=False) == 0:
                await runner.run(["git", "apply", patch], cwd=src, user=user)
            else:
                log(f"Skipping {os.path.basename(patch)}: doesn't apply to xone {tag}")
        await runner.run(["./install.sh"], cwd=src, env={"SUDO_USER": user})

        if firmware_present():
            log("Dongle firmware already installed")
        else:
            await runner.run(["./install/firmware.sh", "--skip-disclaimer"], cwd=src)

        await runner.run(["modprobe", "xone-dongle"])
        await runner.run(["modprobe", "xone-wired"], check=False)
    finally:
        if readonly == "enabled":
            await runner.run(["steamos-readonly", "enable"], check=False)
    outdated = await outdated_modules(runner)
    if outdated:
        log(f"Still running the old {', '.join(outdated)} (in use); restart to load {tag}")
    log(f"xone {tag} installed")
    return bool(outdated)

"""
Read/write helpers for the xone driver's sysfs interface.

Layout (see https://github.com/dlundqvist/xone):

  /sys/bus/usb/drivers/xone-dongle/<intf>/        pairing, active_clients, poweroff
      gipN/                                       one GIP adapter per wireless client
          gipN.0/                                 main client (gamepad, ...)
              uevent                              MODALIAS=gip:<class>
              driver -> xone-gip-gamepad
              power_supply/gipN.0/                status, capacity_level, model_name
              leds/gipN.0:white:status/           brightness, max_brightness, mode
              chat_mix                            headset game/chat dial, 0-100 (our patch)
          gipN.1/                                 attachments (headset, chatpad)
  /sys/bus/usb/drivers/xone-wired/<intf>/gipN/... same, for USB-connected devices

This module has no decky dependency so it can be tested against a fake tree.
"""

import os
import re

SYSFS_ROOT = os.environ.get("XONE_SYSFS_ROOT", "/sys")

DONGLE_DRIVER = "bus/usb/drivers/xone-dongle"
WIRED_DRIVER = "bus/usb/drivers/xone-wired"
GIP_BUS = "bus/xone-gip"

PAIRING_TIMEOUT = 60  # XONE_DONGLE_PAIRING_TIMEOUT in transport/dongle.c

DONGLE_MODELS = {
    "02e6": "Xbox Wireless Adapter (original)",
    "02fe": "Xbox Wireless Adapter",
    "02f9": "Built-in Xbox Wireless Adapter",
    "091e": "Built-in Xbox Wireless Adapter",
}

CLASS_KINDS = {
    "Windows.Xbox.Input.Gamepad": "gamepad",
    "Windows.Xbox.Input.Headset": "headset",
    "Windows.Xbox.Input.Chatpad": "chatpad",
    "MadCatz.Xbox.Guitar.Stratocaster": "guitar",
    "PDP.Xbox.Guitar.Jaguar": "guitar",
    "MadCatz.Xbox.Drums.Glam": "drums",
}

# Microsoft (045e) product IDs, as reported by the gamepad's input device
GAMEPAD_MODELS = {
    "02d1": "Xbox One Controller",
    "02dd": "Xbox One Controller",
    "02ea": "Xbox One S Controller",
    "02e3": "Xbox Elite Controller",
    "0b00": "Xbox Elite Series 2 Controller",
    "0b0a": "Xbox Adaptive Controller",
    "0b12": "Xbox Series X|S Controller",
}

# Product IDs of real chatpad hardware. Some controllers (e.g. Elite Series 2)
# also announce a chatpad client of their own, which reports the controller's
# firmware version instead of its own.
CHATPAD_PRODUCTS = {"02f3"}

# what xone sets on connect (GIP_LED_BRIGHTNESS_DEFAULT, GIP_LED_ON)
LED_DEFAULT_BRIGHTNESS = 20
LED_DEFAULT_MODE = 1

# GIP_LED_* in bus/protocol.h
LED_MODES = {
    0: "Off",
    1: "On",
    2: "Blink fast",
    3: "Blink normal",
    4: "Blink slow",
    8: "Fade slow",
    9: "Fade fast",
}

_ADAPTER_RE = re.compile(r"^gip(\d+)$")
_CLIENT_RE = re.compile(r"^gip(\d+)\.(\d+)$")
_SLOT_RE = re.compile(r"\[(\d+)\](\*?)")


class XoneError(Exception):
    pass


def _path(*parts):
    return os.path.join(SYSFS_ROOT, *parts)


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except OSError as e:
        raise XoneError(f"{os.path.basename(path)}: {e.strerror or e}") from e


def _read_int(path, default=None):
    value = _read(path)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _children(path, pattern):
    try:
        names = os.listdir(path)
    except OSError:
        return []
    matches = [(pattern.match(n), n) for n in names]
    return sorted(
        ((tuple(int(g) for g in m.groups()), n) for m, n in matches if m),
        key=lambda t: t[0],
    )


def driver_loaded():
    return os.path.isdir(_path(GIP_BUS))


def _interfaces(driver):
    root = _path(driver)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    # bound devices are symlinks named like "1-2:1.0"; skip bind/unbind/module etc.
    return sorted(
        (n, os.path.realpath(os.path.join(root, n)))
        for n in names
        if ":" in n and os.path.isdir(os.path.join(root, n))
    )


def _parse_slots(text):
    """Return the indices of occupied slots from the active_clients table."""
    if not text:
        return []
    return sorted(int(i) for i, active in _SLOT_RE.findall(text) if active)


def _read_battery(client_dir, name):
    supply = os.path.join(client_dir, "power_supply", name)
    if not os.path.isdir(supply):
        return None
    status = _read(os.path.join(supply, "status"), "Unknown")
    level = _read(os.path.join(supply, "capacity_level"), "Unknown")
    return {
        "status": status,
        "level": level,
        # GIP_BATT_TYPE_NONE: running off USB power / no batteries installed
        "no_battery": status == "Not charging" and level == "Unknown",
    }


def _read_led(client_dir):
    leds = os.path.join(client_dir, "leds")
    try:
        names = sorted(os.listdir(leds))
    except OSError:
        return None
    for name in names:
        led = os.path.join(leds, name)
        brightness = _read_int(os.path.join(led, "brightness"))
        if brightness is None:
            continue
        return {
            "name": name,
            "brightness": brightness,
            "max_brightness": _read_int(os.path.join(led, "max_brightness"), 50),
            "mode": _read_int(os.path.join(led, "mode"), 1),
            "default_brightness": LED_DEFAULT_BRIGHTNESS,
        }
    return None


def _read_input_id(client_dir):
    """
    Vendor/product/version/serial of the client's first input device,
    e.g. ("045e", "0b00", "0518", "02630039134144"). xone puts the GIP serial
    number in the input device's uniq.
    """
    inputs = os.path.join(client_dir, "input")
    try:
        names = sorted(os.listdir(inputs))
    except OSError:
        return None, None, None, None
    for name in names:
        id_dir = os.path.join(inputs, name, "id")
        vendor = _read(os.path.join(id_dir, "vendor"))
        product = _read(os.path.join(id_dir, "product"))
        if vendor and product:
            version = _read(os.path.join(id_dir, "version"))
            serial = _read(os.path.join(inputs, name, "uniq")) or None
            return vendor, product, version, serial
    return None, None, None, None


def _read_client(client_dir, name):
    uevent = _read(os.path.join(client_dir, "uevent"), "")
    gip_class = None
    for line in uevent.splitlines():
        if line.startswith("MODALIAS=gip:"):
            gip_class = line[len("MODALIAS=gip:"):]
    driver = os.path.join(client_dir, "driver")
    driver_name = (
        os.path.basename(os.path.realpath(driver)) if os.path.islink(driver) else None
    )
    battery = _read_battery(client_dir, name)
    model = _read(os.path.join(client_dir, "power_supply", name, "model_name"))
    kind = CLASS_KINDS.get(gip_class, "unknown")
    vendor_id, product_id, version, serial = _read_input_id(client_dir)
    if kind == "gamepad" and vendor_id == "045e":
        model = GAMEPAD_MODELS.get(product_id, model)
    return {
        "id": name,
        "kind": kind,
        "gip_class": gip_class,
        "driver": driver_name,
        "vendor_id": vendor_id,
        "product_id": product_id,
        "version": version,
        "serial": serial,
        # stable identity for per-device settings; falls back to the model
        "key": f"serial:{serial}" if serial else (f"model:{vendor_id}:{product_id}" if vendor_id else None),
        "phantom": False,
        "name": model or _default_name(kind, gip_class),
        "battery": battery,
        "led": _read_led(client_dir),
        "chat_mix": _read_int(os.path.join(client_dir, "chat_mix")),
    }


def _default_name(kind, gip_class):
    if kind != "unknown":
        return f"Xbox {kind.capitalize()}"
    return gip_class or "Unknown device"


def _mark_phantoms(clients):
    if not clients or clients[0]["kind"] != "gamepad":
        return
    main = clients[0]
    for client in clients[1:]:
        client["phantom"] = (
            client["kind"] == "chatpad"
            and client["product_id"] not in CHATPAD_PRODUCTS
            and client["version"] is not None
            and client["version"] == main["version"]
        )


def _read_adapters(parent_dir):
    """Each GIP adapter under a USB interface is one physical device."""
    devices = []
    for (adapter_id,), adapter in _children(parent_dir, _ADAPTER_RE):
        adapter_dir = os.path.join(parent_dir, adapter)
        children = _children(adapter_dir, _CLIENT_RE)
        clients = [_read_client(os.path.join(adapter_dir, name), name) for _, name in children]
        _mark_phantoms(clients)
        devices.append({
            "adapter": adapter,
            "adapter_id": adapter_id,
            # an adapter without clients is still doing the GIP handshake
            "connecting": not clients,
            # attachments without the main client (gipN.0): xone is part-way through
            # removing the device, e.g. after a power off
            "partial": bool(clients) and children[0][0][1] != 0,
            "clients": clients,
        })
    return devices


def _usb_info(intf_dir):
    usb_dir = os.path.dirname(intf_dir)
    product_id = _read(os.path.join(usb_dir, "idProduct"), "")
    return {
        "product_id": product_id,
        "model": DONGLE_MODELS.get(product_id) or _read(os.path.join(usb_dir, "product")) or "Xbox Wireless Adapter",
        "serial": _read(os.path.join(usb_dir, "serial")),
    }


def read_dongles():
    dongles = []
    for intf, real in _interfaces(DONGLE_DRIVER):
        if not os.path.exists(os.path.join(real, "pairing")):
            continue
        slots = _parse_slots(_read(os.path.join(real, "active_clients")))
        devices = _read_adapters(real)
        # Slots (WCIDs) and adapter IDs are both lowest-free allocations made
        # together in xone_dongle_create_client, so their orders match unless
        # adapter IDs were interleaved with another transport's. Only expose a
        # per-device slot when the counts agree.
        if len(slots) == len(devices):
            for slot, device in zip(slots, devices):
                device["slot"] = slot
        else:
            for device in devices:
                device["slot"] = None
        dongles.append({
            "id": intf,
            **_usb_info(real),
            "pairing": _read(os.path.join(real, "pairing")) == "1",
            "active_clients": len(slots),
            "devices": devices,
        })
    return dongles


def read_wired():
    devices = []
    for intf, real in _interfaces(WIRED_DRIVER):
        for device in _read_adapters(real):
            device["interface"] = intf
            device["slot"] = None
            devices.append(device)
    return devices


def read_state():
    return {
        "driver_loaded": driver_loaded(),
        "dongles": read_dongles(),
        "wired": read_wired(),
    }


def chat_mix_path(client_id):
    return _path(GIP_BUS, "devices", client_id, "chat_mix")


def _dongle_dir(dongle_id):
    for intf, real in _interfaces(DONGLE_DRIVER):
        if intf == dongle_id:
            return real
    raise XoneError(f"dongle {dongle_id} not found")


def set_pairing(dongle_id, enabled):
    _write(os.path.join(_dongle_dir(dongle_id), "pairing"), "1" if enabled else "0")


def power_off(dongle_id, slot):
    slot = int(slot)
    if slot != -1 and not 0 <= slot <= 15:
        raise XoneError(f"invalid slot {slot}")
    _write(os.path.join(_dongle_dir(dongle_id), "poweroff"), slot)


def _led_dir(led_name):
    # only accept LED names that belong to a xone client, never arbitrary paths
    if "/" in led_name or not _CLIENT_RE.match(led_name.split(":", 1)[0]):
        raise XoneError(f"invalid LED {led_name}")
    path = _path("class/leds", led_name)
    if not os.path.isdir(path):
        raise XoneError(f"LED {led_name} not found")
    return path


def set_led(led_name, brightness=None, mode=None):
    path = _led_dir(led_name)
    if mode is not None:
        if int(mode) not in LED_MODES:
            raise XoneError(f"invalid LED mode {mode}")
        _write(os.path.join(path, "mode"), int(mode))
    if brightness is not None:
        max_brightness = _read_int(os.path.join(path, "max_brightness"), 50)
        _write(os.path.join(path, "brightness"), max(0, min(int(brightness), max_brightness)))

"""The audio outputs (record 0003 §10): the sinks `pactl -f json list sinks` gives, each with its
kind glyph and short name; a Bluetooth sink's battery from BlueZ; and BlueZ's paired audio
devices, for `barmenu outputs`.

Everything here only reads: `pactl -f json list sinks`, `busctl --system get-property ...
org.bluez.Battery1 Percentage` and BlueZ's `GetManagedObjects`. Nothing here switches a sink,
changes a volume, or connects, disconnects, pairs or powers a device; the menu's rows do that,
and only when picked. A sink's name and a device's address come from these queries' JSON and go
into argument lists, never a shell string, and each is checked first (SINK_NAME, BLUEZ_PATH,
ADDRESS), so no value can be read as an option or carry anything else.

Nothing here logs a sink, a device, an alias or an address.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from desktop_tools.common import paths, procs

# The kind glyphs (record 0003 §10), current Nerd Font codepoints.
BT_HEADPHONES = "\U000f0970"  # md-headphones_bluetooth
BT_SPEAKER = "\U000f09a2"  # md-speaker_bluetooth
HEADPHONES = "\U000f02cb"  # md-headphones
HEADSET = "\U000f02ce"  # md-headset
TELEVISION = "\U000f0502"  # md-television: HDMI or DisplayPort
USB = "\U000f0553"  # md-usb
SPEAKER = "\U000f04c3"  # md-speaker: anything else

VOL_LOW = "\U000f057f"  # md-volume_low
VOL_MEDIUM = "\U000f0580"  # md-volume_medium
VOL_HIGH = "\U000f057e"  # md-volume_high
VOL_OFF = "\U000f0581"  # md-volume_off: muted
BATTERY_FULL = "\U000f0079"  # md-battery
BATTERY_10 = 0xF007A  # md-battery_10; md-battery_20 to md-battery_90 follow it in order

NAME_MAX = 16  # characters of a short name
TIMEOUT = 2.0  # seconds a query may take
BATTERY = "org.bluez.Battery1"
DEVICE = "org.bluez.Device1"

SINK_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:@+-]*$")
BLUEZ_PATH = re.compile(r"^/org/bluez/[A-Za-z0-9_/]+$")
ADDRESS = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


@dataclass(frozen=True)
class Sink:
    index: int
    name: str
    glyph: str
    short: str
    bluetooth: bool
    path: str  # the BlueZ device (api.bluez5.path), "" for none or a value that isn't one


@dataclass(frozen=True)
class Device:
    address: str
    alias: str
    connected: bool


def cut(text: str, width: int = NAME_MAX) -> str:
    """One line (a newline would end polybar's read of the hook), at most `width` characters."""
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def kind(props: dict[str, Any], active_port: dict[str, Any] | None = None) -> str:
    """The kind glyph of a sink, from its properties and its active port, in the record's
    order: Bluetooth headphones or headset, other Bluetooth, wired headphones or headset, HDMI
    or DisplayPort, USB, then speakers."""
    bus = _text(props.get("device.bus")).lower()
    form = _text(props.get("device.form_factor")).lower()
    if bus == "bluetooth":
        return BT_HEADPHONES if form in ("headphone", "headset") else BT_SPEAKER
    if form == "headset":
        return HEADSET
    port = active_port or {}
    port_words = f"{_text(port.get('name'))} {_text(port.get('type'))}".lower()
    if form == "headphone" or "headphones" in port_words:
        return HEADPHONES
    where = f"{_text(props.get('node.name'))} {_text(props.get('device.profile.name'))}".lower()
    if "hdmi" in where:
        return TELEVISION
    if bus == "usb":
        return USB
    return SPEAKER


def names() -> list[tuple[re.Pattern[str], str]]:
    """Stephen's own names for his sinks: the dotfiles' `audio/devices.json` (a list of
    {pattern, name}), each pattern a regular expression searched for in the sink's name, as
    the `audio` tool does. A file that can't be read, or a pattern that isn't one, gives none."""
    try:
        data = json.loads((paths.data_home() / "audio" / "devices.json").read_text("utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        pattern, name = entry.get("pattern"), entry.get("name")
        if not isinstance(pattern, str) or not isinstance(name, str) or not name.strip():
            continue
        try:
            out.append((re.compile(pattern), name.strip()))
        except re.error:
            continue
    return out


def short_name(
    name: str, props: dict[str, Any], description: str, own: list[tuple[re.Pattern[str], str]]
) -> str:
    """devices.json's name when a pattern matches, else device.nick, else the description,
    cut to NAME_MAX characters."""
    for pattern, friendly in own:
        if pattern.search(name):
            return cut(friendly)
    for found in (_text(props.get("device.nick")), _text(props.get("device.description"))):
        if found:
            return cut(found)
    return cut(description.strip() or name)


def parse_sinks(text: str, own: list[tuple[re.Pattern[str], str]] | None = None) -> list[Sink]:
    """`pactl -f json list sinks` as Sinks; a sink whose name or index isn't usable is skipped.
    Raises ValueError when the text isn't JSON."""
    data = json.loads(text)
    own = names() if own is None else own
    out = []
    for raw in data if isinstance(data, list) else []:
        if not isinstance(raw, dict):
            continue
        name, index = raw.get("name"), raw.get("index")
        if not isinstance(name, str) or not SINK_NAME.match(name):
            continue
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        found = raw.get("properties")
        props: dict[str, Any] = found if isinstance(found, dict) else {}
        listed = raw.get("ports")
        active = raw.get("active_port")
        port = next(
            (
                p
                for p in (listed if isinstance(listed, list) else [])
                if isinstance(p, dict) and p.get("name") == active
            ),
            None,
        )
        bluetooth = _text(props.get("device.bus")).lower() == "bluetooth"
        path = _text(props.get("api.bluez5.path"))
        out.append(
            Sink(
                index=index,
                name=name,
                glyph=kind(props, port),
                short=short_name(name, props, _text(raw.get("description")), own),
                bluetooth=bluetooth,
                path=path if bluetooth and BLUEZ_PATH.match(path) else "",
            )
        )
    return out


def sinks(timeout: float = TIMEOUT) -> list[Sink] | None:
    """Every sink, or None when pactl fails, times out or gives what isn't JSON."""
    out = procs.query(["pactl", "-f", "json", "list", "sinks"], timeout=timeout)
    if out is None:
        return None
    try:
        return parse_sinks(out)
    except ValueError:
        return None


def battery(path: str, timeout: float = TIMEOUT) -> int | None:
    """A BlueZ device's battery percentage, or None when it gives none (no Battery1, no BlueZ,
    a path that isn't BlueZ's, a timeout)."""
    if not BLUEZ_PATH.match(path):
        return None
    argv = ["busctl", "--system", "get-property", "org.bluez", path, BATTERY, "Percentage"]
    match = re.match(r"^y (\d{1,3})\s*$", procs.query(argv, timeout=timeout) or "")
    if not match:
        return None
    level = int(match.group(1))
    return level if level <= 100 else None


def battery_glyph(level: int | None) -> str:
    """md-battery_10 to md-battery_90 by tens, md-battery full; nothing with no level."""
    if level is None:
        return ""
    if level >= 95:
        return BATTERY_FULL
    tens = min(9, max(1, int(level / 10 + 0.5)))
    return chr(BATTERY_10 + tens - 1)


def volume_glyph(volume: int, muted: bool) -> str:
    if muted:
        return VOL_OFF
    if volume < 34:
        return VOL_LOW
    return VOL_MEDIUM if volume < 67 else VOL_HIGH


def _value(variant: object) -> object:
    """busctl's JSON gives each property as {"type": ..., "data": ...}."""
    return variant.get("data") if isinstance(variant, dict) else None


def parse_devices(text: str) -> list[Device]:
    """BlueZ's managed objects (`busctl --json=short`) as the paired audio devices (Icon
    starting `audio-`, Paired true), sorted by alias. Raises ValueError when it isn't JSON."""
    data = json.loads(text)
    objects = _value(data) if isinstance(data, dict) else None
    if isinstance(objects, list):
        objects = objects[0] if objects else {}
    out = []
    for interfaces in (objects or {}).values() if isinstance(objects, dict) else []:
        props = interfaces.get(DEVICE) if isinstance(interfaces, dict) else None
        if not isinstance(props, dict):
            continue
        address, icon = _value(props.get("Address")), _value(props.get("Icon"))
        if not isinstance(address, str) or not ADDRESS.match(address):
            continue
        if not isinstance(icon, str) or not icon.startswith("audio-"):
            continue
        if _value(props.get("Paired")) is not True:
            continue
        alias = str(_value(props.get("Alias")) or _value(props.get("Name")) or "").strip()
        connected = _value(props.get("Connected")) is True
        out.append(Device(address, " ".join(alias.split()) or address, connected))
    return sorted(out, key=lambda d: (d.alias.lower(), d.address))


def devices(timeout: float = TIMEOUT) -> list[Device] | None:
    """The paired Bluetooth audio devices, or None when BlueZ can't be read."""
    argv = [
        "busctl",
        "--system",
        "--json=short",
        "call",
        "org.bluez",
        "/",
        "org.freedesktop.DBus.ObjectManager",
        "GetManagedObjects",
    ]
    out = procs.query(argv, timeout=timeout)
    if out is None:
        return None
    try:
        return parse_devices(out)
    except ValueError:
        return None

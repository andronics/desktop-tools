"""The outputs menu's rows (record 0003 §10): one per sink (the default marked), picking it makes
it the default; then connect or disconnect each paired Bluetooth audio device; then the mixer.

Two read-only queries when it opens (TIMEOUT seconds each): `pactl -f json list sinks` and
BlueZ's managed objects (`busctl --system --json=short call org.bluez / ...GetManagedObjects`).
The default is the `target` in barctl's state for `output-capsule`, or `pactl get-default-sink`
when barctl has none. Nothing runs until a row is picked; every row is an argument list, the
sink and the address from the queries' JSON (checked in barctl/outputs.py), never a shell
string. With BlueZ unreadable the Bluetooth rows are left out and the sinks still show. No row
pairs, removes, trusts or powers a device: that stays in `bt menu`. Nothing here logs a sink,
a device, an alias or an address, and no row sets or clears COORDINATOR, CLAUDECODE or
TESSERA_ACTOR (§6).
"""

from __future__ import annotations

from desktop_tools.barctl import outputs
from desktop_tools.barctl import state as st
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.common import procs

MODULE = "output-capsule"
CONNECT = "\U000f00b1"  # md-bluetooth_connect
DISCONNECT = "\U000f00b2"  # md-bluetooth_off
MIXER = "\U000f057e"  # md-volume_high


def default() -> str:
    """The default sink's name, from barctl's state, else pactl; empty when neither says."""
    data = st.read(MODULE) or {}
    if data.get("tier") not in (None, "unavailable") and data.get("target"):
        return str(data["target"])
    out = procs.query(["pactl", "get-default-sink"], timeout=providers.TIMEOUT)
    return (out or "").strip()


def rows() -> list[Row]:
    out: list[Row] = []
    sinks = outputs.sinks(timeout=providers.TIMEOUT) or []
    current = default() if sinks else ""
    for sink in sinks:
        out.append(
            Row(
                sink.glyph,
                sink.short,
                ["pactl", "set-default-sink", sink.name],
                current=sink.name == current,
            )
        )
    devices = outputs.devices(timeout=providers.TIMEOUT) or []
    out += [
        Row(CONNECT, f"Connect {d.alias}", ["bluetoothctl", "connect", d.address])
        for d in devices
        if not d.connected
    ]
    out += [
        Row(DISCONNECT, f"Disconnect {d.alias}", ["bluetoothctl", "disconnect", d.address])
        for d in devices
        if d.connected
    ]
    out.append(Row(MIXER, "Mixer…", ["pwvucontrol"]))
    return out

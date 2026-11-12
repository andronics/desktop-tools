"""The players menu's rows (record 0003 §4): every player `playerctl -l` lists, with its icon
from the `player` tool's instances.json, the one the capsule shows marked, then `Automatic`
(marked when nothing is pinned).

Picking a player runs `barctl pin player-capsule <instance>`; `Automatic` runs `barctl pin
player-capsule --auto`. A menu of its own keeps the player menu inside eight rows however many
players there are. Read-only: `playerctl -l` and the controller's `ping` for the pin.
"""

from __future__ import annotations

from desktop_tools.barctl import ops
from desktop_tools.barctl.sources.player import _icons, player_icon
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.barmenu.providers.player import MODULE, shown
from desktop_tools.common import procs

AUTOMATIC = "\U000f0387"  # md-music_note: the bar's own choice


def rows() -> list[Row]:
    listed = (procs.query(["playerctl", "-l"], timeout=providers.TIMEOUT) or "").split()
    names = _icons("instances.json", "name", "default")
    target, _ = shown()
    pinned = ops.pins().get("player")
    out = [
        Row(
            player_icon(names, instance.split(".", 1)[0]),
            instance,
            ["barctl", "pin", MODULE, instance],
            current=instance == target,
        )
        for instance in listed
    ]
    out.append(Row(AUTOMATIC, "Automatic", ["barctl", "pin", MODULE, "--auto"], current=not pinned))
    return out

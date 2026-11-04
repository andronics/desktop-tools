"""player: every MPRIS player, from `playerctl -a --follow metadata`, shown as one (record 0001,
question 3): Playing beats Paused beats Stopped, then the player whose status changed most
recently.

Every module this source draws gets the same state: the glyph is the player's icon then its
state's (from the `player` tool's instances.json and states.json), the label "artist: title" cut
to 40 characters, and the target the player's instance name, so a click acts on the player the
bar shows. Each module's display picks what it shows (player-play-pause the glyph,
player-metadata the label). Unavailable with no player, idle paused or stopped, active playing.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import Row
from desktop_tools.barctl.render import METADATA_MAX
from desktop_tools.barctl.sources.base import Source
from desktop_tools.barctl.store import Writer
from desktop_tools.common import paths, procs

US = "\x1f"
FORMAT = US.join(("{{playerInstance}}", "{{playerName}}", "{{status}}", "{{artist}}", "{{title}}"))
RANK = {"Playing": 3, "Paused": 2, "Stopped": 1}


def _icons(file: str, field: str, fallback: str) -> dict[str, str]:
    """name (or state) -> icon from the player tool's JSON, with `*` for its fallback entry."""
    try:
        data = json.loads((paths.data_home() / "player" / file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for entry in data if isinstance(data, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get(field), str):
            key = entry[field]
            out.setdefault("*" if key == fallback else key, str(entry.get("icon", "")))
    return out


def player_icon(icons: dict[str, str], name: str) -> str:
    return icons.get(name, icons.get("*", ""))


def track(artist: str, title: str) -> str:
    text = f"{artist}: {title}" if artist and title else artist + title
    return text if len(text) <= METADATA_MAX else text[: METADATA_MAX - 1] + "…"


@dataclass
class Player:
    status: str
    name: str
    track: str
    seq: int


class PlayerSource(Source):
    name = "player"
    commands = ("playerctl",)

    def __init__(self, modules: Sequence[str], writer: Writer) -> None:
        super().__init__(modules, writer)
        self.players: dict[str, Player] = {}
        self.tick = 0
        self.names = _icons("instances.json", "name", "default")
        self.states = _icons("states.json", "state", "stopped")

    def pick(self) -> str | None:
        """The shown player's instance, or None with no player."""
        best: tuple[int, int] | None = None
        chosen = None
        for instance, p in self.players.items():
            key = (RANK.get(p.status, 0), p.seq)
            if best is None or key > best:
                best, chosen = key, instance
        return chosen

    def prune(self) -> None:
        """Forget players playerctl no longer lists: `--follow` prints an empty line when one
        goes, but not always before the next event."""
        out = procs.query(["playerctl", "-l"])
        live = set((out or "").split())
        for instance in list(self.players):
            if instance not in live:
                del self.players[instance]

    def event(self, line: str) -> None:
        """One line of the stream: instance, name, status, artist, title."""
        fields = line.split(US)
        if len(fields) >= 5 and fields[0]:
            instance, name, status, artist, title = fields[:5]
            old = self.players.get(instance)
            if old is None or old.status != status:
                self.tick += 1
                seq = self.tick
            else:
                seq = old.seq
            self.players[instance] = Player(status, name, track(artist, title), seq)
        self.prune()
        self.update()

    def update(self) -> None:
        instance = self.pick()
        if instance is None:
            self.set_all("unavailable")
            return
        p = self.players[instance]
        tier = "active" if p.status == "Playing" else "idle"
        icon = player_icon(self.names, p.name)
        state_icon = player_icon(self.states, p.status.lower())
        glyph = " ".join(g for g in (icon, state_icon) if g)
        self.set_all(tier, glyph=glyph, label=p.track, target=instance)

    def follow(self) -> None:
        self.players.clear()
        self.update()
        stream = self.stream(["playerctl", "-a", "--follow", "metadata", "--format", FORMAT])
        for line in stream.lines():
            if self.stopping:
                return
            self.event(line)

    def gone(self) -> None:
        self.players.clear()
        self.update()

    @classmethod
    def menu_rows(cls, module: str, state: st.State | None) -> list[Row]:
        """One row per player: picking it plays or pauses that player."""
        names = _icons("instances.json", "name", "default")
        out = procs.query(["playerctl", "-l"]) or ""
        rows = []
        for instance in out.split():
            icon = player_icon(names, instance.split(".", 1)[0])
            rows.append(Row(icon, instance, ["player", "play-pause", instance]))
        return rows

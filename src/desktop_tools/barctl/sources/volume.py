"""volume: the default sink's volume and mute, from `pactl subscribe` (served by pipewire-pulse).

Sink and server events re-read the default sink (a server event covers a new default sink);
anything else (sink inputs, clients) is ignored. Unavailable when the pulse server doesn't
answer, idle when muted, active otherwise. The text is the zsh controller's: a glyph by level
and the percentage padded to four characters.
"""

from __future__ import annotations

import re

from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import Row
from desktop_tools.barctl.sources.base import Source
from desktop_tools.common import procs

VOL_OFF = "\U000f0581"  # md-volume_off: muted or no server
VOL_0 = ""  # fa-volume_off: a speaker without waves
VOL_LOW = ""  # fa-volume_low
VOL_HIGH = ""  # fa-volume_up

EVENT = re.compile(r"^Event '[^']*' on (sink|server) #")
PERCENT = re.compile(r"(\d+)%")


def glyph_for(volume: int) -> str:
    if volume == 0:
        return VOL_0
    return VOL_LOW if volume < 50 else VOL_HIGH


class VolumeSource(Source):
    name = "volume"
    commands = ("pactl",)

    def update(self) -> None:
        sink = procs.query(["pactl", "get-default-sink"])
        if not sink or not sink.strip():
            self.set_all("unavailable", glyph=VOL_OFF)
            return
        out = procs.query(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]) or ""
        match = PERCENT.search(out)
        mute = procs.query(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]) or ""
        if not match:
            self.set_all("unavailable", glyph=VOL_OFF)
            return
        volume = int(match.group(1))
        label = f"{volume}%".ljust(4)
        target = sink.strip()
        if "Mute: yes" in mute:
            self.set_all("idle", glyph=VOL_OFF, label=label, target=target)
        else:
            self.set_all("active", glyph=glyph_for(volume), label=label, target=target)

    def follow(self) -> None:
        self.update()
        stream = self.stream(["pactl", "subscribe"])
        for line in stream.lines():
            if self.stopping:
                return
            if EVENT.match(line):
                self.update()

    def gone(self) -> None:
        self.set_all("unavailable", glyph=VOL_OFF)

    @classmethod
    def menu_rows(cls, module: str, state: st.State | None) -> list[Row]:
        """One row per sink: picking it makes it the default."""
        out = procs.query(["pactl", "list", "short", "sinks"]) or ""
        current = (state or {}).get("target")
        rows = []
        for line in out.splitlines():
            fields = line.split("\t")
            if len(fields) >= 2 and fields[1]:
                name = fields[1]
                glyph = VOL_HIGH if name == current else ""
                rows.append(Row(glyph, name, ["pactl", "set-default-sink", name]))
        return rows

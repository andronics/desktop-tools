"""volume: the default sink's volume and mute, from `pactl subscribe` (served by pipewire-pulse),
and for an output segment (`display = "output"`, record 0003 §10) the sink's kind, short name and
Bluetooth battery, and a notice when a Bluetooth sink comes or goes.

Sink and server events re-read the default sink (a server event covers a new default sink);
anything else (sink inputs, clients) is ignored. Events are coalesced: at most one re-read per
COALESCE seconds, so a fast scroll is not one `pactl` trio per notch. Unavailable when the pulse
server doesn't answer, idle when muted, active otherwise. Every other module's text is the zsh
controller's: a glyph by level and the percentage padded to four characters.

For an output segment the source also reads the sinks' properties (one `pactl -f json list
sinks`), but only when the default sink's name changes or a sink is added or removed, never on
a volume change. A `new` Bluetooth sink writes `<glyph> <name> connected` for NOTICE_FOR
seconds, a removed one `<name> disconnected`. With a Bluetooth sink the default, its battery is
read from BlueZ when it becomes the default and every BATTERY_EVERY seconds while it stays.

Nothing here changes the audio: the only pactl calls are `subscribe`, `get-default-sink`,
`get-sink-volume`, `get-sink-mute`, `-f json list sinks` and `list short sinks`, and the only
busctl call reads Battery1.Percentage. barctl never switches the default sink (open question 12):
WirePlumber decides, and the bar shows what is true. No sink or device name is logged.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Sequence

from desktop_tools.barctl import outputs
from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import Row
from desktop_tools.barctl.sources.base import Source
from desktop_tools.barctl.store import Writer
from desktop_tools.common import procs

VOL_OFF = "\U000f0581"  # md-volume_off: muted or no server
VOL_0 = "\uf026"  # fa-volume_off: a speaker without waves
VOL_LOW = "\uf027"  # fa-volume_low
VOL_HIGH = "\uf028"  # fa-volume_up

EVENT = re.compile(r"^Event '([^']*)' on (sink|server) #(\d+)")
PERCENT = re.compile(r"(\d+)%")
COALESCE = 0.1  # seconds: at most one re-read per this
NOTICE_FOR = 5.0  # seconds a connect or disconnect notice shows
BATTERY_EVERY = 300.0  # seconds between battery reads while a Bluetooth sink is the default


def glyph_for(volume: int) -> str:
    if volume == 0:
        return VOL_0
    return VOL_LOW if volume < 50 else VOL_HIGH


class VolumeSource(Source):
    name = "volume"
    commands = ("pactl",)

    def __init__(self, modules: Sequence[str], writer: Writer) -> None:
        super().__init__(modules, writer)
        self.lock = threading.RLock()
        self.clock: Callable[[], float] = time.time
        self.sinks: dict[int, outputs.Sink] = {}  # index -> sink, from the last listing
        self.relist = True  # the sinks' properties are to be read again
        self.default: str | None = None  # the default sink last seen
        self.battery: int | None = None
        self.battery_path = ""  # the BlueZ device the battery was read from
        self.battery_at = 0.0
        self.notice: tuple[str, float] | None = None  # (text, until)
        self.pending: list[tuple[str, str, int]] = []  # (event, facility, index) not yet read
        self.queue = threading.Lock()  # the stream's reader never waits on a query for this
        self.wake = threading.Event()

    def output_modules(self) -> list[str]:
        """The modules drawn as an output segment: only they need the sinks' properties."""
        return [
            name
            for name in self.modules
            if (m := self.writer.modules.get(name)) is not None and m.display == "output"
        ]

    # ------------------------------------------------------------ reading

    def current(self) -> outputs.Sink | None:
        return next((s for s in self.sinks.values() if s.name == self.default), None)

    def list_sinks(self) -> None:
        found = outputs.sinks()
        if found is not None:  # a failed read keeps the last listing and tries again next time
            self.sinks = {s.index: s for s in found}
            self.relist = False

    def read_battery(self, sink: outputs.Sink | None, now: float) -> None:
        if sink is None or not sink.bluetooth or not sink.path:
            self.battery, self.battery_path = None, ""
            return
        self.battery = outputs.battery(sink.path)
        self.battery_path, self.battery_at = sink.path, now

    def update(self) -> None:
        with self.lock:
            sink = procs.query(["pactl", "get-default-sink"])
            if not sink or not sink.strip():
                self.default = None
                self.set_all("unavailable", glyph=VOL_OFF)
                return
            out = procs.query(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]) or ""
            match = PERCENT.search(out)
            mute = procs.query(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]) or ""
            if not match:
                self.set_all("unavailable", glyph=VOL_OFF)
                return
            target = sink.strip()
            now = self.clock()
            moved, self.default = target != self.default, target
            if self.output_modules():
                if self.relist or moved:
                    self.list_sinks()
                shown = self.current()
                path = shown.path if shown is not None and shown.bluetooth else ""
                if path != self.battery_path:  # a Bluetooth sink became the default, or left
                    self.read_battery(shown, now)
            self.write(int(match.group(1)), "Mute: yes" in mute, target, now)

    def write(self, volume: int, muted: bool, target: str, now: float) -> None:
        tier = "idle" if muted else "active"
        shown = self.current()
        notice = self.notice if self.notice is not None and self.notice[1] > now else None
        for name in self.modules:
            module = self.writer.modules.get(name)
            if module is not None and module.display == "output":
                self.writer.set(
                    name,
                    self.name,
                    tier,
                    glyph=shown.glyph if shown is not None else outputs.SPEAKER,
                    label=shown.short if shown is not None else outputs.cut(target),
                    target=target,
                    output={"volume": volume, "battery": self.battery},
                    notice=notice[0] if notice else None,
                    notice_until=notice[1] if notice else None,
                    now=now,
                )
            else:
                glyph = VOL_OFF if muted else glyph_for(volume)
                label = f"{volume}%".ljust(4)
                self.writer.set(name, self.name, tier, glyph=glyph, label=label, target=target)

    def events(self, events: Sequence[tuple[str, str, int]]) -> None:
        """A batch of `pactl subscribe` events (coalesced): sinks added or removed re-read the
        sinks' properties for an output segment, a Bluetooth one with a notice; then the
        default sink is read again."""
        with self.lock:
            changed = [(e, i) for e, facility, i in events if facility == "sink" and e != "change"]
            if changed and self.output_modules():
                before = dict(self.sinks)
                self.relist = True
                self.list_sinks()
                now = self.clock()
                for event, index in changed:
                    if event == "new" and (s := self.sinks.get(index)) and s.bluetooth:
                        self.notice = (f"{s.glyph} {s.short} connected", now + NOTICE_FOR)
                    elif event == "remove" and (s := before.get(index)) and s.bluetooth:
                        self.notice = (f"{s.short} disconnected", now + NOTICE_FOR)
            self.update()

    def battery_due(self, now: float) -> float | None:
        """Seconds until the next battery read, while a Bluetooth sink is the default."""
        if not self.battery_path:
            return None
        return max(0.0, self.battery_at + BATTERY_EVERY - now)

    def refresh(self, now: float | None = None) -> bool:
        """Re-read the battery if a Bluetooth sink is the default and the last read is
        BATTERY_EVERY seconds old. Returns whether it read."""
        now = self.clock() if now is None else now
        with self.lock:
            due = self.battery_due(now)
            if due is None or due > 0:
                return False
            self.read_battery(self.current(), now)
            self.update()
            return True

    # ------------------------------------------------------------ following

    def _worker(self, done: threading.Event) -> None:
        """Reads what the stream's events asked for: at once after a quiet spell, then at most
        once per COALESCE seconds, and the battery on its timer."""
        last = 0.0
        while True:
            with self.lock:
                due = self.battery_due(self.clock())
            self.wake.wait(due)
            if done.is_set() or self.stopping:
                return
            if self.wake.is_set():
                gap = COALESCE - (time.monotonic() - last)
                if gap > 0 and done.wait(gap):
                    return
                self.wake.clear()
                with self.queue:
                    batch, self.pending = self.pending, []
                last = time.monotonic()
                if batch:
                    self.events(batch)
            else:
                self.refresh()

    def follow(self) -> None:
        with self.lock:
            self.sinks.clear()
            self.relist, self.default, self.notice = True, None, None
            self.battery, self.battery_path, self.pending = None, "", []
            self.wake.clear()
            self.update()
        done = threading.Event()
        worker = threading.Thread(
            target=self._worker, args=(done,), name="volume-events", daemon=True
        )
        worker.start()
        try:
            stream = self.stream(["pactl", "subscribe"])
            for line in stream.lines():
                if self.stopping:
                    return
                match = EVENT.match(line)
                if match:
                    with self.queue:
                        self.pending.append((match[1], match[2], int(match[3])))
                    self.wake.set()
        finally:
            done.set()
            self.wake.set()
            worker.join(3)

    def gone(self) -> None:
        with self.lock:
            self.default, self.notice = None, None
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

"""`crew guard`: keeps the shown coordinator docked, as coord's `coord-guard` did.

Started detached by every show, a singleton (its own lock: a second one exits at once). It reads
bspwm's node events and, once a crew window has had none for `CREW_GUARD_SETTLE` seconds (a
deadline, so other windows' events don't keep pushing it back), puts every shown crew window back
to floating and re-docks it to the stored side and width (`tick`). bspwm reports every motion
step of a pointer drag, and a re-dock then would fight the pointer, so a drag of a crew window,
between its pointer_action begin and end, holds the tick off. Adds and removes of any window are
looked at, since a new or closed window may be a coordinator. The guard exits once no crew window
is shown, giving back the strip of one that was closed rather than hidden.

A tick runs under the switch lock, which a show holds from before it hides the old panel until
after it shows the new one, so a guard never quits mid-swap, and a show after it quits finds the
guard lock free and starts a new one. `wm.place` moves and resizes only what differs, so the
events of a re-dock are answered by a no-op, never another move.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
import time
from collections.abc import Callable
from types import FrameType
from typing import Protocol

from desktop_tools.crew import conf, log, store, wm

EVENTS = ("node_add", "node_remove", "node_geometry", "node_state", "node_flag", "pointer_action")
EOF = object()


class Events(Protocol):
    def read(self, timeout: float | None) -> str | object | None:
        """The next line; None when `timeout` passed first; EOF when the stream ended."""


class Subscription:
    """`bspc subscribe` as a stream of lines, with a timeout on each read."""

    def __init__(self) -> None:
        # S603/S607: bspc with fixed arguments.
        self.proc = subprocess.Popen(  # noqa: S603
            ["bspc", "subscribe", *EVENTS],  # noqa: S607
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if self.proc.stdout is None:  # pragma: no cover - stdout=PIPE always gives one
            raise OSError("bspc subscribe has no output")
        self.fd = self.proc.stdout.fileno()
        self.buffer = b""

    def read(self, timeout: float | None) -> str | object | None:
        while b"\n" not in self.buffer:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                return None
            chunk = os.read(self.fd, 4096)
            if not chunk:
                return EOF
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return line.decode(errors="replace")

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.proc.stdout is not None:
            with contextlib.suppress(OSError):
                self.proc.stdout.close()


def tick(known: set[int]) -> bool:
    """One settled look: re-float and re-dock every shown crew window, and give back the strip
    of any monitor it left. Fills `known` with every crew window, hidden or not. False when none
    is shown (after giving every strip back): the guard's cue to exit."""
    try:
        with store.lock("switch"):
            tree = wm.look()
            known.clear()
            known.update(w.id for w in tree.crew())
            shown = tree.crew(shown_only=True)
            if not shown:
                # A panel closed rather than hidden leaves its strip reserved.
                wm.unpad()
                return False
            for win in shown:
                if not win.floating and not wm.run("node", win.node, "--state", "floating"):
                    log.warning(f"guard: cannot float {win.node}")
            with store.lock("dock"):
                wm.redock(store.width(), store.side())
                wm.unpad()
            return True
    except store.LockError as e:
        # Busy: a show or a width change is at work, and its own events bring the next tick.
        log.debug(f"guard: {e}")
        return True


def follow(
    events: Events,
    alive: Callable[[], bool],
    settle: float | None = None,
    look: Callable[[set[int]], bool] = tick,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """The guard's loop, until nothing is shown or bspwm is gone."""
    settle = conf.guard_settle() if settle is None else settle
    known: set[int] = set()
    dragging = False
    due: float | None = clock()  # a first look at once: fills known, quits if nothing is shown
    while True:
        if due is not None and not dragging:
            wait = due - clock()
            line = None if wait <= 0 else events.read(wait)
            if line is None:
                if not look(known):
                    return
                due = None
                # A read that ended before the deadline is the end of the stream: bspwm is gone.
                if not alive():
                    return
                continue
        else:
            line = events.read(None)
        if line is EOF or not isinstance(line, str):
            return
        fields = line.split()
        if not fields:
            continue
        event = fields[0]
        if event not in ("node_add", "node_remove"):
            node = wm.parse_id(fields[3]) if len(fields) > 3 else None
            if node not in known:
                continue
            if event == "pointer_action":
                dragging = len(fields) > 5 and fields[5] == "begin"
        due = clock() + settle


def _stop(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(143)


def main() -> int:
    """Run the guard; 0 at once when another holds the guard lock."""
    try:
        with store.lock("guard", wait=False):
            sub = Subscription()
            previous = {s: signal.signal(s, _stop) for s in (signal.SIGTERM, signal.SIGHUP)}
            try:
                follow(sub, sub.alive)
            finally:
                sub.close()
                for s, handler in previous.items():
                    signal.signal(s, handler)
    except store.LockError:
        return 0
    except OSError as e:
        log.error(f"guard: cannot follow bspwm: {e.strerror}")
        return 1
    return 0

"""`crew guard`: the settle deadline, the drag hold-off, the tick's re-dock, the singleton lock and
its exit once nothing is shown (coord's `coord-guard` and `_coord-guard-tick`)."""

from __future__ import annotations

import fcntl
import sys

import pytest

from desktop_tools.crew import guard, store
from tests.crew_fakes import Desk
from tests.fakes import run

NODE = "0x00C00001"
QUIET = "quiet"  # a read that times out: the settle deadline passes


class Script:
    """Events played to follow(): a line, QUIET (the timeout), then the end of the stream."""

    def __init__(self, *items: str) -> None:
        self.items = list(items)
        self.reads: list[float | None] = []

    def read(self, timeout: float | None) -> str | object | None:
        self.reads.append(timeout)
        if not self.items:
            return guard.EOF
        item = self.items.pop(0)
        return None if item == QUIET else item


class Looks:
    """A tick that records each call and answers from a list (True: keep going)."""

    def __init__(self, *answers: bool, known: tuple[int, ...] = (0x00C00001,)) -> None:
        self.answers, self.known, self.calls = list(answers), known, 0

    def __call__(self, known: set[int]) -> bool:
        self.calls += 1
        known.update(self.known)
        return self.answers.pop(0) if self.answers else True


def geometry(node: str = NODE) -> str:
    return f"node_geometry 0x00200002 0x00200064 {node} 800x600+0+0"


def test_first_look_at_once_and_quits_when_nothing_is_shown() -> None:
    events, look = Script(geometry()), Looks(False)
    guard.follow(events, lambda: True, settle=0.01, look=look)
    assert look.calls == 1
    assert events.reads == []


def test_settles_after_a_crew_windows_events() -> None:
    events = Script(geometry(), geometry(), QUIET)
    look = Looks(True, True, False)
    guard.follow(events, lambda: True, settle=0.01, look=look)
    assert look.calls == 2  # the first look, then one tick after the burst settled
    assert events.reads[0] is None  # nothing due after the first look: wait for an event


def test_other_windows_events_are_ignored() -> None:
    events = Script(geometry("0x00ABCDEF"), "node_flag 0x1 0x2 0x00ABCDEF hidden on")
    look = Looks(True)
    guard.follow(events, lambda: True, settle=0.01, look=look)
    assert look.calls == 1


def test_any_window_added_or_removed_is_looked_at() -> None:
    events = Script(
        "node_add 0x1 0x2 0x0 0x00ABCDEF", QUIET, "node_remove 0x1 0x2 0x00ABCDEF", QUIET
    )
    look = Looks(True, True, True)
    guard.follow(events, lambda: True, settle=0.01, look=look)
    assert look.calls == 3


def test_a_drag_holds_the_tick_off_until_it_ends() -> None:
    begin = f"pointer_action 0x1 0x2 {NODE} move begin"
    end = f"pointer_action 0x1 0x2 {NODE} move end"
    events = Script(begin, geometry(), geometry(), end, QUIET)
    look = Looks(True, True)
    guard.follow(events, lambda: True, settle=0.01, look=look)
    assert look.calls == 2
    # While dragging, reads wait for the next event with no deadline.
    assert events.reads[1:3] == [None, None]


def test_quits_when_bspwm_goes() -> None:
    events, look = Script(geometry(), QUIET, geometry()), Looks(True, True)
    alive = iter([True, False])
    guard.follow(events, lambda: next(alive), settle=0.01, look=look)
    assert look.calls == 2
    assert events.items == [geometry()]


def test_blank_lines_are_skipped() -> None:
    events, look = Script("", "   ", QUIET), Looks(True)
    guard.follow(events, lambda: True, settle=0.01, look=look)
    assert look.calls == 1


# ---------------------------------------------------------------- the tick


def test_tick_refloats_and_redocks_the_shown_one(desk: Desk) -> None:
    desk.window("desktop", hidden=False, floating=False, rect=(10, 10, 300, 300))
    desk.window("brain")
    known: set[int] = set()
    assert guard.tick(known) is True
    win = desk.windows()["desktop"]
    assert win["floating"] is True
    assert win["rect"] == [3840 - 5 - 1280, 5, 1278, 2148]
    assert desk.padding()["right"] == 1285
    assert known == {0x00C00001, 0x00C00002}


def test_tick_with_none_shown_gives_the_strip_back(desk: Desk) -> None:
    desk.window("desktop")
    d = desk.load()
    d["monitors"][0]["padding"]["right"] = 1285
    desk.save(d)
    assert guard.tick(set()) is False
    assert desk.padding()["right"] == 0


def test_tick_float_failure_warns(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    desk.window("desktop", hidden=False, floating=False)
    desk.fail("state")
    assert guard.tick(set()) is True
    assert f"guard: cannot float {NODE}" in capsys.readouterr().err


def test_tick_with_the_switch_lock_busy_waits_for_the_next(
    desk: Desk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "0")
    desk.window("desktop", hidden=False, rect=(10, 10, 300, 300))
    path = store.lock_path("switch")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert guard.tick(set()) is True
    assert desk.windows()["desktop"]["rect"][:2] == [10, 10]


# ---------------------------------------------------------------- the daemon


def test_guard_snaps_a_dragged_panel_back_and_exits(desk: Desk) -> None:
    desk.window("desktop", hidden=False, rect=(400, 300, 900, 700))
    desk.put("events", "\n".join([geometry(), "sleep 0.1", geometry()]))
    done = run([sys.executable, "-m", "desktop_tools.crew", "guard"], timeout=20)
    assert done.returncode == 0
    assert desk.windows()["desktop"]["rect"] == [2555, 5, 1278, 2148]
    assert ["bspc", "subscribe", *guard.EVENTS] in desk.calls("bspc")


def test_guard_with_nothing_shown_exits_at_once(desk: Desk) -> None:
    desk.window("desktop")
    assert guard.main() == 0


def test_a_second_guard_exits_at_once(desk: Desk) -> None:
    path = store.lock_path("guard")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert guard.main() == 0
    assert desk.calls("bspc") == []


def test_guard_without_bspc(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    (desk.base / "bin" / "bspc").unlink()
    assert guard.main() == 1
    assert "guard: cannot follow bspwm" in capsys.readouterr().err


def test_guard_stops_on_term(desk: Desk) -> None:
    import os
    import signal
    import subprocess
    import time

    desk.window("desktop", hidden=False)
    desk.put("events", "sleep 30")
    proc = subprocess.Popen(
        [sys.executable, "-m", "desktop_tools.crew", "guard"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while not any(c[1:2] == ["subscribe"] for c in desk.calls("bspc")):
        assert time.monotonic() < deadline, "the guard never subscribed"
        time.sleep(0.05)
    time.sleep(0.2)
    os.kill(proc.pid, signal.SIGTERM)
    assert proc.wait(10) == 143

"""The dock: width and side (tests/coordinators.zsh's "dock width" cases), placement on bspwm's gap
model, and the one-time copy of coord's settings. A width set but not printed (sxhkd's stdout gone)
is not a failure, and every failure path says why (the coord-width fix, dotfiles issue #81)."""

from __future__ import annotations

import fcntl
import os
import pty
import subprocess
import sys
from pathlib import Path

import pytest

from desktop_tools.crew import conf, store, switch, wm
from tests.crew_fakes import MONITOR, Desk, monitor
from tests.fakes import run

CREW = [sys.executable, "-m", "desktop_tools.crew"]


def crew(*args: str, stdout: object = None) -> subprocess.CompletedProcess[str]:
    """crew as sxhkd runs it; stdout may be a file that fails every write (/dev/full)."""
    if stdout is None:
        return run([*CREW, *args])
    return run([*CREW, *args], capture_output=False, stdout=stdout, stderr=subprocess.PIPE)


def width_file() -> int:
    return int((conf.state_dir() / "width").read_text())


@pytest.mark.parametrize("shown", [False, True])
@pytest.mark.parametrize(("edge", "want"), [("left", 1408), ("right", 1152)])
def test_width_with_stdout_unwritable(desk: Desk, shown: bool, edge: str, want: int) -> None:
    """coordinators.zsh: width-<edge>-stdout-unwritable[-shown]."""
    if shown:
        desk.window("desktop", hidden=False)
    with open("/dev/full", "w") as full:
        done = crew("width", edge, stdout=full)
    assert (done.returncode, done.stderr) == (0, "")
    assert width_file() == want


@pytest.mark.parametrize("shown", [False, True])
@pytest.mark.parametrize("edge", ["left", "right"])
def test_width_on_a_dead_pty(desk: Desk, shown: bool, edge: str) -> None:
    """coordinators.zsh: width-<edge>-dead-pty[-shown]: stdin, stdout and stderr on a pty whose
    master is closed, as sxhkd's are once the terminal that started it has gone (EIO)."""
    if shown:
        desk.window("desktop", hidden=False)
    master, slave = pty.openpty()
    os.close(master)
    try:
        done = subprocess.run([*CREW, "width", edge], stdin=slave, stdout=slave, stderr=slave)  # noqa: S603
    finally:
        os.close(slave)
    assert done.returncode == 0


def test_width_and_side_print(desk: Desk) -> None:
    """coordinators.zsh: width-and-side-print."""
    desk.window("desktop", hidden=False)
    done = crew("width", "left")
    assert (done.returncode, done.stdout) == (0, "1408\n")
    with open("/dev/full", "w") as full:
        got = crew("side", stdout=full)
        assert got.returncode == 1
        assert "side: could not print the side (right) to stdout" in got.stderr
        assert crew("side", "left", stdout=full).returncode == 0
    assert crew("side").stdout == "left\n"


def test_width_get_logs(desk: Desk) -> None:
    """coordinators.zsh: width-get-logs."""
    with open("/dev/full", "w") as full:
        done = crew("width", stdout=full)
    assert done.returncode == 1
    assert "width: could not print the width (1280) to stdout" in done.stderr
    assert crew("width").stdout == "1280\n"


@pytest.mark.parametrize(
    ("args", "why"),
    [
        (["abc"], "width: expected +N, -N, N, left [N] or right [N], got 'abc'"),
        (["+-3"], "got '+-3'"),
        (["100", "5"], "got '100'"),
        (["left", "x"], "width: expected a step N after 'left', got 'x'"),
    ],
)
def test_width_usage_logs(desk: Desk, args: list[str], why: str) -> None:
    """coordinators.zsh: width-clamp-logs (a width that isn't a number says why)."""
    done = crew("width", *args)
    assert done.returncode == 1 and why in done.stderr


@pytest.mark.parametrize(
    ("args", "want"),
    [(["99999"], 2560), (["1"], 640), (["+100"], 1380), (["-100"], 1180), (["right", "7"], 1273)],
)
def test_width_set_and_clamped(desk: Desk, args: list[str], want: int) -> None:
    assert switch.width(*args) == 0
    assert store.width() == want


def test_width_lock_open_logs(desk: Desk, isolate: Path) -> None:
    """coordinators.zsh: width-lock-open-logs."""
    conf.runtime().parent.mkdir(parents=True, exist_ok=True)
    conf.runtime().write_text("not a folder")
    done = crew("width", "left")
    assert done.returncode == 1
    assert f"lock: cannot open {conf.runtime()}/dock.lock" in done.stderr
    assert "width: cannot take the dock lock" in done.stderr


def test_width_lock_busy_logs(desk: Desk, monkeypatch: pytest.MonkeyPatch) -> None:
    """coordinators.zsh: width-lock-busy-logs."""
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "0")
    path = store.lock_path("dock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done = crew("width", "left")
        side = crew("side", "left")
    assert done.returncode == 1
    assert "dock lock busy after 0s" in done.stderr
    assert "width: cannot take the dock lock" in done.stderr
    assert side.returncode == 1 and "side: cannot take the dock lock" in side.stderr


def test_width_file_logs(desk: Desk) -> None:
    """coordinators.zsh: width-file-logs: the state folder can't be written."""
    conf.state_dir().parent.mkdir(parents=True, exist_ok=True)
    conf.state_dir().write_text("not a folder")
    done = crew("width", "left")
    assert done.returncode == 1
    assert f"width: cannot write 1408 to {conf.state_dir()}/width" in done.stderr
    side = crew("side", "left")
    assert side.returncode == 1 and "side: cannot write left to" in side.stderr


def test_width_place_padding_logs(desk: Desk) -> None:
    """coordinators.zsh: width-place-padding-logs."""
    desk.window("desktop", hidden=False)
    desk.fail("padding")
    done = crew("width", "left")
    assert done.returncode == 1
    assert "place: cannot set right_padding 1413 on 0x00200002" in done.stderr
    assert "redock: cannot place desktop (0x00C00001) at 1408 on the right" in done.stderr
    assert "width: set to 1408, but a shown coordinator was not re-docked" in done.stderr
    side = crew("side", "left")
    assert side.returncode == 1
    assert "side: set to left, but a shown coordinator was not re-docked" in side.stderr


def test_place_to_monitor_logs(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    """coordinators.zsh: place-to-monitor-logs."""
    d = desk.load()
    d["monitors"].append(monitor(0x00200003, "N", x=3840))
    desk.save(d)
    desk.window("desktop", monitor_id=0x00200003)
    desk.fail("tomonitor")
    win = wm.look().crew()[0]
    assert wm.place(win, 1280, "right", MONITOR) is False
    assert "place: cannot move 0x00C00001 to monitor 0x00200002" in capsys.readouterr().err


def test_place_focused_logs(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    """coordinators.zsh: place-focused-logs."""
    desk.window("desktop")
    d = desk.load()
    d["focused_monitor"] = None
    desk.save(d)
    win = wm.look().crew()[0]
    assert wm.place(win, 1280, "right") is False
    assert "place: no focused monitor for 0x00C00001" in capsys.readouterr().err


def test_place_release_failure_logs(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    desk.window("desktop")
    d = desk.load()
    d["monitors"][0]["padding"]["left"] = 7
    desk.save(d)
    (desk.base / "bin" / "bspc").write_text(
        (desk.base / "bin" / "bspc")
        .read_text()
        .replace(
            'm["padding"][side] = int(args[4])',
            'm["padding"][side] = int(args[4])\n        if side == "left": sys.exit(1)',
        )
    )
    assert wm.place(wm.look().crew()[0], 1280, "right") is False
    assert "place: cannot release left_padding on 0x00200002" in capsys.readouterr().err


def test_place_move_and_resize_failures_warn_only(
    desk: Desk, capsys: pytest.CaptureFixture[str]
) -> None:
    desk.window("desktop")
    desk.fail("move", "resize")
    assert wm.place(wm.look().crew()[0], 1280, "right") is True
    err = capsys.readouterr().err
    assert "place: cannot resize 0x00C00001 to 1278x2148" in err
    assert "place: cannot move 0x00C00001 to 2555,5" in err


def test_place_respects_padding_and_gapless_monocle(desk: Desk) -> None:
    desk.window("desktop")
    d = desk.load()
    d["monitors"][0].update(
        {"padding": {"top": 30, "right": 0, "bottom": 0, "left": 0}, "layout": "monocle"}
    )
    d["gapless"] = "true"
    desk.save(d)
    assert wm.place(wm.look().crew()[0], 1000, "left") is True
    assert desk.windows()["desktop"]["rect"] == [0, 30, 998, 2160 - 30 - 2]
    assert desk.padding()["left"] == 1000


def test_no_bspwm_is_an_empty_desktop(desk: Desk) -> None:
    desk.fail("dump")
    assert wm.dump() is None
    assert wm.look().windows == []
    (desk.base / "bin" / "bspc").unlink()
    assert wm.run("node", "x") is False


def test_side_is_checked_and_redocks(desk: Desk) -> None:
    desk.window("desktop", hidden=False)
    assert switch.side("up") == 1
    assert switch.side("left") == 0
    assert desk.windows()["desktop"]["rect"][0] == 5
    assert desk.padding()["left"] == 1285 and desk.padding()["right"] == 0


def test_bad_stored_values_fall_back(isolate: Path) -> None:
    conf.state_dir().mkdir(parents=True)
    (conf.state_dir() / "width").write_text("wide")
    (conf.state_dir() / "side").write_text("up")
    assert (store.width(), store.side()) == (1280, "right")
    (conf.state_dir() / "width").write_text("99999")
    assert store.width() == 2560


def test_coords_settings_are_copied_once(isolate: Path) -> None:
    coord = conf.coord_state_dir()
    coord.mkdir(parents=True)
    (coord / "width").write_text("1536\n")
    (coord / "side").write_text("left\n")
    (coord / "last").write_text("media\n")
    assert (store.width(), store.side(), store.last()) == (1536, "left", "media")
    assert (conf.state_dir() / store.COPIED_MARK).exists()
    # Once only: crew's own values win from then on, and coord's are left as they were.
    store.set_width(900)
    (conf.state_dir() / "side").unlink()
    assert (store.width(), store.side()) == (900, "right")
    assert (coord / "width").read_text() == "1536\n"


def test_crews_own_settings_are_never_overwritten(isolate: Path) -> None:
    coord = conf.coord_state_dir()
    coord.mkdir(parents=True)
    (coord / "width").write_text("1536\n")
    store.set_width(700)  # crew already has one
    assert store.copy_from_coord() == []
    assert store.width() == 700


def test_copy_failure_warns(isolate: Path, capsys: pytest.CaptureFixture[str]) -> None:
    conf.state_dir().parent.mkdir(parents=True, exist_ok=True)
    conf.state_dir().write_text("not a folder")
    assert store.copy_from_coord() == []
    assert "state: cannot copy coord's settings" in capsys.readouterr().err


def test_last_write_failure_warns(isolate: Path, capsys: pytest.CaptureFixture[str]) -> None:
    conf.state_dir().parent.mkdir(parents=True, exist_ok=True)
    conf.state_dir().write_text("not a folder")
    store.set_last("brain")
    assert "state: cannot write the last shown (brain)" in capsys.readouterr().err

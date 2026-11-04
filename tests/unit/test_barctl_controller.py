"""The controller: one at a time, its sources, the control socket, alert and ttl timers, and a
clean stop (ported from tests/barctl.zsh's `run` cases)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from desktop_tools.barctl import control, ops
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.controller import AlreadyRunning, Controller
from desktop_tools.barctl.sources import Source
from tests import fakes
from tests.fakes import FakeBar
from tests.unit.test_barctl_sources import Feed

MODULES = """
[modules.ticker]
source = "volume"
[modules.crew]
pusher = "crew"
"""


class Ticker(Source):
    """A source that writes once and then waits until stopped, or fails on demand."""

    name = "volume"
    fail: type[BaseException] | None = None

    def follow(self) -> None:
        if self.fail is not None:
            raise self.fail("boom")
        self.set_all("active", glyph="T")
        while not self.stopping:
            time.sleep(0.02)


@pytest.fixture
def config(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, mods.Module]:
    path = isolate / "modules.toml"
    path.write_text(MODULES)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    return mods.load()


@pytest.fixture
def running(config: dict[str, mods.Module]) -> Iterator[tuple[Controller, list[str]]]:
    pokes: list[str] = []
    controller = Controller(config, retry=0.05, poke=pokes.append, sources={"volume": Ticker})
    controller.log = lambda message: None
    thread = threading.Thread(target=controller.run, daemon=True)
    thread.start()
    end = time.monotonic() + 3
    while control.request("ping") is None and time.monotonic() < end:
        time.sleep(0.02)
    yield controller, pokes
    controller.stop_event.set()
    thread.join(3)
    assert not thread.is_alive()


def wait_for(check: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_runs_sources_and_answers(running: tuple[Controller, list[str]]) -> None:
    controller, pokes = running
    assert wait_for(lambda: "ticker" in pokes)
    answer = control.request("ping")
    assert answer is not None and answer["sources"] == ["volume"]
    assert st.controller() is not None
    with pytest.raises(AlreadyRunning):
        Controller(controller.modules, sources={}).acquire()


def test_push_and_alert_go_through_the_controller(running: tuple[Controller, list[str]]) -> None:
    _, pokes = running
    ops.push("crew", {"tier": "active"}, source="crew", ttl=0.3)
    assert wait_for(lambda: pokes.count("crew") >= 1)
    # The ttl runs out: the controller redraws it once more.
    assert wait_for(lambda: pokes.count("crew") >= 2, timeout=2)
    before = pokes.count("crew")
    assert ops.alert("crew", 1.2) == "blinking"
    time.sleep(1.5)
    blinks = pokes.count("crew") - before
    assert 3 <= blinks <= 6, blinks  # one per half second, then once when it ends


def test_settings_and_reload(
    running: tuple[Controller, list[str]], config: dict[str, mods.Module]
) -> None:
    controller, _ = running
    ops.enable("ticker", False)
    assert wait_for(lambda: "volume" not in controller.running)
    ops.enable("ticker", True)
    assert wait_for(lambda: "volume" in controller.running)
    assert ops.reload() == ["crew", "ticker"]
    assert control.request("nonsense") == {"ok": False, "error": "unknown request 'nonsense'"}
    assert controller.handle([]) == {"ok": False, "error": "a request is a JSON object"}


def test_reload_with_a_broken_config(running: tuple[Controller, list[str]], isolate: Path) -> None:
    (isolate / "modules.toml").write_text("[broken")
    answer = control.request("reload")
    assert answer is not None and answer["ok"] is False


def test_a_source_that_ends_is_restarted_and_marked_unavailable(
    config: dict[str, mods.Module],
) -> None:
    class Once(Source):
        name = "volume"
        runs = 0

        def follow(self) -> None:
            Once.runs += 1
            self.set_all("active", glyph="O")

    pokes: list[str] = []
    controller = Controller(config, retry=0.05, poke=pokes.append, sources={"volume": Once})
    controller.log = lambda message: None
    thread = threading.Thread(target=controller.run, daemon=True)
    thread.start()
    assert wait_for(lambda: Once.runs >= 3)
    assert st.source_health("volume")["state"] == "failing"  # it keeps ending at once
    controller.stop_event.set()
    thread.join(3)


def test_a_crashing_source_stops_the_controller(config: dict[str, mods.Module]) -> None:
    class Crash(Ticker):
        fail = RuntimeError

    controller = Controller(config, retry=0.01, poke=lambda m: None, sources={"volume": Crash})
    assert controller.run() == 1
    assert st.controller() is None  # cleaned up


def test_a_missing_command_is_retried(config: dict[str, mods.Module]) -> None:
    class Missing(Ticker):
        fail = FileNotFoundError

    logged: list[str] = []
    controller = Controller(config, retry=0.01, poke=lambda m: None, sources={"volume": Missing})
    controller.log = logged.append
    thread = threading.Thread(target=controller.run, daemon=True)
    thread.start()
    assert wait_for(lambda: len(logged) >= 4)
    controller.stop_event.set()
    thread.join(3)
    assert not controller.failed.is_set()


def test_tick_without_anything_to_do(config: dict[str, mods.Module]) -> None:
    controller = Controller(config, poke=lambda m: None, sources={})
    assert controller.tick(now=100.0) == 1.0
    controller.expiries["crew"] = 100.5
    assert controller.tick(now=100.0) == pytest.approx(0.5)


# ---------------------------------------------------------------- the real process


@pytest.fixture
def streams(isolate: Path, commands: Callable[..., Path]) -> tuple[Path, Path, Path]:
    """pactl and playerctl as in the zsh tests: files and FIFOs the test writes."""
    pa = isolate / "pa"
    pa.mkdir()
    for name in ("pa.fifo", "pl.fifo"):
        os.mkfifo(isolate / name)
    players = isolate / "players"
    players.write_text("")
    commands(
        pactl=f"""
P = {str(pa)!r}
if args[0] == 'subscribe':
    os.execvp('cat', ['cat', here + '/pa.fifo'])
elif args[0] == 'get-default-sink':
    print('alsa_output.test')
elif args[0] == 'get-sink-volume':
    print('Volume: front-left: 1 /  ' + open(P + '/vol').read().strip() + '% / 0 dB')
elif args[0] == 'get-sink-mute':
    print('Mute: ' + open(P + '/mute').read().strip())
""",
        playerctl=f"""
if args == ['-l']:
    print(open({str(players)!r}).read(), end='')
else:
    os.execvp('cat', ['cat', here + '/pl.fifo'])
""",
    )
    (pa / "vol").write_text("35")
    (pa / "mute").write_text("no")
    return isolate / "pa.fifo", isolate / "pl.fifo", players


def test_run_as_a_process(
    isolate: Path, bar: FakeBar, streams: tuple[Path, Path, Path], theme: dict[str, str]
) -> None:
    """Ported: run-pokes-all, run-status, run-single, run-player-event, run-stops,
    run-cleans-up, status-not-running."""
    pa, pl, players = streams
    env = {**os.environ, "TOOL_JOURNAL": "off"}
    barctl = [sys.executable, "-m", "desktop_tools.barctl"]
    proc = fakes.start([*barctl, "run"], env=env, stderr=subprocess.PIPE, text=True)
    feeds = [Feed(pa), Feed(pl)]
    try:
        assert sorted(bar.wait(3)) == ["audio-level", "player-metadata", "player-play-pause"]
        status = fakes.run([*barctl, "status"], env=env, capture_output=True, text=True)
        assert f"controller: running (pid {proc.pid}" in status.stdout
        assert "audio-level" in status.stdout and "active" in status.stdout
        assert status.returncode == 0, status.stdout
        second = fakes.run([*barctl, "run"], env=env, capture_output=True, text=True)
        assert second.returncode == 1 and "already running" in second.stderr

        players.write_text("mpv\n")
        bar.clear()
        feeds[1].line("\x1f".join(["mpv", "mpv", "Playing", "a", "b"]))
        assert sorted(bar.wait(2)) == ["player-metadata", "player-play-pause"]
        assert (st.read("player-play-pause") or {})["tier"] == "active"

        proc.send_signal(signal.SIGTERM)
        assert proc.wait(5) == 0
        time.sleep(0.3)
        left = fakes.run(["pgrep", "-f", f"cat {isolate}"], capture_output=True, text=True)
        assert left.stdout == ""
        assert not st.pid_path().exists() and not control.path().exists()
        status = fakes.run([*barctl, "status"], env=env, capture_output=True, text=True)
        assert "controller: not running" in status.stdout and status.returncode == 1
    finally:
        for feed in feeds:
            feed.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stderr is not None:
            proc.stderr.close()

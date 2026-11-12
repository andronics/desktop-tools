"""The visualiser strip (record 0005 phase D): the capsule's `visualiser*` keys, the strip's
frame, when it may show, cava's config and lines, the seek, the title over the strip, frames
sent to each bar's own socket (newest line only, an identical frame not sent again), cava
stopped while paused or expanded, the switch over the key, the CPU budget guard with fake
readings, cava's restart limit, cava missing, the controller's pokes becoming frames, `barctl
visualiser` and doctor's line.

No audio and no bar: cava is a fake that prints the frames a test scripts (the real one is a
tripwire on PATH), and the bars are fake polybar sockets in the test's runtime folder. Every
fake cava started is stopped by its PID, and each test checks none is left.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from desktop_tools.barctl import doctor, ops, render
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl import visualiser as vis
from desktop_tools.barctl.app import app as barctl_app
from desktop_tools.barctl.controller import Controller
from tests.fakes import FakeBar

runner = CliRunner()

CONFIG = """
[modules.player-capsule]
source = "player"
display = "capsule"
glyph_override = { idle = "I", active = "A" }
width = 8
visualiser = true
visualiser_title = 5
expand_for = 5

[modules.player-capsule.clicks]
left = ["playerctl", "-p", "{target}", "play-pause"]

[modules.player-capsule.icon_clicks]
left = ["barctl", "expand", "player-capsule"]

[modules.player-plain]
source = "player"
display = "capsule"
"""
COLOURS = {
    "unavailable": "#111111",
    "idle": "#222222",
    "active": "#333333",
    "alert": "#444444",
    "underline": "#555555",
}
NAME = "player-capsule"
# The fake cava: it notes its pid, prints the chunks its script gives (each one or more
# lines), then waits to be stopped, or exits.
CAVA = r"""
script = json.load(open(os.path.join(here, "cava.json")))
with open(os.path.join(here, "cava.pids"), "a") as fh:
    fh.write(f"{os.getpid()}\n")
for chunk in script["chunks"]:
    sys.stdout.write(chunk)
    sys.stdout.flush()
    time.sleep(script.get("gap", 0))
if script.get("then") == "exit":
    sys.exit(1)
while True:
    time.sleep(1)
"""


def playing(now: float, **extra: Any) -> st.State:
    state: st.State = {
        "tier": "active",
        "glyph": "P",
        "label": "Artist - Title",
        "label_since": now - 100,
        "target": "spotify",
        "progress": {"position": 50.0, "length": 200.0, "rate": 1.0, "at": now, "playing": True},
        "updated": now,
    }
    state.update(extra)
    return state


def wait_for(check: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


def glyphs(line: str) -> str:
    """A line's text without its tags."""
    return re.sub(r"%\{[^}]*\}", "", line)


def sends(bar: FakeBar) -> list[str]:
    return [a for a in bar.actions() if ".send." in a]


def gone(pid: int) -> bool:
    return not alive(pid)


def ended(strip: vis.Strip) -> bool:
    return strip.ended


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def config(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, mods.Module]:
    path = isolate / "modules.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    return mods.load()


@pytest.fixture
def cava(isolate: Path, commands: Callable[..., Path]) -> Iterator[Callable[..., list[list[str]]]]:
    """Script the fake cava: cava(chunks, gap=, then=) -> its calls so far. On teardown, every
    fake cava that ran must be gone."""
    log = commands(cava=CAVA)

    def script(chunks: list[str], gap: float = 0.0, then: str = "wait") -> list[list[str]]:
        (isolate / "cava.json").write_text(json.dumps({"chunks": chunks, "gap": gap, "then": then}))
        return [c for c in (json.loads(x) for x in log.read_text().splitlines()) if c[0] == "cava"]

    script([])
    yield script
    pids = isolate / "cava.pids"
    for pid in [int(x) for x in pids.read_text().split()] if pids.exists() else []:
        assert wait_for(partial(gone, pid)), f"fake cava {pid} left running"


@pytest.fixture
def made(
    config: dict[str, mods.Module],
    theme: dict[str, str],
    cava: Callable[..., list[list[str]]],
) -> Iterator[tuple[vis.Visualiser, list[str], list[str]]]:
    """A Visualiser with recorded pokes and journal lines; stopped (cava by its PID) after."""
    pokes: list[str] = []
    logs: list[str] = []
    found = vis.Visualiser(config, poke=pokes.append, log=logs.append)
    yield found, pokes, logs
    found.stop()


def cava_pids(isolate: Path) -> list[int]:
    path = isolate / "cava.pids"
    return [int(x) for x in path.read_text().split()] if path.exists() else []


# ---------------------------------------------------------------- the keys


def test_keys_default_off_and_rate_15(config: dict[str, mods.Module]) -> None:
    plain = config["player-plain"]
    assert plain.visualiser is False
    assert (plain.visualiser_fps, plain.visualiser_title, plain.visualiser_budget) == (15, 5, 6)
    assert config[NAME].visualiser is True
    shown = config[NAME].as_dict()
    assert shown["visualiser"] is True and shown["visualiser_fps"] == 15


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("visualiser = 1", "visualiser must be true or false"),
        ("visualiser_fps = 4", "visualiser_fps must be 5 to 30"),
        ("visualiser_fps = 31", "visualiser_fps must be 5 to 30"),
        ("visualiser_fps = 15.5", "visualiser_fps must be a whole number"),
        ("visualiser_title = 31", "visualiser_title must be 0 to 30"),
        ("visualiser_budget = 0.5", "visualiser_budget must be 1 to 25"),
        ("visualiser_budget = 26", "visualiser_budget must be 1 to 25"),
        ('visualiser_budget = "6"', "visualiser_budget must be a number"),
    ],
)
def test_bad_keys_are_load_errors(line: str, error: str) -> None:
    import tomllib

    raw = tomllib.loads(f'[modules.c]\nsource = "player"\ndisplay = "capsule"\n{line}\n')
    with pytest.raises(mods.ConfigError, match=error):
        mods.parse(raw)


def test_budget_takes_a_fraction() -> None:
    import tomllib

    raw = tomllib.loads(
        '[modules.c]\nsource = "player"\ndisplay = "capsule"\nvisualiser_budget = 2.5\n'
    )
    assert mods.parse(raw)["c"].visualiser_budget == 2.5


def test_packaged_modules_turn_nothing_on() -> None:
    packaged = mods.load(mods.PACKAGED)
    assert not any(m.visualiser for m in packaged.values())
    text = mods.PACKAGED.read_text()
    assert "# visualiser = false" in text
    assert not any(line.startswith("visualiser") for line in text.splitlines())


# ---------------------------------------------------------------- the frame


def test_strip_draws_blocks_in_two_colours_with_the_underline(
    config: dict[str, mods.Module],
) -> None:
    module = config[NAME]
    now = 1000.0
    state = playing(now)  # 50 of 200 s: two of the eight cells underlined
    line = render.strip(module, state, now, COLOURS, [0, 1, 2, 7, 7, 3, 1, 0])
    accent = COLOURS["underline"]
    assert line.startswith("%{A3:barctl click player-capsule right:}")
    assert "%{A1:barctl click player-capsule left:}" in line
    assert f"%{{A1:barctl click player-capsule left --segment icon:}}%{{F{accent}}}A" in line
    # Low levels (0-1) in fg_dim, the rest in the accent; runs of one colour joined.
    assert f"%{{u{accent}}}%{{+u}}%{{F{COLOURS['idle']}}}▁▂%{{F-}}%{{-u}}" in line
    assert f"%{{F{accent}}}▃██▄%{{F-}}" in line
    assert f"%{{F{COLOURS['idle']}}}▂▁%{{F-}}" in line
    assert COLOURS["alert"] not in line
    visible = "".join(c for c in line if c in render.LEVELS)
    assert visible == "▁▂▃██▄▂▁"


def test_strip_fills_and_cuts_to_the_width(config: dict[str, mods.Module]) -> None:
    module = config[NAME]
    state = playing(1000.0, progress=None)
    short = render.strip(module, state, 1000.0, COLOURS, [7])
    assert "".join(c for c in short if c in render.LEVELS) == "█▁▁▁▁▁▁▁"
    long = render.strip(module, state, 1000.0, COLOURS, [9] * 20)
    assert "".join(c for c in long if c in render.LEVELS) == "█" * 8
    assert "%{+u}" not in long  # a stream: no progress, no underline


def test_strip_never_takes_the_alert_colour(config: dict[str, mods.Module]) -> None:
    state = playing(1000.0, alert_until=2000.0)
    line = render.strip(config[NAME], state, 1000.25, COLOURS, [7] * 8)
    assert COLOURS["alert"] not in line.split("A%{F-}", 1)[1]


def test_strip_takes_the_arts_colour(isolate: Path) -> None:
    module = mods.Module("c", source="player", display="capsule", width=8, accent="art")
    state = playing(1000.0, accent="#abcdef", progress=None)
    line = render.strip(module, state, 1000.0, COLOURS, [7] * 8)
    assert "%{F#abcdef}████████%{F-}" in line


@pytest.mark.parametrize(
    ("change", "shows"),
    [
        ({}, True),
        ({"tier": "idle"}, False),  # paused
        ({"tier": "unavailable"}, False),  # no player
        ({"expanded_until": 1003.0}, False),  # the transport row is open
        ({"segments": [{"id": "x", "tier": "idle", "label": "x"}]}, False),
        ({"expires": 999.0}, False),  # stale
    ],
)
def test_when_the_strip_may_show(
    config: dict[str, mods.Module], change: dict[str, Any], shows: bool
) -> None:
    assert render.strip_shows(config[NAME], playing(1000.0, **change), 1000.0) is shows
    assert render.strip_shows(config["player-plain"], playing(1000.0), 1000.0) is False
    assert render.strip_shows(config[NAME], None, 1000.0) is False


def test_faded_capsule_stands_aside() -> None:
    module = mods.Module("c", source="player", display="capsule", visualiser=True, fade_after=1)
    paused = playing(1000.0, tier="idle", status_at=900.0)
    assert render.faded(module, paused, 1000.0)
    assert not render.strip_shows(module, paused, 1000.0)


# ---------------------------------------------------------------- cava's side


def test_cava_config(config: dict[str, mods.Module]) -> None:
    text = vis.cava_conf(config[NAME])
    for line in (
        "framerate = 15",
        "bars = 8",
        "method = pipewire",
        "source = auto",
        "method = raw",
        "raw_target = /dev/stdout",
        "data_format = ascii",
        "ascii_max_range = 7",
        "channels = mono",
    ):
        assert f"\n{line}\n" in text


def test_levels_of_a_line() -> None:
    assert vis.levels(b"0;3;7;9;\n") == [0, 3, 7, 7]
    assert vis.levels(b"") is None
    assert vis.levels(b"1;x;2;") is None


def test_seek_is_a_jump_on_the_same_track() -> None:
    before = playing(1000.0)
    on = playing(1010.0, progress={**before["progress"], "position": 60.0, "at": 1010.0})
    jumped = playing(1010.0, progress={**before["progress"], "position": 150.0, "at": 1010.0})
    other = {**jumped, "label": "Another - Track"}
    assert not vis.seeked(before, on)
    assert vis.seeked(before, jumped)
    assert not vis.seeked(before, other)  # a new track is the label's change, not a seek
    assert not vis.seeked(None, jumped)


def test_title_shows_over_the_strip_after_a_track_change_and_a_seek(
    config: dict[str, mods.Module],
) -> None:
    strip = vis.Strip(config[NAME], "cava", COLOURS, dict, time.time)
    now = 1000.0
    strip.state = playing(now, label_since=now - 2)
    assert strip.title_on(now)
    frame = strip.frame([7] * 8, now)
    assert "Tit" in glyphs(frame) and "█" not in frame
    strip.state = playing(now, label_since=now - 6)
    assert not strip.title_on(now)
    assert "█" in strip.frame([7] * 8, now)
    strip.seek_at = now - 1
    assert strip.title_on(now)
    module = mods.Module(
        "c", source="player", display="capsule", visualiser=True, visualiser_title=0
    )
    never = vis.Strip(module, "cava", COLOURS, dict, time.time)
    never.state = playing(now, label_since=now)
    assert not never.title_on(now)


# ---------------------------------------------------------------- frames to the bars


def test_frames_go_to_each_bars_own_socket(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
    isolate: Path,
) -> None:
    found, pokes, _ = made
    other = FakeBar(isolate / "xdg" / "runtime" / "polybar", pid=4343)
    try:
        cava(["1;2;3;4;5;6;7;0;\n"])
        st.write(NAME, playing(time.time()))
        found.sync()
        assert found.drawing(NAME)
        assert wait_for(lambda: bool(sends(bar) and sends(other)))
        line = sends(bar)[0]
        assert line.startswith(f"#{NAME}.send.%{{A3:barctl click {NAME} right:}}")
        assert f"%{{A1:barctl click {NAME} left:}}" in line
        assert sends(other) == [line]
        assert glyphs(line) == f"#{NAME}.send.A ▂▃▄▅▆▇█▁"
        calls = cava([])
        assert calls[-1] == ["cava", "-p", str(vis.conf_path())]
        assert "bars = 8" in vis.conf_path().read_text()
        assert pokes == []  # nothing is poked while the strip draws
        assert not [a for a in bar.actions() if ".hook." in a]
    finally:
        found.stop()
        other.close()


def test_only_the_newest_line_is_drawn_and_repeats_are_not_sent(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
) -> None:
    found, _, _ = made
    burst = "".join(f"{i % 8};0;0;0;0;0;0;0;\n" for i in range(60)) + "7;7;7;7;7;7;7;7;\n"
    cava([burst, "7;7;7;7;7;7;7;7;\n", "7;7;7;7;7;7;7;7;\n"], gap=0.1)
    st.write(NAME, playing(time.time()))
    found.sync()
    assert wait_for(lambda: len(sends(bar)) >= 1)
    time.sleep(0.5)
    sent = sends(bar)
    assert len(sent) == 1, sent  # 61 lines at once: one frame, the newest; repeats skipped
    assert glyphs(sent[0]) == f"#{NAME}.send.A ████████"


def test_paused_stops_cava_and_draws_the_capsule(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
    isolate: Path,
) -> None:
    found, pokes, _ = made
    cava(["7;7;7;7;7;7;7;7;\n"])
    st.write(NAME, playing(time.time()))
    found.sync()
    assert wait_for(lambda: bool(cava_pids(isolate)))
    pid = cava_pids(isolate)[0]
    st.write(NAME, playing(time.time(), tier="idle"))
    found.sync()
    assert not found.drawing(NAME)
    assert not alive(pid)  # stopped by its PID, and reaped
    assert pokes == [NAME]  # one ordinary poke draws the capsule again
    found.sync()
    assert pokes == [NAME] and len(cava_pids(isolate)) == 1  # nothing polls or restarts


def test_expanded_stands_aside(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
) -> None:
    found, pokes, _ = made
    st.write(NAME, playing(time.time()))
    found.sync()
    assert found.drawing(NAME)
    st.write(NAME, playing(time.time(), expanded_until=time.time() + 5))
    found.sync()
    assert not found.drawing(NAME) and pokes == [NAME]


def test_disabled_module_never_starts(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
) -> None:
    found, _, _ = made
    st.set_enabled(NAME, False)
    st.write(NAME, playing(time.time()))
    found.sync()
    assert not found.drawing(NAME) and cava([]) == []


def test_off_switch_wins_over_the_key_and_on_lifts_it(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
) -> None:
    found, pokes, logs = made
    st.write(NAME, playing(time.time()))
    found.sync()
    assert found.drawing(NAME)
    assert st.set_visualiser(False)
    found.reset()
    assert not found.drawing(NAME) and pokes == [NAME]
    assert st.visualiser_switch()["reason"] == "switch"
    assert logs == []  # the user's own switch: no journal line
    assert st.set_visualiser(True)
    found.reset()
    assert found.drawing(NAME)
    # Survives a restart: it is in the settings file, beside the disabled modules.
    st.set_visualiser(False)
    assert json.loads(st.settings_path().read_text())["visualiser"]["on"] is False


def test_on_never_starts_a_capsule_without_the_key(isolate: Path) -> None:
    module = mods.Module("c", source="player", display="capsule")
    st.set_visualiser(True)
    found = vis.Visualiser({"c": module}, poke=lambda m: None, log=lambda m: None)
    st.write("c", playing(time.time()))
    found.sync()
    assert not found.drawing("c")


# ---------------------------------------------------------------- the guards


def test_budget_guard_turns_the_strip_off_after_three_samples(
    config: dict[str, mods.Module],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
    theme: dict[str, str],
) -> None:
    clock = [0.0]
    used = [0.0]
    pokes: list[str] = []
    logs: list[str] = []
    found = vis.Visualiser(
        config,
        poke=pokes.append,
        log=logs.append,
        cpu=lambda: used[0],
        monotonic=lambda: clock[0],
    )
    try:
        st.write(NAME, playing(time.time()))
        found.sync()
        found.guard()  # the first reading
        # 5% of a core (under the 6% budget), then 7% twice, 5% (the count starts again),
        # then 7% three times: off on the third.
        for percent, still in ((5, True), (7, True), (7, True), (5, True), (7, True), (7, True)):
            clock[0] += vis.SAMPLE
            used[0] += percent / 100 * vis.SAMPLE
            found.guard()
            assert found.drawing(NAME) is still
        clock[0] += 3  # not yet another sample: nothing changes
        used[0] += 1
        found.guard()
        assert found.drawing(NAME)
        clock[0] += vis.SAMPLE
        used[0] += 0.7
        found.guard()
        assert not found.drawing(NAME)
        assert logs == ["visualiser off: over its CPU budget"]
        assert st.visualiser_switch()["reason"] == "budget"
        assert pokes == [NAME]
        found.sync()
        assert not found.drawing(NAME)  # stays off until `barctl visualiser on`
    finally:
        found.stop()


def test_guard_counts_only_while_the_strip_runs(
    config: dict[str, mods.Module], theme: dict[str, str]
) -> None:
    clock = [0.0]
    found = vis.Visualiser(
        config, poke=lambda m: None, log=lambda m: None, cpu=lambda: 99.0, monotonic=lambda: 0
    )
    for _ in range(5):
        clock[0] += vis.SAMPLE
        found.guard()
    assert found.sample is None and found.over == 0


def test_cava_exiting_three_times_turns_it_off(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
) -> None:
    found, _, logs = made
    cava(["7;7;7;7;7;7;7;7;\n"], then="exit")
    st.write(NAME, playing(time.time()))
    for _ in range(3):
        found.sync()
        strip = found.strip
        assert strip is not None
        assert wait_for(partial(ended, strip))
    found.sync()
    assert not found.drawing(NAME)
    assert logs == ["visualiser off: cava exited 3 times in 5 minutes"]
    assert len(cava([])) == 3


def test_cava_exiting_twice_restarts_it(
    made: tuple[vis.Visualiser, list[str], list[str]],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
) -> None:
    found, _, logs = made
    cava(["7;7;7;7;7;7;7;7;\n"], then="exit")
    st.write(NAME, playing(time.time()))
    found.sync()
    for _ in range(2):
        strip = found.strip
        assert strip is not None and wait_for(partial(ended, strip))
        found.sync()
    assert found.drawing(NAME) and logs == []


def test_cava_missing_turns_it_off(
    made: tuple[vis.Visualiser, list[str], list[str]], isolate: Path
) -> None:
    found, _, logs = made
    (isolate / "bin" / "cava").unlink()  # the tripwire: no cava anywhere on PATH
    st.write(NAME, playing(time.time()))
    found.sync()
    assert not found.drawing(NAME)
    assert logs == ["visualiser off: cava is not installed"]
    found.sync()
    assert logs == ["visualiser off: cava is not installed"]  # one line, not one a tick


# ---------------------------------------------------------------- the controller


def test_controller_pokes_become_frames(
    config: dict[str, mods.Module],
    cava: Callable[..., list[list[str]]],
    bar: FakeBar,
    theme: dict[str, str],
) -> None:
    pokes: list[str] = []
    controller = Controller(config, poke=pokes.append, sources={})
    controller.log = lambda message: None
    try:
        cava(["7;7;7;7;7;7;7;7;\n"])
        st.write(NAME, playing(time.time()))
        controller._poke(NAME)  # a source's write: the strip starts and draws it
        assert controller.visualiser.drawing(NAME)
        controller._poke(NAME)
        controller.tick()
        controller._poke("player-plain")
        assert pokes == ["player-plain"]
        answer = controller.handle({"op": "ping"})
        assert answer["visualiser"]["drawing"] == NAME
        st.set_visualiser(False)
        answer = controller.handle({"op": "visualiser"})
        assert answer["ok"] and answer["drawing"] is None
        assert pokes == ["player-plain", NAME]
        st.set_visualiser(True)
        controller.handle({"op": "visualiser"})
        assert controller.visualiser.drawing(NAME)
    finally:
        controller.shutdown()
    assert not controller.visualiser.drawing(NAME)


# ---------------------------------------------------------------- the verb and doctor


def test_visualiser_verb(
    config: dict[str, mods.Module], monkeypatch: pytest.MonkeyPatch, isolate: Path
) -> None:
    from desktop_tools.barctl import control

    asked: list[str] = []

    def request(op: str, **fields: object) -> None:
        asked.append(op)

    monkeypatch.setattr(control, "request", request)
    r = runner.invoke(barctl_app, ["visualiser", "off"])
    assert r.exit_code == 0, r.output
    assert "visualiser: off (turned off with barctl visualiser off since" in r.output
    assert st.visualiser_off() and "visualiser" in asked
    r = runner.invoke(barctl_app, ["visualiser", "on"])
    assert r.exit_code == 0
    assert "visualiser: on for player-capsule (the controller is not running)" in r.output
    r = runner.invoke(barctl_app, ["visualiser", "status", "--json"])
    data = json.loads(r.output)
    assert data["state"] == "on" and data["switch"] == "on" and data["modules"] == [NAME]
    r = runner.invoke(barctl_app, ["visualiser", "sideways"])
    assert r.exit_code == 2
    with pytest.raises(ops.Failure):
        ops.visualiser("sideways")


def test_status_with_no_capsule_asking(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = isolate / "modules.toml"
    path.write_text('[modules.c]\nsource = "player"\ndisplay = "capsule"\n')
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    data = ops.visualiser("status")
    assert data["state"] == "off" and data["why"] == "no capsule has visualiser = true"


@pytest.mark.parametrize(
    ("reason", "state", "words"),
    [
        ("switch", "ok", "off: turned off with barctl visualiser off"),
        ("budget", "warn", "off: over its CPU budget"),
        ("cava-missing", "warn", "off: cava is not installed"),
        ("cava-exits", "warn", "off: cava exited 3 times in 5 minutes"),
    ],
)
def test_doctor_says_why_it_is_off(
    config: dict[str, mods.Module], reason: str, state: str, words: str
) -> None:
    st.set_visualiser(False, reason)
    check = doctor.visualiser_check(config)
    assert check["state"] == state and check["detail"].startswith(words)
    assert ("barctl visualiser on" in check["fix"]) is (state != "ok")


def test_doctor_on_and_off_by_the_key(config: dict[str, mods.Module], isolate: Path) -> None:
    check = doctor.visualiser_check(config)
    assert check["detail"] == "on for player-capsule: needs cava"
    assert check["state"] == "ok"  # the test PATH's cava tripwire counts as installed
    (isolate / "bin" / "cava").unlink()
    check = doctor.visualiser_check(config)
    assert check["state"] == "warn" and "install cava" in check["fix"]
    plain = {"player-plain": config["player-plain"]}
    assert doctor.visualiser_check(plain)["detail"] == "off: no capsule has visualiser = true"
    assert any(c["name"] == "visualiser" for c in doctor.checks())


def test_cpu_reads_cava_from_proc(isolate: Path, config: dict[str, mods.Module]) -> None:
    ticks = os.sysconf("SC_CLK_TCK")
    folder = isolate / "proc" / "777"
    folder.mkdir()
    # pid (comm with a space) state ppid ... utime stime: fields 14 and 15.
    folder.joinpath("stat").write_text(
        f"777 (ca va) S 1 1 1 0 -1 0 0 0 0 0 {3 * ticks} {ticks} 0 0 20 0 1 0 0\n"
    )
    assert vis.proc_cpu(777) == 4.0
    assert vis.proc_cpu(778) is None
    found = vis.Visualiser(config, poke=lambda m: None, log=lambda m: None)
    found.cava_cpu[777] = 4.0  # a cava that has ended still counts
    own = os.times()
    assert found.cpu() >= own.user + own.system + 4.0


def test_a_config_write_failure_is_not_cava_missing(
    made: tuple[vis.Visualiser, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found, _, logs = made

    def broken(self: vis.Strip) -> Path:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(vis.Strip, "write_conf", broken)
    st.write(NAME, playing(time.time()))
    found.sync()
    found.sync()
    assert not found.drawing(NAME) and not st.visualiser_off()
    assert logs == [f"visualiser: can't write {vis.conf_path()}: Permission denied"]


def test_a_guard_holds_the_strip_off_when_settings_cant_be_written(
    made: tuple[vis.Visualiser, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found, _, logs = made
    st.write(NAME, playing(time.time()))
    found.sync()
    assert found.drawing(NAME)

    def broken(*args: object) -> bool:
        raise OSError(28, "No space left on device")

    real = st.set_visualiser
    monkeypatch.setattr(st, "set_visualiser", broken)
    found.turn_off("budget")
    found.sync()
    assert not found.drawing(NAME)
    assert logs == [
        "visualiser: can't write the settings: No space left on device",
        "visualiser off: over its CPU budget",
    ]
    monkeypatch.setattr(st, "set_visualiser", real)
    found.reset()  # `barctl visualiser on` lifts it
    assert found.drawing(NAME)


def test_candidates_hold_the_controllers_lock(config: dict[str, mods.Module]) -> None:
    import threading

    lock = threading.RLock()
    found = vis.Visualiser(config, poke=lambda m: None, log=lambda m: None, modules_lock=lock)
    taken: list[bool] = []
    real = lock.__enter__

    class Spy:
        def __enter__(self) -> None:
            taken.append(True)
            real()

        def __exit__(self, *exc: object) -> None:
            lock.release()

    found.modules_lock = Spy()  # type: ignore[assignment]  # records that the lock was taken
    assert [m.name for m in found.candidates()] == [NAME]
    assert taken == [True]


def test_settings_writers_dont_lose_each_others_changes(isolate: Path) -> None:
    import threading

    def flip(i: int) -> None:
        st.set_enabled(f"m{i}", False)
        st.set_visualiser(i % 2 == 0, now=float(i))

    threads = [threading.Thread(target=flip, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert st.disabled() == {f"m{i}" for i in range(20)}

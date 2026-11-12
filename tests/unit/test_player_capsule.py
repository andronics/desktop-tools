"""The player capsule (record 0003 §1-9): its modules.toml keys, the `progress` and `accent`
state fields, the capsule's render (padding, scroll, progress line, accent), the controller's
tick, the player source's new fields and its pin, the art accent, the `player` and `players`
menus, and the environment rule.

No player, no bar: playerctl, curl and magick are fakes. The fake playerctl fails the test if it
is ever asked to control a player (play, pause, play-pause, stop, next, previous, a position
with a value, a loop or shuffle mode, or volume), so no source or provider code can.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from desktop_tools.barctl import art, control, doctor, ops, render
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.app import app as barctl_app
from desktop_tools.barctl.controller import Controller
from desktop_tools.barctl.sources import PlayerSource
from desktop_tools.barctl.sources.player import FORMAT, US, seconds
from desktop_tools.barctl.store import Writer, shown
from desktop_tools.barmenu import cli as barmenu_cli
from desktop_tools.barmenu import menus as bm
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.providers import player as player_menu
from desktop_tools.barmenu.providers import players as players_menu
from desktop_tools.common import procs
from tests.fakes import calls

runner = CliRunner()

CONFIG = """
[modules.player-capsule]
source = "player"
display = "capsule"
glyph = "N"
glyph_override = { active = "P", idle = "Z", unavailable = "N" }
width = 10
scroll = 2.0
scroll_rest = 10

[modules.player-capsule.clicks]
left = ["playerctl", "-p", "{target}", "play-pause"]
middle = ["playerctl", "-p", "{target}", "next"]
scroll-up = ["playerctl", "-p", "{target}", "volume", "0.05+"]
scroll-down = ["playerctl", "-p", "{target}", "volume", "0.05-"]
right = ["barmenu", "player"]

[modules.player-art]
source = "player"
display = "capsule"
accent = "art"

[modules.player-metadata]
source = "player"
display = "text"

[modules.player-both]
source = "player"
display = "both"

[modules.audio-level]
source = "volume"
display = "both"
"""
ROLES = {"dim": "#111111", "fg_dim": "#222222", "accent": "#333333", "urgent": "#444444"}
COLOURS = {"unavailable": "#111111", "idle": "#222222", "active": "#333333", "alert": "#444444"}
COLOURS = {**COLOURS, "underline": "#333333"}
LABEL = "abcdefghijklmnop"  # 16 characters in a 10-cell capsule: it scrolls

# A fake playerctl's first lines: any command that would control a player is logged and fails.
GUARD = """
CONTROL = {'play', 'pause', 'play-pause', 'stop', 'next', 'previous', 'volume'}
rest = list(args)
while rest and rest[0].startswith('-'):
    opt = rest.pop(0)
    if opt in ('-p', '--player', '-i', '--ignore-player') and rest:
        rest.pop(0)
verb = rest[0] if rest else ''
if verb in CONTROL or (verb in ('position', 'loop', 'shuffle') and len(rest) > 1):
    open(here + '/controlled', 'a').write(' '.join(args) + '\\n'); sys.exit(1)
"""


@pytest.fixture
def config(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, mods.Module]]:
    path = isolate / "modules.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    yield mods.load()
    assert not (isolate / "controlled").exists(), (isolate / "controlled").read_text()


@pytest.fixture
def playerctl(isolate: Path, commands: Callable[..., Path]) -> Callable[..., Path]:
    """A guarded fake playerctl: `listing` is `-l`'s output, `positions` instance -> seconds,
    `metadata` instance -> the `metadata --format` line (fields joined with |)."""

    def make(
        listing: str = "",
        positions: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
        sleep: float = 0,
    ) -> Path:
        (isolate / "listing").write_text(listing)
        body = (
            GUARD
            + f"""
import json
positions = {positions or {}!r}
metadata = {metadata or {}!r}
time.sleep({sleep})
if args == ['-l']:
    print(open(here + '/listing').read(), end='')
elif args[0] == '-p' and args[2:] == ['position'] and args[1] in positions:
    print(positions[args[1]])
elif args[0] == '-p' and args[2:4] == ['metadata', '--format'] and args[1] in metadata:
    print(metadata[args[1]].replace('|', '\\x1f'))
else:
    sys.exit(1)
"""
        )
        return commands(playerctl=body)

    return make


def capsule(config: dict[str, mods.Module]) -> mods.Module:
    return config["player-capsule"]


def visible(line: str) -> str:
    """What polybar shows: the tags gone, an escaped `%%{` back to `%{`, the break gone."""
    return re.sub(r"(?<!%)%\{[^}]*\}", "", line).replace("%%{", "%{").replace(render.BREAK, "")


def playing(**extra: Any) -> st.State:
    return {
        "tier": "active",
        "label": LABEL,
        "label_since": 100.0,
        "target": "spotify",
        **extra,
    }


def progress(position: float = 60, length: float | None = 120, at: float = 100.0) -> st.State:
    return {"position": position, "length": length, "rate": 1.0, "at": at, "playing": True}


# ---------------------------------------------------------------- modules.toml (§2)


def test_capsule_keys_default(isolate: Path) -> None:
    found = mods.parse({"modules": {"c": {"source": "player", "display": "capsule"}}})["c"]
    assert (found.width, found.scroll, found.scroll_rest, found.accent) == (32, 2.0, 10.0, "role")
    assert found.as_dict()["width"] == 32
    assert "width" not in mods.parse({"modules": {"t": {"source": "player"}}})["t"].as_dict()


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("width", 7, "width must be 8 to 80"),
        ("width", 81, "width must be 8 to 80"),
        ("width", 3.5, "width must be a whole number"),
        ("width", True, "width must be a whole number"),
        ("scroll", -1, "scroll must be 0 to 4"),
        ("scroll", 4.5, "scroll must be 0 to 4"),
        ("scroll", "fast", "scroll must be a number"),
        ("scroll_rest", 121, "scroll_rest must be 0 to 120"),
        ("scroll_rest", [], "scroll_rest must be a number"),
        ("accent", "blue", "accent is one of role, art"),
        ("accent", 3, "accent must be a string"),
    ],
)
def test_capsule_key_errors_name_the_key(key: str, value: object, message: str) -> None:
    raw = {"source": "player", "display": "capsule", key: value}
    with pytest.raises(mods.ConfigError, match=f"modules.c: {re.escape(message)}"):
        mods.parse({"modules": {"c": raw}})


def test_capsule_keys_are_read_only_for_a_capsule() -> None:
    found = mods.parse({"modules": {"t": {"source": "player", "display": "text", "width": 999}}})
    assert found["t"].width == 32


def test_the_packaged_file_keeps_its_player_entries_and_the_example_is_commented() -> None:
    packaged = mods.load(mods.PACKAGED)
    assert {"player-play-pause", "player-metadata"} <= set(packaged)
    assert "player-capsule" not in packaged
    assert "# [modules.player-capsule]" in mods.PACKAGED.read_text()


# ---------------------------------------------------------------- state (§5)


def test_progress_and_accent_validated() -> None:
    clean = st.validate({"progress": progress(length=None), "accent": "#A0B1C2"})
    assert clean["progress"] == {
        "position": 60.0,
        "length": None,
        "rate": 1.0,
        "at": 100.0,
        "playing": True,
    }
    assert clean["accent"] == "#a0b1c2"


@pytest.mark.parametrize(
    "bad",
    [
        {"accent": "#fff"},
        {"accent": "red"},
        {"accent": "#12345g"},
        {"accent": "%{F#fff}"},
        {"accent": "#12%{ab"},
        {"progress": [1, 2]},
        {"progress": {**progress(), "position": -1}},
        {"progress": {**progress(), "length": "long"}},
        {"progress": {**progress(), "rate": 99}},
        {"progress": {**progress(), "at": None}},
        {"progress": {**progress(), "playing": "yes"}},
        {"progress": {**progress(), "position": float("nan")}},
    ],
)
def test_bad_progress_and_accent_are_state_errors(bad: dict[str, object]) -> None:
    field = next(iter(bad))
    with pytest.raises(st.StateError, match=field):
        st.validate(bad)


# ---------------------------------------------------------------- render (§1, §3)


def test_capsule_pads_to_its_width(config: dict[str, mods.Module]) -> None:
    line = render.render(
        capsule(config), playing(label="short"), now=100.0, colours=COLOURS, controller=True
    )
    assert visible(line) == "P " + "short".ljust(10)
    assert "%{A1:barctl click player-capsule left:}" in line
    assert "%{A3:barctl click player-capsule right:}" in line


@pytest.mark.parametrize(
    ("now", "text"),
    [
        (100.0, "abcdefghij"),  # the start of a pass
        (102.6, "fghijklmno"),  # mid pass: 5 steps at 2 a second
        (109.4, " abcdefghi"),  # the end: through the gap, the start coming round
        (110.0, "abcdefghij"),  # resting at the start
        (119.0, "abcdefghij"),  # still resting
        (120.1, "bcdefghijk"),  # the next pass
    ],
)
def test_scroll_offset_at_chosen_times(
    config: dict[str, mods.Module], now: float, text: str
) -> None:
    line = render.render(capsule(config), playing(), now=now, colours=COLOURS, controller=True)
    assert visible(line) == f"P {text}"


@pytest.mark.parametrize("why", ["paused", "scroll 0"])
def test_no_scroll_paused_or_with_scroll_0_cuts_with_an_ellipsis(
    config: dict[str, mods.Module], why: str
) -> None:
    module = capsule(config)
    state = playing()
    if why == "paused":
        state["tier"] = "idle"
    else:
        module.scroll = 0
    for now in (100.0, 102.6, 109.4):
        line = render.render(module, state, now=now, colours=COLOURS, controller=True)
        assert visible(line) == ("Z " if why == "paused" else "P ") + "abcdefghi…"
    assert render.next_change(module, state, 100.0) is None


def test_progress_underlines_its_cells(config: dict[str, mods.Module]) -> None:
    state = playing(label="short", progress=progress())
    line = render.render(capsule(config), state, now=100.0, colours=COLOURS, controller=True)
    assert "%{u#333333}%{+u}short%{-u}     " in line  # half of 120 s: 5 of 10 cells
    later = render.render(capsule(config), state, now=112.0, colours=COLOURS, controller=True)
    assert "%{u#333333}%{+u}short %{-u}    " in later  # 72 s: 6 cells
    paused = {**state, "progress": {**progress(), "playing": False}}
    still = render.render(capsule(config), paused, now=150.0, colours=COLOURS, controller=True)
    assert "%{+u}short%{-u}" in still  # paused: the position doesn't move


def test_no_line_without_a_length_or_a_player(config: dict[str, mods.Module]) -> None:
    stream = playing(label="radio", progress=progress(length=None))
    line = render.render(capsule(config), stream, now=100.0, colours=COLOURS, controller=True)
    assert "%{+u}" not in line
    nobody = render.render(capsule(config), None, now=100.0, colours=COLOURS, controller=True)
    assert visible(nobody) == "N" and "%{+u}" not in nobody
    assert nobody.count("%{F#111111}") == 1  # the icon alone, dim


def test_the_accent_is_on_the_line_and_icon_never_the_text(
    config: dict[str, mods.Module],
) -> None:
    state = playing(label="short", glyph="G", progress=progress(), accent="#abcdef")
    line = render.render(config["player-art"], state, now=100.0, colours=COLOURS, controller=True)
    assert "%{F#abcdef}" in line  # the icon
    assert "%{u#abcdef}%{+u}" in line  # the line
    assert "%{F#333333}%{u#abcdef}" in line  # the text keeps the role colour
    role = render.render(capsule(config), state, now=100.0, colours=COLOURS, controller=True)
    assert "#abcdef" not in role  # accent = "role" ignores the art's colour
    bad = {**state, "accent": "%{A1:x:}"}
    hacked = render.render(config["player-art"], bad, now=100.0, colours=COLOURS, controller=True)
    assert "%{A1:x:}" not in hacked


def test_a_title_is_escaped_even_where_it_is_cut(config: dict[str, mods.Module]) -> None:
    whole = render.render(
        capsule(config), playing(label="%{F#f00}x"), now=100.0, colours=COLOURS, controller=True
    )
    assert "%%{F#f00}x" in whole and visible(whole) == "P %{F#f00}x "
    state = playing(label="ab%{F#0}c", progress=progress(position=30))
    line = render.render(capsule(config), state, now=100.0, colours=COLOURS, controller=True)
    # The line ends after 3 cells, between `%` and `{`: the break after the `%` keeps the
    # `%{-u}` that follows a tag, and the `{` after it is plain text.
    assert f"%{{+u}}ab%{render.BREAK}%{{-u}}{{F#0}}c " in line
    assert visible(line) == "P ab%{F#0}c "


def test_text_and_both_still_cut_to_40(config: dict[str, mods.Module]) -> None:
    state = playing(label="x" * 60, glyph="G")
    text = visible(render.render(config["player-metadata"], state, now=1.0, colours=COLOURS))
    both = visible(render.render(config["player-both"], state, now=1.0, colours=COLOURS))
    assert text == "x" * 39 + "…"
    assert both == "G " + "x" * 39 + "…"


def test_shown_ignores_the_position(config: dict[str, mods.Module]) -> None:
    module = capsule(config)
    state = playing(progress=progress())
    moved = playing(progress=progress(position=90, at=130.0))
    assert shown(module, state, 100.0) == shown(module, moved, 100.0)
    assert shown(module, state, 100.0) != shown(module, playing(progress=progress(length=200)))
    stopped = playing(progress={**progress(), "playing": False})
    assert shown(module, state, 100.0) != shown(module, stopped, 100.0)


# ---------------------------------------------------------------- the controller's tick (§3)


def test_next_change_while_scrolling_at_a_cell_and_both(config: dict[str, mods.Module]) -> None:
    module = capsule(config)
    # Scrolling (no length): the next step, half a second on.
    assert render.next_change(module, playing(), 100.0) == pytest.approx(100.5)
    assert render.next_change(module, playing(), 100.7) == pytest.approx(101.0)
    # A title that fits: the next progress cell, 66 s into 120 (5.5 of 10 cells).
    fits = playing(label="short", progress=progress())
    assert render.next_change(module, fits, 100.0) == pytest.approx(106.0)
    # Both, while resting: the progress cell comes before the next pass.
    both = playing(progress=progress())
    assert render.next_change(module, both, 110.0) == pytest.approx(118.0)
    # Mid pass the step alone counts: every step redraws the line too.
    assert render.next_change(module, both, 101.2) == pytest.approx(101.5)


def test_never_more_than_scroll_a_second_nor_progress_more_than_once(
    config: dict[str, mods.Module],
) -> None:
    module = capsule(config)
    state = playing(progress=progress(position=0, length=5))  # a cell every half second
    for start in (100.0, 110.0):
        now, wakes = start, []
        while now < start + 10:
            nxt = render.next_change(module, state, now)
            assert nxt is not None and nxt > now
            wakes.append(nxt - now)
            now = nxt
        assert min(wakes) >= 1 / module.scroll - 1e-9
    fits = playing(label="short", progress=progress(position=0, length=5))
    assert render.next_change(module, fits, 100.0) == pytest.approx(101.0)


def test_no_wake_for_a_paused_or_empty_capsule(config: dict[str, mods.Module]) -> None:
    module = capsule(config)
    paused = {**playing(progress={**progress(), "playing": False}), "tier": "idle"}
    assert render.next_change(module, paused, 100.0) is None
    assert render.next_change(module, None, 100.0) is None
    assert render.next_change(module, {"tier": "unavailable"}, 100.0) is None
    assert render.next_change(config["player-metadata"], playing(), 100.0) is None


def test_the_tick_pokes_a_capsule_when_its_frame_changes(config: dict[str, mods.Module]) -> None:
    pokes: list[str] = []
    controller = Controller(config, poke=pokes.append, sources={})
    st.write("player-capsule", playing())
    assert controller.tick(now=100.0) == pytest.approx(0.52)
    assert pokes == []  # first sight: the source's write already drew it
    controller.tick(now=100.25)
    assert pokes == []  # the same frame
    controller.tick(now=100.52)
    assert pokes == ["player-capsule"]
    st.write("player-capsule", {**playing(), "tier": "idle"})
    pokes.clear()
    assert controller.tick(now=101.0) == 1.0  # paused: nothing moves
    assert controller.tick(now=105.0) == 1.0
    assert pokes == ["player-capsule"]  # the cut title once, then nothing
    st.set_enabled("player-capsule", False)
    assert controller.tick(now=106.0) == 1.0


# ---------------------------------------------------------------- the source (§5)


@pytest.fixture
def source(config: dict[str, mods.Module]) -> tuple[PlayerSource, list[str], list[float]]:
    pokes: list[str] = []
    clock = [1000.0]
    found = PlayerSource(["player-capsule", "player-metadata"], Writer(config, pokes.append))
    found.clock = lambda: clock[0]
    return found, pokes, clock


def line(*fields: str) -> str:
    return US.join(fields)


def test_the_format_has_length_and_art() -> None:
    assert FORMAT.split(US)[5:7] == ["{{mpris:length}}", "{{mpris:artUrl}}"]
    assert seconds("240000000") == 240.0
    assert seconds("") is None and seconds("0") is None and seconds("x") is None


def test_progress_on_an_event_and_the_30_second_reread(
    source: tuple[PlayerSource, list[str], list[float]],
    playerctl: Callable[..., Path],
    isolate: Path,
) -> None:
    found, pokes, clock = source
    log = playerctl("spotify\n", positions={"spotify": "12.5"})
    found.event(line("spotify", "spotify", "Playing", "Massive Attack", "Teardrop", "240000000"))
    state = st.read("player-capsule") or {}
    assert state["label"] == "Massive Attack \u2013 Teardrop"
    assert state["progress"] == {
        "position": 12.5,
        "length": 240.0,
        "rate": 1.0,
        "at": 1000.0,
        "playing": True,
    }
    assert state["label_since"] == 1000.0
    assert sorted(pokes) == ["player-capsule", "player-metadata"]
    assert ["playerctl", "-p", "spotify", "position"] in calls(log)

    pokes.clear()
    clock[0] = 1010.0
    assert found.refresh() is False  # not 30 s yet
    clock[0] = 1031.0
    playerctl("spotify\n", positions={"spotify": "43.6"})
    assert found.refresh() is True
    state = st.read("player-capsule") or {}
    assert (state["progress"]["position"], state["progress"]["at"]) == (43.6, 1031.0)
    assert state["label_since"] == 1000.0  # the same title: its scroll clock is kept
    assert pokes == []  # only position and at changed: nothing to redraw

    found.event(line("spotify", "spotify", "Paused", "Massive Attack", "Teardrop", "240000000"))
    assert sorted(pokes) == ["player-capsule", "player-metadata"]
    clock[0] = 1100.0
    assert found.refresh() is False  # paused: no re-read


def test_a_failed_position_read_waits_like_a_good_one(
    source: tuple[PlayerSource, list[str], list[float]], playerctl: Callable[..., Path]
) -> None:
    found, _, clock = source
    log = playerctl("radio\n")
    found.event(line("radio", "radio", "Playing", "", "A Stream", ""))
    assert "progress" not in (st.read("player-capsule") or {})
    clock[0] = 1005.0
    assert found.refresh() is False
    reads = [c for c in calls(log) if c[-1] == "position"]
    assert len(reads) == 1


def test_the_source_never_controls_a_player(
    source: tuple[PlayerSource, list[str], list[float]],
    playerctl: Callable[..., Path],
    isolate: Path,
) -> None:
    """The guard itself: it catches a control verb, and the source's calls never trip it."""
    found, _, clock = source
    log = playerctl(
        "spotify\nmpv\n",
        positions={"spotify": "1", "mpv": "2"},
        metadata={"mpv": "mpv|mpv|Paused|a|b|1000000|"},
    )
    found.event(line("spotify", "spotify", "Playing", "a", "b", "1000000"))
    clock[0] = 2000.0
    found.refresh()
    found.pin("mpv")
    found.pin(None)
    found.prune()
    for argv in calls(log):
        assert argv[0] == "playerctl"
    assert not (isolate / "controlled").exists()
    procs.query(["playerctl", "-p", "spotify", "position", "10+"])
    assert (isolate / "controlled").read_text() == "-p spotify position 10+\n"
    (isolate / "controlled").unlink()


# ---------------------------------------------------------------- the pin (§5)


def test_a_pinned_player_beats_a_playing_one_until_it_goes(
    source: tuple[PlayerSource, list[str], list[float]],
    playerctl: Callable[..., Path],
    isolate: Path,
) -> None:
    found, _, _ = source
    playerctl(
        "spotify\nmpv\n",
        positions={"spotify": "1", "mpv": "2"},
        metadata={"mpv": "mpv|mpv|Paused|An|Other|60000000|"},
    )
    found.event(line("spotify", "spotify", "Playing", "a", "b", "1000000"))
    assert found.pick() == "spotify"
    assert found.pin("mpv") == "mpv"
    state = st.read("player-capsule") or {}
    assert (state["target"], state["tier"], state["label"]) == ("mpv", "idle", "An \u2013 Other")
    found.event(line("spotify", "spotify", "Playing", "a", "c", "1000000"))
    assert found.pick() == "mpv"
    with pytest.raises(LookupError, match="no player 'vlc'"):
        found.pin("vlc")
    (isolate / "listing").write_text("spotify\n")
    found.event(line("spotify", "spotify", "Playing", "a", "d", "1000000"))
    assert (found.pinned, found.pick()) == (None, "spotify")  # mpv went: the pin with it
    playerctl("spotify\nmpv\n", metadata={"mpv": "mpv|mpv|Paused|An|Other||"})
    found.pin("mpv")
    assert found.pin(None) is None and found.pick() == "spotify"  # --auto


def test_the_controller_holds_the_pin(
    config: dict[str, mods.Module],
    source: tuple[PlayerSource, list[str], list[float]],
    playerctl: Callable[..., Path],
) -> None:
    found, _, _ = source
    playerctl("spotify\n", positions={"spotify": "1"})
    controller = Controller(config, poke=lambda m: None, sources={})
    assert controller.handle({"op": "pin", "module": "player-capsule", "instance": "spotify"}) == {
        "ok": False,
        "error": "the player source is not running",
    }
    controller.running["player"] = (found, threading.Thread(target=lambda: None))
    answer = controller.handle({"op": "pin", "module": "player-capsule", "instance": "spotify"})
    assert answer == {"ok": True, "pinned": "spotify"}
    assert controller.handle({"op": "ping"})["pinned"] == {"player": "spotify"}
    assert controller.handle({"op": "pin", "module": "player-capsule", "instance": None}) == {
        "ok": True,
        "pinned": None,
    }
    for request, error in (
        ({"module": "audio-level", "instance": "x"}, "audio-level is not drawn by the player"),
        ({"module": "nope", "instance": "x"}, "unknown module 'nope'"),
        ({"module": "player-capsule", "instance": 3}, "instance is a player's name"),
        ({"module": "player-capsule", "instance": "vlc"}, "no player 'vlc'"),
    ):
        answer = controller.handle({"op": "pin", **request})
        assert answer["ok"] is False and str(answer["error"]).startswith(error)


def test_barctl_pin_on_the_command_line(
    config: dict[str, mods.Module], monkeypatch: pytest.MonkeyPatch
) -> None:
    refused = runner.invoke(barctl_app, ["pin", "audio-level", "spotify"])
    assert refused.exit_code == 2
    assert refused.output.strip() == (
        "barctl: audio-level is not drawn by the player source: nothing to pin"
    )
    assert runner.invoke(barctl_app, ["pin", "player-capsule"]).exit_code == 2
    assert runner.invoke(barctl_app, ["pin", "player-capsule", "x", "--auto"]).exit_code == 2
    assert runner.invoke(barctl_app, ["pin", "player-capsule", "x"]).exit_code == 4  # no controller

    answers: list[dict[str, Any]] = []

    def request(op: str, timeout: float = 1.0, **fields: Any) -> dict[str, Any]:
        answers.append({"op": op, **fields})
        if fields.get("instance") == "vlc":
            return {"ok": False, "error": "no player 'vlc' (playerctl -l lists them)"}
        return {"ok": True, "pinned": fields.get("instance")}

    monkeypatch.setattr(control, "request", request)
    done = runner.invoke(barctl_app, ["pin", "player-capsule", "spotify"])
    assert (done.exit_code, done.output) == (0, "pinned spotify\n")
    auto = runner.invoke(barctl_app, ["pin", "player-capsule", "--auto"])
    assert (auto.exit_code, auto.output) == (0, "automatic\n")
    assert runner.invoke(barctl_app, ["pin", "player-capsule", "vlc"]).exit_code == 5
    assert answers[1] == {"op": "pin", "module": "player-capsule", "instance": None}


def test_status_gives_the_player_modules_pinned(
    config: dict[str, mods.Module], monkeypatch: pytest.MonkeyPatch
) -> None:
    st.runtime().mkdir(parents=True, exist_ok=True)
    st.pid_path().write_text(f"{os.getpid()}\n1.0\n")
    monkeypatch.setattr(ops, "pins", lambda: {"player": "spotify"})
    infos = {m["name"]: m for m in ops.status()["modules"]}
    assert infos["player-capsule"]["pinned"] == "spotify"
    assert infos["player-metadata"]["pinned"] == "spotify"
    assert "pinned" not in infos["audio-level"]
    monkeypatch.setattr(ops, "pins", lambda: {"player": None})
    assert {m["name"]: m for m in ops.status()["modules"]}["player-capsule"]["pinned"] is None


# ---------------------------------------------------------------- the art accent (§5)


@pytest.fixture
def artwork(isolate: Path, commands: Callable[..., Path]) -> Callable[[str], Path]:
    """Fake curl (writes a small file to --output) and magick (prints the colour asked for)."""

    def make(colour: str = "#E0C060", fail: bool = False) -> Path:
        state = isolate / "xdg" / "state" / "theme" / "current"
        state.mkdir(parents=True, exist_ok=True)
        (state / "theme.zsh").write_text(
            "typeset -gA THEME_ROLE=(\n    [bg]='#000000'\n    [accent]='#333333'\n)\n"
        )
        return commands(
            curl=f"""
if {fail!r}:
    sys.exit(22)
out = args[args.index('--output') + 1]
open(out, 'wb').write(b'not really a png')
""",
            magick=f"""
print('# ImageMagick pixel enumeration: 1,1,255,srgb')
print('0,0: (224,192,96)  {colour}  srgb(224,192,96)')
""",
        )

    return make


def test_art_from_https_and_file(artwork: Callable[..., Path], isolate: Path) -> None:
    log = artwork()
    url = "https://i.scdn.co/image/abc"
    assert art.colour(url) == "#e0c060"
    curl = [c for c in calls(log) if c[0] == "curl"]
    assert curl[0][:2] == ["curl", "-q"]
    assert {"--proto", "=https", "--max-time", "2", "--max-filesize", "1048576"} <= set(curl[0])
    assert curl[0][-2:] == ["--", url]
    cached = list(art.cache_dir().iterdir())
    assert [f.name for f in cached] == [__import__("hashlib").sha256(url.encode()).hexdigest()]
    assert art.colour(url) == "#e0c060"
    assert len([c for c in calls(log) if c[0] == "curl"]) == 1  # one fetch per URL
    cover = isolate / "cover file.jpg"
    cover.write_bytes(b"x")
    assert art.colour("file://" + str(cover).replace(" ", "%20")) == "#e0c060"
    assert len([c for c in calls(log) if c[0] == "curl"]) == 1  # read where it is
    assert art.colour("http://insecure.example/a") is None
    assert art.colour("file:///no/such/file") is None


def test_low_contrast_and_failures_give_no_accent(artwork: Callable[..., Path]) -> None:
    artwork(colour="#0A141E")  # near black on a black bg
    assert art.colour("https://example.org/dark") is None
    artwork(fail=True)
    assert art.colour("https://example.org/missing") is None
    assert art.contrast("#ffffff", "#000000") == pytest.approx(21.0)


def test_the_cache_keeps_twenty(isolate: Path) -> None:
    folder = art.cache_dir()
    folder.mkdir(parents=True)
    for i in range(25):
        f = folder / f"{i:02d}"
        f.write_text("x")
        os.utime(f, (1000 + i, 1000 + i))
    art._prune(folder)
    assert sorted(f.name for f in folder.iterdir()) == [f"{i:02d}" for i in range(5, 25)]


def test_the_source_fetches_art_once_and_only_for_art_modules(
    config: dict[str, mods.Module],
    playerctl: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playerctl("spotify\n", positions={"spotify": "1"})
    asked: list[str] = []
    gate = threading.Event()

    def colour(url: str) -> str | None:
        asked.append(url)
        gate.wait(2)
        return "#e0c060"

    monkeypatch.setattr(art, "colour", colour)
    found = PlayerSource(["player-capsule", "player-art"], Writer(config, lambda m: None))
    art_line = line("spotify", "spotify", "Playing", "a", "b", "1000000", "https://x.org/a")
    for _ in range(3):
        found.event(art_line)
    gate.set()
    end = time.monotonic() + 3
    while "accent" not in (st.read("player-art") or {}) and time.monotonic() < end:
        time.sleep(0.02)
    assert asked == ["https://x.org/a"]
    assert (st.read("player-art") or {})["accent"] == "#e0c060"
    assert "accent" not in (st.read("player-capsule") or {})  # accent = "role"
    role_only = PlayerSource(["player-capsule"], Writer(config, lambda m: None))
    role_only.event(line("spotify", "spotify", "Playing", "a", "b", "1000000", "https://x.org/b"))
    assert asked == ["https://x.org/a"]  # no module asks for art: nothing fetched


def test_doctor_names_the_art_commands(config: dict[str, mods.Module]) -> None:
    found = {c["name"]: c for c in doctor.checks()}
    assert found["art accent"]["state"] == "warn"
    assert "player-art" in found["art accent"]["detail"]
    assert "curl, magick" in found["art accent"]["fix"]


# ---------------------------------------------------------------- barmenu player (§4)


def capsule_state(target: str = "spotify", length: float | None = 240.0) -> None:
    st.write(
        "player-capsule",
        {"tier": "active", "label": "x", "target": target, "progress": progress(length=length)},
    )


def table(rows: list[bm.Row]) -> list[tuple[str, str, str | list[str], bool]]:
    return [(r.glyph, r.label, r.command, r.current) for r in rows]


P = ["playerctl", "-p", "spotify"]
NEXT = ("\U000f04ad", "Next", [*P, "next"], False)
PREVIOUS = ("\U000f04ae", "Previous", [*P, "previous"], False)
PLAYER = ("\U000f0411", "Player: spotify \u203a", ["barmenu", "players"], False)
OUTPUT = ("\U000f04c3", "Output… \u203a", ["barmenu", "outputs"], False)
SEEK = [
    ("\U000f0d2a", "Back 10 s", [*P, "position", "10-"], False),
    ("\U000f0d71", "Forward 10 s", [*P, "position", "10+"], False),
]


@pytest.mark.parametrize(
    ("loop", "row"),
    [
        ("None", ("\U000f0457", "Loop: off", [*P, "loop", "Track"], False)),
        ("Track", ("\U000f0458", "Loop: track", [*P, "loop", "Playlist"], True)),
        ("Playlist", ("\U000f0456", "Loop: playlist", [*P, "loop", "None"], True)),
    ],
)
@pytest.mark.parametrize(
    ("shuffle", "srow"),
    [
        ("true", ("\U000f049f", "Shuffle: on", [*P, "shuffle", "Off"], True)),
        ("false", ("\U000f049e", "Shuffle: off", [*P, "shuffle", "On"], False)),
    ],
)
def test_player_rows(
    config: dict[str, mods.Module],
    playerctl: Callable[..., Path],
    loop: str,
    row: tuple[str, str, list[str], bool],
    shuffle: str,
    srow: tuple[str, str, list[str], bool],
) -> None:
    capsule_state()
    log = playerctl(metadata={"spotify": f"Playing|{loop}|{shuffle}"})
    assert table(player_menu.rows()) == [NEXT, PREVIOUS, row, srow, PLAYER, *SEEK, OUTPUT]
    query = ["playerctl", "-p", "spotify", "metadata", "--format", player_menu.FORMAT]
    assert calls(log) == [query]


def test_player_rows_hide_what_the_player_doesnt_give(
    config: dict[str, mods.Module], playerctl: Callable[..., Path]
) -> None:
    capsule_state(length=None)
    playerctl(metadata={"spotify": "Playing||"})
    assert table(player_menu.rows()) == [NEXT, PREVIOUS, PLAYER, OUTPUT]


NO_PLAYER = [
    ("\U000f038a", "No player", [], False),
    ("\U000f0411", "Player… \u203a", ["barmenu", "players"], False),
    OUTPUT,
]


def test_player_rows_with_no_player_or_a_failing_query(
    config: dict[str, mods.Module],
    playerctl: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert table(player_menu.rows()) == NO_PLAYER  # no state at all
    st.write("player-capsule", {"tier": "unavailable"})
    assert table(player_menu.rows()) == NO_PLAYER
    capsule_state()
    playerctl()  # the query fails
    assert table(player_menu.rows()) == NO_PLAYER
    monkeypatch.setattr(providers, "TIMEOUT", 0.2)
    playerctl(metadata={"spotify": "Playing|None|false"}, sleep=1)
    started = time.monotonic()
    assert table(player_menu.rows()) == NO_PLAYER
    assert time.monotonic() - started < 0.9


def test_no_player_runs_nothing(launched: list[list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm, "choose", lambda menu, extra=None: 0)  # rofi picks the first row
    picked = bm.open_menu(bm.Menu("player", rows=[bm.Row("", "No player", [])]))
    assert picked is not None and picked.label == "No player"
    assert launched == []


def test_players_rows_marks_and_the_pin_argv(
    config: dict[str, mods.Module],
    playerctl: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    isolate: Path,
) -> None:
    folder = isolate / "xdg" / "data" / "player"
    folder.mkdir(parents=True)
    (folder / "instances.json").write_text(
        '[{"name": "spotify", "icon": "S"}, {"name": "default", "icon": "D"}]'
    )
    capsule_state()
    playerctl("spotify\nfirefox.instance12\n")
    monkeypatch.setattr(ops, "pins", lambda: {})
    pin = ["barctl", "pin", "player-capsule"]
    assert table(players_menu.rows()) == [
        ("S", "spotify", [*pin, "spotify"], True),
        ("D", "firefox.instance12", [*pin, "firefox.instance12"], False),
        ("\U000f0387", "Automatic", [*pin, "--auto"], True),
    ]
    monkeypatch.setattr(ops, "pins", lambda: {"player": "spotify"})
    assert players_menu.rows()[-1].current is False


def test_the_menus_are_listed_and_help_calls_nothing(isolate: Path) -> None:
    menus = bm.load()
    assert (menus["player"].provider, menus["player"].side) == ("player", "right")
    assert (menus["players"].provider, menus["players"].title) == ("players", "Players")
    result = runner.invoke(barmenu_cli.build(), ["--help"])
    assert result.exit_code == 0
    assert "player " in result.output and "players" in result.output
    # The tripwire playerctl would have been reached by a provider; the isolate fixture checks.


# ---------------------------------------------------------------- the environment rule (§6)

AGENT = ("COORDINATOR", "CLAUDECODE", "TESSERA_ACTOR")


@pytest.mark.parametrize("tainted", [False, True])
def test_no_row_or_click_touches_the_agent_variables(
    config: dict[str, mods.Module],
    playerctl: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    tainted: bool,
) -> None:
    for name in AGENT:
        if tainted:
            monkeypatch.setenv(name, "x")
        else:
            monkeypatch.delenv(name, raising=False)
    capsule_state()
    playerctl("spotify\n", metadata={"spotify": "Playing|Track|true"})
    monkeypatch.setattr(ops, "pins", lambda: {})
    started: list[tuple[list[str], object]] = []

    def detach(argv: list[str], env: object = None, cwd: object = None) -> int:
        started.append((list(argv), env))
        return 1

    monkeypatch.setattr(procs, "detach", detach)
    argvs = [r.argv() for r in player_menu.rows() + players_menu.rows()]
    for button in ("left", "middle", "scroll-up", "scroll-down", "right"):
        ops.click("player-capsule", button)
    argvs += [argv for argv, _ in started]
    assert started and all(env is None for _, env in started)  # the bar's own environment
    for argv in argvs:
        words = " ".join(argv)
        assert not any(name in words for name in AGENT), argv
        assert argv[0] not in ("env", "unset", "zsh", "sh"), argv
    assert [argv for argv, _ in started] == [
        ["playerctl", "-p", "spotify", "play-pause"],
        ["playerctl", "-p", "spotify", "next"],
        ["playerctl", "-p", "spotify", "volume", "0.05+"],
        ["playerctl", "-p", "spotify", "volume", "0.05-"],
        ["barmenu", "player"],
    ]


def test_a_click_with_no_player_runs_nothing(
    config: dict[str, mods.Module], launched: list[list[str]]
) -> None:
    st.write("player-capsule", {"tier": "unavailable"})
    assert ops.click("player-capsule", "left") is None
    assert launched == []


def test_doctor_warns_of_an_agents_environment_by_name_only(
    config: dict[str, mods.Module], isolate: Path
) -> None:
    proc = isolate / "proc"
    (proc / "77").mkdir()
    (proc / "77" / "environ").write_bytes(b"PATH=/bin\0COORDINATOR=apps-coordinator\0HOME=/h\0")
    (proc / "78").mkdir()
    (proc / "78" / "environ").write_bytes(b"PATH=/bin\0CLAUDECODE=1\0TESSERA_ACTOR=agent-x\0")
    (proc / "79").mkdir()
    (proc / "79" / "environ").write_bytes(b"PATH=/bin\0")
    found = doctor.environment(77, [78, 79, 80])
    assert [c["name"] for c in found] == ["environment controller 77", "environment bar 78"]
    assert all(c["state"] == "warn" for c in found)
    assert found[0]["detail"].startswith("the bar runs in an agent's environment")
    assert "(COORDINATOR set)" in found[0]["detail"]
    assert "(CLAUDECODE, TESSERA_ACTOR set)" in found[1]["detail"]
    text = repr(found)
    assert "apps-coordinator" not in text and "agent-x" not in text
    # Through the whole doctor: the controller's own process.
    st.runtime().mkdir(parents=True, exist_ok=True)
    st.pid_path().write_text(f"{os.getpid()}\n1.0\n")
    (proc / str(os.getpid())).mkdir()
    (proc / str(os.getpid()) / "environ").write_bytes(b"COORDINATOR=x\0")
    names = [c["name"] for c in doctor.checks()]
    assert f"environment controller {os.getpid()}" in names


def test_the_followed_stream_rereads_the_position_on_its_timer(
    source: tuple[PlayerSource, list[str], list[float]],
    playerctl: Callable[..., Path],
    isolate: Path,
) -> None:
    from tests.unit.test_barctl_sources import Feed, run_source

    found, _, clock = source
    stream = isolate / "pl.fifo"
    os.mkfifo(stream)
    log = playerctl("spotify\n", positions={"spotify": "5"})
    script = isolate / "bin" / "playerctl"
    follow = f"if args[:2] == ['-a', '--follow']:\n    os.execvp('cat', ['cat', {str(stream)!r}])\n"
    script.write_text(script.read_text().replace("import json\n", "import json\n" + follow))
    feed = Feed(stream)
    thread = run_source(found)
    feed.line(line("spotify", "spotify", "Playing", "a", "b", "60000000"))
    end = time.monotonic() + 3
    while "progress" not in (st.read("player-capsule") or {}) and time.monotonic() < end:
        time.sleep(0.02)
    clock[0] += 31
    end = time.monotonic() + 3
    while len([c for c in calls(log) if c[-1] == "position"]) < 2 and time.monotonic() < end:
        time.sleep(0.05)
    assert len([c for c in calls(log) if c[-1] == "position"]) == 2
    feed.close()
    thread.join(3)
    assert not thread.is_alive()

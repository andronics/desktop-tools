"""The player chips (record 0005 phase A): the `chips` display and its keys, per-segment click
tables, the player source's chips (order by first seen, the shown one underlined, the pin's
label, `chips_min`, `chips_max` and `+N`, an over-long instance left out), the chips' render and
clicks, and `barctl pin --toggle`.

No player, no bar: playerctl is the guarded fake from the capsule's tests, which fails the test
if anything asks it to control a player. A chip's middle click is checked by its argv, which
`procs.detach` records and never runs.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from desktop_tools.barctl import control, ops, render
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.app import app as barctl_app
from desktop_tools.barctl.controller import Controller
from desktop_tools.barctl.sources import PlayerSource
from desktop_tools.barctl.sources.player import MORE, PIN
from desktop_tools.barctl.store import Writer, shown
from tests.fakes import calls
from tests.unit.test_player_capsule import GUARD, line, visible

runner = CliRunner()

CONFIG = """
[modules.player-capsule]
source = "player"
display = "capsule"

[modules.player-chips]
source = "player"
display = "chips"
glyph = "G"
separator = "|"
chips_min = 2
chips_max = 4

[modules.player-chips.segment_clicks]
left = ["barctl", "pin", "player-capsule", "{segment}", "--toggle"]
middle = ["playerctl", "-p", "{segment}", "play-pause"]
right = ["barmenu", "players"]

[modules.player-chips.segment_clicks.more]
left = ["barmenu", "players"]
"""
COLOURS = {
    "unavailable": "#111111",
    "idle": "#222222",
    "active": "#333333",
    "alert": "#444444",
    "underline": "#333333",
}
ICONS = [{"name": "spotify", "icon": "S"}, {"name": "firefox", "icon": "F"}, {"name": "mpv"}]


@pytest.fixture
def config(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, mods.Module]]:
    path = isolate / "modules.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    folder = isolate / "xdg" / "data" / "player"
    folder.mkdir(parents=True)
    (folder / "instances.json").write_text(json.dumps(ICONS))
    yield mods.load()
    assert not (isolate / "controlled").exists(), (isolate / "controlled").read_text()


@pytest.fixture
def playerctl(isolate: Path, commands: Callable[..., Path]) -> Callable[[str], Path]:
    """A guarded fake playerctl: `-l` prints the listing; a position read prints 1."""

    def make(listing: str) -> Path:
        (isolate / "listing").write_text(listing)
        body = (
            GUARD
            + """
if args == ['-l']:
    print(open(here + '/listing').read(), end='')
elif args[0] == '-p' and args[2:] == ['position']:
    print('1')
else:
    sys.exit(1)
"""
        )
        return commands(playerctl=body)

    return make


@pytest.fixture
def source(config: dict[str, mods.Module]) -> tuple[PlayerSource, list[str]]:
    pokes: list[str] = []
    found = PlayerSource(["player-capsule", "player-chips"], Writer(config, pokes.append))
    found.clock = lambda: 1000.0
    return found, pokes


def event(found: PlayerSource, instance: str, status: str, title: str = "t") -> None:
    found.event(line(instance, instance.split(".")[0], status, "a", title, "1000000"))


def cells(name: str = "player-chips") -> list[dict[str, Any]]:
    return list((st.read(name) or {}).get("segments") or [])


# ---------------------------------------------------------------- modules.toml


def test_chips_keys_default_and_are_read_only_for_chips() -> None:
    found = mods.parse({"modules": {"c": {"source": "player", "display": "chips"}}})["c"]
    assert (found.chips_min, found.chips_max) == (2, 4)
    assert found.as_dict()["chips_min"] == 2
    other = mods.parse({"modules": {"t": {"source": "player", "display": "text", "chips_max": 99}}})
    assert "chips_max" not in other["t"].as_dict()


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("chips_min", 0, "chips_min must be 1 to 8"),
        ("chips_max", 9, "chips_max must be 1 to 8"),
        ("chips_max", 2.5, "chips_max must be a whole number"),
        ("chips_min", True, "chips_min must be a whole number"),
    ],
)
def test_chips_key_errors_name_the_key(key: str, value: object, message: str) -> None:
    with pytest.raises(mods.ConfigError, match=message):
        mods.parse({"modules": {"c": {"source": "player", "display": "chips", key: value}}})


def test_per_segment_tables_parse_and_fall_back(config: dict[str, mods.Module]) -> None:
    chips = config["player-chips"]
    assert chips.cell_clicks == {"more": {"left": ["barmenu", "players"]}}
    assert chips.clicks_for("more")["left"] == ["barmenu", "players"]
    assert chips.clicks_for("more")["middle"] == ["playerctl", "-p", "{segment}", "play-pause"]
    assert chips.clicks_for("spotify")["left"][:3] == ["barctl", "pin", "player-capsule"]
    assert chips.clicks_for(None) == {}
    table = chips.as_dict()["segment_clicks"]
    assert isinstance(table, dict) and table["more"] == {"left": ["barmenu", "players"]}


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"bad id": {"left": ["x"]}}, r"segment_clicks\.bad id: not a segment id"),
        ({"x" * 65: {"left": ["x"]}}, "not a segment id"),
        ({"more": {"hover": ["x"]}}, r"segment_clicks\.more: unknown button 'hover'"),
        ({"more": {"left": []}}, r"segment_clicks\.more\.left: a command is a non-empty list"),
        ({"hover": ["x"]}, "unknown button 'hover'"),
    ],
)
def test_bad_per_segment_tables_are_load_errors(table: dict[str, Any], message: str) -> None:
    raw = {"pusher": "crew", "segment_clicks": table}
    with pytest.raises(mods.ConfigError, match=message):
        mods.parse({"modules": {"crew": raw}})


def test_crews_strip_is_unchanged() -> None:
    packaged = mods.load(mods.PACKAGED)
    assert packaged["crew"].cell_clicks == {}
    assert packaged["crew"].segment_clicks["left"] == ["crew", "toggle", "--launch", "{segment}"]
    assert "player-chips" not in packaged  # off until the dotfiles turn it on
    text = mods.PACKAGED.read_text()
    assert '# [modules.player-chips]\n# source = "player"\n# display = "chips"' in text


# ---------------------------------------------------------------- the source


def test_chips_by_first_seen_the_shown_one_underlined(
    source: tuple[PlayerSource, list[str]], playerctl: Callable[[str], Path]
) -> None:
    found, _ = source
    playerctl("spotify\nfirefox\nmpv\n")
    event(found, "spotify", "Paused")
    assert cells() == []  # one player: fewer than chips_min
    event(found, "firefox", "Playing")
    event(found, "mpv", "Stopped")
    assert cells() == [
        {"id": "spotify", "tier": "idle", "glyph": "S"},
        {"id": "firefox", "tier": "active", "glyph": "F", "underline": True},
        {"id": "mpv", "tier": "idle", "glyph": "G"},  # no icon: the module's glyph
    ]
    event(found, "spotify", "Playing")
    event(found, "firefox", "Paused")
    assert [c["id"] for c in cells()] == ["spotify", "firefox", "mpv"]  # places kept
    assert [c.get("underline") for c in cells()] == [True, None, None]
    chips = st.read("player-chips") or {}
    assert "label" not in chips and "target" not in chips
    assert (st.read("player-capsule") or {})["target"] == "spotify"  # the capsule as before


def test_the_pinned_chip_carries_the_pin(
    source: tuple[PlayerSource, list[str]], playerctl: Callable[[str], Path]
) -> None:
    found, _ = source
    playerctl("spotify\nfirefox\n")
    event(found, "spotify", "Playing")
    event(found, "firefox", "Paused")
    found.pin("firefox")
    assert cells()[1] == {
        "id": "firefox",
        "tier": "idle",
        "glyph": "F",
        "label": PIN,
        "underline": True,
    }
    assert "label" not in cells()[0] and "underline" not in cells()[0]


def test_past_chips_max_the_last_cell_is_more(
    source: tuple[PlayerSource, list[str]], playerctl: Callable[[str], Path]
) -> None:
    found, _ = source
    names = [f"firefox.instance_{i}" for i in range(6)]
    playerctl("\n".join(names) + "\n")
    for name in names:
        event(found, name, "Paused")
    got = cells()
    assert [c["id"] for c in got] == [*names[:3], "more"]
    assert got[-1] == {"id": "more", "tier": "idle", "glyph": MORE, "label": "3"}
    st.validate(st.read("player-chips"))  # every id is a valid segment id


def test_an_over_long_instance_or_one_named_more_is_left_out(
    source: tuple[PlayerSource, list[str]], playerctl: Callable[[str], Path]
) -> None:
    found, _ = source
    long = "firefox.instance_" + "9" * 60
    playerctl(f"spotify\nfirefox\n{long}\nmore\n")
    for name in ("spotify", long, "more", "firefox"):
        event(found, name, "Paused")
    assert [c["id"] for c in cells()] == ["spotify", "firefox"]


def test_no_player_or_a_gone_stream_draws_no_chips(
    source: tuple[PlayerSource, list[str]], playerctl: Callable[[str], Path]
) -> None:
    found, _ = source
    playerctl("spotify\nfirefox\n")
    event(found, "spotify", "Playing")
    event(found, "firefox", "Playing")
    assert len(cells()) == 2
    found.gone()
    assert cells() == []
    assert (st.read("player-chips") or {})["tier"] == "unavailable"


def test_a_chip_change_pokes_the_chips_and_a_title_the_capsule(
    source: tuple[PlayerSource, list[str]], playerctl: Callable[[str], Path]
) -> None:
    found, pokes = source
    playerctl("spotify\nfirefox\n")
    event(found, "spotify", "Playing")
    event(found, "firefox", "Paused")
    pokes.clear()
    event(found, "spotify", "Playing", title="another")
    assert pokes == ["player-capsule"]
    pokes.clear()
    found.pin("firefox")
    assert "player-chips" in pokes


# ---------------------------------------------------------------- render and clicks


def test_render_draws_each_chip_with_its_own_clicks(config: dict[str, mods.Module]) -> None:
    chips = config["player-chips"]
    state: st.State = {
        "tier": "active",
        "segments": [
            {"id": "spotify", "tier": "active", "glyph": "S", "underline": True},
            {"id": "firefox", "tier": "idle", "glyph": "F", "label": PIN},
            {"id": "more", "tier": "idle", "glyph": MORE, "label": "2"},
        ],
    }
    out = render.render(chips, state, now=1.0, colours=COLOURS, controller=False)
    assert visible(out) == f"S|F {PIN}|{MORE} 2"
    first, second, third = out.split("|%{A")
    assert "%{A1:barctl click player-chips left --segment spotify:}" in first
    assert "%{A2:barctl click player-chips middle --segment spotify:}" in first
    assert "%{A3:barctl click player-chips right --segment spotify:}" in first
    assert "%{u#333333}%{+u}" in first and "%{F#333333}" in first
    assert "--segment firefox" in second and "%{+u}" not in second and "%{F#222222}" in second
    assert "--segment more" in third
    assert "%{A4" not in out and "%{A5" not in out  # scroll does nothing


def test_render_with_no_chips_is_empty(config: dict[str, mods.Module]) -> None:
    chips = config["player-chips"]
    for state in (None, {"tier": "unavailable"}, {"tier": "active", "source": "player"}):
        assert render.render(chips, state, now=1.0, colours=COLOURS, controller=False) == ""
    assert shown(chips, {"tier": "idle"}, 1.0) == shown(chips, {"tier": "idle", "label": "x"}, 1.0)


def test_chip_clicks_run_the_right_argv(
    config: dict[str, mods.Module], launched: list[list[str]]
) -> None:
    st.write("player-chips", {"tier": "active", "segments": [{"id": "spotify", "tier": "idle"}]})
    assert ops.click("player-chips", "left", "spotify") == [
        "barctl",
        "pin",
        "player-capsule",
        "spotify",
        "--toggle",
    ]
    assert ops.click("player-chips", "middle", "spotify") == [
        "playerctl",
        "-p",
        "spotify",
        "play-pause",
    ]
    assert ops.click("player-chips", "right", "spotify") == ["barmenu", "players"]
    assert ops.click("player-chips", "left", "more") == ["barmenu", "players"]  # its own table
    assert ops.click("player-chips", "scroll-up", "spotify") is None
    assert launched == [
        ["barctl", "pin", "player-capsule", "spotify", "--toggle"],
        ["playerctl", "-p", "spotify", "play-pause"],
        ["barmenu", "players"],
        ["barmenu", "players"],
    ]


# ---------------------------------------------------------------- pin --toggle


def test_toggle_unpins_the_pinned_player(
    source: tuple[PlayerSource, list[str]], playerctl: Callable[[str], Path]
) -> None:
    found, _ = source
    log = playerctl("spotify\nfirefox\n")
    event(found, "spotify", "Playing")
    event(found, "firefox", "Paused")
    assert found.pin("firefox", toggle=True) == "firefox"  # not pinned yet: pins
    assert found.pin("spotify", toggle=True) == "spotify"  # another: pins that one
    assert found.pin("spotify", toggle=True) is None  # the pinned one: unpins
    assert found.pick() == "spotify"
    for argv in calls(log):
        assert argv[1:] == ["-l"] or (argv[1], argv[3:]) == ("-p", ["position"]), argv


def test_the_controller_passes_toggle(
    config: dict[str, mods.Module],
    source: tuple[PlayerSource, list[str]],
    playerctl: Callable[[str], Path],
) -> None:
    found, _ = source
    playerctl("spotify\n")
    controller = Controller(config, poke=lambda m: None, sources={})
    controller.running["player"] = (found, threading.Thread(target=lambda: None))
    request = {"op": "pin", "module": "player-chips", "instance": "spotify"}
    assert controller.handle({**request, "toggle": True}) == {"ok": True, "pinned": "spotify"}
    assert controller.handle(request) == {"ok": True, "pinned": "spotify"}  # no toggle: stays
    assert controller.handle({**request, "toggle": True}) == {"ok": True, "pinned": None}
    assert controller.handle({**request, "toggle": "yes"}) == {"ok": True, "pinned": "spotify"}


def test_barctl_pin_toggle_on_the_command_line(
    config: dict[str, mods.Module], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []
    pinned: list[str | None] = [None]

    def request(op: str, timeout: float = 1.0, **fields: Any) -> dict[str, Any]:
        sent.append({"op": op, **fields})
        instance = fields.get("instance")
        pinned[0] = None if fields.get("toggle") and pinned[0] == instance else instance
        return {"ok": True, "pinned": pinned[0]}

    monkeypatch.setattr(control, "request", request)
    first = runner.invoke(barctl_app, ["pin", "player-capsule", "spotify", "--toggle"])
    assert (first.exit_code, first.output) == (0, "pinned spotify\n")
    again = runner.invoke(barctl_app, ["pin", "player-capsule", "spotify", "--toggle"])
    assert (again.exit_code, again.output) == (0, "automatic\n")
    assert sent[0] == {
        "op": "pin",
        "module": "player-capsule",
        "instance": "spotify",
        "toggle": True,
    }
    refused = runner.invoke(barctl_app, ["pin", "player-capsule", "--auto", "--toggle"])
    assert refused.exit_code == 2 and "--toggle needs a player" in refused.output
    plain = runner.invoke(barctl_app, ["pin", "player-capsule", "spotify"])
    assert plain.exit_code == 0 and "toggle" not in sent[-1]

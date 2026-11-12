"""The transport row (record 0005 phase C): the capsule's `expand_for` and `icon_clicks` keys,
the `loop`, `shuffle` and `expanded_until` state fields, the row's cells at widths 32 and 20,
each cell's action tag, the seek fractions, the stream case, `barctl transport`'s argv per cell
with the loop cycle and the re-arm, and `barctl expand` writing, keeping and ending
`expanded_until` with and without a controller.

No player, no bar: playerctl is the guarded fake from the capsule's tests, which fails the test
if anything asks it to control a player. Every press is checked by its argv, which
`procs.detach` records and never runs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from desktop_tools.barctl import control, ops, render, transport
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.app import app as barctl_app
from desktop_tools.barctl.controller import Controller
from desktop_tools.barctl.sources import PlayerSource
from desktop_tools.barctl.sources.player import FORMAT, US, shuffle_of
from desktop_tools.barctl.store import Writer, shown
from tests.unit.test_player_capsule import GUARD, visible

runner = CliRunner()

CONFIG = """
[modules.player-capsule]
source = "player"
display = "capsule"
glyph_override = { idle = "I", active = "A" }
width = 32
expand_for = 5

[modules.player-capsule.clicks]
left = ["playerctl", "-p", "{target}", "play-pause"]
scroll-up = ["playerctl", "-p", "{target}", "volume", "0.05+"]

[modules.player-capsule.icon_clicks]
left = ["barctl", "expand", "player-capsule"]

[modules.player-capsule.segment_clicks]
left = ["barctl", "transport", "player-capsule", "{segment}"]

[modules.player-narrow]
source = "player"
display = "capsule"
width = 20
expand_for = 5

[modules.player-off]
source = "player"
display = "capsule"
width = 32

[modules.player-metadata]
source = "player"
display = "text"
"""
COLOURS = {
    "unavailable": "#111111",
    "idle": "#222222",
    "active": "#333333",
    "alert": "#444444",
    "underline": "#555555",
}
NOW = 1000.0


@pytest.fixture
def config(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, mods.Module]]:
    path = isolate / "modules.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    yield mods.load()
    assert not (isolate / "controlled").exists(), (isolate / "controlled").read_text()


@pytest.fixture
def no_controller(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """No controller answers; polybar's pokes are recorded instead of sent."""
    from desktop_tools.common import polybar

    pokes: list[str] = []
    monkeypatch.setattr(control, "request", lambda op, timeout=1.0, **fields: None)

    def poke(name: str) -> dict[int, bool]:
        pokes.append(name)
        return {}

    monkeypatch.setattr(polybar, "poke", poke)
    return pokes


@pytest.fixture
def controller_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A controller that answers ok, recording each request."""
    sent: list[dict[str, Any]] = []

    def request(op: str, timeout: float = 1.0, **fields: Any) -> dict[str, Any]:
        sent.append({"op": op, **fields})
        return {"ok": True}

    monkeypatch.setattr(control, "request", request)
    return sent


def playing(**extra: Any) -> st.State:
    return {
        "tier": "active",
        "label": "Massive Attack - Teardrop",
        "label_since": 100.0,
        "target": "spotify",
        "progress": {"position": 50.0, "length": 200.0, "rate": 1.0, "at": NOW, "playing": True},
        "loop": "None",
        "shuffle": False,
        **extra,
    }


def opened(**extra: Any) -> st.State:
    return playing(**{"expanded_until": NOW + 5, **extra})


def draw(module: mods.Module, state: st.State | None, now: float = NOW) -> str:
    return render.render(module, state, now=now, colours=COLOURS, controller=True)


# ---------------------------------------------------------------- modules.toml and state


def test_the_keys_default_off_and_are_read_for_a_capsule_only() -> None:
    found = mods.parse({"modules": {"c": {"source": "player", "display": "capsule"}}})["c"]
    assert (found.expand_for, found.icon_clicks) == (0, {})
    assert found.as_dict()["expand_for"] == 0 and found.as_dict()["icon_clicks"] == {}
    other = mods.parse(
        {"modules": {"t": {"source": "player", "display": "text", "expand_for": "x"}}}
    )
    assert "expand_for" not in other["t"].as_dict()


def test_the_packaged_file_turns_nothing_on() -> None:
    for module in mods.load(mods.PACKAGED).values():
        assert (module.expand_for, module.icon_clicks) == (0, {})


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("expand_for", 31, "expand_for must be 0 to 30"),
        ("expand_for", -1, "expand_for must be 0 to 30"),
        ("expand_for", 2.5, "expand_for must be a whole number"),
        ("expand_for", True, "expand_for must be a whole number"),
        ("icon_clicks", ["barctl"], "icon_clicks: must be a table"),
        ("icon_clicks", {"hover": ["x"]}, "unknown button 'hover'"),
        ("icon_clicks", {"left": "barctl"}, "icon_clicks.left: a command is a non-empty list"),
    ],
)
def test_key_errors_name_the_key(key: str, value: object, message: str) -> None:
    with pytest.raises(mods.ConfigError, match=message):
        mods.parse({"modules": {"c": {"source": "player", "display": "capsule", key: value}}})


def test_the_icon_is_a_capsules_own_segment(config: dict[str, mods.Module]) -> None:
    capsule = config["player-capsule"]
    assert capsule.clicks_for(mods.ICON) == {"left": ["barctl", "expand", "player-capsule"]}
    assert capsule.clicks_for("next") == {
        "left": ["barctl", "transport", "player-capsule", "{segment}"]
    }
    assert config["player-metadata"].clicks_for(mods.ICON) == {}  # only a capsule has one


def test_loop_shuffle_and_expanded_until_are_validated() -> None:
    clean = st.validate({"loop": "Track", "shuffle": True, "expanded_until": 5})
    assert clean == {"loop": "Track", "shuffle": True, "expanded_until": 5.0}
    assert st.validate({"loop": "", "shuffle": None}) == {}
    with pytest.raises(st.StateError, match="loop must be one of None, Track, Playlist"):
        st.validate({"loop": "Once"})
    with pytest.raises(st.StateError, match="shuffle must be true, false or null"):
        st.validate({"shuffle": "on"})
    with pytest.raises(st.StateError, match="expanded_until must be epoch seconds"):
        st.validate({"expanded_until": "soon"})


# ---------------------------------------------------------------- the row's cells


def test_the_row_at_width_32_fills_the_capsule_exactly(config: dict[str, mods.Module]) -> None:
    cells = render.row(config["player-capsule"], opened(), NOW)
    ids = [c.id for c in cells if c.id]
    assert ids[:5] == ["previous", "play-pause", "next", "loop", "shuffle"]
    assert ids[5:] == [f"seek-{i}" for i in range(16)]
    assert len(transport.plain(cells)) == 32
    buttons = [c.text for c in cells if c.paint == "button"]
    assert buttons == [
        f" {g} "
        for g in (
            transport.PREVIOUS,
            transport.PLAY_PAUSE,
            transport.NEXT,
            transport.LOOP["None"][0],
            transport.SHUFFLE_OFF,
        )
    ]
    # 50 of 200 seconds: a quarter, 4 of the 16 cells filled.
    seek = "".join(c.text for c in cells if c.id and c.id.startswith("seek-"))
    assert seek == "━" * 4 + "─" * 12


def test_the_row_at_width_20_gives_the_seek_bar_up_for_back_and_forward(
    config: dict[str, mods.Module],
) -> None:
    cells = render.row(config["player-narrow"], opened(), NOW)
    ids = [c.id for c in cells if c.id]
    assert ids == ["previous", "play-pause", "next", "loop", "shuffle", "back", "forward"]
    assert len(transport.plain(cells)) == 20
    assert [c.text for c in cells if c.id == "back"] == [transport.BACK[10] + " "]


def test_a_stream_and_spoken_word_get_their_skip_buttons(config: dict[str, mods.Module]) -> None:
    stream = opened(progress={"position": 5, "length": None, "rate": 1, "at": NOW})
    cells = render.row(config["player-capsule"], stream, NOW)
    assert [c.id for c in cells if c.id][-2:] == ["back", "forward"]
    assert len(transport.plain(cells)) == 32
    spoken = render.row(config["player-narrow"], opened(kind="spoken"), NOW)
    glyphs = {c.id: c.text.strip() for c in spoken if c.id}
    assert (glyphs["back"], glyphs["forward"]) == (transport.BACK[30], transport.FORWARD[30])


def test_loop_and_shuffle_are_left_out_when_the_player_gives_none(
    config: dict[str, mods.Module],
) -> None:
    state = {k: v for k, v in opened().items() if k not in ("loop", "shuffle")}
    ids = [c.id for c in render.row(config["player-capsule"], state, NOW) if c.id]
    assert ids[:4] == ["previous", "play-pause", "next", "seek-0"]
    on = render.row(config["player-capsule"], opened(loop="Playlist", shuffle=True), NOW)
    texts = {c.id: c.text.strip() for c in on if c.id}
    assert (texts["loop"], texts["shuffle"]) == (
        transport.LOOP["Playlist"][0],
        transport.SHUFFLE_ON,
    )


def test_each_cell_has_its_own_action_tag_and_the_icon_its_own(
    config: dict[str, mods.Module],
) -> None:
    out = draw(config["player-capsule"], opened())
    for cell in ("previous", "play-pause", "next", "loop", "shuffle", "seek-0", "seek-15"):
        assert f"%{{A1:barctl click player-capsule left --segment {cell}:}}" in out
    assert "%{A1:barctl click player-capsule left --segment icon:}" in out
    assert "right --segment" not in out  # one menu tag, the capsule's own, not one per cell
    # The capsule's own tag still wraps the line, but not its left click: a press between cells
    # does nothing, and scroll keeps the volume.
    assert "%{A1:barctl click player-capsule left:}" not in out
    assert out.startswith("%{A4:barctl click player-capsule scroll-up:}")
    assert visible(out) == "A " + transport.plain(
        render.row(config["player-capsule"], opened(), NOW)
    )
    assert "%{F#555555}━%{F-}" in out and "%{F#222222}─%{F-}" in out  # accent, then idle


def test_the_title_comes_back_when_the_time_is_up(config: dict[str, mods.Module]) -> None:
    capsule = config["player-capsule"]
    later = NOW + 5
    out = draw(capsule, opened(), now=later)
    assert "Massive Attack" in visible(out)
    assert "%{A1:barctl click player-capsule left:}" in out  # the title is play-pause again
    assert "%{A1:barctl click player-capsule left --segment icon:}" in out  # the icon expands
    assert len(render.capsule_frame(capsule, opened(), later)[0]) == 32  # the same width


def test_expand_for_0_never_draws_the_row(config: dict[str, mods.Module]) -> None:
    out = draw(config["player-off"], opened())
    assert "Massive Attack" in visible(out) and "--segment" not in out


def test_no_row_without_a_player_or_once_faded(config: dict[str, mods.Module]) -> None:
    capsule = config["player-capsule"]
    assert not render.expanded(capsule, {"tier": "unavailable", "expanded_until": NOW + 5}, NOW)
    capsule.fade_after = 1
    faded = opened(tier="idle", status_at=NOW - 120)
    assert not render.expanded(capsule, faded, NOW)


def test_the_seek_fraction_moves_with_the_time(config: dict[str, mods.Module]) -> None:
    capsule = config["player-capsule"]
    # 50 s of 200 is 4 cells; the next boundary is at 4.5/16 of 200 = 56.25 s, 6.25 s on: past
    # the fold, so the fold is the next change.
    assert render.next_change(capsule, opened(), NOW) == NOW + 5
    long_open = opened(expanded_until=NOW + 30)
    assert render.next_change(capsule, long_open, NOW) == pytest.approx(NOW + 6.25)
    paused = opened(progress={"position": 50, "length": 200, "rate": 1, "at": NOW})
    assert render.next_change(capsule, paused, NOW) == NOW + 5
    assert render.next_change(config["player-narrow"], long_open, NOW) == NOW + 30


def test_the_tick_pokes_when_the_row_folds(config: dict[str, mods.Module]) -> None:
    pokes: list[str] = []
    controller = Controller(config, poke=pokes.append, sources={})
    st.write("player-capsule", opened(progress=None))
    assert controller.capsules(NOW) == (NOW + 5, [])
    assert controller.capsules(NOW + 2) == (NOW + 5, [])
    assert controller.capsules(NOW + 5)[1] == ["player-capsule"]


def test_the_controller_draws_an_expand_at_once(config: dict[str, mods.Module]) -> None:
    import time

    pokes: list[str] = []
    controller = Controller(config, poke=pokes.append, sources={})
    now = time.time()
    controller.capsules(now)  # at rest: the title's frame is noted
    st.write("player-capsule", playing(expanded_until=now + 60, progress=None))
    assert controller.handle({"op": "expand", "module": "player-capsule"}) == {"ok": True}
    assert pokes == ["player-capsule"]
    # The row's frame is noted, so the next tick doesn't poke the same row again.
    assert controller.capsules(time.time())[1] == []
    assert controller.handle({"op": "expand", "module": "nope"})["ok"] is False


# ---------------------------------------------------------------- barctl transport


@pytest.mark.parametrize(
    ("cell", "state", "argv"),
    [
        ("previous", {}, ["previous"]),
        ("play-pause", {}, ["play-pause"]),
        ("next", {}, ["next"]),
        ("loop", {"loop": "None"}, ["loop", "Track"]),
        ("loop", {"loop": "Track"}, ["loop", "Playlist"]),
        ("loop", {"loop": "Playlist"}, ["loop", "None"]),
        ("shuffle", {"shuffle": True}, ["shuffle", "toggle"]),
        ("seek-0", {}, ["position", "0.0"]),
        ("seek-4", {}, ["position", "50.0"]),
        ("seek-15", {}, ["position", "187.5"]),
        ("back", {}, ["position", "10-"]),
        ("forward", {}, ["position", "10+"]),
        ("back", {"kind": "spoken"}, ["position", "30-"]),
        ("forward", {"kind": "spoken"}, ["position", "30+"]),
    ],
)
def test_transport_argv_per_cell(cell: str, state: dict[str, Any], argv: list[str]) -> None:
    assert transport.argv(cell, playing(**state)) == ["playerctl", "-p", "spotify", *argv]


def test_transport_runs_nothing_without_a_target_or_a_length() -> None:
    assert transport.argv("next", None) is None
    assert transport.argv("next", playing(target="")) is None
    assert transport.argv("next", playing(tier="unavailable")) is None
    assert transport.argv("seek-3", playing(progress={"length": None, "at": 1})) is None
    assert transport.argv("loop", playing(loop="")) is None


@pytest.mark.parametrize("cell", ["stop", "seek-16", "seek-x", "seek-", "icon"])
def test_transport_refuses_a_cell_the_row_never_has(cell: str) -> None:
    with pytest.raises(transport.UnknownCell):
        transport.argv(cell, playing())


def test_a_press_runs_the_argv_detached_and_rearms_the_row(
    config: dict[str, mods.Module],
    launched: list[list[str]],
    controller_requests: list[dict[str, Any]],
) -> None:
    st.write("player-capsule", opened())
    assert ops.transport_press("player-capsule", "next", now=NOW + 3) == [
        "playerctl",
        "-p",
        "spotify",
        "next",
    ]
    assert launched == [["playerctl", "-p", "spotify", "next"]]
    assert (st.read("player-capsule") or {})["expanded_until"] == NOW + 3 + 5
    assert controller_requests == [{"op": "expand", "module": "player-capsule"}]


def test_a_press_on_a_folded_row_does_not_open_it(
    config: dict[str, mods.Module],
    launched: list[list[str]],
    controller_requests: list[dict[str, Any]],
) -> None:
    st.write("player-capsule", playing())
    assert ops.transport_press("player-capsule", "play-pause", now=NOW) is not None
    assert "expanded_until" not in (st.read("player-capsule") or {})
    assert controller_requests == []


def test_a_press_with_no_player_runs_nothing(
    config: dict[str, mods.Module], launched: list[list[str]]
) -> None:
    st.write("player-capsule", {"tier": "unavailable", "expanded_until": NOW + 5})
    assert ops.transport_press("player-capsule", "next", now=NOW) is None
    assert launched == []


def test_transport_on_the_command_line(
    config: dict[str, mods.Module],
    launched: list[list[str]],
    controller_requests: list[dict[str, Any]],
) -> None:
    st.write("player-capsule", playing())
    done = runner.invoke(barctl_app, ["transport", "player-capsule", "loop"])
    assert done.exit_code == 0 and launched == [["playerctl", "-p", "spotify", "loop", "Track"]]
    bad = runner.invoke(barctl_app, ["transport", "player-capsule", "eject"])
    assert bad.exit_code == 2 and "no cell 'eject'" in bad.output
    other = runner.invoke(barctl_app, ["transport", "player-metadata", "next"])
    assert other.exit_code == 2 and "not a capsule" in other.output
    st.write("player-capsule", {"tier": "unavailable"})
    none = runner.invoke(barctl_app, ["transport", "player-capsule", "next"])
    assert (none.exit_code, none.output) == (0, "nothing to act on\n")


def test_a_cell_click_reaches_barctl_transport(
    config: dict[str, mods.Module], launched: list[list[str]]
) -> None:
    st.write("player-capsule", opened())
    assert ops.click("player-capsule", "left", "seek-3") == [
        "barctl",
        "transport",
        "player-capsule",
        "seek-3",
    ]
    assert ops.click("player-capsule", "left", "icon") == ["barctl", "expand", "player-capsule"]
    assert ops.click("player-capsule", "left") == ["playerctl", "-p", "spotify", "play-pause"]


# ---------------------------------------------------------------- barctl expand


def test_expand_writes_and_folds_with_a_controller(
    config: dict[str, mods.Module], controller_requests: list[dict[str, Any]]
) -> None:
    st.write("player-capsule", playing())
    assert ops.expand("player-capsule", now=NOW) == NOW + 5
    assert (st.read("player-capsule") or {})["expanded_until"] == NOW + 5
    assert ops.expand("player-capsule", now=NOW + 1) is None  # the icon again: folds
    assert "expanded_until" not in (st.read("player-capsule") or {})
    assert ops.expand("player-capsule", 20, now=NOW) == NOW + 20
    assert ops.expand("player-capsule", 20, now=NOW + 1) == NOW + 21  # --for keeps it open
    assert ops.expand("player-capsule", off=True, now=NOW + 2) is None
    assert ops.expand("player-capsule", off=True, now=NOW + 3) is None  # already folded
    assert [r["op"] for r in controller_requests] == ["expand"] * 5


def test_expand_without_a_controller_pokes_and_redraws_later(
    config: dict[str, mods.Module], launched: list[list[str]], no_controller: list[str]
) -> None:
    st.write("player-capsule", playing())
    ops.expand("player-capsule", now=NOW)
    assert no_controller == ["player-capsule"]
    assert len(launched) == 1 and launched[0][-2:] == ["5.1", "player-capsule"]
    assert "ops.reload" in launched[0][2]


def test_expand_is_refused_when_the_row_is_off_or_not_a_capsule(
    config: dict[str, mods.Module], controller_requests: list[dict[str, Any]]
) -> None:
    with pytest.raises(ops.Failure, match="expand_for is 0") as off:
        ops.expand("player-off", now=NOW)
    assert off.value.code == ops.REFUSED
    with pytest.raises(ops.Failure, match="not a capsule") as other:
        ops.expand("player-metadata", now=NOW)
    assert other.value.code == ops.USAGE
    with pytest.raises(ops.Failure, match="0 to 30"):
        ops.expand("player-capsule", 31, now=NOW)


def test_the_source_keeps_an_open_row_and_drops_an_ended_one(
    config: dict[str, mods.Module],
) -> None:
    writer = Writer(config, lambda m: None)
    st.write("player-capsule", opened())
    writer.set("player-capsule", "player", "active", label="x", target="spotify", now=NOW + 1)
    assert (st.read("player-capsule") or {})["expanded_until"] == NOW + 5
    writer.set("player-capsule", "player", "active", label="y", target="spotify", now=NOW + 6)
    assert "expanded_until" not in (st.read("player-capsule") or {})


def test_expand_on_the_command_line(
    config: dict[str, mods.Module], controller_requests: list[dict[str, Any]]
) -> None:
    st.write("player-capsule", playing())
    first = runner.invoke(barctl_app, ["expand", "player-capsule", "--for", "10s"])
    assert first.exit_code == 0 and first.output.startswith("open until ")
    folded = runner.invoke(barctl_app, ["expand", "player-capsule", "--off"])
    assert (folded.exit_code, folded.output) == (0, "folded\n")
    both = runner.invoke(barctl_app, ["expand", "player-capsule", "--off", "--for", "5s"])
    assert both.exit_code == 2
    bad = runner.invoke(barctl_app, ["expand", "player-capsule", "--for", "soon"])
    assert bad.exit_code == 2
    refused = runner.invoke(barctl_app, ["expand", "player-off"])
    assert refused.exit_code == 3 and "expand_for is 0" in refused.output


# ---------------------------------------------------------------- the source and the store


@pytest.fixture
def playerctl(isolate: Path, commands: Callable[..., Path]) -> Callable[[str], Path]:
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


def stream_line(status: str, loop: str = "", shuffle: str = "") -> str:
    fields = ("spotify", "spotify", status, "a", "t", "100000000", "", "", "", "", loop, shuffle)
    return US.join(fields)


def test_the_format_reads_loop_and_shuffle() -> None:
    assert FORMAT.split(US)[10:] == ["{{loop}}", "{{shuffle}}"]
    assert (shuffle_of("true"), shuffle_of("False"), shuffle_of("")) == (True, False, None)


def test_the_source_gives_a_capsule_loop_and_shuffle(
    config: dict[str, mods.Module], playerctl: Callable[[str], Path]
) -> None:
    playerctl("spotify\n")
    found = PlayerSource(list(config), Writer(config, lambda m: None))
    found.clock = lambda: NOW
    found.event(stream_line("Playing", "Track", "true"))
    capsule = st.read("player-capsule") or {}
    assert (capsule["loop"], capsule["shuffle"]) == ("Track", True)
    assert "loop" not in (st.read("player-metadata") or {})  # only a capsule's
    found.event(stream_line("Playing"))  # a player that gives neither
    capsule = st.read("player-capsule") or {}
    assert "loop" not in capsule and "shuffle" not in capsule
    found.event(stream_line("Playing", "Sometimes", "maybe"))  # nonsense: left out
    assert "loop" not in (st.read("player-capsule") or {})


def test_loop_and_shuffle_poke_only_an_open_row(config: dict[str, mods.Module]) -> None:
    capsule = config["player-capsule"]
    rest, rest_on = playing(), playing(loop="Track", shuffle=True)
    assert shown(capsule, rest, NOW) == shown(capsule, rest_on, NOW)
    assert shown(capsule, opened(), NOW) != shown(capsule, opened(loop="Track"), NOW)


def test_nothing_on_the_line_is_a_tag_a_writer_gave(config: dict[str, mods.Module]) -> None:
    out = draw(config["player-capsule"], opened(label="%{A1:rm -rf ~:}x"))
    assert "rm -rf" not in out  # the row hides the title; its cells are barctl's own
    tags = re.findall(r"%\{A1:([^}]*):\}", out)
    assert all(t.startswith("barctl click player-capsule") for t in tags)

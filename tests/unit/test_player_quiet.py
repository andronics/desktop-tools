"""Quiet when idle and spoken-word controls (record 0005 phase B): the capsule's new keys, the
`status_at` and `kind` state fields, the fade after `fade_after` minutes paused (render, the one
tick wake, play bringing it back), the empty capsule with `unavailable = ""`, each spoken-word
rule and its misses, the Rate read once per track, and the player menu's spoken rows and speed
steps.

No player, no bus, no bar: playerctl is the guarded fake from the capsule's tests, and busctl a
fake that fails the test on `set-property`; the speed row's set-property is checked by its argv,
never run.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import render
from desktop_tools.barctl import state as st
from desktop_tools.barctl.controller import Controller
from desktop_tools.barctl.sources import PlayerSource
from desktop_tools.barctl.sources.player import FORMAT, US, spoken_hint
from desktop_tools.barctl.store import Writer
from desktop_tools.barmenu import menus as bm
from desktop_tools.barmenu.providers import player as player_menu
from tests.fakes import calls
from tests.unit.test_player_capsule import GUARD, visible

CONFIG = """
[modules.player-capsule]
source = "player"
display = "capsule"
glyph_override = { idle = "I", active = "A", unavailable = "" }
width = 10
fade_after = 10
spoken = true
spoken_players = ["Cozy"]

[modules.player-capsule.clicks]
left = ["playerctl", "-p", "{target}", "play-pause"]

[modules.player-plain]
source = "player"
display = "capsule"
width = 10

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
MODULES = ["player-capsule", "player-plain", "player-metadata"]
SET_GUARD = """
if 'set-property' in args:
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
def fakes(isolate: Path, commands: Callable[..., Path]) -> Callable[..., Path]:
    """A guarded playerctl (`-l` lists `listing`, a position read prints 1, `metadata` prints
    `metadata` with | as the separator) and a guarded busctl printing `rates`, one line each."""

    def make(listing: str = "", metadata: str = "", rates: str | None = None) -> Path:
        (isolate / "listing").write_text(listing)
        playerctl = (
            GUARD
            + f"""
metadata = {metadata!r}
if args == ['-l']:
    print(open(here + '/listing').read(), end='')
elif args[0] == '-p' and args[2:] == ['position']:
    print('1')
elif args[0] == '-p' and args[2:4] == ['metadata', '--format'] and metadata:
    print(metadata.replace('|', '\\x1f'))
else:
    sys.exit(1)
"""
        )
        busctl = (
            SET_GUARD
            + f"""
rates = {rates!r}
if os.path.exists(here + '/rates'):
    rates = open(here + '/rates').read()
if rates is None:
    sys.exit(1)
print(rates)
"""
        )
        return commands(playerctl=playerctl, busctl=busctl)

    return make


# ---------------------------------------------------------------- modules.toml


def test_the_keys_default_off_and_are_read_only_for_a_capsule() -> None:
    found = mods.parse({"modules": {"c": {"source": "player", "display": "capsule"}}})["c"]
    assert (found.fade_after, found.spoken, found.spoken_players) == (0, False, ())
    assert found.as_dict()["fade_after"] == 0 and found.as_dict()["spoken"] is False
    other = mods.parse({"modules": {"t": {"source": "player", "display": "text", "spoken": 3}}})
    assert "spoken" not in other["t"].as_dict()


def test_the_packaged_file_turns_nothing_on() -> None:
    for module in mods.load(mods.PACKAGED).values():
        assert (module.fade_after, module.spoken, module.spoken_players) == (0, False, ())


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("fade_after", 241, "fade_after must be 0 to 240"),
        ("fade_after", -1, "fade_after must be 0 to 240"),
        ("fade_after", 2.5, "fade_after must be a whole number"),
        ("fade_after", True, "fade_after must be a whole number"),
        ("spoken", "yes", "spoken must be true or false"),
        ("spoken_players", "cozy", "spoken_players must be a list of player names"),
        ("spoken_players", [1], "spoken_players must be a list of player names"),
        ("spoken_players", [""], "spoken_players must be a list of player names"),
    ],
)
def test_key_errors_name_the_key(key: str, value: object, message: str) -> None:
    with pytest.raises(mods.ConfigError, match=message):
        mods.parse({"modules": {"c": {"source": "player", "display": "capsule", key: value}}})


# ---------------------------------------------------------------- state


def test_status_at_and_kind_are_validated() -> None:
    assert st.validate({"status_at": 5, "kind": "spoken"}) == {"status_at": 5.0, "kind": "spoken"}
    assert st.validate({"kind": ""}) == {}
    with pytest.raises(st.StateError, match="status_at must be epoch seconds"):
        st.validate({"status_at": "soon"})
    with pytest.raises(st.StateError, match="kind must be spoken or empty"):
        st.validate({"kind": "music"})


# ---------------------------------------------------------------- the fade


def paused(status_at: float = 1000.0, **extra: object) -> st.State:
    return {"tier": "idle", "label": "Artist", "glyph": "g", "status_at": status_at, **extra}


def test_the_capsule_fades_to_its_icon_after_fade_after_minutes(
    config: dict[str, mods.Module],
) -> None:
    module = config["player-capsule"]
    state = paused()
    before = render.render(module, state, now=1599.0, colours=COLOURS, controller=True)
    assert visible(before) == "I Artist    "
    after = render.render(module, state, now=1600.0, colours=COLOURS, controller=True)
    assert visible(after) == "I"
    assert "%{F#222222}I%{F-}" in after  # the idle colour, not the accent
    assert "%{A1:barctl click player-capsule left:}" in after  # the faded icon still plays
    assert render.capsule_frame(module, state, 1600.0) == ("", 0)
    assert render.text_of(module, state, 1600.0) == ("idle", "I")


def test_no_fade_while_playing_or_with_fade_after_0(config: dict[str, mods.Module]) -> None:
    playing = {**paused(), "tier": "active"}
    assert render.capsule_frame(config["player-capsule"], playing, 9999.0)[0].strip() == "Artist"
    plain = config["player-plain"]  # fade_after = 0
    assert render.capsule_frame(plain, paused(), 9999.0)[0].strip() == "Artist"
    assert render.next_change(plain, paused(), 1001.0) is None
    no_clock = {k: v for k, v in paused().items() if k != "status_at"}
    assert render.capsule_frame(config["player-capsule"], no_clock, 9999.0)[0].strip() == "Artist"


def test_next_change_wakes_once_at_the_fade(config: dict[str, mods.Module]) -> None:
    module = config["player-capsule"]
    assert render.next_change(module, paused(), 1001.0) == 1600.0
    assert render.next_change(module, paused(), 1600.0) is None  # faded: nothing moves


def test_the_tick_pokes_once_at_the_fade(config: dict[str, mods.Module]) -> None:
    pokes: list[str] = []
    controller = Controller(config, poke=pokes.append, sources={})
    st.write("player-capsule", paused())
    soonest, changed = controller.capsules(1001.0)
    assert soonest == 1600.0 and changed == []
    assert controller.capsules(1300.0) == (1600.0, [])
    assert controller.capsules(1600.0) == (None, ["player-capsule"])
    assert controller.capsules(1700.0) == (None, [])  # once only


def test_play_brings_it_back(config: dict[str, mods.Module]) -> None:
    module = config["player-capsule"]
    back = {**paused(), "tier": "active", "status_at": 2000.0}
    assert visible(render.render(module, back, now=2001.0, colours=COLOURS, controller=True)) == (
        "A Artist    "
    )


def test_no_player_draws_nothing_with_an_empty_unavailable_glyph(
    config: dict[str, mods.Module],
) -> None:
    module = config["player-capsule"]
    assert render.render(module, None, now=1.0, colours=COLOURS, controller=True) == ""
    gone = {"tier": "unavailable"}
    assert render.render(module, gone, now=1.0, colours=COLOURS, controller=True) == ""


# ---------------------------------------------------------------- the source


@pytest.fixture
def source(config: dict[str, mods.Module]) -> tuple[PlayerSource, list[float]]:
    clock = [1000.0]
    found = PlayerSource(MODULES, Writer(config, lambda m: None))
    found.clock = lambda: clock[0]
    return found, clock


def line(instance: str, status: str, title: str = "t", *extra: str) -> str:
    return US.join((instance, instance.split(".")[0], status, "a", title, "100000000", "", *extra))


def test_the_format_reads_the_three_spoken_word_fields() -> None:
    assert FORMAT.split(US)[7:] == ["{{mpris:trackid}}", "{{xesam:url}}", "{{xesam:genre}}"]


def test_status_at_follows_the_shown_players_status_and_who_is_shown(
    config: dict[str, mods.Module],
    source: tuple[PlayerSource, list[float]],
    fakes: Callable[..., Path],
) -> None:
    found, clock = source
    fakes("spotify\nmpv\n")
    found.event(line("spotify", "Paused"))
    assert (st.read("player-capsule") or {})["status_at"] == 1000.0
    clock[0] = 1100.0
    found.event(line("spotify", "Paused", "another title"))  # same status: same clock
    assert (st.read("player-capsule") or {})["status_at"] == 1000.0
    clock[0] = 1200.0
    found.event(line("mpv", "Paused"))  # a newer change: mpv is shown now
    assert (st.read("player-capsule") or {})["target"] == "mpv"
    assert (st.read("player-capsule") or {})["status_at"] == 1200.0
    clock[0] = 1300.0
    found.event(line("spotify", "Playing"))
    assert (st.read("player-capsule") or {})["status_at"] == 1300.0
    assert "status_at" not in (st.read("player-metadata") or {})  # only a capsule's


@pytest.mark.parametrize(
    ("trackid", "url", "genre", "spoken"),
    [
        ("spotify:episode:4rOoJ6Egrf8K2IrywzwOMk", "", "", True),
        ("/org/mpd/Tracks/1", "https://pod.example/episode/12", "", True),
        ("", "", "Podcast", True),
        ("", "", "Fiction, Audiobook", True),
        ("", "", "audio book", True),
        ("", "", "Spoken Word", True),
        ("", "file:///home/s/Books/dune.m4b", "", True),
        ("", "file:///home/s/Books/dune.AAX", "", True),
        ("", "file:///home/s/Podcasts/show/1.mp3", "", True),
        ("", "file:///home/s/audiobooks/x/1.mp3", "", True),
        ("spotify:track:4uLU6hMCjMI75M1A2tKUQC", "", "Trip Hop", False),
        ("", "file:///home/s/Music/mix.mp3", "Electronic", False),
        ("", "https://radio.example/stream.m4b.html", "", False),
        ("", "file:///home/s/Podcasts.mp3", "", False),
        ("", "", "", False),
    ],
)
def test_each_spoken_word_rule_and_its_misses(
    trackid: str, url: str, genre: str, spoken: bool
) -> None:
    assert spoken_hint(trackid, url, genre) is spoken


def test_kind_is_a_capsules_with_spoken_on_and_keeps_nothing_else(
    isolate: Path,
    config: dict[str, mods.Module],
    source: tuple[PlayerSource, list[float]],
    fakes: Callable[..., Path],
) -> None:
    found, _ = source
    fakes("spotify\n", rates="d 1.0")
    url = "https://pod.example/episode/12"
    found.event(line("spotify", "Playing", "t", "spotify:episode:abc", url, "Podcast"))
    assert (st.read("player-capsule") or {})["kind"] == "spoken"
    assert "kind" not in (st.read("player-plain") or {})  # spoken = false: off
    assert "kind" not in (st.read("player-metadata") or {})
    saved = "".join(p.read_text() for p in (isolate / "runtime" / "modules").glob("*.json"))
    assert "episode" not in saved and "Podcast" not in saved  # read, then dropped
    found.event(line("spotify", "Playing", "a song", "spotify:track:x", "", "Rock"))
    assert "kind" not in (st.read("player-capsule") or {})


def test_spoken_players_name_a_player_as_spoken_word(
    config: dict[str, mods.Module],
    source: tuple[PlayerSource, list[float]],
    fakes: Callable[..., Path],
) -> None:
    found, _ = source
    fakes("cozy\n", rates=None)
    found.event(line("cozy", "Playing"))  # spoken_players = ["Cozy"]: any case
    assert (st.read("player-capsule") or {})["kind"] == "spoken"


def test_the_rate_is_read_once_per_track_for_spoken_word_only(
    config: dict[str, mods.Module],
    source: tuple[PlayerSource, list[float]],
    fakes: Callable[..., Path],
) -> None:
    found, clock = source
    log = fakes("spotify\n", rates="d 1.5")
    episode = ("spotify:episode:abc", "", "")
    found.event(line("spotify", "Playing", "one", *episode))
    found.event(line("spotify", "Paused", "one", *episode))
    reads = [c for c in calls(log) if c[0] == "busctl"]
    assert reads == [
        [
            "busctl",
            "--user",
            "get-property",
            "org.mpris.MediaPlayer2.spotify",
            "/org/mpris/MediaPlayer2",
            "org.mpris.MediaPlayer2.Player",
            "Rate",
        ]
    ]
    assert (st.read("player-capsule") or {})["progress"]["rate"] == 1.5
    found.event(line("spotify", "Playing", "two", *episode))
    assert len([c for c in calls(log) if c[0] == "busctl"]) == 2
    (Path(str(log)).parent / "rates").write_text("d 2.0")  # the speed set mid-track
    found.event(line("spotify", "Playing", "two", *episode))
    assert len([c for c in calls(log) if c[0] == "busctl"]) == 2  # same track: no read
    clock[0] = 1000.0 + 31
    assert found.refresh()  # the 30-second re-read reads the Rate again
    assert len([c for c in calls(log) if c[0] == "busctl"]) == 3
    assert (st.read("player-capsule") or {})["progress"]["rate"] == 2.0
    found.event(line("spotify", "Playing", "a song"))  # music: no read, the rate 1.0
    assert len([c for c in calls(log) if c[0] == "busctl"]) == 3
    assert (st.read("player-capsule") or {})["progress"]["rate"] == 1.0


def test_an_unreadable_rate_stays_1(
    config: dict[str, mods.Module],
    source: tuple[PlayerSource, list[float]],
    fakes: Callable[..., Path],
) -> None:
    found, _ = source
    fakes("spotify\n", rates="garbage")
    found.event(line("spotify", "Playing", "one", "spotify:episode:abc"))
    assert (st.read("player-capsule") or {})["progress"]["rate"] == 1.0


def test_with_spoken_off_nothing_reads_the_bus(
    isolate: Path, commands: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = isolate / "plain.toml"
    path.write_text('[modules.player-plain]\nsource = "player"\ndisplay = "capsule"\n')
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    (isolate / "listing").write_text("spotify\n")
    log = commands(
        playerctl=GUARD + "print(open(here + '/listing').read() if args == ['-l'] else '1')",
        busctl="sys.exit(1)",
    )
    found = PlayerSource(["player-plain"], Writer(mods.load(), lambda m: None))
    found.event(line("spotify", "Playing", "one", "spotify:episode:abc"))
    assert "kind" not in (st.read("player-plain") or {})
    assert [c for c in calls(log) if c[0] == "busctl"] == []


# ---------------------------------------------------------------- barmenu player


P = ["playerctl", "-p", "spotify"]
BUS = ["org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player"]
NEXT = ("\U000f04ad", "Next", [*P, "next"], False)
PREVIOUS = ("\U000f04ae", "Previous", [*P, "previous"], False)
LOOP = ("\U000f0457", "Loop: off", [*P, "loop", "Track"], False)
SHUFFLE = ("\U000f049e", "Shuffle: off", [*P, "shuffle", "On"], False)
PLAYER = ("\U000f0411", "Player: spotify \u203a", ["barmenu", "players"], False)
OUTPUT = ("\U000f04c3", "Output… \u203a", ["barmenu", "outputs"], False)
SEEK_10 = [
    ("\U000f0d2a", "Back 10 s", [*P, "position", "10-"], False),
    ("\U000f0d71", "Forward 10 s", [*P, "position", "10+"], False),
]
SEEK_30 = [
    ("\U000f0d96", "Back 30 s", [*P, "position", "30-"], False),
    ("\U000f0d06", "Forward 30 s", [*P, "position", "30+"], False),
]


def speed(label: str, after: str, current: bool) -> tuple[str, str, list[str], bool]:
    command = ["busctl", "--user", "set-property", *BUS, "Rate", "d", after]
    return ("\U000f04c5", f"Speed: {label}\u00d7", command, current)


def capsule_state(kind: str = "spoken") -> None:
    progress = {"position": 1, "length": 3600.0, "rate": 1.0, "at": 1.0, "playing": True}
    data: st.State = {"tier": "active", "label": "x", "target": "spotify", "progress": progress}
    if kind:
        data["kind"] = kind
    st.write("player-capsule", data)


def table(rows: list[bm.Row]) -> list[tuple[str, str, str | list[str], bool]]:
    return [(r.glyph, r.label, r.command, r.current) for r in rows]


@pytest.mark.parametrize(
    ("rates", "row"),
    [
        ("d 1.0\nd 0.5\nd 3.0", speed("1", "1.25", False)),
        ("d 1.25\nd 0.5\nd 3.0", speed("1.25", "1.5", True)),
        ("d 2.0\nd 0.5\nd 3.0", speed("2", "0.75", True)),  # round to the first
        ("d 1.5\nd 1.0\nd 1.5", speed("1.5", "1", True)),  # within the player's own range
        ("d 0.6\nd 0.5\nd 3.0", speed("0.6", "0.75", True)),
    ],
)
def test_spoken_word_rows_keep_eight_and_step_the_speed(
    config: dict[str, mods.Module],
    fakes: Callable[..., Path],
    rates: str,
    row: tuple[str, str, list[str], bool],
) -> None:
    capsule_state()
    log = fakes(metadata="Playing|None|false", rates=rates)
    found = table(player_menu.rows())
    assert found == [NEXT, PREVIOUS, LOOP, row, PLAYER, *SEEK_30, OUTPUT]
    assert len(found) == 8
    reads = [c for c in calls(log) if c[0] == "busctl"]
    assert reads == [
        ["busctl", "--user", "get-property", *BUS, "Rate", "MinimumRate", "MaximumRate"]
    ]


@pytest.mark.parametrize("rates", ["d 1.0\nd 1.0\nd 1.0", None, "d 1.0\nd 0.5", "s x\nd 1\nd 2"])
def test_no_speed_row_on_one_speed_or_an_unreadable_range(
    config: dict[str, mods.Module], fakes: Callable[..., Path], rates: str | None
) -> None:
    capsule_state()
    fakes(metadata="Playing|None|false", rates=rates)
    assert table(player_menu.rows()) == [NEXT, PREVIOUS, LOOP, PLAYER, *SEEK_30, OUTPUT]


def test_music_keeps_shuffle_and_10_s_and_reads_no_rate(
    config: dict[str, mods.Module], fakes: Callable[..., Path]
) -> None:
    capsule_state(kind="")
    log = fakes(metadata="Playing|None|false", rates="d 1.0\nd 0.5\nd 3.0")
    assert table(player_menu.rows()) == [NEXT, PREVIOUS, LOOP, SHUFFLE, PLAYER, *SEEK_10, OUTPUT]
    assert [c for c in calls(log) if c[0] == "busctl"] == []


def test_the_speed_rows_argv_is_a_list_and_never_runs_here(
    config: dict[str, mods.Module], fakes: Callable[..., Path]
) -> None:
    capsule_state()
    fakes(metadata="Playing|None|false", rates="d 1.0\nd 0.5\nd 3.0")
    row = next(r for r in player_menu.rows() if r.label.startswith("Speed"))
    assert isinstance(row.command, list) and json.dumps(row.command).count("set-property") == 1

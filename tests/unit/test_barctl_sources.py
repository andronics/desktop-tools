"""The controller's own sources, against fake pactl and playerctl whose streams the test writes
(ported from tests/barctl.zsh): the player choice, one poke per change to the right module, the
texts, and unavailable when a stream ends."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.sources import PlayerSource, VolumeSource
from desktop_tools.barctl.sources.player import US, player_icon, track
from desktop_tools.barctl.store import Writer

PLAYER_MODS = ["player-play-pause", "player-metadata"]


class Pokes:
    def __init__(self) -> None:
        self.names: list[str] = []

    def __call__(self, name: str) -> None:
        self.names.append(name)

    def wait(self, count: int, timeout: float = 3.0) -> list[str]:
        end = time.monotonic() + timeout
        while len(self.names) < count and time.monotonic() < end:
            time.sleep(0.02)
        time.sleep(0.3)
        return list(self.names)


@pytest.fixture
def writer() -> tuple[Writer, Pokes]:
    pokes = Pokes()
    return Writer(mods.load(), pokes), pokes


@pytest.fixture
def player_data(isolate: Path) -> None:
    """The player tool's instances.json and states.json, as the dotfiles ship them."""
    folder = isolate / "xdg" / "data" / "player"
    folder.mkdir(parents=True)
    (folder / "instances.json").write_text(
        json.dumps(
            [
                {"name": "spotify", "icon": ""},
                {"name": "firefox", "icon": ""},
                {"name": "default", "icon": ""},
            ]
        )
    )
    (folder / "states.json").write_text(
        json.dumps(
            [
                {"state": "paused", "icon": ""},
                {"state": "playing", "icon": ""},
                {"state": "stopped", "icon": ""},
            ]
        )
    )


# ---------------------------------------------------------------- the player choice


def pick(source: PlayerSource, *events: str) -> str | None:
    for e in events:
        source.event(e.replace("|", US))
    return source.pick()


CASES = {
    "playing-beats-paused": (
        "spotify",
        ["spotify|spotify|Playing|a|b", "firefox|firefox|Paused|a|b"],
    ),
    "paused-beats-stopped": (
        "firefox",
        ["spotify|spotify|Stopped|a|b", "firefox|firefox|Paused|a|b", "mpv|mpv|Stopped|a|b"],
    ),
    "latest-playing": ("firefox", ["spotify|spotify|Playing|a|b", "firefox|firefox|Playing|a|b"]),
    "latest-status-change": (
        "spotify",
        [
            "spotify|spotify|Playing|a|b",
            "firefox|firefox|Playing|a|b",
            "spotify|spotify|Paused|a|b",
            "spotify|spotify|Playing|a|b",
        ],
    ),
    "track-change-is-not-status": (
        "firefox",
        [
            "spotify|spotify|Playing|a|b",
            "firefox|firefox|Playing|a|b",
            "spotify|spotify|Playing|a|c",
        ],
    ),
    "both-paused-latest": ("spotify", ["firefox|firefox|Paused|a|b", "spotify|spotify|Paused|a|b"]),
}


@pytest.mark.parametrize("case", CASES)
def test_pick(case: str, writer: tuple[Writer, Pokes], commands: Callable[..., Path]) -> None:
    """Ported: pick-<case>, with spotify, firefox and mpv all live."""
    commands(playerctl="print('spotify\\nfirefox\\nmpv')")
    want, events = CASES[case]
    assert pick(PlayerSource(PLAYER_MODS, writer[0]), *events) == want


def test_gone_players_dropped(
    writer: tuple[Writer, Pokes], commands: Callable[..., Path], isolate: Path
) -> None:
    """Ported: pick-gone-player-dropped and pick-none-left."""
    players = isolate / "players"
    commands(playerctl=f"print(open({str(players)!r}).read())")
    players.write_text("firefox\n")
    source = PlayerSource(PLAYER_MODS, writer[0])
    assert (
        pick(source, "spotify|spotify|Playing|a|b", "firefox|firefox|Paused|a|b", "") == "firefox"
    )
    players.write_text("")
    assert pick(source, "") is None


def test_track_text() -> None:
    assert track("Dear Rouge", "I Heard I Had") == "Dear Rouge: I Heard I Had"
    assert track("", "only title") == "only title"
    long = track("An Artist With A Long Name", "And A Title Long Enough To Be Cut")
    assert len(long) == 40 and long.endswith("…")
    assert player_icon({"*": "D"}, "unknown") == "D"
    assert player_icon({}, "unknown") == ""


# ---------------------------------------------------------------- following the streams


@pytest.fixture
def fifo(isolate: Path) -> Callable[[str], Path]:
    def make(name: str) -> Path:
        path = isolate / f"{name}.fifo"
        os.mkfifo(path)
        return path

    return make


class Feed:
    """The writing end of a FIFO the fake command's stream reads."""

    def __init__(self, path: Path) -> None:
        self.fd = os.open(path, os.O_RDWR)

    def line(self, text: str) -> None:
        os.write(self.fd, (text + "\n").encode())

    def close(self) -> None:
        os.close(self.fd)


def run_source(source: VolumeSource | PlayerSource) -> threading.Thread:
    def follow() -> None:
        source.follow()
        if not source.stopping:
            source.gone()

    thread = threading.Thread(target=follow, daemon=True)
    thread.start()
    return thread


@pytest.fixture
def pulse(
    isolate: Path, commands: Callable[..., Path], fifo: Callable[[str], Path]
) -> Iterator[tuple[Path, Path, Path]]:
    """A fake pulse server: up while pa/up exists; volume and mute are files."""
    pa = isolate / "pa"
    pa.mkdir()
    stream = fifo("pa")
    log = commands(
        pactl=f"""
P = {str(pa)!r}
if not os.path.exists(P + '/up'):
    sys.stderr.write('Connection failure: Connection refused\\n'); sys.exit(1)
if args[0] == 'subscribe':
    os.execvp('cat', ['cat', {str(stream)!r}])
elif args[0] == 'get-default-sink':
    print('alsa_output.test')
elif args[0] == 'get-sink-volume':
    v = open(P + '/vol').read().strip()
    print(f'Volume: front-left: 22937 /  {{v}}% / -27.36 dB,   '
          f'front-right: 22937 /  {{v}}% / -27.36 dB')
elif args[0] == 'get-sink-mute':
    print('Mute: ' + open(P + '/mute').read().strip())
elif args[:3] == ['list', 'short', 'sinks']:
    print('57\\talsa_output.test\\tPipeWire\\ts32le 2ch 48000Hz\\tRUNNING')
    print('58\\tbluez_output.x\\tPipeWire\\ts16le 2ch 48000Hz\\tSUSPENDED')
else:
    open(here + '/unexpected', 'a').write(' '.join(args) + '\\n'); sys.exit(1)
"""
    )
    yield pa, stream, log


def tier(module: str) -> str:
    return str((st.read(module) or {}).get("tier", ""))


def test_volume_follows_pactl_subscribe(
    writer: tuple[Writer, Pokes], pulse: tuple[Path, Path, Path], isolate: Path
) -> None:
    """Ported: volume-start, -mute-one-poke, -ignores-sink-input, -server-event,
    -unchanged-no-poke, -server-gone, -no-other-pactl."""
    pa, stream, _log = pulse
    (pa / "up").touch()
    (pa / "vol").write_text("35")
    (pa / "mute").write_text("no")
    w, pokes = writer
    source = VolumeSource(["audio-level"], w)
    feed = Feed(stream)
    thread = run_source(source)
    assert pokes.wait(1) == ["audio-level"]
    state = st.read("audio-level") or {}
    assert (state["tier"], state["label"], state["glyph"], state["target"]) == (
        "active",
        "35% ",
        "",
        "alsa_output.test",
    )

    (pa / "mute").write_text("yes")
    feed.line("Event 'change' on sink #57")
    assert pokes.wait(2) == ["audio-level"] * 2
    assert tier("audio-level") == "idle"

    (pa / "vol").write_text("60")
    feed.line("Event 'change' on sink-input #12")
    assert len(pokes.wait(3, timeout=0.5)) == 2

    (pa / "mute").write_text("no")
    feed.line("Event 'change' on server #1")
    assert len(pokes.wait(3)) == 3
    assert (st.read("audio-level") or {})["label"] == "60% "
    assert (st.read("audio-level") or {})["glyph"] == ""

    feed.line("Event 'change' on sink #57")
    assert len(pokes.wait(4, timeout=0.5)) == 3

    (pa / "up").unlink()
    feed.close()
    thread.join(3)
    assert len(pokes.names) == 4 and tier("audio-level") == "unavailable"
    assert not (isolate / "unexpected").exists()


def test_volume_zero_and_menu_rows(
    writer: tuple[Writer, Pokes], pulse: tuple[Path, Path, Path]
) -> None:
    pa, _, _ = pulse
    (pa / "up").touch()
    (pa / "vol").write_text("0")
    (pa / "mute").write_text("no")
    source = VolumeSource(["audio-level"], writer[0])
    source.update()
    assert (st.read("audio-level") or {})["glyph"] == ""
    rows = VolumeSource.menu_rows("audio-level", st.read("audio-level"))
    assert [(r.label, r.command) for r in rows] == [
        ("alsa_output.test", ["pactl", "set-default-sink", "alsa_output.test"]),
        ("bluez_output.x", ["pactl", "set-default-sink", "bluez_output.x"]),
    ]
    assert rows[0].glyph and not rows[1].glyph  # the current sink is marked


@pytest.fixture
def players(
    isolate: Path, commands: Callable[..., Path], fifo: Callable[[str], Path], player_data: None
) -> tuple[Path, Path]:
    stream = fifo("pl")
    listing = isolate / "players"
    listing.write_text("")
    commands(
        playerctl=f"""
if args == ['-l']:
    print(open({str(listing)!r}).read(), end='')
elif args[:4] == ['-a', '--follow', 'metadata', '--format']:
    os.execvp('cat', ['cat', {str(stream)!r}])
else:
    open(here + '/unexpected', 'a').write(' '.join(args) + '\\n'); sys.exit(1)
"""
    )
    return stream, listing


def test_player_follows_playerctl(
    writer: tuple[Writer, Pokes], players: tuple[Path, Path], isolate: Path
) -> None:
    """Ported: player-start-none, -playing, -icon, -track-one-poke, -same-no-poke,
    -paused-idle, -metadata-40, -no-other-playerctl."""
    stream, listing = players
    listing.write_text("spotify\n")
    w, pokes = writer
    source = PlayerSource(PLAYER_MODS, w)
    feed = Feed(stream)
    thread = run_source(source)
    assert sorted(pokes.wait(2)) == sorted(PLAYER_MODS)
    assert tier("player-play-pause") == tier("player-metadata") == "unavailable"

    pokes.names.clear()
    feed.line(US.join(["spotify", "spotify", "Playing", "Dear Rouge", "I Heard I Had"]))
    assert sorted(pokes.wait(2)) == sorted(PLAYER_MODS)
    state = st.read("player-metadata") or {}
    assert (state["tier"], state["label"], state["target"]) == (
        "active",
        "Dear Rouge: I Heard I Had",
        "spotify",
    )
    assert (st.read("player-play-pause") or {})["glyph"] == " "

    pokes.names.clear()
    feed.line(US.join(["spotify", "spotify", "Playing", "Dear Rouge", "Next Song"]))
    assert pokes.wait(1) == ["player-metadata"]  # the icon didn't change: one poke

    pokes.names.clear()
    feed.line(US.join(["spotify", "spotify", "Playing", "Dear Rouge", "Next Song"]))
    assert pokes.wait(1, timeout=0.5) == []

    feed.line(US.join(["spotify", "spotify", "Paused", "Dear Rouge", "Next Song"]))
    assert len(pokes.wait(2)) == 2
    assert tier("player-play-pause") == tier("player-metadata") == "idle"

    long = ["An Artist With A Long Name", "And A Title Long Enough To Be Cut %{F#ff0000}"]
    feed.line(US.join(["spotify", "spotify", "Playing", *long]))
    time.sleep(0.4)
    label = (st.read("player-metadata") or {})["label"]
    assert len(label) == 40 and label.endswith("…") and "%{F" not in label

    feed.close()
    thread.join(3)
    assert tier("player-play-pause") == "unavailable"
    assert not (isolate / "unexpected").exists()


def test_player_menu_rows(players: tuple[Path, Path]) -> None:
    _, listing = players
    listing.write_text("spotify\nfirefox.instance123\n")
    rows = PlayerSource.menu_rows("player-play-pause", None)
    assert [(r.glyph, r.label, r.command) for r in rows] == [
        ("", "spotify", ["player", "play-pause", "spotify"]),
        ("", "firefox.instance123", ["player", "play-pause", "firefox.instance123"]),
    ]


def test_source_stop_ends_the_stream(
    writer: tuple[Writer, Pokes], players: tuple[Path, Path]
) -> None:
    source = PlayerSource(PLAYER_MODS, writer[0])
    thread = run_source(source)
    time.sleep(0.3)
    source.stop()
    thread.join(3)
    assert not thread.is_alive()

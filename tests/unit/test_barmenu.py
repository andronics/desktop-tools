"""barmenu: menus as data, rofi placed above the pointer, the pick launched detached, and the
same command line as the zsh barmenu."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from desktop_tools.barctl import state as st
from desktop_tools.barmenu import cli
from desktop_tools.barmenu import menus as bm
from desktop_tools.common import procs
from tests.fakes import FakeJournal, calls

runner = CliRunner()
LEGACY = re.compile("[豈-﫿]")


def rofi(pick: str, code: int = 0) -> str:
    """A fake rofi that records its stdin and picks a row."""
    return (
        f"open(here + '/rofi.in', 'w').write(sys.stdin.read())\nprint({pick!r})\nsys.exit({code})"
    )


def test_the_zsh_menus_carried_over() -> None:
    menus = bm.load()
    assert list(menus) == [
        "layout",
        "lock",
        "player",
        "players",
        "screenshot",
        "session",
        "settings",
        "tessera",
        "theme",
        "vpn",
    ]
    assert [r.label for r in menus["vpn"].rows] == ["CONNECT", "Disconnect", "Information"]
    assert menus["screenshot"].settle == 0.5 and menus["session"].side == "right"
    assert len(menus["layout"].rows) == 8
    for menu in menus.values():
        assert not LEGACY.search(menu.glyph), menu.name
        for row in menu.rows:
            assert not LEGACY.search(row.glyph), (menu.name, row.label)
    assert menus["vpn"].rows[2].argv() == [
        "zsh",
        "-fc",
        'dunstify -t 0 "VPN Status" "$(nordvpn status)"',
    ]


def test_override_adds_and_replaces(isolate: Path) -> None:
    path = isolate / "xdg" / "config" / "barmenu" / "menus.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[menus.vpn]\ntitle = "VPN"\nrows = [{ label = "Only", command = ["nordvpn", "status"] }]\n'
        '[menus.extra]\nrows = []\ndynamic = "audio-level"\n'
    )
    menus = bm.load()
    assert [r.label for r in menus["vpn"].rows] == ["Only"]
    assert menus["vpn"].rows[0].argv() == ["nordvpn", "status"]
    assert menus["extra"].dynamic == "audio-level"


@pytest.mark.parametrize(
    "toml",
    [
        "menus = 1",
        "[menus.run]",
        "[menus.Bad]",
        "[menus]\nx = 1",
        '[menus.x]\nside = "up"',
        "[menus.x]\nsettle = -1",
        "[menus.x]\nrows = 1",
        "[menus.x]\ndynamic = 1",
        "[menus.x]\nglyph = 1",
        "[menus.x]\nrows = [1]",
        '[menus.x]\nrows = [{ label = "" }]',
        '[menus.x]\nrows = [{ label = "a", command = [] }]',
        '[menus.x]\nrows = [{ label = "a", command = "b", current = "yes" }]',
        '[menus.x]\nprovider = "nosuch"',
        "[menus.x]\nprovider = 1",
        '[menus.x]\nprovider = "lock"\ndynamic = "audio-level"',
        "[menus.x",
    ],
)
def test_bad_menus(isolate: Path, monkeypatch: pytest.MonkeyPatch, toml: str) -> None:
    path = isolate / "menus.toml"
    path.write_text(toml)
    monkeypatch.setenv("BARMENU_CONFIG", str(path))
    with pytest.raises(bm.MenuError):
        bm.load()


def test_placement_above_the_pointer(commands: Callable[..., Path]) -> None:
    commands(
        xdotool="print('X=5000\\nY=1400\\nSCREEN=0\\nWINDOW=1')",
        xrandr="print('Monitors: 2\\n 0: +*DP-2 5120/1200x1440/340+0+0  DP-2\\n"
        " 1: +HDMI-1 1920/500x1080/300+5120+0  HDMI-1')",
    )
    args = bm.place("left")
    assert args[:2] == ["-m", "DP-2"]
    # Clamped so the window stays on the monitor: 5120 - 360 - 8.
    assert "x-offset: 4752px" in args[3]


def test_placement_falls_back_to_the_side(commands: Callable[..., Path]) -> None:
    commands(xdotool="sys.exit(1)", xrandr="sys.exit(1)")
    assert "south east" in bm.place("right")[1]
    assert "south west" in bm.place("left")[1]


def test_rows_are_pango_with_a_glyph_column() -> None:
    rows = [bm.Row("", "A & <b>", "x"), bm.Row("", "Plain", "y")]
    assert bm.lines(rows) == [
        "<span font_family='Symbols Nerd Font Mono'></span> A &amp; &lt;b&gt;",
        "Plain",
    ]


def test_choose_with_rofi(isolate: Path, commands: Callable[..., Path]) -> None:
    theme_file = isolate / "xdg" / "config" / "rofi" / "themes" / "bar-menu.rasi"
    theme_file.parent.mkdir(parents=True)
    theme_file.write_text("")
    log = commands(rofi=rofi("1"), xdotool="sys.exit(1)")
    menu = bm.load()["vpn"]
    assert bm.choose(menu) == 1
    argv = calls(log)[-1]
    assert argv[:8] == [
        "rofi",
        "-dmenu",
        "-i",
        "-no-custom",
        "-markup-rows",
        "-format",
        "i",
        "-theme",
    ]
    assert argv[argv.index("-p") + 1] == "\U000f0582 VPN"
    assert (isolate / "rofi.in").read_text().count("\n") == 2
    commands(rofi=rofi("", 1))
    assert bm.choose(menu) is None  # Escape
    commands(rofi=rofi("9"))
    assert bm.choose(menu) is None  # out of range
    assert bm.choose(bm.Menu("empty")) is None


def test_choose_without_rofi(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(isolate / "empty"))
    assert bm.choose(bm.load()["vpn"]) is None
    monkeypatch.setenv("BARMENU_THEME", str(isolate / "missing.rasi"))
    assert bm.theme_args() == []


def test_open_runs_the_pick_detached_after_settling(
    commands: Callable[..., Path], launched: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    # Only barmenu's own `time`: the global time.sleep is subprocess's wait loop too, so
    # patching it made every query's wait spin and record its polls (a flake under load).
    monkeypatch.setattr(bm, "time", SimpleNamespace(sleep=slept.append))
    commands(rofi=rofi("3"), xdotool="sys.exit(1)")
    row = bm.open_menu(bm.load()["screenshot"])
    assert row is not None and row.label == "WINDOW"
    assert launched == [["zsh", "-fc", "screenshot window"]]
    assert slept == [0.5]
    commands(rofi=rofi("", 1))
    assert bm.open_menu(bm.load()["vpn"]) is None


def test_dynamic_rows_from_barctl(
    isolate: Path, commands: Callable[..., Path], launched: list[list[str]]
) -> None:
    commands(
        pactl="print('57\\tsink.a\\tx\\ty\\tz')",
        rofi=rofi("1"),
        xdotool="sys.exit(1)",
    )
    st.write("audio-level", {"tier": "active", "target": "sink.a"})
    menu = bm.Menu("sound", rows=[bm.Row("", "Mixer", ["pwvucontrol"])], dynamic="audio-level")
    assert [r.label for r in bm.with_dynamic(menu).rows] == ["Mixer", "sink.a"]
    bm.open_menu(menu)
    assert launched == [["pactl", "set-default-sink", "sink.a"]]
    assert bm.with_dynamic(bm.Menu("x", dynamic="nosuch")).rows == []


def test_run_detached(launched: list[list[str]]) -> None:
    r = runner.invoke(cli.app, ["run", "power", "menu", "--now"])
    assert r.exit_code == 0
    assert launched == [["power", "menu", "--now"]]


def test_the_command_line(
    isolate: Path,
    commands: Callable[..., Path],
    launched: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = runner.invoke(cli.app, ["--help"])
    for name in (
        "layout",
        "lock",
        "screenshot",
        "session",
        "settings",
        "theme",
        "vpn",
        "run",
        "list",
    ):
        assert name in r.stdout
    assert (
        "VPN menu: CONNECT, Disconnect, Information"
        in runner.invoke(cli.app, ["vpn", "--help"]).stdout
    )
    commands(rofi=rofi("0"), xdotool="sys.exit(1)")
    assert runner.invoke(cli.app, ["settings"]).exit_code == 0
    assert launched == [["zsh", "-fc", "code ~/.config/bspwm"]]
    assert runner.invoke(cli.app, ["list"]).stdout.split()[0] == "layout"


def test_command_line_failures(
    isolate: Path, monkeypatch: pytest.MonkeyPatch, commands: Callable[..., Path]
) -> None:
    def broken(argv: list[str], env: object = None, cwd: object = None) -> int:
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(procs, "detach", broken)
    monkeypatch.setattr(procs, "close_inherited", lambda fd_dir="": [])
    assert runner.invoke(cli.app, ["run", "nosuch"]).exit_code == 4
    commands(rofi=rofi("0"), xdotool="sys.exit(1)")
    assert runner.invoke(cli.app, ["vpn"]).exit_code == 4
    path = isolate / "menus.toml"
    path.write_text("[menus.x")
    monkeypatch.setenv("BARMENU_CONFIG", str(path))
    assert runner.invoke(cli.app, ["vpn"]).exit_code == 2
    assert runner.invoke(cli.app, ["list"]).exit_code == 2
    assert list(cli.build().registered_commands)  # still builds: run and list


def test_main_logs_one_run(
    journal_sock: FakeJournal, monkeypatch: pytest.MonkeyPatch, launched: list[list[str]]
) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["barmenu", "run", "true"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    (entry,) = journal_sock.received()
    assert (entry["SYSLOG_IDENTIFIER"], entry["TOOL_COMMAND"]) == ("barmenu", "run")
    monkeypatch.setattr(sys, "argv", ["barmenu", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    assert journal_sock.received() == []

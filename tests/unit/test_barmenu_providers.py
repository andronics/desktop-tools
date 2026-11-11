"""barmenu's providers (record 0001): the theme and lock menus' rows from stubbed queries, each
row's marked state, and the state-free rows when a query fails or times out."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from desktop_tools.barmenu import cli, providers
from desktop_tools.barmenu import menus as bm
from desktop_tools.barmenu.providers import lock, theme
from desktop_tools.common import procs
from tests.fakes import calls

runner = CliRunner()


def printing(data: object) -> str:
    """A fake command body printing this as JSON."""
    return f"print({json.dumps(data)!r})"


def table(rows: list[bm.Row]) -> list[tuple[str, str, str | list[str], bool]]:
    return [(r.glyph, r.label, r.command, r.current) for r in rows]


# ---------------------------------------------------------------- theme (record 0001 §2)

THEME_TAIL = [
    ("\U000f02f9", "Wallpaper…", ["theme", "pick", "wallpapers"], False),
    ("\U000f076e", "Random wallpaper", ["theme", "random"], False),
]
THEME_END = [
    ("\U000f054c", "Undo", ["theme", "undo"], False),
    ("\U000f0450", "Reload", ["theme", "reload"], False),
    ("\U000f02dc", "Default", ["theme", "apply", "default"], False),
]


def test_theme_rows_dark(commands: Callable[..., Path]) -> None:
    log = commands(
        theme=printing({"name": "catppuccin-mocha", "title": "Catppuccin Mocha", "mode": "dark"})
    )
    assert table(theme.rows()) == [
        ("\U000f08b5", "Scheme: Catppuccin Mocha…", ["theme", "pick"], False),
        *THEME_TAIL,
        ("\U000f050e", "Light mode", ["theme", "mode", "toggle"], False),
        *THEME_END,
    ]
    assert calls(log) == [["theme", "current", "--json"]]  # one read-only query


def test_theme_rows_light(commands: Callable[..., Path]) -> None:
    commands(theme=printing({"title": "Gruvbox Light", "mode": "light"}))
    rows = theme.rows()
    assert rows[0].label == "Scheme: Gruvbox Light…"
    assert rows[3].label == "Dark mode"
    assert not any(r.current for r in rows)


@pytest.mark.parametrize(
    "body",
    [
        "sys.exit(1)",  # the query fails
        "print('not json')",
        printing(["a list"]),
        printing({"title": "", "mode": "dim"}),
        printing({"title": 3}),
    ],
)
def test_theme_rows_without_the_state(commands: Callable[..., Path], body: str) -> None:
    commands(theme=body)
    assert table(theme.rows()) == [
        ("\U000f08b5", "Scheme…", ["theme", "pick"], False),
        *THEME_TAIL,
        ("\U000f050e", "Toggle dark/light", ["theme", "mode", "toggle"], False),
        *THEME_END,
    ]


def test_theme_rows_without_theme(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(isolate / "empty"))
    assert theme.rows()[0].label == "Scheme…"


def test_queries_time_out(commands: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers, "TIMEOUT", 0.2)
    commands(
        theme="time.sleep(5)\n" + printing({"title": "Late", "mode": "dark"}),
        lockscreen="time.sleep(5)\n" + printing({"state": "armed", "until": None}),
    )
    assert theme.rows()[0].label == "Scheme…"
    assert not any(r.current for r in lock.rows())


def test_queries_use_the_two_second_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[list[str], float]] = []

    def query(argv: list[str], timeout: float = 3.0) -> str | None:
        seen.append((list(argv), timeout))
        return None

    monkeypatch.setattr(procs, "query", query)
    theme.rows()
    lock.rows()
    assert seen == [
        (["theme", "current", "--json"], 2.0),
        (["lockscreen", "status", "--json"], 2.0),
    ]


# ---------------------------------------------------------------- lock (record 0001 §3)


def lock_rows(on: tuple[str, list[str], bool], off: bool, timed: tuple[str, bool]) -> list[object]:
    return [
        ("\U000f033e", "Lock now", ["lockscreen", "activate"], False),
        ("\U000f097f", on[0], on[1], on[2]),
        ("\U000f1671", "Idle lock off", ["lockscreen", "hook-disable"], off),
        ("\U000f051f", timed[0], ["lockscreen", "hook-disable", "1h"], timed[1]),
        ("\U000f0904", "Suspend", ["power", "suspend"], False),
        ("\U000f030a", "Forget GPG passphrase", ["lockscreen", "forget-passphrase"], False),
    ]


ENABLE = ["lockscreen", "hook-enable"]
HOUR = "Idle lock off for 1 hour"


def test_lock_armed(commands: Callable[..., Path]) -> None:
    log = commands(lockscreen=printing({"state": "armed", "until": None}))
    assert table(lock.rows()) == lock_rows(("Idle lock on", ENABLE, True), False, (HOUR, False))
    assert calls(log) == [["lockscreen", "status", "--json"]]


def test_lock_paused(commands: Callable[..., Path]) -> None:
    commands(lockscreen=printing({"state": "paused", "until": None}))
    assert table(lock.rows()) == lock_rows(("Idle lock on", ENABLE, False), True, (HOUR, False))


def test_lock_paused_for_a_while(commands: Callable[..., Path]) -> None:
    # A naive ISO time is local; one with an offset is shown in local time.
    commands(lockscreen=printing({"state": "paused", "until": "2026-11-04T15:30:00"}))
    assert table(lock.rows()) == lock_rows(
        ("Idle lock on", ENABLE, False), False, ("Idle lock off until 15:30", True)
    )
    commands(lockscreen=printing({"state": "paused", "until": "2026-11-04T15:30:00+00:00"}))
    assert lock.rows()[3].label.startswith("Idle lock off until ")
    assert lock.rows()[3].current


def test_lock_paused_until_an_unreadable_time(commands: Callable[..., Path]) -> None:
    # Still a timed pause, so its row is marked, with the label that names no time.
    commands(lockscreen=printing({"state": "paused", "until": "soon"}))
    assert table(lock.rows()) == lock_rows(("Idle lock on", ENABLE, False), False, (HOUR, True))
    commands(lockscreen=printing({"state": "paused", "until": 5}))
    assert lock.rows()[3].current


def test_lock_not_running(commands: Callable[..., Path]) -> None:
    commands(lockscreen=printing({"state": "not running", "until": None}))
    assert table(lock.rows()) == lock_rows(
        ("Idle lock on (start it)", ["lockscreen", "hook-init"], False), False, (HOUR, False)
    )


@pytest.mark.parametrize(
    "body",
    [
        "sys.exit(1)",  # today's lockscreen: no --json
        "print('armed')",
        printing({"state": "asleep"}),
        printing(["armed"]),
    ],
)
def test_lock_without_the_state(commands: Callable[..., Path], body: str) -> None:
    commands(lockscreen=body)
    assert table(lock.rows()) == lock_rows(("Idle lock on", ENABLE, False), False, (HOUR, False))


# ---------------------------------------------------------------- the menus


def test_the_packaged_menus_use_the_providers() -> None:
    menus = bm.load()
    assert (menus["theme"].provider, menus["theme"].glyph, menus["theme"].side) == (
        "theme",
        "\U000f03d8",
        "left",
    )
    assert (menus["lock"].provider, menus["lock"].glyph, menus["lock"].side) == (
        "lock",
        "",
        "right",
    )
    assert menus["theme"].rows == [] and menus["lock"].rows == []
    with pytest.raises(KeyError):
        providers.rows("nosuch")


def test_help_names_the_provider_without_calling_it(commands: Callable[..., Path]) -> None:
    log = commands(lockscreen="sys.exit(1)", theme="sys.exit(1)")
    r = runner.invoke(cli.build(), ["lock", "--help"])
    assert "Lock menu: rows from the lock provider" in r.stdout
    assert "theme provider" in runner.invoke(cli.build(), ["theme", "--help"]).stdout
    assert calls(log) == []


def test_static_rows_follow_the_providers(isolate: Path, commands: Callable[..., Path]) -> None:
    commands(lockscreen="sys.exit(1)")
    path = isolate / "xdg" / "config" / "barmenu" / "menus.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[menus.lock]\nprovider = "lock"\nside = "right"\n'
        'rows = [{ label = "Idle lock off for 30 minutes", '
        'command = ["lockscreen", "hook-disable", "30m"], current = true }]\n'
    )
    menu = bm.with_provider(bm.load()["lock"])
    assert [r.label for r in menu.rows][-2:] == [
        "Forget GPG passphrase",
        "Idle lock off for 30 minutes",
    ]
    assert menu.rows[-1].current and menu.side == "right"
    assert (
        "rows from the lock provider, Idle lock off for 30 minutes"
        in bm.load()["lock"].description()
    )
    plain = bm.Menu("x")
    assert bm.with_provider(plain) is plain


def test_current_rows_go_to_rofi_as_active(
    commands: Callable[..., Path], launched: list[list[str]]
) -> None:
    log = commands(
        lockscreen=printing({"state": "paused", "until": None}),
        rofi="sys.stdin.read()\nprint('3')",
        xdotool="sys.exit(1)",
    )
    row = bm.open_menu(bm.load()["lock"])
    assert row is not None and row.label == HOUR
    argv = next(c for c in calls(log) if c[0] == "rofi")
    assert argv[argv.index("-a") + 1] == "2"
    assert "-selected-row" not in argv  # the cursor still starts on the first row
    assert launched == [["lockscreen", "hook-disable", "1h"]]


def test_several_current_rows_and_none(commands: Callable[..., Path]) -> None:
    log = commands(rofi="sys.stdin.read()\nprint('0')", xdotool="sys.exit(1)")
    menu = bm.Menu(
        "x",
        rows=[
            bm.Row("", "a", "a", current=True),
            bm.Row("", "b", "b"),
            bm.Row("", "c", "c", current=True),
        ],
    )
    assert bm.choose(menu) == 0
    assert bm.choose(bm.Menu("y", rows=[bm.Row("", "a", "a")])) == 0
    first, second = (c for c in calls(log) if c[0] == "rofi")
    assert first[first.index("-a") + 1] == "0,2"
    assert "-a" not in second


def test_a_static_row_can_be_current(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = isolate / "menus.toml"
    path.write_text(
        '[menus.x]\nrows = [{ label = "a", command = "a", current = true },\n'
        '  { label = "b", command = "b" }]\n'
    )
    monkeypatch.setenv("BARMENU_CONFIG", str(path))
    assert [r.current for r in bm.load()["x"].rows] == [True, False]


def test_the_theme_menu_opens_with_its_rows(
    commands: Callable[..., Path], launched: list[list[str]]
) -> None:
    commands(
        theme=printing({"title": "Dracula", "mode": "dark"}),
        rofi="open(here + '/rofi.in', 'w').write(sys.stdin.read())\nprint('0')",
        xdotool="sys.exit(1)",
    )
    assert runner.invoke(cli.build(), ["theme"]).exit_code == 0
    assert launched == [["theme", "pick"]]
    shown = (Path(commands()).parent / "rofi.in").read_text().splitlines()
    assert len(shown) == 7 and shown[0].endswith(" Scheme: Dracula…")


# ---------------------------------------------------------------- tessera (record 0002 §2-6)

from datetime import UTC, datetime, timedelta  # noqa: E402

from desktop_tools.barmenu.providers import tessera  # noqa: E402

PLANTED_NAME = "planted/entry-name"  # an entry name that must never reach a row


def fetched(hours: int) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def tessera_status(
    lock: str = "locked",
    waiting: int = 0,
    sync: dict[str, object] | None = None,
    version: str = "0.1.3",
    sync_check: str = "ok",
) -> dict[str, object]:
    return {
        "summary": "v0.1.3",
        "state": "ok",
        "version": version,
        "lock": lock,
        "waiting": waiting,
        "sync": {
            "state": "level",
            "ahead": 0,
            "behind": 0,
            "dirty": 0,
            "first_sync": "done",
            "last_fetch": fetched(20),
            "failing_since": None,
            **(sync or {}),
        },
        "checks": [
            {"name": "sync", "state": sync_check, "detail": "level; ahead 0, behind 0"},
            {"name": "lock", "state": "ok", "detail": "the key is locked"},
        ],
        "names": [PLANTED_NAME],  # not a field tessera gives; if it ever did, no row may show it
    }


def fake_tessera(commands: Callable[..., Path], data: object, code: int = 0) -> Path:
    """A fake tessera that answers `status --json` and fails the test (exit 99) on anything else."""
    return commands(
        tessera=(
            "if args == ['status', '--json']:\n"
            f"    {printing(data)}\n    sys.exit({code})\n"
            "sys.exit(99)"
        )
    )


@pytest.fixture(autouse=True)
def clean_agent_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tessera.AGENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


UNLOCK_ARGV = [
    "alacritty",
    "--class",
    "tessera-prompt",
    "-e",
    "zsh",
    "-fc",
    'tessera unlock || read -sk1 "?Press any key to close"',
]
LOCK_ARGV = [*UNLOCK_ARGV[:-1], 'tessera lock || read -sk1 "?Press any key to close"']
STATUS_ARGV = [*UNLOCK_ARGV[:-1], 'tessera status || read -sk1 "?Press any key to close"']


def labels(rows: list[bm.Row]) -> list[str]:
    return [r.label for r in rows]


def test_tessera_one_query_and_nothing_else(commands: Callable[..., Path]) -> None:
    log = fake_tessera(commands, tessera_status())
    rows = tessera.rows()
    assert calls(log) == [["tessera", "status", "--json"]]
    for row in rows:
        words = " ".join(row.argv())
        for forbidden in ("sync", "show", "otp", "names", "log", "health", "pass "):
            assert f"tessera {forbidden}" not in words
        assert PLANTED_NAME not in words and PLANTED_NAME not in row.label


def test_tessera_uses_the_two_second_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[list[str], float]] = []

    def query(argv: list[str], timeout: float = 3.0, *, any_exit: bool = False) -> str | None:
        seen.append((list(argv), timeout))
        return None

    monkeypatch.setattr(procs, "query", query)
    tessera.rows()
    assert seen == [(["tessera", "status", "--json"], 2.0)]


def test_tessera_locked(commands: Callable[..., Path]) -> None:
    fake_tessera(commands, tessera_status("locked"))
    rows = tessera.rows()
    assert table(rows[:3]) == [
        ("\U000f033e", "Locked", LOCK_ARGV, True),
        ("\U000f033f", "Unlock…", UNLOCK_ARGV, False),
        ("\U000f07f5", "Pick…", ["tessera", "pick"], False),
    ]


def test_tessera_unlocked(commands: Callable[..., Path]) -> None:
    fake_tessera(commands, tessera_status("unlocked"))
    rows = tessera.rows()
    assert (rows[0].label, rows[0].current) == ("Locked", False)
    assert (rows[1].label, rows[1].current) == ("Unlocked", True)


def test_tessera_locked_with_reads_waiting(commands: Callable[..., Path]) -> None:
    fake_tessera(commands, tessera_status("locked", waiting=2))
    rows = tessera.rows()
    assert rows[1].label == "Unlock: 2 waiting…"
    assert rows[1].command == UNLOCK_ARGV


def test_tessera_a_failing_status_still_reads(commands: Callable[..., Path]) -> None:
    """`tessera status` exits 1 when a check fails but prints its JSON: the rows keep the state."""
    fake_tessera(commands, tessera_status("unlocked"), code=1)
    assert tessera.rows()[1].current


SYNC_CASES = [
    ({}, "Sync: level, 20h ago", "\U000f04e6", "ok"),
    ({"state": "ahead", "ahead": 2}, "Sync: ahead 2", "\U000f04e7", "warn"),
    ({"state": "behind", "behind": 3}, "Sync: behind 3", "\U000f04e7", "warn"),
    ({"state": "diverged", "ahead": 1, "behind": 1}, "Sync: diverged", "\U000f04e7", "fail"),
    ({"first_sync": "pending"}, "Sync: first sync pending", "\U000f04e7", "warn"),
    ({"failing_since": "2026-11-10T00:00:00Z"}, "Sync: failing", "\U000f04e7", "fail"),
]


@pytest.mark.parametrize(("sync", "label", "glyph", "check"), SYNC_CASES)
def test_tessera_sync_row(
    commands: Callable[..., Path], sync: dict[str, object], label: str, glyph: str, check: str
) -> None:
    fake_tessera(commands, tessera_status(sync=sync, sync_check=check))
    row = tessera.rows()[-1]
    assert (row.glyph, row.label) == (glyph, label)
    assert row.command[:4] == ["dunstify", "-a", "tessera", "Password store"]
    lines = str(row.command[4]).splitlines()
    assert lines[1] == "ok   lock  the key is locked"
    if check == "ok":
        assert lines[0] == "ok   sync  level; ahead 0, behind 0"
    else:
        assert lines[0].startswith(f"{check:<4} sync  ") and lines[0].endswith(tessera.FIX + ")")
    assert PLANTED_NAME not in " ".join(row.command)


@pytest.mark.parametrize("version", ["0.1.3", "0.2.0", "garbage"])
def test_tessera_pick_flags_follow_the_version(
    commands: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    fake_tessera(commands, tessera_status(version=version))
    assert tessera.PICK_FLAGS_FROM is None  # hidden until the release exists
    assert labels(tessera.rows()) == ["Locked", "Unlock…", "Pick…", "Sync: level, 20h ago"]
    monkeypatch.setattr(tessera, "PICK_FLAGS_FROM", (0, 2, 0))
    rows = tessera.rows()
    if version != "0.2.0":
        assert "Copy password…" not in labels(rows)
        return
    assert table(rows[2:4]) == [
        ("\U000f0306", "Copy password…", ["tessera", "pick", "--password"], False),
        ("\U000f09af", "Copy two-factor code…", ["tessera", "pick", "--otp"], False),
    ]


@pytest.mark.parametrize(
    "body", ["sys.exit(4)", "print('not json')", printing(["a list"]), "time.sleep(5)"]
)
def test_tessera_unreadable_status(
    commands: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    monkeypatch.setattr(providers, "TIMEOUT", 0.2)
    monkeypatch.setattr(tessera, "PICK_FLAGS_FROM", (0, 0, 1))  # even a gated row stays hidden
    commands(tessera=body)
    assert table(tessera.rows()) == [
        ("\U000f033e", "Lock", LOCK_ARGV, False),
        ("\U000f033f", "Unlock…", UNLOCK_ARGV, False),
        ("\U000f07f5", "Pick…", ["tessera", "pick"], False),
        ("\U000f04e6", "Sync status…", STATUS_ARGV, False),
    ]


def test_tessera_missing(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(isolate / "empty"))
    assert labels(tessera.rows()) == ["Lock", "Unlock…", "Pick…", "Sync status…"]


@pytest.mark.parametrize("variable", tessera.AGENT_VARIABLES)
def test_tessera_tainted_environment(
    commands: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    fake_tessera(commands, tessera_status())
    monkeypatch.setenv(variable, "x")
    rows = tessera.rows()
    assert labels(rows) == [
        "Not available: the bar runs in an agent's environment",
        "Sync: level, 20h ago",
    ]
    assert rows[0].command[:4] == ["dunstify", "-a", "tessera", "Password menu"]
    assert not any(r.current for r in rows)


@pytest.mark.parametrize("tainted", [False, True])
def test_tessera_never_touches_the_caller_variables(
    commands: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, tainted: bool
) -> None:
    if tainted:
        monkeypatch.setenv("TESSERA_ACTOR", "x")
    fake_tessera(commands, tessera_status())
    for row in tessera.rows():
        words = " ".join(row.argv())
        assert not any(v in words for v in tessera.AGENT_VARIABLES)
        assert row.argv()[0] not in ("env", "unset") and "unset" not in words


def test_tessera_rows_are_argument_lists_but_the_windows(commands: Callable[..., Path]) -> None:
    fake_tessera(commands, tessera_status())
    rows = tessera.rows()
    assert all(isinstance(r.command, list) for r in rows)
    assert rows[0].command == LOCK_ARGV and rows[1].command == UNLOCK_ARGV
    # the shell strings are the two windows' inner commands and nothing else
    inner = [r.command[-1] for r in rows if r.command[:1] == ["alacritty"]]
    assert inner == [LOCK_ARGV[-1], UNLOCK_ARGV[-1]]


def test_tessera_menu_loads_and_help_runs_nothing(commands: Callable[..., Path]) -> None:
    log = commands(tessera="sys.exit(99)")
    menu = bm.load()["tessera"]
    assert (menu.glyph, menu.title, menu.side, menu.provider) == (
        "\U000f033e",
        "Passwords",
        "right",
        "tessera",
    )
    assert "tessera" in providers.NAMES
    result = runner.invoke(cli.app, ["--help"])
    assert "tessera" in result.stdout
    assert calls(log) == []

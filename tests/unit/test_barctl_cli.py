"""The `barctl` command: the fast path, `--help` running nothing on every command, run records,
and each verb's output and exit code."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner, Result

from desktop_tools.barctl import app as barctl_app
from desktop_tools.barctl import cli
from desktop_tools.barctl import state as st
from desktop_tools.barmenu.cli import app as barmenu_app
from desktop_tools.cli import app as top
from tests import fakes
from tests.fakes import FakeBar, FakeJournal, calls

runner = CliRunner()
BARCTL = [sys.executable, "-m", "desktop_tools.barctl"]
EVERY_COMMAND = [
    "pactl",
    "playerctl",
    "polybar",
    "polybar-msg",
    "rofi",
    "xdotool",
    "xrandr",
    "setsid",
    "zsh",
    "sh",
    "bspc",
    "theme",
    "player",
    "audio",
    "pwvucontrol",
    "crew",
    "notify-send",
    "dunstify",
    "nordvpn",
    "systemctl",
    "cat",
]


def leaves(app: typer.Typer) -> list[list[str]]:
    root = typer.main.get_command(app)

    def walk(group: object, prefix: list[str]) -> list[list[str]]:
        out = []
        for name, cmd in sorted(getattr(group, "commands", {}).items()):
            if hasattr(cmd, "commands"):
                out += walk(cmd, [*prefix, name])
            else:
                out.append([*prefix, name])
        return out

    return walk(root, [])


def test_every_verb_exists() -> None:
    assert sorted(c[0] for c in leaves(barctl_app.app)) == sorted(cli.VERBS)


def test_help_runs_nothing(
    isolate: Path, bar: FakeBar, journal_sock: FakeJournal, commands: Callable[..., Path]
) -> None:
    """Every command's --help, in a real process, under fakes that fail on any call: nothing is
    called, nothing written, no bar or journal message (record 0003 §A7)."""
    log = commands(**dict.fromkeys(EVERY_COMMAND, "sys.exit(1)"))
    env = {**os.environ}
    report = []
    runs = [
        (["barctl"], BARCTL, leaves(barctl_app.app)),
        (
            ["barmenu"],
            [sys.executable, "-c", "from desktop_tools.barmenu.cli import main; main()"],
            leaves(barmenu_app),
        ),
        (["desktop-tools"], [sys.executable, "-m", "desktop_tools"], leaves(top)),
    ]
    for name, argv, commands_ in runs:
        for words in [[], *commands_]:
            for flag in ("--help", "-h") if words and words[0] in cli.FAST else ("--help",):
                result = fakes.run(
                    [*argv, *words, flag], env=env, capture_output=True, text=True, check=False
                )
                line = f"{' '.join([*name, *words, flag])}: exit {result.returncode}"
                report.append(line)
                assert result.returncode == 0, (line, result.stderr)
                assert "Usage" in result.stdout, line
    assert calls(log) == []
    assert bar.messages == []
    assert journal_sock.received() == []
    assert not (isolate / "xdg" / "runtime" / "barctl").exists()
    assert not (isolate / "runs").exists()
    out = os.environ.get("HELP_REPORT")
    if out:
        Path(out).write_text("\n".join(report) + "\n")


def test_fast_path_skips_typer(isolate: Path, theme: dict[str, str]) -> None:
    code = (
        "import sys; sys.argv = ['barctl', 'render', 'audio-level']\n"
        "from desktop_tools.barctl import cli\n"
        "try:\n    cli.main()\nexcept SystemExit:\n    pass\n"
        "sys.stderr.write(str(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('typer', 'click', 'rich', 'interpose', 'yaml'))))\n"
    )
    r = fakes.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert r.stderr == "[]"
    assert theme["unavailable"] in r.stdout  # the default glyph, before any source


def test_render_and_push_write_no_run_record(
    isolate: Path, journal_sock: FakeJournal, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = isolate / "m.toml"
    path.write_text('[modules.crew]\npusher = "crew"\n')
    env = {**os.environ, "BARCTL_CONFIG": str(path)}
    for args in (["render", "crew"], ["push", "crew", "--tier", "active", "--source", "crew"]):
        assert (
            fakes.run([*BARCTL, *args], env=env, capture_output=True, check=False).returncode == 0
        )
    assert journal_sock.received() == []
    assert not (isolate / "runs").exists()
    # Every other verb writes one.
    fakes.run([*BARCTL, "list"], env=env, capture_output=True, check=False)
    (entry,) = journal_sock.received()
    assert (entry["TOOL_EVENT"], entry["TOOL_COMMAND"], entry["SYSLOG_IDENTIFIER"]) == (
        "run",
        "list",
        "barctl",
    )


def test_click_counts_even_under_tool_stats_skip(
    isolate: Path, journal_sock: FakeJournal, commands: Callable[..., Path]
) -> None:
    log = commands(audio="pass")
    env = {**os.environ, "TOOL_STATS": "skip"}
    r = fakes.run(
        [*BARCTL, "click", "audio-level", "left"], env=env, capture_output=True, check=False
    )
    assert r.returncode == 0
    (entry,) = [e for e in journal_sock.received() if e["TOOL_EVENT"] == "run"]
    assert entry["TOOL_COMMAND"] == "click"
    import time

    time.sleep(0.5)
    assert calls(log) == [["audio", "mute-toggle"]]
    # A polled verb under TOOL_STATS=skip: none.
    fakes.run([*BARCTL, "list"], env=env, capture_output=True, check=False)
    assert journal_sock.received() == []


def test_a_usage_error_is_exit_2_and_a_warning(journal_sock: FakeJournal) -> None:
    r = fakes.run([*BARCTL, "show"], capture_output=True, text=True, check=False)
    assert r.returncode == 2
    events = [e["TOOL_EVENT"] for e in journal_sock.received()]
    assert events == ["warning", "run"]


def test_push_through_the_command(
    isolate: Path, bar: FakeBar, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = isolate / "m.toml"
    path.write_text('[modules.crew]\npusher = "crew"\n[modules.audio-level]\nsource = "volume"\n')
    env = {**os.environ, "BARCTL_CONFIG": str(path), "TOOL_JOURNAL": "off"}

    def push(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return fakes.run(
            [*BARCTL, "push", *args],
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    assert (
        push(
            "crew", "--tier=active", "--label", "busy", "--count", "3", "--source", "crew"
        ).returncode
        == 0
    )
    assert (st.read("crew") or {})["count"] == 3
    whole = json.dumps({"source": "crew", "segments": [{"id": "brain", "tier": "alert"}]})
    assert push("crew", "--json", "-", stdin=whole).returncode == 0
    assert (st.read("crew") or {})["segments"][0]["id"] == "brain"
    assert push("audio-level", "--tier", "idle", "--source", "crew").returncode == 3
    assert push("nosuch", "--source", "crew").returncode == 5
    for bad in (
        [],
        ["--tier", "x"],
        ["crew", "--count", "lots"],
        ["crew", "--nope", "1"],
        ["crew", "stray"],
        ["crew", "--label"],
        ["crew", "--json", "file.json"],
        ["crew", "--ttl", "soon"],
    ):
        r = push(*bad)
        assert r.returncode == 2, (bad, r.stderr)
        assert "usage: barctl push" in r.stderr
    assert push("crew", "--json", "-", stdin="[1]").returncode == 2
    assert push("crew", "--tier", "loud", "--source", "crew").returncode == 2
    assert fakes.run([*BARCTL, "render"], env=env, capture_output=True, check=False).returncode == 2
    assert (
        fakes.run([*BARCTL, "render", "a/b"], env=env, capture_output=True, check=False).returncode
        == 2
    )


def invoke(args: list[str]) -> Result:
    return runner.invoke(barctl_app.app, args)


def test_verbs_in_process(
    isolate: Path, bar: FakeBar, theme: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOOL_JOURNAL", "off")
    st.write("audio-level", {"tier": "active", "glyph": "G", "label": "35% ", "updated": 1.0})
    r = invoke(["list"])
    assert r.stdout.split() == ["audio-level", "crew", "player-metadata", "player-play-pause"]
    data = json.loads(invoke(["list", "--json"]).stdout)
    assert data[0] == {
        "name": "audio-level",
        "source": "volume",
        "pusher": None,
        "display": "both",
        "enabled": True,
    }
    r = invoke(["show", "audio-level"])
    assert "volume" in r.stdout and r.exit_code == 0
    assert json.loads(invoke(["show", "audio-level", "--json"]).stdout)["label"] == "35% "
    assert invoke(["show", "nosuch"]).exit_code == 5
    r = invoke(["status"])
    assert r.exit_code == 1 and "controller: not running" in r.stdout
    assert "bar 4242: answering" in r.stdout
    assert json.loads(invoke(["status", "--json"]).stdout)["state"] == "fail"
    assert "(override)" not in invoke(["status"]).stdout  # no packaged module sets one
    assert theme["active"] in invoke(["render", "audio-level"]).stdout
    assert invoke(["disable", "audio-level"]).exit_code == 0
    assert "[disabled]" in invoke(["status"]).stdout
    assert invoke(["enable", "audio-level"]).exit_code == 0
    assert invoke(["enable", "nosuch"]).exit_code == 5
    assert invoke(["reload"]).exit_code == 0
    assert invoke(["reload", "nosuch"]).exit_code == 5
    assert invoke(["hide"]).exit_code == 0 and invoke(["unhide"]).exit_code == 0
    r = invoke(["doctor"])
    assert r.exit_code == 1 and "controller: not running" in r.stdout
    assert isinstance(json.loads(invoke(["doctor", "--json"]).stdout), list)
    assert invoke(["alert", "audio-level", "--for", "soon"]).exit_code == 2
    assert invoke(["alert", "nosuch"]).exit_code == 5
    assert invoke(["click", "nosuch", "left"]).exit_code == 5
    assert invoke(["menu", "nosuch"]).exit_code == 5
    assert invoke(["push", "nosuch", "--source", "x"]).exit_code == 5


def test_alert_and_click_in_process(
    isolate: Path, bar: FakeBar, launched: list[list[str]], commands: Callable[..., Path]
) -> None:
    r = invoke(["alert", "audio-level", "--for", "5s"])
    assert r.exit_code == 0 and "steady urgent" in r.stdout
    assert invoke(["click", "audio-level", "scroll-up"]).exit_code == 0
    assert ["audio", "volume-increase"] in launched
    commands(pactl="print('1\\tsink.a\\tx\\ty\\tz')", rofi="pass", xdotool="sys.exit(1)")
    assert invoke(["menu", "audio-level"]).exit_code == 0  # Escape in the fake rofi


def test_restart_and_theme_report(monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop_tools.common import polybar

    result = polybar.RestartResult()
    result.notes.append("polybar 1 froze on restart; killing and relaunching it")
    result.dead.append(polybar.Launch(["polybar", "main"], {}))
    monkeypatch.setattr("desktop_tools.barctl.ops.restart", lambda bar=None: result)
    r = invoke(["restart"])
    assert r.exit_code == 1 and "froze" in r.stderr and "exited on its config" in r.stderr
    assert invoke(["theme"]).exit_code == 1


def test_run_refuses_a_second_controller(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    folder = st.runtime()
    folder.mkdir(parents=True)
    fd = os.open(folder / "run.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        r = invoke(["run"])
        assert r.exit_code == 1 and "already running" in r.stderr
    finally:
        os.close(fd)
    monkeypatch.setenv("BARCTL_CONFIG", str(isolate / "missing.toml"))
    assert invoke(["run"]).exit_code == 4


def test_watch_follows_changes(isolate: Path) -> None:
    lines: list[str] = []
    rounds = iter(range(3))

    def stop() -> bool:
        n = next(rounds, 99)
        if n == 0:
            st.write("crew", {"tier": "active", "glyph": "G", "label": "busy"})
        if n == 1:
            st.clear("crew")
        return n >= 2

    st.write("audio-level", {"tier": "idle", "glyph": "A"})
    barctl_app.follow([], False, lines.append, stop, interval=0)
    assert [line.split(" ", 1)[1] for line in lines] == [
        "audio-level idle A",
        "crew active G busy",
        "crew gone",
    ]
    out: list[str] = []
    barctl_app.follow(["audio-level"], True, out.append, lambda: True, interval=0)
    assert json.loads(out[0]) == {"module": "audio-level", "state": {"tier": "idle", "glyph": "A"}}


def test_desktop_tools_mounts_the_tools(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_JOURNAL", "off")
    r = runner.invoke(top, ["barctl", "list"])
    assert r.exit_code == 0 and "audio-level" in r.stdout
    r = runner.invoke(top, ["barmenu", "list"])
    assert r.stdout.split() == [
        "layout",
        "lock",
        "outputs",
        "player",
        "players",
        "printer",  # record 0004 §3
        "printer-default",
        "printer-queue",
        "scanner",
        "scanner-devices",
        "scanner-folders",
        "scanner-presets",
        "screenshot",
        "session",
        "settings",
        "tessera",
        "theme",
        "vpn",
    ]
    out = isolate / "completions"
    r = runner.invoke(top, ["completions", "zsh", "--out", str(out)])
    assert r.exit_code == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "_barctl_cmd",
        "_barmenu_cmd",
        "_crew_cmd",
        "_devices_cmd",
    ]
    assert runner.invoke(top, ["completions", "bash", "--out", str(out)]).exit_code == 2


def test_main_entry_points(monkeypatch: pytest.MonkeyPatch, isolate: Path) -> None:
    monkeypatch.setenv("TOOL_JOURNAL", "off")
    monkeypatch.setattr(sys, "argv", ["barctl", "list"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    monkeypatch.setattr(sys, "argv", ["barctl", "render", "audio-level"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    assert cli.run_app([]) == 2  # no command: help, and Typer's usage exit


def test_status_marks_an_overridden_glyph(
    isolate: Path, bar: FakeBar, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOOL_JOURNAL", "off")
    path = isolate / "m.toml"
    path.write_text(
        '[modules.t]\npusher = "t"\nglyph_override = "O"\n[modules.u]\npusher = "u"\nglyph = "U"\n'
    )
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    st.write("t", {"tier": "idle", "glyph": "P", "updated": 1.0})
    st.write("u", {"tier": "idle", "glyph": "P", "updated": 1.0})
    lines = {ln.split()[0]: ln for ln in invoke(["status"]).stdout.splitlines() if "idle" in ln}
    assert "O (override)" in lines["t"] and "P" not in lines["t"].split("O (override)")[1]
    assert "(override)" not in lines["u"] and lines["u"].rstrip().endswith("P")
    data = {m["name"]: m for m in json.loads(invoke(["status", "--json"]).stdout)["modules"]}
    assert data["t"]["glyph_source"] == "override" and data["t"]["glyph_pushed"] == "P"

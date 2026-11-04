"""The `crew` command: the fast path, `--help` running nothing, run records, and each verb's exit
code through the Typer app."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from desktop_tools.cli import app as top
from desktop_tools.crew import app as crew_app
from desktop_tools.crew import cli, store
from tests import fakes
from tests.crew_fakes import Desk
from tests.fakes import FakeJournal, calls

runner = CliRunner()
CREW = [sys.executable, "-m", "desktop_tools.crew"]


def verbs(app: typer.Typer) -> list[str]:
    root = typer.main.get_command(app)
    return sorted(getattr(root, "commands", {}))


def invoke(*args: str) -> int:
    return runner.invoke(crew_app.app, list(args)).exit_code


def test_every_verb_exists() -> None:
    assert verbs(crew_app.app) == sorted(cli.VERBS)


def test_help_runs_nothing(
    isolate: Path, journal_sock: FakeJournal, commands: Callable[..., Path]
) -> None:
    """Every verb's --help, in a real process, under fakes that fail on any call."""
    names = ["bspc", "tmux", "meta", "alacritty", "notify-send", "xprop", "barctl"]
    log = commands(**dict.fromkeys(names, "sys.exit(1)"))
    for words in [[], *([v] for v in cli.VERBS)]:
        for flag in ("--help", "-h"):
            done = fakes.run([*CREW, *words, flag])
            assert done.returncode == 0, (words, done.stderr)
            assert "Usage" in done.stdout
    assert calls(log) == []
    assert journal_sock.received() == []
    assert not (isolate / "runs").exists()
    assert not (isolate / "xdg" / "runtime" / "crew").exists()
    done = fakes.run([*CREW])
    assert "Usage" in done.stdout


def test_desktop_tools_mounts_crew() -> None:
    result = runner.invoke(top, ["crew", "--help"])
    assert result.exit_code == 0 and "switchboard" in result.stdout


@pytest.mark.parametrize("verb", ["status", "bar"])
def test_fast_path_skips_typer(desk: Desk, verb: str) -> None:
    desk.coordinators("brain")
    code = (
        f"import sys; sys.argv = ['crew', {verb!r}]\n"
        "from desktop_tools.crew import cli\n"
        "try:\n    cli.main()\nexcept SystemExit:\n    pass\n"
        "sys.stderr.write(str(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('typer', 'click', 'rich', 'interpose', 'yaml'))))\n"
    )
    done = fakes.run([sys.executable, "-c", code], input="{}")
    assert done.stderr == "[]"


def test_fast_verbs_write_no_run_record(desk: Desk, journal_sock: FakeJournal) -> None:
    desk.coordinators("brain")
    payload = json.dumps({"cwd": f"{desk.actors}/brain", "hook_event_name": "Stop"})
    assert fakes.run([*CREW, "status"], input=payload).returncode == 0
    assert fakes.run([*CREW, "bar"]).returncode == 0
    assert not (isolate_runs := desk.base / "runs").exists(), isolate_runs
    # Every other verb writes one.
    fakes.run([*CREW, "width"])
    (entry,) = [e for e in journal_sock.received() if e.get("TOOL_EVENT") == "run"]
    assert (entry["TOOL_COMMAND"], entry["SYSLOG_IDENTIFIER"], entry["TOOL_OWNER"]) == (
        "width",
        "crew",
        "desktop-coordinator",
    )


def test_guard_writes_no_run_record(desk: Desk, journal_sock: FakeJournal) -> None:
    assert fakes.run([*CREW, "guard"]).returncode == 0
    assert [e for e in journal_sock.received() if e.get("TOOL_EVENT") == "run"] == []


def test_a_failure_is_logged_for_the_owner(desk: Desk, journal_sock: FakeJournal) -> None:
    done = fakes.run([*CREW, "width", "abc"])
    assert done.returncode == 1
    errors = [e for e in journal_sock.received() if e.get("PRIORITY") == "3"]
    assert errors and errors[0]["SYSLOG_IDENTIFIER"] == "crew"


def test_a_usage_error_is_exit_2(desk: Desk) -> None:
    assert fakes.run([*CREW, "cycle", "up"]).returncode == 2
    assert fakes.run([*CREW, "nosuch"]).returncode == 2


def test_verbs_through_the_app(desk: Desk) -> None:
    desk.coordinators("brain", "desktop")
    desk.window("desktop")
    assert invoke("toggle", "desktop") == 0
    assert desk.shown() == ["desktop"]
    assert invoke("hide") == 0
    assert invoke("hide", "--toggle") == 0
    assert desk.shown() == ["desktop"]
    assert invoke("show", "desktop") == 0
    assert invoke("show", "brain") == 1  # stopped: flashed, not started
    assert invoke("toggle", "--launch", "brain") == 0
    assert desk.launched() == ["brain"]
    assert invoke("cycle", "next") == 0
    assert desk.shown() == ["desktop"]
    assert invoke("width", "-128") == 0
    assert store.width() == 1152
    assert invoke("side", "left") == 0
    assert invoke("side") == 0
    assert invoke("width") == 0
    out = runner.invoke(crew_app.app, ["list"])
    assert out.exit_code == 0 and "desktop        visible" in out.stdout
    assert invoke("bar", "--quiet") == 0
    assert invoke("bar") == 0
    assert invoke("status") == 0
    assert invoke("status", "Stop") == 0
    assert invoke("notify", "desktop", "x") == 0
    assert invoke("guard") == 0
    assert invoke("stopped") == 2
    assert invoke("stopped", "brain") == 1  # its window is still open


def test_status_and_bar_fast_dispatch(desk: Desk, monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop_tools.crew import fast

    seen: list[list[str]] = []

    def recorder(verb: str) -> Callable[[list[str]], int]:
        def record(args: list[str]) -> int:
            seen.append([verb, *args])
            return 0

        return record

    monkeypatch.setattr(fast, "status", recorder("status"))
    monkeypatch.setattr(fast, "bar", recorder("bar"))
    for argv in (["status", "Stop"], ["bar", "--quiet"]):
        monkeypatch.setattr(sys, "argv", ["crew", *argv])
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
    assert seen == [["status", "Stop"], ["bar", "--quiet"]]

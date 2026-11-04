"""The journal helper (brain record 0017), with the brain's own test cases for it.

Ported from andronics/brain `tools/tests/test_journal.py` at commit
9544ce8d625f4eac9a0b7918427d080a1806db26, the cases for the helper this package copies: the
native protocol, the fields on every entry, the actor rule, one run entry per run with the right
outcome, exceptions re-raised, a usage error a warning, a CalledProcessError logged by program
and code only, TOOL_STATS=skip and TOOL_JOURNAL=off, a missing socket changing nothing, the rate
limit, size limits, every redaction pattern, arguments scrubbed, the run store's modes and
fields, concurrent appends and the thirteen months kept. The cases for the brain's readers, its
shell helper and its own tools stay in the brain.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import struct
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from desktop_tools.common import journal
from tests import fakes
from tests.fakes import FakeJournal, decode

SECRETS = [
    "zq7HunterPlainWord",
    "hunter2",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "s3cr3tUserPass",
    "0123456789abcdef0123456789abcdef01234567",
]
FINGERPRINT = "903B 5312 0A1C 44D2 9E7F  1B2C 3D4E 5F60 7182 93A4"


@pytest.fixture(autouse=True)
def fresh(
    journal_sock: FakeJournal, monkeypatch: pytest.MonkeyPatch, isolate: Path
) -> Iterator[None]:
    for key in ("COORDINATOR", "CLAUDECODE", "TOOL_JOURNAL", "TOOL_STATS"):
        monkeypatch.setenv(key, "")
    journal._state = journal._Run()
    yield
    journal._state = journal._Run()


def runs(isolate: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for f in sorted((isolate / "runs").glob("*.jsonl"))
        for line in f.read_text().splitlines()
    ]


def raw_store(isolate: Path) -> str:
    root = isolate / "runs"
    return "".join(f.read_text() for f in root.glob("*.jsonl")) if root.is_dir() else ""


def assert_no_secret(*texts: str) -> None:
    for t in texts:
        for s in SECRETS:
            assert s not in t


def run_main(main: Callable[[], object], **kw: object) -> int:
    journal._state = journal._Run()
    return journal.run(main, tool="demo", owner="desktop-coordinator", **kw)  # type: ignore[arg-type]  # the keywords are run()'s own


# ---------------------------------------------------------------- protocol


def test_both_value_forms() -> None:
    data = journal._encode({"MESSAGE": "one", "TRACEBACK": "a\nb"})
    assert data == b"MESSAGE=one\nTRACEBACK\n" + struct.pack("<Q", 3) + b"a\nb\n"
    assert decode(data) == {"MESSAGE": "one", "TRACEBACK": "a\nb"}


def test_fields_on_every_entry(journal_sock: FakeJournal) -> None:
    journal.setup("demo", "desktop-coordinator", commands=["go"])
    journal.command("go")
    journal.error("it broke")
    (e,) = journal_sock.received()
    for k in (
        "SYSLOG_IDENTIFIER",
        "TOOL_OWNER",
        "TOOL_ACTOR",
        "TOOL_VERSION",
        "TOOL_RUN",
        "TOOL_EVENT",
        "TOOL_COMMAND",
    ):
        assert k in e
    assert (e["SYSLOG_IDENTIFIER"], e["TOOL_OWNER"], e["TOOL_EVENT"], e["PRIORITY"]) == (
        "demo",
        "desktop-coordinator",
        "error",
        "3",
    )
    assert e["TOOL_COMMAND"] == "go"
    assert len(e["TOOL_RUN"]) == 8
    assert e["TOOL_VERSION"]  # the installed package's version


def test_command_only_from_the_fixed_list(journal_sock: FakeJournal) -> None:
    journal.setup("demo", "o", commands=["go"])
    journal.command("password=hunter2")
    journal.error("x")
    assert "TOOL_COMMAND" not in journal_sock.received()[0]


def test_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    for env, want in (
        ({"COORDINATOR": "media-coordinator"}, "media-coordinator"),
        ({"COORDINATOR": "Bad Name!"}, "unknown"),
        ({"COORDINATOR": "", "CLAUDECODE": "1"}, "claude"),
    ):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert journal.actor() == want
    monkeypatch.setenv("CLAUDECODE", "")
    assert journal.actor() in ("stephen", "system")
    r = fakes.run(
        [sys.executable, "-c", "from desktop_tools.common import journal; print(journal.actor())"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "COORDINATOR": "", "CLAUDECODE": ""},
        check=False,
    )
    assert r.stdout.strip() == "system"


# ---------------------------------------------------------------- runs


def test_one_run_entry_per_run_and_outcomes(journal_sock: FakeJournal, isolate: Path) -> None:
    assert run_main(lambda: 0) == 0
    assert run_main(lambda: 1, results={1}) == 1
    assert run_main(lambda: 4, results={1}) == 4
    entries = [e for e in journal_sock.received() if e["TOOL_EVENT"] == "run"]
    assert [(e["EXIT_CODE"], e["OUTCOME"], e["PRIORITY"]) for e in entries] == [
        ("0", "ok", "6"),
        ("1", "result", "6"),
        ("4", "fail", "3"),
    ]
    assert [r["outcome"] for r in runs(isolate)] == ["ok", "result", "fail"]


def test_system_exit_and_exceptions_re_raised(journal_sock: FakeJournal) -> None:
    def boom() -> None:
        raise ValueError("bad value")

    with pytest.raises(ValueError):
        run_main(boom)
    with pytest.raises(SystemExit) as c:
        run_main(lambda: sys.exit(5))
    assert c.value.code == 5
    with pytest.raises(SystemExit):
        run_main(lambda: sys.exit("demo: it failed"), results={1})
    got = journal_sock.received()
    events = [(e["TOOL_EVENT"], e.get("OUTCOME")) for e in got]
    assert events == [
        ("exception", None),
        ("run", "fail"),
        ("run", "fail"),
        ("error", None),
        ("run", "fail"),
    ]
    exc = got[0]
    assert exc["MESSAGE"] == "ValueError: bad value"
    assert exc["CODE_FUNC"] == "boom"
    assert "in boom" in exc["TRACEBACK"]
    assert got[3]["MESSAGE"] == "demo: it failed"
    assert [e.get("TOOL_ERRORS") for e in got if e["TOOL_EVENT"] == "run"] == ["1", "0", "1"]


def test_keyboard_interrupt_is_130(journal_sock: FakeJournal) -> None:
    def stop() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_main(stop)
    (e,) = journal_sock.received()
    assert e["EXIT_CODE"] == "130"


def test_usage_error_is_a_warning(journal_sock: FakeJournal) -> None:
    import argparse

    def main() -> None:
        argparse.ArgumentParser(prog="demo").parse_args(["--nope"])

    with pytest.raises(SystemExit):
        run_main(main)
    got = journal_sock.received()
    assert got[0]["TOOL_EVENT"] == "warning"
    assert "usage error" in got[0]["MESSAGE"]
    assert (got[1]["EXIT_CODE"], got[1]["OUTCOME"]) == ("2", "fail")
    assert argparse.ArgumentParser.error.__name__ == "error"  # restored


def test_called_process_error_logs_program_and_code_only(
    journal_sock: FakeJournal, isolate: Path
) -> None:
    """0017 §2.2's test case: the wifi-connect pattern."""

    def main() -> None:
        raise subprocess.CalledProcessError(
            1,
            ["nmcli", "device", "wifi", "connect", "x", "password", "hunter2"],
            output="out hunter2",
            stderr="err hunter2",
        )

    with pytest.raises(subprocess.CalledProcessError):
        run_main(main)

    def timeout() -> None:
        raise subprocess.TimeoutExpired(["/usr/bin/nmcli", "password", "hunter2"], 5)

    with pytest.raises(subprocess.TimeoutExpired):
        run_main(timeout)
    got = journal_sock.received()
    assert got[0]["MESSAGE"] == "CalledProcessError: nmcli exited 1"
    assert got[2]["MESSAGE"] == "TimeoutExpired: nmcli timed out after 5s"
    assert_no_secret(*(json.dumps(e) for e in got), raw_store(isolate))
    assert journal._program("VAR=x cmd") == "?"


def test_stats_skip_and_off(
    journal_sock: FakeJournal, isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOOL_STATS", "skip")

    def broken() -> int:
        journal.error("polled and broken")
        return 0

    run_main(broken)
    assert [e["TOOL_EVENT"] for e in journal_sock.received()] == ["error"]
    assert raw_store(isolate) == ""
    monkeypatch.setenv("TOOL_STATS", "")
    monkeypatch.setenv("TOOL_JOURNAL", "off")
    run_main(broken)
    assert journal_sock.received() == []
    assert raw_store(isolate) == ""


def test_missing_socket_changes_nothing(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_JOURNAL_SOCKET", str(isolate / "nope.sock"))
    assert run_main(lambda: 3, results={3}) == 3
    args = [sys.executable, "-m", "desktop_tools.barctl", "show", "nosuch"]
    on = fakes.run(args, capture_output=True, text=True, check=False)
    off = fakes.run(
        args, capture_output=True, text=True, env={**os.environ, "TOOL_JOURNAL": "off"}, check=False
    )
    assert (on.returncode, on.stdout, on.stderr) == (off.returncode, off.stdout, off.stderr)
    assert on.returncode == 5


def test_rate_limit(journal_sock: FakeJournal, isolate: Path) -> None:
    journal.setup("demo", "o")
    for n in range(3):
        journal.error(f"failed after {n} tries")  # one signature
    assert len(journal_sock.received()) == 1
    stamp = next((isolate / "stamps").iterdir())
    last, count = stamp.read_text().split()
    assert count == "2"
    stamp.write_text(f"{float(last) - 61} {count}")
    journal.error("failed after 9 tries")
    (e,) = journal_sock.received()
    assert e["SUPPRESSED"] == "2"
    journal.warning("another fault")  # another signature: not limited
    assert len(journal_sock.received()) == 1


def test_size_limits(journal_sock: FakeJournal) -> None:
    journal.setup("demo", "o")
    journal.error("x" * 10000)
    (e,) = journal_sock.received()
    assert len(e["MESSAGE"]) == journal.MESSAGE_MAX


def test_die(journal_sock: FakeJournal, capsys: pytest.CaptureFixture[str]) -> None:
    journal.setup("demo", "o")
    with pytest.raises(SystemExit) as c:
        journal.die("demo: gone wrong", 4)
    assert c.value.code == 4
    assert "gone wrong" in capsys.readouterr().err
    assert journal_sock.received()[0]["TOOL_EVENT"] == "error"


# ---------------------------------------------------------------- redaction

PLANTED = {
    "password=hunter2": "password=[redacted]",
    "passwd: hunter2": "passwd: [redacted]",
    "token ghx9TopSecretValue": "token [redacted]",
    "the apikey=abc123def": "the apikey=[redacted]",
    "https://stephen:s3cr3tUserPass@example.com/x": "https://[redacted]@example.com/x",
    "Authorization: Bearer abc.def.ghi": "Authorization: [redacted]",
    "curl -H 'bearer zz9TokenValue'": "curl -H 'bearer [redacted]'",
    (
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA\n-----END OPENSSH PRIVATE KEY-----"
    ): "[redacted]",
    "key ghp_abcdefghijklmnopqrstuvwxyz0123456789 here": "key [redacted] here",
    "github_pat_11ABCDEFG0123456789_abcdefghijkl": "[redacted]",
    "fp 0123456789abcdef0123456789abcdef01234567": "fp [redacted]",
    "b64 dGhpcyBpcyBhIHNlY3JldCB2YWx1ZSBmb3IgdGVzdHM9PQ==": "b64 [redacted]",
}


@pytest.mark.parametrize(("raw", "want"), PLANTED.items())
def test_each_pattern_is_masked(raw: str, want: str) -> None:
    assert journal.redact(raw) == want


def test_sensitive_field_names_dropped(journal_sock: FakeJournal) -> None:
    journal.setup("demo", "o")
    # S106: planted field names, the point of the test.
    journal.error("x", API_KEY="v", MY_PASSWORD="v", SESSION_COOKIE="v", GH_AUTH="v", SAFE="kept")  # noqa: S106
    (e,) = journal_sock.received()
    assert e["SAFE"] == "kept"
    for k in ("API_KEY", "MY_PASSWORD", "SESSION_COOKIE", "GH_AUTH"):
        assert k not in e


def test_spaced_fingerprint_and_paths_untouched() -> None:
    for s in (
        FINGERPRINT,
        "/pool/local/actors/desktop/work/barctl-python/desktop-tools/src/desktop_tools",
        "short abc123 sha",
        "a-very-long-path-component-with-only-letters-in-it",
        "",
    ):
        assert journal.redact(s) == s


def test_real_help_text_passes_unchanged() -> None:
    """Real data: barctl's own --help, which a message may quote, is not mangled."""
    r = fakes.run(
        [sys.executable, "-m", "desktop_tools.barctl", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "TOOL_JOURNAL": "off"},
        check=False,
    )
    assert r.returncode == 0
    assert journal.redact(r.stdout) == r.stdout


def test_arguments_scrubbed_everywhere(journal_sock: FakeJournal) -> None:
    journal.setup(
        "demo", "o", argv=["--name=zq7HunterPlainWord", "zz", "prompt"], commands=["prompt"]
    )
    journal.error("no such thing: zq7HunterPlainWord (prompt, zz)")
    (e,) = journal_sock.received()
    assert e["MESSAGE"] == "no such thing: [arg] (prompt, zz)"


# ---------------------------------------------------------------- the run store


def test_modes_and_fields(isolate: Path) -> None:
    journal.setup("demo", "desktop-coordinator", commands=["go"])
    journal.command("go")
    journal.record(0, 12)
    (f,) = (isolate / "runs").glob("*.jsonl")
    assert f.stat().st_mode & 0o777 == 0o600
    assert (isolate / "runs").stat().st_mode & 0o777 == 0o700
    (line,) = runs(isolate)
    assert set(line) == {
        "ts",
        "tool",
        "command",
        "exit",
        "outcome",
        "duration_ms",
        "actor",
        "owner",
        "version",
        "run",
    }
    assert (line["tool"], line["command"], line["exit"], line["duration_ms"]) == (
        "demo",
        "go",
        0,
        12,
    )


def test_concurrent_appends(isolate: Path) -> None:
    code = (
        "from desktop_tools.common import journal\njournal.setup('demo', 'o')\n"
        "for n in range(50):\n    journal._state.run = '%08x' % n\n    journal.record(n % 3, n)\n"
    )
    procs = [fakes.start([sys.executable, "-c", code]) for _ in range(6)]
    for p in procs:
        assert p.wait(30) == 0
    lines = runs(isolate)
    assert len(lines) == 300


def test_thirteen_months_kept(isolate: Path) -> None:
    root = isolate / "runs"
    root.mkdir(mode=0o700)
    for name in ("2025-10.jsonl", "2025-11.jsonl", "2026-10.jsonl", "notes.txt"):
        (root / name).write_text("")
    journal.prune(root, dt.datetime(2026, 11, 4, tzinfo=dt.UTC))
    assert sorted(p.name for p in root.iterdir()) == ["2025-11.jsonl", "2026-10.jsonl", "notes.txt"]


def test_exit_codes_and_outcomes() -> None:
    assert journal._exit_code(None) == 0
    assert journal._exit_code(True) == 1
    assert journal._exit_code("message") == 1
    assert journal.outcome(5, {5}) == "result"
    assert journal.signature("failed 123 at deadbeef01") == "failed N at N"

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

import builtins
import datetime as dt
import json
import os
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

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
    "nmcli --password hunter2": "nmcli --password [redacted]",
    "password = hunter2": "password = [redacted]",
    "gh-token: abc123": "gh-token: [redacted]",
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


def test_pass_paths_with_their_ages_untouched() -> None:
    """A pass path and its age in days: a path ending in a keyword (token, api-key, secret,
    password) is a name, not a key and its value (the brain's planted defect, PR 158)."""
    for s in (
        "accounts/github.com/gh-cli-token  312",
        "accounts/last.fm/api-key  312",
        "accounts/last.fm/shared-secret  4",
        "accounts/nordvpn.com/cli-password  27",
        "services/github/token 12",
        "actors/tagwarden/api_key  9",
        "services/github/github-token  12",
        "accounts/example.com/X-Api-Key  5",
        "gh-cli-token 312",
        "--token-file /run/x",
    ):
        assert journal.redact(s) == s


HYPHENATED = {
    "gh api --github-token abc123": "gh api --github-token [redacted]",
    "--api-key=x": "--api-key=[redacted]",
    "--api-key x9": "--api-key [redacted]",
    "mysql --db-password hunter2": "mysql --db-password [redacted]",
    "--client-secret s3cr3t": "--client-secret [redacted]",
    "X-Auth-Token deadbeef": "X-Auth-Token [redacted]",
    "curl -H 'X-API-Key k9zz'": "curl -H 'X-API-Key [redacted]'",
    "X-Gitlab-Token: deadbeef": "X-Gitlab-Token: [redacted]",
    "Authorization: Bearer x": "Authorization: [redacted]",
    # Over-masks, the safe direction: a negated option looks like a secret option.
    "--no-password foo": "--no-password [redacted]",
}


@pytest.mark.parametrize(("raw", "want"), HYPHENATED.items())
def test_hyphenated_options_and_headers_masked(raw: str, want: str) -> None:
    """With only a space after it, a keyword ending a hyphenated name was left alone, so an
    option or a header name kept its value (found by this port, fixed in brain PR 193)."""
    assert journal.redact(raw) == want


def test_lowercase_header_without_colon_passes() -> None:
    """As the brain documents: a header name is masked only in Capitalised-Words (or with a
    colon), so a lowercase one with only a space keeps the word after it."""
    assert journal.redact("x-auth-token value") == "x-auth-token value"


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


# ---------------------------------------------------------------- the fields journald adds itself
#
# journald adds _CMDLINE (the sender's /proc/<pid>/cmdline) to every entry: the helper's own
# redaction can't reach it, so the helper rewrites its command line before its first entry. The
# fake journald below reads the command line the way journald does, while the sender is alive.

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="/proc and SO_PASSCRED are Linux's"
)
CMDLINE_SECRET = "SHOULDNOTAPPEAR"  # noqa: S105 - a planted argument, the point of the tests
RAW_SENDER = """import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.sendto(b"MESSAGE=raw\\nSYSLOG_IDENTIFIER=jc-raw\\n", sys.argv[1])
sys.stdin.readline()
"""
PROBE = """import sys
from desktop_tools.common import journal

def main():
    journal.error("probe error")
    sys.stdin.readline()  # alive while the fake journald reads our command line
    return 0

code = journal.run(main, tool="jc-probe", owner="desktop-coordinator")
sys.stdin.readline()
sys.exit(code)
"""
# Loaded first by every Python started with this folder on PYTHONPATH: after each entry it sends,
# the real tool waits for a line on stdin, so the fake journald can read its command line.
PAUSE = """import sys
from desktop_tools.common import journal

_send = journal._send


def _paused(fields):
    _send(fields)
    sys.stdin.readline()


journal._send = _paused
"""


@pytest.fixture
def journald(journal_sock: FakeJournal) -> FakeJournal:
    """The fake journal socket, asking for the sender's credentials as journald does."""
    journal_sock.sock.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    return journal_sock


def receive(fake: FakeJournal, timeout: float = 10.0) -> dict[str, str]:
    """One entry, with the fields journald would add from the sender's credentials and /proc."""
    end = time.time() + timeout
    while True:
        try:
            data, anc, _, _ = fake.sock.recvmsg(1 << 20, socket.CMSG_SPACE(12))
            break
        except BlockingIOError:
            if time.time() > end:
                raise AssertionError("no entry arrived") from None
            time.sleep(0.01)
    ((pid, _uid, _gid),) = [
        struct.unpack("iII", d[:12])
        for lvl, kind, d in anc
        if lvl == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS
    ]
    fields = decode(data)
    fields["_PID"] = str(pid)
    raw = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
    fields["_CMDLINE"] = " ".join(a.decode(errors="replace") for a in raw)
    fields["_COMM"] = Path(f"/proc/{pid}/comm").read_text().strip()
    fields["_EXE"] = os.readlink(f"/proc/{pid}/exe")
    return fields


def hits(entries: list[dict[str, str]]) -> int:
    return sum(CMDLINE_SECRET in v for e in entries for v in e.values())


def entries_of(fake: FakeJournal, p: subprocess.Popen[str], n: int) -> list[dict[str, str]]:
    """n entries from a sender that waits for a line on stdin after each, then its exit."""
    assert p.stdin is not None
    got = []
    try:
        for _ in range(n):
            got.append(receive(fake))
            p.stdin.write("\n")
            p.stdin.flush()
        p.communicate("\n", timeout=30)
    finally:
        p.kill()
    return got


@linux_only
def test_the_fake_journald_sees_a_command_line_secret(journald: FakeJournal) -> None:
    """The planted defect: a sender without the helper has its argument in _CMDLINE."""
    p = fakes.start(
        [sys.executable, "-c", RAW_SENDER, str(journald.path), f"--token={CMDLINE_SECRET}"],
        stdin=subprocess.PIPE,
    )
    (e,) = entries_of(journald, p, 1)
    assert hits([e]) == 1
    assert CMDLINE_SECRET in e["_CMDLINE"]


@linux_only
def test_no_argument_in_any_field_of_a_tool_entry(journald: FakeJournal, isolate: Path) -> None:
    script = isolate / "jc-probe.py"
    script.write_text(PROBE)
    p = fakes.start(
        [sys.executable, str(script), f"--token={CMDLINE_SECRET}", "other words"],
        stdin=subprocess.PIPE,
    )
    got = entries_of(journald, p, 2)  # the error while main() waits, the run while the tool does
    assert p.returncode == 0
    assert [e["TOOL_EVENT"] for e in got] == ["error", "run"]
    assert hits(got) == 0
    assert {e["_CMDLINE"] for e in got} == {f"{sys.executable} {script}"}  # the program alone
    assert CMDLINE_SECRET not in raw_store(isolate)


def _paused_env(isolate: Path) -> dict[str, str]:
    site = isolate / "pause"
    site.mkdir()
    (site / "sitecustomize.py").write_text(PAUSE)
    path = os.pathsep.join(p for p in (str(site), os.environ.get("PYTHONPATH", "")) if p)
    return {**os.environ, "PYTHONPATH": path}


@linux_only
@pytest.mark.parametrize("form", ["module", "script"])
def test_a_desktop_tools_tool_keeps_its_arguments_out(
    journald: FakeJournal, isolate: Path, form: str
) -> None:
    """crew itself, as `python -m desktop_tools.crew` and as the installed `crew` script (what a
    `uv tool` shim or `uv run crew` runs): a usage error's warning and its run entry name the
    program and none of its arguments."""
    if form == "module":
        argv, program = [sys.executable, "-m", "desktop_tools.crew"], None
    else:
        crew = Path(sys.executable).parent / "crew"
        if not crew.is_file():
            pytest.skip("no installed crew script in this environment")
        argv, program = [str(crew)], str(crew)
    p = fakes.start(
        [*argv, "no-such-verb", f"--token={CMDLINE_SECRET}"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_paused_env(isolate),
    )
    got = entries_of(journald, p, 2)
    assert p.returncode == 2
    assert [e["TOOL_EVENT"] for e in got] == ["warning", "run"]
    assert {e["SYSLOG_IDENTIFIER"] for e in got} == {"crew"}
    assert hits(got) == 0
    (cmdline,) = {e["_CMDLINE"] for e in got}
    if program is None:
        assert cmdline == f"{sys.executable} -m desktop_tools.crew"
    else:
        # The script's shebang interpreter, then the script: never the verb or the option.
        assert cmdline.split(" ")[-1] == program
        assert len(cmdline.split(" ")) == 2
    assert CMDLINE_SECRET not in raw_store(isolate)


@linux_only
def test_no_entry_when_the_command_line_cant_be_rewritten(
    journald: FakeJournal, isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal.setup("demo", "desktop-coordinator", argv=[f"--token={CMDLINE_SECRET}"])
    real_open = builtins.open
    tried: list[object] = []

    def refuse(path: object, *a: Any, **k: Any) -> Any:
        if str(path) == "/proc/self/mem":
            tried.append(path)
            raise PermissionError(path)
        return real_open(path, *a, **k)  # type: ignore[call-overload]  # open's own arguments

    with monkeypatch.context() as m:
        m.setattr(sys, "argv", [sys.argv[0], f"--token={CMDLINE_SECRET}"])
        # A program this process isn't, so the rewrite can't find it already done by an
        # earlier test's entry (which rewrote pytest's own command line to its program).
        m.setattr(sys, "orig_argv", [sys.executable, "/nonexistent/jc-demo", *sys.argv[1:]])
        m.setattr(builtins, "open", refuse)
        journal.error("boom")
        journal.record(1, 5)
    assert tried == ["/proc/self/mem"]  # the write was tried, once, and refused
    assert journald.received() == []
    assert len(runs(isolate)) == 1  # the run store still has its line

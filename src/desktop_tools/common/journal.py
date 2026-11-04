"""The journal helper (brain record 0017, with its 2026-11-04 amendment).

Copied from andronics/brain `tools/journal.py` at commit 1aa3be646a9d43867364b864d2cca85063c931a9
(PR 170, 2026-11-04; first copied at 9544ce8, PR 128), as dotfiles record 0003 §A8 decided (its
open question 6: a copy, not a shared package). Changes from the brain's copy, and only these:

- typed for `mypy --strict`, and `except Exception: pass` written as `contextlib.suppress`;
- TOOL_VERSION is the installed package's version, not a checkout's commit (record 0003 §A8:
  `uv tool` installs have no checkout to ask git);
- the readers (`parse_since`, `read_runs`, `oldest_run`, `journalctl`, `owner_map`) and the
  `journal.sh` command line are left out: they serve the brain's `tool-errors`, `tool-stats`
  and shell tools, which live in the brain;
- `allow_commands`, `owner`, `current_owner` and `SLUG_COMMAND` are left out: they serve the
  brain's `meta`, which names its commands and owners at run time.

A tool wraps its main in run() and gets, without changing its output or its exit code:

- **Errors, warnings and uncaught exceptions** to the user journal, over its native socket
  (/run/systemd/journal/socket): error() and warning() for what the tool already prints, die()
  to print, log and exit, a `sys.exit("message")` logged as an error, an argparse usage error as
  a warning, an uncaught exception with its innermost frame and a traceback. The same error
  from the same tool is written at most once a minute; the next one carries SUPPRESSED=<n>.
- **One run record per run**, at the end: to the journal (TOOL_EVENT=run) and as one JSON line
  in ~/.local/state/tool-runs/<YYYY-MM>.jsonl (mode 600, one O_APPEND write per line, thirteen
  months kept), which the brain's `tool-stats` reads. Outcome: `ok` for 0, `result` for a
  declared result code, `fail` for anything else (and for a die() or a `sys.exit("message")`,
  whatever its code).

Every entry carries SYSLOG_IDENTIFIER (the command name), TOOL_OWNER, TOOL_ACTOR (COORDINATOR,
else `claude` under CLAUDECODE, else `stephen` at a terminal, else `system`), TOOL_VERSION,
TOOL_RUN (8 random hex characters, one per run), TOOL_EVENT and, when it is one of the tool's
fixed names, TOOL_COMMAND. Never the arguments: each value is redacted (redact()), every argument
the tool was given (4 characters or more) is replaced by `[arg]` wherever it appears, and a
CalledProcessError or TimeoutExpired is logged as its program's name and code only.

Nor in the fields journald adds itself: it reads the sender's /proc/<pid>/cmdline into
_CMDLINE. So before its first entry the helper rewrites its own process's argument area to the
program alone (`python3 /…/bin/crew`, the arguments dropped), through /proc/self/mem: about
0.1 ms, once per run, and only in a run that writes an entry. From then on `ps` shows the
tool without its arguments; sys.argv is a copy and is unchanged. Where the area can't be
rewritten, the helper writes no journal entry at all rather than one carrying the arguments
(the run store still gets its line).

The helper never fails the tool: every error of its own is swallowed.

Environment: TOOL_JOURNAL=off (write nothing at all), TOOL_STATS=skip (no run record: the
status bar and completions; errors are still written), TOOL_JOURNAL_SOCKET (another socket, for
tests), TOOL_RUNS_DIR (another run store; default $XDG_STATE_HOME/tool-runs), TOOL_JOURNAL_STAMPS
(the rate limit's folder; default $XDG_RUNTIME_DIR/tool-journal).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

SOCKET = "/run/systemd/journal/socket"
MESSAGE_MAX = 4096
TRACEBACK_MAX = 8192
RATE_SECONDS = 60
KEEP_MONTHS = 13
ARG_MIN = 4  # shorter arguments aren't scrubbed: they would mangle every message
PRIORITY = {"error": 3, "exception": 3, "warning": 4}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# ---------------------------------------------------------------- redaction (0017 §2)

SENSITIVE_FIELD = re.compile(r"PASS|SECRET|TOKEN|KEY|AUTH|COOKIE|CRED")
REDACTED = "[redacted]"
_PATTERNS = [
    # Private-key blocks, closed or not.
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]*KEY-----.*?(?:-----END [A-Z0-9 ]*KEY-----|\Z)", re.S),
        REDACTED,
    ),
    # Authorization headers and Bearer values.
    (
        re.compile(r"(?i)\b(authorization\s*:\s*)(?:(?:bearer|basic|token)\s+)?[^\s'\"]+"),
        r"\1" + REDACTED,
    ),
    (re.compile(r"(?i)\b(bearer\s+)[^\s'\"]+"), r"\1" + REDACTED),
    # URL user-info.
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]*@"), r"\1" + REDACTED + "@"),
    # password=…, token: …, secret …: the keyword stays, the word after it goes. With `=` or `:` the
    # keyword may end a longer name (gh-token:, my.password=); with only a space it must stand alone
    # (`password hunter2`, `--password x`), so a name that merely ends in one, such as a pass path
    # (accounts/last.fm/api-key 312) or gh-cli-token, keeps the word after it.
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key)(\s*[=:]\s*)(['\"]?)[^\s'\",;]+"
        ),
        r"\1\2\3" + REDACTED,
    ),
    (
        re.compile(
            r"(?i)(?<![\w/.@])(?<!\w-)(password|passwd|secret|token|api[_-]?key)(\s+)(?![=:])(['\"]?)[^\s'\",;]+"
        ),
        r"\1\2\3" + REDACTED,
    ),
    # GitHub tokens.
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{10,})"), REDACTED),
    # Long hex runs (keys, unspaced fingerprints).
    (re.compile(r"\b[0-9A-Fa-f]{32,}\b"), REDACTED),
]
# Long base64 runs: 32 or more base64 characters with a digit, an upper- and a lower-case
# letter in them, so a long path or a word made of letters alone is left alone.
_B64 = re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}")


def _b64(m: re.Match[str]) -> str:
    s = m.group(0)
    if re.search(r"\d", s) and re.search(r"[a-z]", s) and re.search(r"[A-Z]", s):
        return REDACTED
    return s


def redact(text: str) -> str:
    """Mask what looks like a secret (0017 §2.3). Spaced GPG fingerprints are left alone."""
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return _B64.sub(_b64, text)


def signature(message: str) -> str:
    """A message with its numbers and hex replaced: one signature per kind of fault."""
    s = re.sub(r"\b[0-9a-fA-F]{6,}\b", "N", message or "")
    s = re.sub(r"\d+", "N", s)
    return " ".join(s.split())[:300]


# ---------------------------------------------------------------- the run's state


class _Run:
    def __init__(self) -> None:
        self.tool = Path(sys.argv[0]).name.removesuffix(".py") or "python"
        self.owner = "unknown"
        self.results: frozenset[int] = frozenset()
        self.commands: frozenset[str] = frozenset()
        self.command: str | None = None
        self.run = secrets.token_hex(4)
        self.args: list[str] = []
        self.usage = False
        self.errors = 0  # error, warning and exception events this run, written or suppressed
        self.died = False  # die() or sys.exit("message"): a fail, whatever the code
        self._version: str | None = None
        self.hidden: bool | None = None  # the command line rewritten (None: not yet tried)

    def version(self) -> str:
        if self._version is None:
            # The installed package's version (record 0003 §A8), not a checkout's commit.
            try:
                from importlib.metadata import version

                self._version = version("desktop-tools")
            except Exception:
                self._version = ""
        return self._version


_state = _Run()


def _off() -> bool:
    return os.environ.get("TOOL_JOURNAL", "").lower() in {"off", "0", "no", "false"}


def _skip_stats() -> bool:
    return os.environ.get("TOOL_STATS", "").lower() == "skip"


def actor() -> str:
    """Who is calling (0017 §1): COORDINATOR, else claude, stephen or system."""
    c = os.environ.get("COORDINATOR", "").strip()
    if c:
        return c if SLUG.match(c) else "unknown"
    if os.environ.get("CLAUDECODE"):
        return "claude"
    with contextlib.suppress(Exception):
        if sys.stdin.isatty() or sys.stderr.isatty():
            return "stephen"
    return "system"


def _arg_values(argv: list[str]) -> list[str]:
    """The values in a command line: every word, and what follows `=` in an option."""
    out = []
    for token in argv:
        if token.startswith("-"):
            if "=" in token:
                out.append(token.split("=", 1)[1])
            continue
        out.append(token)
    return sorted(
        {v for v in out if len(v) >= ARG_MIN and v not in _state.commands}, key=len, reverse=True
    )


def scrub(text: str) -> str:
    """Redact, and replace every argument of this run, wherever it appears, by [arg]."""
    if not text:
        return text
    for value in _arg_values(_state.args):
        text = text.replace(value, "[arg]")
    return redact(text)


def setup(
    tool: str,
    owner: str,
    *,
    results: Iterable[int] = (),
    commands: Iterable[str] = (),
    argv: list[str] | None = None,
) -> None:
    """Name the tool and its owner; run() calls it. results: exit codes that are answers.
    commands: the tool's fixed subcommand names, the only values TOOL_COMMAND may take."""
    _state.tool, _state.owner = tool, owner
    _state.results = frozenset(int(r) for r in results)
    _state.commands = frozenset(commands)
    _state.args = list(sys.argv[1:] if argv is None else argv)


def command(name: str | None) -> None:
    """The run's subcommand, if it is one of the fixed names given to setup()."""
    _state.command = name if name in _state.commands else None


# ---------------------------------------------------------------- writing to the journal


def _encode(fields: dict[str, str]) -> bytes:
    out = bytearray()
    for key, value in fields.items():
        data = value.encode("utf-8", "replace")
        if b"\n" in data:
            out += key.encode() + b"\n" + struct.pack("<Q", len(data)) + data + b"\n"
        else:
            out += key.encode() + b"=" + data + b"\n"
    return bytes(out)


def _program_words() -> list[str]:
    """This process's command line without the tool's arguments: the interpreter, its options
    and the script, or `-m module`; for `-c` the code goes too. Read from the interpreter's own
    command line (sys.orig_argv), not sys.argv, which a tool may have changed."""
    orig = list(getattr(sys, "orig_argv", None) or [])
    i = 1
    while i < len(orig):
        w = orig[i]
        if w.startswith("-c"):
            return [*orig[:i], "-c"]
        if w == "-m":
            return orig[: i + 2]
        if w.startswith("-m"):
            return orig[: i + 1]
        if w in ("-X", "-W", "--check-hash-based-pycs"):
            i += 2
        elif w == "--":
            return orig[: i + 2]
        elif w.startswith("-") and w != "-":
            i += 1
        else:
            return orig[: i + 1]  # the script (or `-`, stdin)
    return orig or [_state.tool]


def _hide_arguments() -> bool:
    """Rewrite this process's argument area, which journald copies into _CMDLINE, to the program
    alone. True when /proc/self/cmdline then holds no argument (or there were none)."""
    if _state.hidden is not None:
        return _state.hidden
    want = b"\0".join(os.fsencode(w) for w in _program_words())
    try:
        with open("/proc/self/cmdline", "rb") as fh:
            now = fh.read()
        if now.rstrip(b"\0") == want:
            _state.hidden = True  # nothing to hide, or done before in this process
            return True
        with open("/proc/self/stat", "rb") as fh:
            stat = fh.read()
        fields = stat[stat.rfind(b")") + 2 :].split()
        start, end = int(fields[45]), int(fields[46])  # arg_start, arg_end (proc(5) fields 48, 49)
        size = end - start
        if not 0 < len(want) < size:
            want = os.fsencode(_state.tool)[: max(0, size - 1)]
        with open("/proc/self/mem", "r+b", buffering=0) as mem:
            mem.seek(start)
            mem.write(want + b"\0" * (size - len(want)))  # ends in NUL: the kernel reads it all
        with open("/proc/self/cmdline", "rb") as fh:
            _state.hidden = fh.read().rstrip(b"\0") == want
    except Exception:
        _state.hidden = False
    return _state.hidden


def _send(fields: dict[str, str]) -> None:
    path = os.environ.get("TOOL_JOURNAL_SOCKET") or SOCKET
    if not _hide_arguments():
        return  # never an entry whose _CMDLINE would carry the arguments
    with (
        contextlib.suppress(Exception),
        socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s,
    ):
        s.sendto(_encode(fields), path)


def _limited(event: str, message: str) -> int | None:
    """None when this error was written less than a minute ago (and it is counted); else how
    many were suppressed since the last one written."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    root = os.environ.get("TOOL_JOURNAL_STAMPS") or (
        os.path.join(runtime, "tool-journal") if runtime else ""
    )
    if not root:
        return 0
    key = hashlib.sha256(f"{_state.tool}\0{event}\0{signature(message)}".encode()).hexdigest()[:24]
    old = os.umask(0o077)
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(root, key), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except Exception:
        return 0
    finally:
        os.umask(old)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        raw = os.read(fd, 64).decode().split()
        last, count = (float(raw[0]), int(raw[1])) if len(raw) == 2 else (0.0, 0)
        now = time.time()
        result: int | None
        if now - last < RATE_SECONDS:
            new, result = f"{last} {count + 1}", None
        else:
            new, result = f"{now} 0", count
        os.lseek(fd, 0, 0)
        os.ftruncate(fd, 0)
        os.write(fd, new.encode())
        return result
    except Exception:
        return 0
    finally:
        os.close(fd)


def _fields(
    event: str, priority: int, message: str, extra: dict[str, str] | None = None
) -> dict[str, str]:
    fields = {
        "MESSAGE": scrub(message)[:MESSAGE_MAX],
        "PRIORITY": str(priority),
        "SYSLOG_IDENTIFIER": _state.tool,
        "TOOL_OWNER": _state.owner,
        "TOOL_ACTOR": actor(),
        "TOOL_VERSION": _state.version(),
        "TOOL_RUN": _state.run,
        "TOOL_EVENT": event,
    }
    if _state.command:
        fields["TOOL_COMMAND"] = _state.command
    for key, value in (extra or {}).items():
        value = scrub(str(value))
        fields[key] = value[:TRACEBACK_MAX] if key == "TRACEBACK" else value[:MESSAGE_MAX]
    return {k: v for k, v in fields.items() if not SENSITIVE_FIELD.search(k)}


def _event(event: str, message: str, extra: dict[str, str] | None = None) -> None:
    with contextlib.suppress(Exception):
        if _off():
            return
        _state.errors += 1
        suppressed = _limited(event, scrub(message))
        if suppressed is None:
            return
        extra = dict(extra or {})
        if suppressed:
            extra["SUPPRESSED"] = str(suppressed)
        _send(_fields(event, PRIORITY[event], message, extra))


def error(message: str, **fields: str) -> None:
    """Log an error the tool already prints (it doesn't print it)."""
    _event("error", message, fields)


def warning(message: str, **fields: str) -> None:
    """Log a warning the tool already prints (it doesn't print it)."""
    _event("warning", message, fields)


def die(message: str, code: int = 1) -> None:
    """Print the message on stderr, log it as an error, and exit with code."""
    sys.stderr.write(message + "\n")
    error(message)
    _state.died = True
    raise SystemExit(code)


def _program(cmd: object) -> str:
    first: Any
    first = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else str(cmd or "").split(" ", 1)[0]
    name = os.path.basename(os.fsdecode(first))
    # Never `VAR=value` from a shell string.
    return name if re.fullmatch(r"[\w.+-]{1,64}", name) else "?"


def exception(e: BaseException) -> None:
    """Log an uncaught exception: its type, its message (a command's only by program and code),
    the innermost frame and the traceback's frames (file, line and function, no source)."""
    with contextlib.suppress(Exception):
        kind = type(e).__name__
        if isinstance(e, subprocess.CalledProcessError):
            text = f"{_program(e.cmd)} exited {e.returncode}"
        elif isinstance(e, subprocess.TimeoutExpired):
            text = f"{_program(e.cmd)} timed out after {e.timeout}s"
        else:
            text = str(e)
        message = f"{kind}: {text}" if text else kind
        frames = traceback.extract_tb(e.__traceback__)
        # The frames without their source lines: a line of code can hold a literal secret.
        extra = {
            "TRACEBACK": "".join(
                f'  File "{f.filename}", line {f.lineno}, in {f.name}\n' for f in frames
            )
            + message
        }
        if frames:
            extra.update(
                CODE_FILE=frames[-1].filename,
                CODE_LINE=str(frames[-1].lineno),
                CODE_FUNC=frames[-1].name,
            )
        _event("exception", message, extra)


# ---------------------------------------------------------------- the run record


def runs_dir() -> Path:
    if os.environ.get("TOOL_RUNS_DIR"):
        return Path(os.environ["TOOL_RUNS_DIR"])
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return Path(state) / "tool-runs"


def _months(d: dt.datetime) -> int:
    return d.year * 12 + d.month - 1


def prune(root: Path, now: dt.datetime | None = None) -> None:
    """Keep this month's file and the twelve before it."""
    now = now or dt.datetime.now(dt.UTC)
    for f in root.glob("*.jsonl"):
        m = re.fullmatch(r"(\d{4})-(\d{2})\.jsonl", f.name)
        if m and int(m[1]) * 12 + int(m[2]) - 1 <= _months(now) - KEEP_MONTHS:
            with contextlib.suppress(OSError):
                f.unlink()


def outcome(code: int, results: Iterable[int] = frozenset()) -> str:
    return "ok" if code == 0 else "result" if code in set(results) else "fail"


def record(code: int, duration_ms: int, now: dt.datetime | None = None) -> None:
    """The run's end: one journal entry and one line in the run store."""
    with contextlib.suppress(Exception):
        if _off() or _skip_stats():
            return
        now = now or dt.datetime.now(dt.UTC)
        out = "fail" if _state.died and code else outcome(code, _state.results)
        name = f"{_state.tool}{' ' + _state.command if _state.command else ''}"
        _send(
            _fields(
                "run",
                3 if out == "fail" else 6,
                f"{name}: exit {code} ({out}), {duration_ms} ms",
                {
                    "EXIT_CODE": str(code),
                    "OUTCOME": out,
                    "DURATION_MS": str(duration_ms),
                    "TOOL_ERRORS": str(_state.errors),
                },
            )
        )
        line = {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "tool": _state.tool,
            "command": _state.command,
            "exit": code,
            "outcome": out,
            "duration_ms": duration_ms,
            "actor": actor(),
            "owner": _state.owner,
            "version": _state.version(),
            "run": _state.run,
        }
        data = (json.dumps(line, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        root = runs_dir()
        path = root / f"{now:%Y-%m}.jsonl"
        old = os.umask(0o077)
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            new = not path.exists()
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
            try:
                os.write(fd, data)  # one write per line, under O_APPEND: safe for concurrent runs
            finally:
                os.close(fd)
        finally:
            os.umask(old)
        if new:
            prune(root, now)


def _exit_code(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 1  # sys.exit("message")


def run(
    main: Callable[..., object],
    *args: object,
    tool: str,
    owner: str,
    results: Iterable[int] = (),
    commands: Iterable[str] = (),
    command_of: Callable[[list[str]], str | None] | None = None,
) -> int:
    """Run main(*args) and log it (0017 §3): its exit code is returned, and a SystemExit or an
    exception is re-raised, so the tool behaves as without it. command_of(argv) names the
    subcommand from the tool's fixed `commands`."""
    import argparse

    setup(tool, owner, results=results, commands=commands)
    if command_of:
        with contextlib.suppress(Exception):
            command(command_of(list(_state.args)))
    original = argparse.ArgumentParser.error

    def usage(self: argparse.ArgumentParser, message: str) -> Any:
        if not _state.usage:
            _state.usage = True
            warning(f"usage error: {message}")
        return original(self, message)

    argparse.ArgumentParser.error = usage  # type: ignore[method-assign]  # restored below
    start = time.monotonic()
    code = 1
    try:
        code = _exit_code(main(*args))
        return code
    except SystemExit as e:
        code = _exit_code(e.code)
        if isinstance(e.code, str):
            error(e.code)
            _state.died = True
        raise
    except KeyboardInterrupt:
        code = 130
        raise
    except BaseException as e:
        code = 1
        exception(e)
        raise
    finally:
        argparse.ArgumentParser.error = original  # type: ignore[method-assign]  # the original
        record(code, int((time.monotonic() - start) * 1000))

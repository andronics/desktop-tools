"""One call to the brain's `meta` for a coordinator's lifecycle (brain record 0019 §3a):
`meta <name> launch|stop|restart [args]`. crew starts and stops coordinators only through it, and
keeps none of its rules: who may, the brain, the resume notes and the old names are all meta's.

What comes back is meta's exit code and its one-line reason, for the notification and for crew's
own exit status. meta's codes: 0 done, 1 a result (for a stop: the notes are not clean, nothing
ended), 2 usage or no home, 3 refused, 4 failed, 5 not found, 6 broken. When meta can't be run
at all (not on PATH, or no answer in time), crew answers 4 itself.
"""

from __future__ import annotations

import re
import subprocess

from desktop_tools.crew import conf

RESULT, FAILED, NOT_FOUND = 1, 4, 5
# What meta's failure codes mean, in words (record 0019's exit codes). 0, 1 and 5 are results.
MEANS = {2: "usage", 3: "refused", 4: "failed", 6: "the module is broken"}
TIMEOUTS = {"launch": 30.0, "stop": 90.0, "restart": 150.0}  # restart: a stop, up to 30 s, a launch
_WHY = re.compile(r' why=(?:"((?:[^"\\]|\\.)*)"|(\S+))')


class Result:
    __slots__ = ("code", "ran", "why")

    def __init__(self, code: int, why: str, ran: bool = True) -> None:
        self.code, self.why, self.ran = code, why, ran

    @property
    def ok(self) -> bool:
        return self.code == 0


def exited(code: int) -> str:
    """`exited 3 (refused)`: the code, and what it means when it is one of meta's failures."""
    return f"exited {code} ({MEANS[code]})" if code in MEANS else f"exited {code}"


def reason(stdout: str, stderr: str) -> str:
    """meta's one line: the stop script's `why=` from its log line on stdout (its verdict), else
    the last line meta wrote on stderr (its own refusals and errors), else stdout's last line."""
    out = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    for line in reversed(out):
        found = _WHY.search(line)
        if found:
            text = found.group(1) if found.group(1) is not None else found.group(2)
            return text.replace('\\"', '"').replace("\\\\", "\\")
    err = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    if err:
        return err[-1]
    return out[-1] if out else ""


def call(
    args: list[str], timeout: float | None = None
) -> subprocess.CompletedProcess[str] | Result:
    """`meta <args...>` with no terminal, its output kept (the quick menu's items and views): the
    finished process, or a Result (code 4, ran False) when meta couldn't be run."""
    argv = [conf.meta(), *args]
    verb = args[1] if len(args) > 1 else ""
    try:
        # S603: a fixed argument list; meta is $BRAIN_BIN/meta or found on PATH.
        return subprocess.run(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout or TIMEOUTS.get(verb, 30.0),
            check=False,
        )
    except FileNotFoundError:
        return Result(FAILED, "meta is not on PATH", ran=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Result(FAILED, f"meta {' '.join(args[:2])}: {type(e).__name__}", ran=False)


def run(name: str, verb: str, *args: str) -> Result:
    """`meta <name> <verb> [args]`, with no terminal: crew runs from keys, the bar and the menu."""
    done = call([name, verb, *args])
    if isinstance(done, Result):
        return done
    return Result(done.returncode, reason(done.stdout, done.stderr))

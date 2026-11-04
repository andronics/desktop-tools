"""crew's messages: one line on stderr (`crew: ...`) and, for errors and warnings, the journal
(brain record 0017), rate-limited by the helper.

crew runs from sxhkd, polybar and Claude's hooks, whose stderr may be a terminal that has gone;
a failed write there is not a failure of the command, so every write here is guarded.
"""

from __future__ import annotations

import contextlib
import os
import sys


def _write(line: str) -> None:
    with contextlib.suppress(OSError, ValueError):
        sys.stderr.write(f"crew: {line}\n")
        sys.stderr.flush()


def _journal(kind: str, message: str) -> None:
    from desktop_tools.common import journal

    with contextlib.suppress(Exception):
        # Inside journal.run (the Typer verbs) the run is already named; setting it up again
        # would drop its command. The fast path and the detached helpers name it here.
        if journal._state.owner == "unknown":
            journal.setup("crew", "desktop-coordinator", argv=sys.argv[1:])
        (journal.error if kind == "error" else journal.warning)(message)


def error(message: str) -> None:
    _write(message)
    _journal("error", message)


def warning(message: str) -> None:
    _write(message)
    _journal("warning", message)


def info(message: str) -> None:
    _write(message)


def debug(message: str) -> None:
    if os.environ.get("CREW_DEBUG", "") not in ("", "0"):
        _write(message)

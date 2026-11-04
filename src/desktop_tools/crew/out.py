"""crew's one way to write stdout (the CLI's lines: a width, a side, the strip, the list)."""

from __future__ import annotations

import os
import sys


def say(text: str) -> bool:
    """One line on stdout, unbuffered. False when stdout is gone (sxhkd's dead pty, a full
    disk): the caller decides whether that matters."""
    try:
        if sys.stdout is sys.__stdout__:
            # Unbuffered, so nothing is left for Python to fail flushing at exit (exit 120).
            os.write(1, (text + "\n").encode())
        else:  # a caller's own stream (a test's runner)
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
    except (OSError, ValueError):
        return False
    return True

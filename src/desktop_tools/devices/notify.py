"""Notifications for the devices: `dunstify -a printer|scanner`, the result in words (§4)."""

from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Sequence


def send(app: str, title: str, body: str = "", *extra: str) -> None:
    """A notification; quietly nothing when dunstify is missing or fails."""
    send_raw(["dunstify", "-a", app, *extra, title, *([body] if body else [])])


def ask(app: str, title: str, body: str, actions: Sequence[tuple[str, str]]) -> str:
    """A notification with actions: the action picked, or "" when it closed (it waits)."""
    argv = ["dunstify", "-a", app]
    for key, label in actions:
        argv += ["-A", f"{key},{label}"]
    try:
        # S603/S607: as above; it blocks until an action is picked or the notification closes.
        done = subprocess.run(  # noqa: S603
            [*argv, title, body],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip()


def progress(app: str, title: str, body: str) -> subprocess.Popen[str] | None:
    """A notification with a `Stop` action that stays up (`-t 0`): its process prints its id
    (`-p`) and then `stop` when Stop is picked. None when it can't start."""
    try:
        # S603/S607: as above.
        return subprocess.Popen(  # noqa: S603
            ["dunstify", "-a", app, "-p", "-t", "0", "-A", "stop,Stop", title, body],  # noqa: S607
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None


def close(notification_id: str) -> None:
    if notification_id.isdigit():
        send_raw(["dunstify", "-C", notification_id])


def send_raw(argv: list[str]) -> None:
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        # S603: a fixed argument list; dunstify is found on PATH like every bar command.
        subprocess.run(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )

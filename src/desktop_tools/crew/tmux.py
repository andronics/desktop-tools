"""tmux, read only: which coordinator sessions exist. Every call names the server crew was told
to use (`CREW_TMUX_SOCKET`, `-L` or `-S`; the default server when unset), so a test never reaches
the live one."""

from __future__ import annotations

import subprocess

from desktop_tools.crew import conf

TIMEOUT = 3.0


def sessions() -> set[str]:
    """Every session's name; empty when tmux or its server isn't there."""
    try:
        # S603: tmux with crew's fixed arguments.
        done = subprocess.run(  # noqa: S603
            [*conf.tmux(), "list-sessions", "-F", "#S"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if done.returncode != 0:
        return set()
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


def attach_argv(session: str) -> list[str]:
    """What a crew window runs: attach to the session, exactly (`=`), never create one, so
    opening a window can't start a coordinator."""
    return [*conf.tmux(), "attach-session", "-t", f"={session}"]

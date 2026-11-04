"""Running other programs: a short query, a followed stream, and a detached launch.

Every child of the desktop tools starts here, so the rules live in one place:

- Commands are argument lists, never shell strings, unless a caller asks for a shell on purpose
  (barmenu's rows are shell commands, as they were in the zsh barmenu).
- polybar 3.7 opens its module pipes without close-on-exec and forks click commands from
  several threads, so a click handler can inherit another module's output pipe; anything
  long-lived that holds it can freeze the bar's next restart. A launch from a click therefore
  closes every inherited descriptor and starts a new session (`detach`), and a click handler
  that stays up for a while itself (barmenu, while rofi is open) first drops the pipes it
  inherited (`close_inherited`): the zsh `_barmenu-close-inherited` rule, pipes only.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path


class Stream:
    """A child whose stdout is read line by line until it ends or stop() is called."""

    def __init__(self, argv: Sequence[str]) -> None:
        # S603: argv is a fixed list from the caller, never a shell string.
        self.proc = subprocess.Popen(  # noqa: S603
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
            close_fds=True,
        )

    def lines(self) -> Iterator[str]:
        """Each line until the stream ends or stop() is called; the child is reaped after."""
        out = self.proc.stdout
        try:
            while out is not None:
                try:
                    line = out.readline()
                except (OSError, ValueError):  # closed by stop() from another thread
                    break
                if not line:
                    break
                yield line.rstrip("\n")
        finally:
            self.stop()

    def stop(self) -> None:
        # The child goes first, so a reader blocked on its pipe sees the end, then the pipe.
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.proc.stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                self.proc.stdout.close()


def query(argv: Sequence[str], timeout: float = 3.0) -> str | None:
    """A short command's stdout, or None when it is missing, fails or times out."""
    try:
        # S603: argv is a fixed list from the caller, never a shell string.
        result = subprocess.run(  # noqa: S603
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


_launched: list[subprocess.Popen[bytes]] = []


def detach(
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> int:
    """Start argv in its own session on /dev/null with no inherited descriptors, and return its
    pid at once (`setsid -f` in the zsh tools). Raises OSError when it can't start."""
    # Children are kept until they end (and reaped on the next launch), so a short-lived caller
    # never collects a running child's Popen, which would warn.
    _launched[:] = [p for p in _launched if p.poll() is None]
    # S603: argv is a list the caller built from config or its own arguments.
    proc = subprocess.Popen(  # noqa: S603
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=dict(env) if env is not None else None,
        cwd=cwd,
    )
    _launched.append(proc)
    return proc.pid


def close_inherited(fd_dir: str = "/proc/self/fd") -> list[int]:
    """Close every pipe this process inherited beyond 0-2, and point 0-2 at /dev/null when they
    are pipes (a terminal or a file is kept, for use from a shell). Returns what it changed."""
    changed: list[int] = []
    try:
        names = os.listdir(fd_dir)
    except OSError:
        return changed
    for name in sorted(names, key=lambda n: int(n) if n.isdigit() else -1):
        if not name.isdigit():
            continue
        fd = int(name)
        try:
            target = os.readlink(os.path.join(fd_dir, name))
        except OSError:
            continue
        if not target.startswith("pipe:"):
            continue
        if fd > 2:
            try:
                os.close(fd)
            except OSError:
                continue
        else:
            null = os.open(os.devnull, os.O_RDWR)
            os.dup2(null, fd)
            os.close(null)
        changed.append(fd)
    return changed

"""crew's files: the dock's width and side, the last coordinator shown, each coordinator's
activity, and the locks.

- `$XDG_STATE_HOME/crew/{width,side,last}` survive logouts. The first time crew finds them
  missing it copies coord's (`$XDG_STATE_HOME/coord/`), once, and leaves a mark so it never does
  again (brain record 0019 §7).
- `$XDG_RUNTIME_DIR/crew/state/<name>` holds idle, busy or waiting, written by `crew status`.
- `$XDG_RUNTIME_DIR/crew/<lock>.lock`: `flock` per lock name, as coord's. `dock` serialises the
  width and side files' read-modify-write (a held key's repeats); `switch` serialises showing
  and hiding, so a double-tapped chord finds the window the first press opened.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from collections.abc import Iterator
from pathlib import Path

from desktop_tools.crew import conf, log

COPIED_MARK = ".copied-from-coord"
STATES = ("idle", "busy", "waiting")


class LockError(Exception):
    """A lock that can't be opened or taken: its message says why."""


# ---------------------------------------------------------------- the one-time copy


def copy_from_coord() -> list[str]:
    """Copy coord's width, side and last into crew's folder where crew has none, once.
    Returns what was copied."""
    folder = conf.state_dir()
    mark = folder / COPIED_MARK
    if mark.exists():
        return []
    import shutil

    copied = []
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("width", "side", "last"):
            src, dst = conf.coord_state_dir() / name, folder / name
            if src.is_file() and not dst.exists():
                shutil.copyfile(src, dst)
                copied.append(name)
        mark.write_text("", encoding="utf-8")
    except OSError as e:
        log.warning(f"state: cannot copy coord's settings into {folder}: {e.strerror}")
    return copied


def _read(name: str) -> str:
    copy_from_coord()
    try:
        return (conf.state_dir() / name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _write(name: str, value: str) -> None:
    """Raises OSError."""
    folder = conf.state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{name}.{os.getpid()}.tmp"
    try:
        tmp.write_text(value + "\n", encoding="utf-8")
        os.replace(tmp, folder / name)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def clamp(width: int) -> int:
    return max(conf.WIDTH_MIN, min(conf.WIDTH_MAX, width))


def width() -> int:
    text = _read("width")
    return clamp(int(text)) if text.isascii() and text.isdecimal() else conf.WIDTH_DEFAULT


def set_width(value: int) -> None:
    _write("width", str(value))


def side() -> str:
    text = _read("side")
    return text if text in conf.SIDES else conf.SIDE_DEFAULT


def set_side(value: str) -> None:
    _write("side", value)


def last() -> str:
    return _read("last")


def set_last(name: str) -> None:
    try:
        _write("last", name)
    except OSError as e:
        log.warning(f"state: cannot write the last shown ({name}): {e.strerror}")


# ---------------------------------------------------------------- activity


def activity_path(name: str) -> Path:
    return conf.activity_dir() / name


def activity(name: str) -> str:
    """idle, busy or waiting as recorded; "" when nothing is."""
    try:
        text = activity_path(name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    return text if text in STATES else ""


def set_activity(name: str, state: str) -> bool:
    """Write a state (or remove it, for ""), by rename. False when it couldn't be written."""
    path = activity_path(name)
    if not state:
        clear_activity(name)
        return True
    tmp = path.with_name(f".{name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp.write_text(state + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False
    return True


def clear_activity(name: str) -> None:
    with contextlib.suppress(OSError):
        activity_path(name).unlink()


# ---------------------------------------------------------------- locks


def lock_path(name: str) -> Path:
    return conf.runtime() / f"{name}.lock"


@contextlib.contextmanager
def lock(name: str, timeout: float | None = None, wait: bool = True) -> Iterator[None]:
    """Hold `<runtime>/<name>.lock` for the block. Raises LockError when it can't be opened, or
    is still held by another after `timeout` seconds (at once with wait=False)."""
    timeout = conf.launch_timeout() if timeout is None else timeout
    path = lock_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError:
        raise LockError(f"lock: cannot open {path}") from None
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not wait or time.monotonic() >= deadline:
                    raise LockError(f"{name} lock busy after {timeout:g}s ({path})") from None
                time.sleep(0.02)
        yield
    finally:
        os.close(fd)

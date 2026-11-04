"""Talking to polybar: the only module in the package that does (dotfiles record 0003 §B1).

polybar 3.7 listens on one Unix stream socket per bar, `$XDG_RUNTIME_DIR/polybar/ipc.<pid>.sock`.
A message is a 13-byte header then the payload: the magic `polyipc`, a version byte (0), the
payload's length (uint32, little-endian) and a type byte (1 a command such as `restart`, 2 an
action such as `#audio-level.hook.0`). The bar answers with the same header, type 0 for OK or
255 for an error with its message as the payload; it refuses any other type it is sent,
0 included.

barctl speaks this itself instead of starting a `polybar-msg` per message. When a bar answers
in a format it doesn't recognise (another magic or version), it falls back to `polybar-msg`,
and `doctor` reports the version so the change is seen.

Bars are found and restarted here too (`restart`, from the dotfiles' `_theme-reload-polybar`):
each bar is restarted in place; a bar that won't take the restart, or doesn't answer within a
few seconds after it (frozen), is killed with its scripts and relaunched from its own command
line and environment; a bar that exits by itself can't parse its config and is reported.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import struct
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from desktop_tools.common import paths

MAGIC = b"polyipc"
VERSION = 0
HEADER = struct.Struct("<7sBIB")
# The type byte, as polybar 3.7's include/ipc/msg.hpp defines it: TYPE_OK and TYPE_ERR, then
# v0::ipc_type (the protocol's type_t values). tests/fixtures holds a copy the tests pin these to.
TYPE_CMD = 1  # msg.hpp v0::ipc_type::CMD
TYPE_ACTION = 2  # msg.hpp v0::ipc_type::ACTION
TYPE_OK = 0  # msg.hpp TYPE_OK
TYPE_ERR = 255  # msg.hpp TYPE_ERR
PING = "#barctl-ping.ping"  # an action no module has: every bar answers it, nothing happens
TIMEOUT = 2.0


class Reply:
    """A bar's answer: ok, the protocol version it spoke, and its error message if any."""

    def __init__(self, ok: bool, version: int | None, message: str = "") -> None:
        self.ok, self.version, self.message = ok, version, message

    @property
    def known(self) -> bool:
        return self.version == VERSION

    def __repr__(self) -> str:
        return f"Reply(ok={self.ok}, version={self.version}, message={self.message!r})"


def socket_dir() -> Path:
    return paths.runtime_dir() / "polybar"


def sockets() -> dict[int, Path]:
    """pid -> socket of every running bar that has one. A socket whose bar is gone (killed, so
    it couldn't remove it) is skipped: kill_bar removes it."""
    out: dict[int, Path] = {}
    try:
        entries = list(socket_dir().iterdir())
    except OSError:
        return out
    for entry in entries:
        name = entry.name
        if name.startswith("ipc.") and name.endswith(".sock") and name[4:-5].isdigit():
            pid = int(name[4:-5])
            if (proc_root() / str(pid)).is_dir():
                out[pid] = entry
    return dict(sorted(out.items()))


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("polybar closed the connection")
        data += chunk
    return data


def send(path: Path, kind: int, payload: str, timeout: float = TIMEOUT) -> Reply:
    """Send one message to one bar and read its answer. Raises OSError when the bar doesn't
    answer (no socket, refused, timed out)."""
    body = payload.encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(HEADER.pack(MAGIC, VERSION, len(body), kind) + body)
        head = _recv_exact(sock, HEADER.size)
        magic, version, size, rtype = HEADER.unpack(head)
        if magic != MAGIC:
            return Reply(False, None, "not a polybar IPC answer")
        if version != VERSION:
            return Reply(False, version, f"protocol version {version}")
        message = _recv_exact(sock, size).decode(errors="replace") if size else ""
        return Reply(rtype == TYPE_OK, version, message)


def _fallback(pid: int, kind: int, payload: str) -> bool:
    """The same message through polybar-msg, for a bar whose protocol barctl doesn't know."""
    import shutil  # here, not at the top: push imports this module on its fast path

    exe = shutil.which("polybar-msg")
    if not exe:
        return False
    from desktop_tools.common import procs

    args = [exe, "-p", str(pid), "cmd" if kind == TYPE_CMD else "action", payload]
    return procs.query(args, timeout=TIMEOUT) is not None


def message(kind: int, payload: str, pids: Iterable[int] | None = None) -> dict[int, bool]:
    """Send to every bar (or those pids): pid -> whether it took the message."""
    found = sockets()
    targets = found if pids is None else {p: found[p] for p in pids if p in found}
    out: dict[int, bool] = {}
    for pid, path in targets.items():
        try:
            reply = send(path, kind, payload)
        except OSError:
            out[pid] = False
            continue
        out[pid] = reply.ok if reply.known else _fallback(pid, kind, payload)
    return out


def poke(module: str, hook: int = 0) -> dict[int, bool]:
    """Run a module's hook on every bar: polybar redraws it from `barctl render`."""
    return message(TYPE_ACTION, f"#{module}.hook.{hook}")


def command(cmd: str, pids: Iterable[int] | None = None) -> dict[int, bool]:
    """A bar command (`hide`, `show`, `restart`, ...) to every bar, or those pids."""
    return message(TYPE_CMD, cmd, pids)


def ping(pid: int, timeout: float = TIMEOUT) -> Reply | None:
    """One bar's answer to a harmless action, or None when it doesn't answer."""
    path = sockets().get(pid)
    if path is None:
        return None
    try:
        return send(path, TYPE_ACTION, PING, timeout)
    except OSError:
        return None


# ---------------------------------------------------------------- the bar processes


def proc_root() -> Path:
    return Path(os.environ.get("BARCTL_PROC", "/proc"))


def bar_pids(root: Path | None = None) -> list[int]:
    """This user's polybar processes."""
    root = root or proc_root()
    out = []
    uid = os.getuid()
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            if (entry / "comm").read_text().strip() == "polybar":
                out.append(int(entry.name))
        except OSError:
            continue
    return sorted(out)


def children(pid: int, root: Path | None = None) -> list[int]:
    root = root or proc_root()
    out = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        # pid (comm) state ppid pgrp ...: comm may hold spaces and parentheses.
        fields = stat.rsplit(")", 1)[-1].split()
        if len(fields) >= 3 and fields[1] == str(pid):
            out.append(int(entry.name))
    return sorted(out)


class Launch:
    """How a bar was started: its command line and environment, read from /proc."""

    def __init__(self, argv: list[str], env: dict[str, str]) -> None:
        self.argv, self.env = argv, env

    @classmethod
    def of(cls, pid: int, root: Path | None = None) -> Launch | None:
        root = root or proc_root()
        try:
            argv = (root / str(pid) / "cmdline").read_bytes().split(b"\0")
            envv = (root / str(pid) / "environ").read_bytes().split(b"\0")
        except OSError:
            return None
        args = [a.decode(errors="surrogateescape") for a in argv if a]
        env = {}
        for item in envv:
            key, sep, value = item.decode(errors="surrogateescape").partition("=")
            if sep and key:
                env[key] = value
        return cls(args, env) if args else None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def start(launch: Launch) -> int:
    """Start a bar from a recorded launch, detached, with TOOL_STATS=skip so the polled
    modules' tools don't write run records (record 0003 §B5)."""
    from desktop_tools.common import procs

    env = {**launch.env, "TOOL_STATS": "skip"}
    return procs.detach(launch.argv, env=env, cwd=Path.home())


def kill_bar(pid: int, root: Path | None = None) -> None:
    """Kill a bar and its scripts (each script is its own process group), and remove its socket."""
    kids = children(pid, root)
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)
    for kid in kids:
        try:
            if os.getpgid(kid) == kid:
                os.killpg(kid, signal.SIGKILL)
            os.kill(kid, signal.SIGKILL)
        except OSError:
            continue
    for _ in range(20):
        if not alive(pid):
            break
        time.sleep(0.05)
    # A SIGKILLed bar can't remove its socket: barctl does, so nothing finds a dead bar there.
    with contextlib.suppress(OSError):
        (socket_dir() / f"ipc.{pid}.sock").unlink()


class RestartResult:
    def __init__(self) -> None:
        self.restarted: list[int] = []
        self.relaunched: list[int] = []
        self.started: list[int] = []
        self.dead: list[Launch] = []
        self.notes: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.dead


def restart(
    pids: Iterable[int] | None = None,
    wait: float | None = None,
    root: Path | None = None,
    starter: Callable[[Launch], int] = start,
    sleep: Callable[[float], None] = time.sleep,
) -> RestartResult:
    """Restart every running bar (or those pids) in place; relaunch any that froze or wouldn't
    take the restart."""
    wait = float(os.environ.get("BARCTL_POLYBAR_WAIT", "6")) if wait is None else wait
    result = RestartResult()
    launches: dict[int, Launch] = {}
    waiting: set[int] = set()
    for pid in bar_pids(root) if pids is None else sorted(pids):
        launch = Launch.of(pid, root)
        if launch:
            launches[pid] = launch
        took = command("restart", [pid]).get(pid, False)
        if took:
            waiting.add(pid)
        else:
            result.notes.append(f"polybar {pid} didn't take the restart; relaunching it")
            _relaunch(pid, launch, result, starter, root)
    deadline = time.monotonic() + wait
    while waiting:
        sleep(0.25)
        for pid in sorted(waiting):
            if not alive(pid):
                waiting.discard(pid)
                if pid in launches:
                    result.dead.append(launches[pid])
            elif ping(pid) is not None:
                waiting.discard(pid)
                result.restarted.append(pid)
            elif time.monotonic() >= deadline:
                waiting.discard(pid)
                result.notes.append(f"polybar {pid} froze on restart; killing and relaunching it")
                _relaunch(pid, launches.get(pid), result, starter, root)
    _check_started(result, launches, sleep)
    return result


def _relaunch(
    pid: int,
    launch: Launch | None,
    result: RestartResult,
    starter: Callable[[Launch], int],
    root: Path | None,
) -> None:
    kill_bar(pid, root)
    if launch is None:
        result.notes.append(f"no command line recorded for polybar {pid}")
        return
    try:
        new = starter(launch)
    except OSError as e:
        result.notes.append(f"couldn't relaunch polybar: {e.strerror}")
        result.dead.append(launch)
        return
    result.relaunched.append(new)


def _check_started(
    result: RestartResult, launches: Mapping[int, Launch], sleep: Callable[[float], None]
) -> None:
    """A bar that can't parse its config exits within milliseconds of starting."""
    fresh = result.relaunched + result.started
    if not fresh:
        return
    sleep(0.5)
    by_pid = {**launches}
    for pid in fresh:
        if not alive(pid):
            result.dead.append(by_pid.get(pid, Launch(["polybar"], {})))


def start_bar(
    bar: str,
    env: Mapping[str, str] | None = None,
    starter: Callable[[Launch], int] = start,
    sleep: Callable[[float], None] = time.sleep,
) -> RestartResult:
    """Start one bar when none is running (the dotfiles' `polybar-reload`)."""
    result = RestartResult()
    environ = dict(os.environ if env is None else env)
    from desktop_tools.common import procs

    if not environ.get("HOST_MONITOR"):
        out = procs.query(["bspc", "query", "-M", "--names"])
        if out and out.split():
            environ["HOST_MONITOR"] = out.split()[0]
    import shutil

    exe = shutil.which("polybar", path=environ.get("PATH")) or "polybar"
    launch = Launch([exe, "-q", bar], environ)
    try:
        pid = starter(launch)
    except OSError as e:
        result.notes.append(f"couldn't start polybar: {e.strerror}")
        result.dead.append(launch)
        return result
    result.started.append(pid)
    _check_started(result, {pid: launch}, sleep)
    return result

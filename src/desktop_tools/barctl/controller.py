"""`barctl run`: the controller (dotfiles record 0003 §B5-B6).

One at a time (a lock in the runtime folder). It runs every enabled source in a thread of its
own, restarting a source whose stream ended after BARCTL_RETRY seconds; serves the control socket
for `push`, `alert`, `reload`, `enable`, `disable` and `pin`; blinks alerting modules; redraws a
pushed module when its ttl runs out; and pokes a capsule when its frame changes (the next scroll
step or progress cell, record 0003 §3). On start it clears its own sources' states (they are
redrawn within a second from the live sources) and keeps pushed ones.

It runs from systemd (barctl.service), never from polybar: polybar 3.7 leaks its module pipes
into long-lived children, which can freeze its next restart. It exits 0 on SIGTERM, and non-zero
when a source keeps failing in a way a restart can't fix (a bug, not a stream that ended), for
systemd to restart it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from desktop_tools.barctl import control, render
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.sources import SOURCES, PlayerSource, Source
from desktop_tools.barctl.store import Writer
from desktop_tools.common import journal, polybar

LATE = 0.02  # seconds after a change the tick wakes, so the render lands past it
QUICK = 5.0  # a stream that ends sooner than this after starting counts as a failure
MAX_CRASHES = 3  # unexpected exceptions in a row from one source before the controller exits


class AlreadyRunning(Exception):
    pass


class Controller:
    def __init__(
        self,
        modules: dict[str, mods.Module] | None = None,
        *,
        retry: float | None = None,
        poke: Callable[[str], object] = polybar.poke,
        sources: dict[str, type[Source]] | None = None,
    ) -> None:
        self.modules = modules if modules is not None else mods.load()
        self.retry = float(os.environ.get("BARCTL_RETRY", "2")) if retry is None else retry
        self.poke = poke
        self.source_types = SOURCES if sources is None else sources
        self.stop_event = threading.Event()
        self.failed = threading.Event()
        self.lock = threading.RLock()
        self.writer = Writer(self.modules, self._poke)
        self.running: dict[str, tuple[Source, threading.Thread]] = {}
        self.alerts: dict[str, float] = {}
        self.expiries: dict[str, float] = {}
        self.frames: dict[str, tuple[str, int]] = {}  # capsule -> the frame last drawn
        self._lock_fd: int | None = None
        self._server: socket.socket | None = None
        self.log: Callable[[str], None] = journal.warning

    def _poke(self, module: str) -> object:
        return self.poke(module)

    # ------------------------------------------------------------ lifecycle

    def acquire(self) -> None:
        folder = st.runtime()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(folder / "run.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            running = st.controller()
            raise AlreadyRunning(
                f"already running (pid {running[0]})" if running else "already running"
            ) from None
        self._lock_fd = fd
        st.pid_path().write_text(f"{os.getpid()}\n{time.time()}\n")

    def release(self) -> None:
        with contextlib.suppress(OSError):
            st.pid_path().unlink()
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def wanted(self) -> dict[str, list[str]]:
        """source -> its enabled modules, for the sources barctl has."""
        off = st.disabled()
        out: dict[str, list[str]] = {}
        for source, names in mods.by_source(self.modules).items():
            live = [n for n in names if n not in off]
            if live and source in self.source_types:
                out[source] = live
        return out

    def start_source(self, name: str, modules: list[str]) -> None:
        source = self.source_types[name](modules, self.writer)
        thread = threading.Thread(target=self._supervise, args=(source,), name=f"source-{name}")
        thread.daemon = True
        self.running[name] = (source, thread)
        thread.start()

    def stop_source(self, name: str) -> None:
        entry = self.running.pop(name, None)
        if entry:
            entry[0].stop()
            entry[1].join(3)

    def sync_sources(self) -> None:
        """Start the sources that should run and stop the others (after enable or disable)."""
        with self.lock:
            wanted = self.wanted()
            for name in list(self.running):
                source = self.running[name][0]
                if name not in wanted or wanted[name] != source.modules:
                    self.stop_source(name)
            for name, names in wanted.items():
                if name not in self.running:
                    self.start_source(name, names)

    def _health(self, source: str, **fields: Any) -> None:
        path = st.source_health_path(source)
        with contextlib.suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            data = {**st.source_health(source), **fields, "updated": time.time()}
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, sort_keys=True))
            os.replace(tmp, path)

    def _supervise(self, source: Source) -> None:
        crashes = 0
        restarts = 0
        while not self.stop_event.is_set() and not source.stopping:
            started = time.monotonic()
            self._health(source.name, state="running", since=time.time(), restarts=restarts)
            try:
                source.follow()
                crashes = 0
            except OSError as e:
                # A missing or failing command: retried, and shown by status and doctor.
                self.log(f"source {source.name}: {e.strerror or e}")
            except Exception as e:
                crashes += 1
                journal.exception(e)
                if crashes >= MAX_CRASHES:
                    self._health(source.name, state="failing", error=type(e).__name__)
                    self.failed.set()
                    self.stop_event.set()
                    return
            if self.stop_event.is_set() or source.stopping:
                return
            quick = time.monotonic() - started < QUICK
            restarts += 1
            self._health(source.name, state="failing" if quick else "restarting", restarts=restarts)
            self.log(f"source {source.name} ended; restarting it in {self.retry:g}s")
            with contextlib.suppress(Exception):
                source.gone()
            self.stop_event.wait(self.retry)

    # ------------------------------------------------------------ the control socket

    def serve(self) -> None:
        path = control.path()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(8)
        server.settimeout(0.2)
        self._server = server
        thread = threading.Thread(target=self._accept, name="control", daemon=True)
        thread.start()

    def _accept(self) -> None:
        assert self._server is not None  # noqa: S101 - serve() set it before starting us
        while not self.stop_event.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(1.0)
                try:
                    data = b""
                    while not data.endswith(b"\n") and len(data) < 65536:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    answer = self.handle(json.loads(data or b"{}"))
                except (OSError, ValueError) as e:
                    answer = {"ok": False, "error": str(e)}
                with contextlib.suppress(OSError):
                    conn.sendall((json.dumps(answer) + "\n").encode())

    def handle(self, request: object) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {"ok": False, "error": "a request is a JSON object"}
        op = request.get("op")
        module = request.get("module")
        if op == "ping":
            return {
                "ok": True,
                "pid": os.getpid(),
                "sources": sorted(self.running),
                "pinned": self.pins(),
            }
        if op == "pin":
            return self.pin(module, request.get("instance"))
        if op in ("pushed", "alert") and isinstance(module, str) and module in self.modules:
            self.follow_state(module)
            self.poke(module)
            return {"ok": True}
        if op == "reload":
            try:
                fresh = mods.load()
            except mods.ConfigError as e:
                return {"ok": False, "error": str(e)}
            with self.lock:
                self.modules.clear()
                self.modules.update(fresh)
            self.sync_sources()
            return {"ok": True}
        if op == "settings":
            self.sync_sources()
            if isinstance(module, str) and module in self.modules:
                self.poke(module)
            return {"ok": True}
        return {"ok": False, "error": f"unknown request {op!r}"}

    def _player(self) -> PlayerSource | None:
        entry = self.running.get("player")
        source = entry[0] if entry else None
        return source if isinstance(source, PlayerSource) else None

    def pins(self) -> dict[str, str | None]:
        """source -> its pinned instance (or None), for `status --json`."""
        source = self._player()
        return {"player": source.pinned} if source is not None else {}

    def pin(self, module: object, instance: object) -> dict[str, Any]:
        """Show one player on a player module's source until it goes (None: back to the rank).
        Held here, in memory: a restart forgets it (record 0003 §5, open question 8)."""
        found = self.modules.get(module) if isinstance(module, str) else None
        if found is None:
            return {"ok": False, "error": f"unknown module {module!r}"}
        if found.source != "player":
            return {"ok": False, "error": f"{found.name} is not drawn by the player source"}
        if instance is not None and (not isinstance(instance, str) or not instance):
            return {"ok": False, "error": "instance is a player's name"}
        source = self._player()
        if source is None:
            return {"ok": False, "error": "the player source is not running"}
        try:
            pinned = source.pin(instance)
        except LookupError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "pinned": pinned}

    def follow_state(self, module: str) -> None:
        """Note a module's alert and expiry, to redraw it when they change."""
        data = st.read(module) or {}
        until = max(
            [float(data.get("alert_until") or 0)]
            + [float(s.get("alert_until") or 0) for s in data.get("segments") or []]
        )
        now = time.time()
        with self.lock:
            if until > now:
                self.alerts[module] = until
            else:
                self.alerts.pop(module, None)
            expires = float(data.get("expires") or 0)
            if expires > now:
                self.expiries[module] = expires
            else:
                self.expiries.pop(module, None)

    # ------------------------------------------------------------ timers

    def tick(self, now: float | None = None) -> float:
        """Poke what blinks or expired; returns how long to sleep until the next change."""
        now = time.time() if now is None else now
        due: list[str] = []
        with self.lock:
            for module, until in list(self.alerts.items()):
                due.append(module)
                if until <= now:
                    del self.alerts[module]
            for module, expires in list(self.expiries.items()):
                if expires <= now:
                    due.append(module)
                    del self.expiries[module]
            blinking = bool(self.alerts)
            nearest = min(self.expiries.values(), default=now + 1.0)
        moving, frames = self.capsules(now)
        due.extend(frames)
        for module in sorted(set(due)):
            self.poke(module)
        if moving is not None:
            nearest = min(nearest, moving + LATE)
        # Wake at the next half of a blink, a little after it, so a render lands in it.
        if blinking:
            nearest = min(nearest, now + st.BLINK - (now % st.BLINK) + LATE)
        return max(0.05, min(1.0, nearest - now))

    def capsules(self, now: float) -> tuple[float | None, list[str]]:
        """The capsules whose frame changed since it was last drawn (to poke), and when the
        next one changes. A source's own write pokes what it changed; this covers the scroll
        and the progress line, which move with the time alone."""
        changed: list[str] = []
        soonest: float | None = None
        with self.lock:
            capsules = [m for m in self.modules.values() if m.display == "capsule"]
        off = st.disabled() if capsules else set()
        for module in capsules:
            if module.name in off:
                self.frames.pop(module.name, None)
                continue
            data = st.read(module.name)
            frame = render.capsule_frame(module, data, now)
            if self.frames.get(module.name, frame) != frame:
                changed.append(module.name)
            self.frames[module.name] = frame
            wake = render.next_change(module, data, now)
            if wake is not None:
                soonest = wake if soonest is None else min(soonest, wake)
        return soonest, changed

    # ------------------------------------------------------------ run

    def run(self) -> int:
        self.acquire()
        handlers = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                handlers[sig] = signal.signal(sig, lambda *_: self.stop_event.set())
        try:
            for names in mods.by_source(self.modules).values():
                for name in names:
                    st.clear(name)
            for module in st.stored():
                if module in self.modules:
                    self.follow_state(module)
            self.serve()
            self.sync_sources()
            while not self.stop_event.is_set():
                self.stop_event.wait(self.tick())
        finally:
            self.shutdown()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
        return 1 if self.failed.is_set() else 0

    def shutdown(self) -> None:
        self.stop_event.set()
        for name in list(self.running):
            self.stop_source(name)
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(OSError):
                control.path().unlink()
        self.release()


def lock_path() -> Path:
    return st.runtime() / "run.lock"

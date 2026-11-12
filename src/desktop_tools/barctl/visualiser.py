"""The visualiser strip (design record 0005 phase D): a cava spectrum in the capsule's cells.

While the capsule's player plays and the capsule is at rest, the controller runs cava as its
child, with its own config (`$XDG_RUNTIME_DIR/barctl/cava.conf`: PipeWire, the default sink's
monitor, `visualiser_fps` frames a second, one bar per text cell, raw ASCII levels 0-7), reads
its frames and sends each one to every bar over polybar's `send` action, one message to each
bar's own socket, with no process per frame (`barctl render` per frame would cost about 40 ms of
CPU each). Only the newest line cava printed is drawn; older ones are dropped, and a frame the
same as the last one sent is not sent again (but once every 2 s, for a bar that restarted). The
title shows instead for `visualiser_title` seconds after the track changes or a seek.

cava runs only while the strip should show: paused, expanded, faded, no player, the module
disabled or the strip off, it is stopped by its PID and nothing polls. A controller that dies
takes cava with it: cava's next write to the closed pipe ends it.

Off by default (`visualiser = false`), and three ways to turn it off without editing a file:
`barctl visualiser off` (kept in barctl's settings; it wins over the key), the CPU budget guard
(every 10 s it adds up cava's CPU and the controller's own; over `visualiser_budget` percent of
one core three samples in a row, the strip turns itself off), and cava missing or exiting three
times in five minutes. Each writes one journal line and `barctl doctor` says why.

Privacy: cava reads everything that plays, calls included; it turns it into levels in memory.
Nothing here records, stores or logs audio or levels.
"""

from __future__ import annotations

import contextlib
import os
import select
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from desktop_tools.barctl import render
from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import Module
from desktop_tools.common import polybar, theme

SAMPLE = 10.0  # seconds between budget samples
OVER = 3  # samples in a row over the budget before the strip turns itself off
EXITS = 3  # cava exiting by itself this many times ...
EXIT_WINDOW = 300.0  # ... within this many seconds turns the strip off
SEEK = 2.0  # seconds a position may differ from where it should be before it counts as a seek
SOCKETS_EVERY = 2.0  # seconds between looks for bars that started or went
SEND_TIMEOUT = 0.2  # a bar that doesn't take a frame this fast loses it: the next replaces it
STOP_WAIT = 2.0  # seconds cava has to end on SIGTERM before SIGKILL


def conf_path() -> Path:
    return st.runtime() / "cava.conf"


def cava_conf(module: Module) -> str:
    """cava's config for a capsule (record 0005 phase D): the default sink's monitor through
    PipeWire, one bar per text cell, raw ASCII levels 0-7, one line a frame."""
    return (
        "# Written by barctl for the visualiser strip (design record 0005 phase D).\n"
        "[general]\n"
        f"framerate = {module.visualiser_fps}\n"
        f"bars = {module.width}\n"
        "sleep_timer = 0\n\n"
        "[input]\n"
        "method = pipewire\n"
        "source = auto\n\n"
        "[output]\n"
        "method = raw\n"
        "raw_target = /dev/stdout\n"
        "data_format = ascii\n"
        "ascii_max_range = 7\n"
        "channels = mono\n"
        "bar_delimiter = 59\n"
        "frame_delimiter = 10\n"
    )


def levels(line: bytes) -> list[int] | None:
    """One cava frame, `3;0;7;...;`, as levels 0-7; None for a line that isn't one."""
    text = line.strip().strip(b";")
    if not text:
        return None
    out = []
    for part in text.split(b";"):
        if not part.isdigit():
            return None
        out.append(min(7, int(part)))
    return out


def proc_cpu(pid: int) -> float | None:
    """A process's CPU seconds (user and system) from /proc/<pid>/stat, or None."""
    try:
        stat = (polybar.proc_root() / str(pid) / "stat").read_text()
    except OSError:
        return None
    fields = stat.rsplit(")", 1)[-1].split()
    try:
        # After the comm: state is fields[0], so utime and stime (fields 14 and 15) are 11, 12.
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (IndexError, ValueError):
        return None


class Strip:
    """One capsule's strip: cava as a child and a thread drawing its frames."""

    def __init__(
        self,
        module: Module,
        command: str,
        colours: dict[str, str],
        sockets: Callable[[], dict[int, Path]],
        clock: Callable[[], float],
    ) -> None:
        self.module, self.command, self.colours = module, command, colours
        self.sockets_of, self.clock = sockets, clock
        self.stopping = False
        self.ended = False  # cava ended by itself
        self.proc: subprocess.Popen[bytes] | None = None
        self.thread: threading.Thread | None = None
        self.state: st.State | None = None
        self.stamp: int | None = None  # the state file's mtime, to re-read it when it changes
        self.seek_at = 0.0
        self.last = ""
        self.sockets: dict[int, Path] = {}
        self.sockets_at = -SOCKETS_EVERY
        self.sent = 0

    def write_conf(self) -> Path:
        path = conf_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(cava_conf(self.module), encoding="utf-8")
        return path

    def start(self, path: Path) -> None:
        """Start cava (raises OSError when it can't) and the thread that draws its frames."""
        # S603: barctl's own fixed argument list. SIGPIPE is cava's default again (Popen's
        # restore_signals), so it ends when the controller does and the pipe closes.
        self.proc = subprocess.Popen(  # noqa: S603
            [self.command, "-p", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.thread = threading.Thread(target=self._follow, name="visualiser", daemon=True)
        self.thread.start()

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else None

    def stop(self) -> None:
        """Stop cava by its PID and wait for the thread (its read ends with cava's pipe)."""
        self.stopping = True
        proc = self.proc
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(proc.pid, signal.SIGTERM)
            try:
                proc.wait(STOP_WAIT)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(proc.pid, signal.SIGKILL)
                proc.wait()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(STOP_WAIT)
        if proc is not None and proc.stdout is not None:
            proc.stdout.close()

    # ------------------------------------------------------------ frames

    def _follow(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stdout is not None  # noqa: S101 - start() set them
        fd = proc.stdout.fileno()
        buf = b""
        while not self.stopping:
            try:
                chunk = os.read(fd, 4096)  # blocks until cava prints: no polling
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            # A reader that fell behind skips ahead: take whatever else is waiting too.
            while select.select([fd], [], [], 0)[0]:
                try:
                    more = os.read(fd, 65536)
                except OSError:
                    more = b""
                if not more:
                    break
                buf += more
            if b"\n" not in buf:
                continue
            *lines, buf = buf.split(b"\n")
            found = levels(lines[-1])  # only the newest whole frame is drawn
            if found is not None and not self.stopping:
                self.draw(found, self.clock())
        if not self.stopping:
            self.ended = True
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                proc.wait(STOP_WAIT)

    def refresh(self, now: float) -> None:
        """Re-read the capsule's state when its file changed, noting a seek."""
        try:
            stamp = st.state_path(self.module.name).stat().st_mtime_ns
        except OSError:
            stamp = None
        if stamp == self.stamp and self.state is not None:
            return
        self.stamp = stamp
        new = st.read(self.module.name)
        if seeked(self.state, new):
            self.seek_at = now
        self.state = new

    def title_on(self, now: float) -> bool:
        """Whether the title shows over the strip: `visualiser_title` seconds after the
        label changed (a new track) or a seek."""
        span = self.module.visualiser_title
        if span <= 0:
            return False
        since = float((self.state or {}).get("label_since") or 0)
        return now < since + span or now < self.seek_at + span

    def frame(self, found: list[int], now: float) -> str:
        if self.title_on(now):
            return render.render(
                self.module, self.state, now=now, colours=self.colours, controller=True
            )
        return render.strip(self.module, self.state, now, self.colours, found)

    def draw(self, found: list[int], now: float) -> None:
        self.refresh(now)
        line = self.frame(found, now)
        fresh = False
        if now - self.sockets_at >= SOCKETS_EVERY or now < self.sockets_at:
            # Bars that started or went; and the frame is sent again even when it is the same,
            # so a bar restarted in place (same pid, its hook drew the capsule) gets it too.
            self.sockets, self.sockets_at = self.sockets_of(), now
            fresh = True
        if line == self.last and not fresh:
            return
        self.last = line
        payload = f"#{self.module.name}.send.{line}"
        for path in self.sockets.values():
            # One message to each bar's own socket; a lost frame is replaced by the next.
            with contextlib.suppress(OSError):
                polybar.send(path, polybar.TYPE_ACTION, payload, SEND_TIMEOUT)
        self.sent += 1


def seeked(old: st.State | None, new: st.State | None) -> bool:
    """Whether the position moved more than SEEK seconds from where it should be (a seek),
    on the same track."""
    if not old or not new or old.get("label") != new.get("label"):
        return False
    a, b = old.get("progress"), new.get("progress")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    try:
        expected = float(a.get("position") or 0)
        if a.get("playing"):
            elapsed = float(b.get("at") or 0) - float(a.get("at") or 0)
            expected += max(0.0, elapsed) * float(a.get("rate") or 0)
        return abs(float(b.get("position") or 0) - expected) > SEEK
    except (TypeError, ValueError):
        return False


class Visualiser:
    """The controller's part: which capsule shows the strip, cava's lifecycle and the guards.

    One strip at a time: the first capsule (by name) with `visualiser = true` that may show
    it. `sync` is called on the controller's tick, on a write that pokes a capsule and on the
    control requests that change what shows; `guard` on the tick."""

    def __init__(
        self,
        modules: dict[str, Module],
        *,
        poke: Callable[[str], object],
        log: Callable[[str], None],
        cpu: Callable[[], float] | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sockets: Callable[[], dict[int, Path]] = polybar.sockets,
        modules_lock: threading.RLock | None = None,
    ) -> None:
        self.modules, self.poke, self.log = modules, poke, log
        # The controller's lock: a reload clears and refills `modules` under it.
        self.modules_lock = modules_lock or threading.RLock()
        self.failure = ""  # the last error writing cava's config, said once
        self.held = False  # turned off by a guard in this run, even if settings can't be written
        self.cpu = cpu or self._cpu
        self.clock, self.monotonic, self.sockets = clock, monotonic, sockets
        self.lock = threading.RLock()
        self.strip: Strip | None = None
        self.exits: list[float] = []
        self.over = 0
        self.sample: tuple[float, float] | None = None
        self.cava_cpu: dict[int, float] = {}  # cava pid -> its CPU when last read

    # ------------------------------------------------------------ what shows

    def candidates(self) -> list[Module]:
        with self.modules_lock:
            found = list(self.modules.values())
        return [m for m in found if m.display == "capsule" and m.visualiser]

    def wanted(self, now: float) -> Module | None:
        """The capsule that should show the strip now, or None."""
        found = self.candidates()
        if not found or self.held or st.visualiser_off():
            return None
        off = st.disabled()
        for module in found:
            if module.name not in off and render.strip_shows(module, st.read(module.name), now):
                return module
        return None

    def drawing(self, module: str) -> bool:
        with self.lock:
            return self.strip is not None and self.strip.module.name == module

    def handles(self, module: str) -> bool:
        """For the controller's poke: True when the strip draws `module`, so the change goes
        out with its next frame (or the strip just stopped and drew the capsule itself)."""
        if not any(m.name == module for m in self.candidates()):
            return False
        before = self.drawing(module)
        self.sync()
        return before or self.drawing(module)

    def sync(self, now: float | None = None) -> None:
        """Start the strip where it should show, stop it where it should not."""
        if not self.candidates() and self.strip is None:
            return
        now = self.clock() if now is None else now
        with self.lock:
            strip = self.strip
            if strip is not None and strip.ended:
                self._stop(redraw=True)
                if self._exited():
                    return
            want = self.wanted(now)
            strip = self.strip
            if strip is not None and (want is None or want is not strip.module):
                self._stop(redraw=True)
            if want is not None and self.strip is None:
                self._start(want)

    def _exited(self) -> bool:
        """cava ended by itself: note it; the third time in five minutes turns the strip off."""
        t = self.monotonic()
        self.exits = [e for e in self.exits if t - e < EXIT_WINDOW] + [t]
        if len(self.exits) >= EXITS:
            self.turn_off("cava-exits")
            return True
        return False

    def _start(self, module: Module) -> None:
        command = shutil.which("cava")
        if command is None:
            self.turn_off("cava-missing")
            return
        colours = theme.roles({**st.ROLES, "underline": render.UNDERLINE_ROLE})
        strip = Strip(module, command, colours, self.sockets, self.clock)
        try:
            conf = strip.write_conf()
        except OSError as e:
            # The runtime folder, not cava: say it once, try again on a later tick.
            error = f"visualiser: can't write {conf_path()}: {e.strerror or e}"
            if error != self.failure:
                self.failure = error
                self.log(error)
            return
        self.failure = ""
        try:
            strip.start(conf)
        except OSError:
            strip.stop()
            self.turn_off("cava-missing")
            return
        self.strip = strip
        self.sample = None
        self.over = 0

    def _stop(self, redraw: bool) -> None:
        strip, self.strip = self.strip, None
        if strip is None:
            return
        pid = strip.pid
        strip.stop()
        if pid is not None:
            self.cava_cpu.pop(pid, None)
        self.sample = None
        if redraw:
            # One ordinary poke: the hook render draws the capsule over the last frame.
            self.poke(strip.module.name)

    def stop(self) -> None:
        """Stop the strip (the controller's reload and shutdown)."""
        with self.lock:
            self._stop(redraw=True)

    def turn_off(self, reason: str) -> None:
        """Off as `barctl visualiser off` would, with why: one journal line, nothing else."""
        with self.lock:
            changed = not self.held
            self.held = True
            try:
                changed = st.set_visualiser(False, reason, self.clock()) or changed
            except OSError as e:
                # Still off for this run (held); only keeping it across restarts failed.
                self.log(f"visualiser: can't write the settings: {e.strerror or e}")
            self._stop(redraw=True)
        if changed:
            self.log(f"visualiser off: {st.VISUALISER_REASONS.get(reason, reason)}")

    def reset(self) -> None:
        """The switch changed (`barctl visualiser on|off`): start the guards' counts again."""
        with self.lock:
            self.held = False
            self.exits.clear()
            self.over = 0
            self.sample = None
        self.sync()

    # ------------------------------------------------------------ the budget guard

    def _cpu(self) -> float:
        """The controller's CPU seconds and every cava's it started (each cava's as last
        read, so the sum never goes back when one ends)."""
        times = os.times()
        pid = self.strip.pid if self.strip is not None else None
        if pid is not None:
            found = proc_cpu(pid)
            if found is not None:
                self.cava_cpu[pid] = found
        return times.user + times.system + sum(self.cava_cpu.values())

    def guard(self) -> None:
        """Every SAMPLE seconds while the strip runs: the CPU it and cava used, as a percent
        of one core; over the budget OVER samples in a row, the strip turns itself off."""
        with self.lock:
            strip = self.strip
            if strip is None:
                self.sample, self.over = None, 0
                return
            t = self.monotonic()
            if self.sample is None:
                self.sample = (t, self.cpu())
                return
            started, used = self.sample
            if t - started < SAMPLE:
                return
            now_used = self.cpu()
            percent = max(0.0, now_used - used) / (t - started) * 100
            self.sample = (t, now_used)
            self.over = self.over + 1 if percent > strip.module.visualiser_budget else 0
            over = self.over >= OVER
        if over:
            self.turn_off("budget")

    # ------------------------------------------------------------ status

    def status(self) -> dict[str, Any]:
        with self.lock:
            strip = self.strip
            return {
                "drawing": strip.module.name if strip is not None else None,
                "cava_pid": strip.pid if strip is not None else None,
                "frames": strip.sent if strip is not None else 0,
            }

"""What crew's verbs do: show, hide, toggle, cycle, the dock's width and side, the list, and the
desktop half of a stop. Each returns an exit code: 0 done, 1 failed (logged with its reason), 2 a
usage error, as coord's.

**Showing never starts a coordinator, except on purpose** (the brain coordinator's decision,
2026-11-04). A coordinator is running when its window or its tmux session exists. Showing one
with a session but no window opens a window that attaches to the session. Showing one that is
stopped flashes "<name> is stopped" and returns 1: `show`, `toggle`, `hide --toggle` and the
waiting notification's click. `cycle` skips stopped ones. Only `toggle --launch` (the bar
glyph's left click, and later the menu's start row) starts one, through `launch()`, the one call
to `meta <name> launch`.

Each coordinator window is alacritty with class `crew` and the coordinator's name as instance,
running `tmux attach-session -t =<session>`; bspwmrc's rule makes it floating, sticky and hidden
at birth. Showing one docks it (`wm.place`) and hides any other; `hide` hides whichever is shown
and gives its strip back. Every show starts the guard (`crew guard`), which keeps it docked.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time

from desktop_tools.crew import conf, log, metacall, store, strip, tmux, wm
from desktop_tools.crew.out import say
from desktop_tools.crew.registry import Coordinator, Registry, valid_name

OK, FAILED, USAGE = 0, 1, 2


def crew_argv(*args: str) -> list[str]:
    """crew itself, as a child: the same interpreter, so it needs nothing on PATH."""
    return [sys.executable, "-m", "desktop_tools.crew", *args]


def detach(argv: list[str]) -> bool:
    from desktop_tools.common import procs

    try:
        procs.detach(argv)
    except OSError as e:
        log.error(f"cannot start {argv[0]}: {e.strerror}")
        return False
    return True


def notify(title: str, body: str, *options: str) -> None:
    """A notification, detached, when notify-send is there (dunstrc sets markup = full)."""
    if shutil.which("notify-send") is None:
        return
    body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    detach(["notify-send", f"--app-name={conf.window_class()}", *options, title, body])


def alert(title: str, body: str) -> None:
    """Why something didn't happen: the log, and a notification, since crew runs from keys and
    the bar with no terminal to read."""
    log.error(f"{title}: {body}")
    notify(title, body, "--hint=string:x-dunst-stack-tag:crew-alert")


def refresh(reg: Registry) -> None:
    strip.push(reg)


def flash(reg: Registry, name: str | None) -> int:
    """Say a coordinator is stopped (or that none is running), refresh the strip, return 1. The
    stack tag makes repeated presses replace the notification instead of piling up."""
    title = f"{name} is stopped" if name else "no coordinator running"
    body = "start it from the menu or click its icon" if name else "start one from the menu"
    log.info(title)
    notify(title, body, "-t", "1500", "--hint=string:x-dunst-stack-tag:crew-stopped")
    refresh(reg)
    return FAILED


def guard_start() -> None:
    """Start the guard unless it is running: its own lock makes a second one exit at once."""
    detach(crew_argv("guard"))


# ---------------------------------------------------------------- finding windows


def find(tree: wm.Tree, reg: Registry, name: str) -> wm.Window | None:
    return next((w for w in tree.crew() if reg.resolve(w.instance) == name), None)


def session_of(c: Coordinator, sessions: set[str]) -> str | None:
    return next((s for s in c.sessions if s in sessions), None)


def wait_window(reg: Registry, name: str, timeout: float | None = None) -> wm.Window | None:
    """Poll bspwm, not X: a window exists in X a moment before bspwm manages it."""
    timeout = conf.launch_timeout() if timeout is None else timeout
    deadline = time.monotonic() + timeout
    while True:
        win = find(wm.look(), reg, name)
        if win is not None:
            return win
        if time.monotonic() >= deadline:
            log.error(f"{name}: no window after {timeout:g}s")
            return None
        time.sleep(0.1)


def open_window(c: Coordinator, session: str) -> bool:
    """A terminal attached to the coordinator's running session. It never creates a session."""
    cls = conf.window_class()
    argv = [
        "alacritty",
        "--class",
        f"{cls},{c.name}",
        "--title",
        f"{cls} - {c.name}",
        "-e",
        *tmux.attach_argv(session),
    ]
    if shutil.which("alacritty") is None:
        log.error(f"{c.name}: cannot open a window: alacritty is not on PATH")
        return False
    return detach(argv)


def launch(reg: Registry, c: Coordinator) -> wm.Window | None:
    """The one way a show starts a coordinator (brain record 0019 §3a): `meta <name> launch`
    starts its tmux session, then crew opens its window and waits for it. A coordinator that is
    already running (exit 3) gets its window. Every failure is logged and notified."""
    done = metacall.run(c.name, "launch")
    if not done.ran:
        alert(f"{c.name}: not started", done.why)
        return None
    session = session_of(c, tmux.sessions())
    if not done.ok and not (done.code == 3 and session):
        alert(
            f"{c.name}: not started",
            f"meta {c.name} launch {metacall.exited(done.code)}: {done.why}",
        )
        return None
    if session is None:
        alert(f"{c.name}: not started", f"no tmux session {c.session} after meta launch")
        return None
    if not open_window(c, session):
        return None
    return wait_window(reg, c.name)


# ---------------------------------------------------------------- showing and hiding


def _known(reg: Registry, name: str) -> Coordinator | None:
    if not valid_name(name):
        log.error(f"invalid coordinator name: {name!r}")
        return None
    c = reg.get(name)
    if c is None:
        log.error(f"no coordinator {name!r} (crew names lists them)")
    return c


def show(reg: Registry, name: str, *, launching: bool = False, tree: wm.Tree | None = None) -> int:
    """Show `name` docked, hiding any other, and record it as the last shown. Already shown, it
    is re-docked and focused, never hidden. The caller holds the switch lock."""
    c = _known(reg, name)
    if c is None:
        return FAILED
    win = find(wm.look() if tree is None else tree, reg, c.name)
    if win is None:
        session = session_of(c, tmux.sessions())
        if session is not None:
            if not open_window(c, session):
                return FAILED
            win = wait_window(reg, c.name)
        elif launching:
            win = launch(reg, c)
        else:
            return flash(reg, c.name)
        if win is None:
            return FAILED
    # Padding is set before the swap and released only after it, so swapping coordinators
    # never lets tiled windows reflow into the strip.
    if not wm.place(win, store.width(), store.side()):
        return FAILED
    for other in wm.look().crew(shown_only=True):
        if other.id != win.id:
            wm.hide(other)
    if not wm.run("node", win.node, "--flag", "hidden=off", "--focus"):
        log.error(f"{c.name}: cannot show {win.node}")
        return FAILED
    wm.unpad()
    store.set_last(c.name)
    guard_start()
    refresh(reg)
    return OK


def summon(reg: Registry, name: str) -> int:
    """`crew show <name>`: show it, never hide it, never start it."""
    try:
        with store.lock("switch"):
            return show(reg, name)
    except store.LockError as e:
        log.error(str(e))
        return FAILED


def toggle(reg: Registry, name: str, *, launching: bool = False) -> int:
    """Hide `name` if it is shown and focused, else show it (starting it only with launching)."""
    if _known(reg, name) is None:
        return FAILED
    try:
        with store.lock("switch"):
            tree = wm.look()
            win = find(tree, reg, reg.resolve(name))
            if win is not None and not win.hidden and tree.focused(win):
                wm.hide(win)
                wm.unpad()
                refresh(reg)
                return OK
            return show(reg, reg.resolve(name), launching=launching, tree=tree)
    except store.LockError as e:
        log.error(str(e))
        return FAILED


def last_shown(reg: Registry) -> str | None:
    name = reg.resolve(store.last())
    return name if name in reg.names else None


def hide(reg: Registry, *, toggling: bool = False) -> int:
    """Hide the shown coordinator, focused or not, and give its strip back. With toggling and
    none shown, show the last one shown (or the first), if it is running."""
    try:
        with store.lock("switch"):
            hidden = failed = False
            for win in wm.look().crew(shown_only=True):
                if wm.hide(win):
                    hidden = True
                else:
                    log.error(f"hide: cannot hide {win.instance} ({win.node})")
                    failed = True
            if failed:
                if hidden:
                    wm.unpad()
                    refresh(reg)
                return FAILED
            if hidden:
                wm.unpad()
                refresh(reg)
                return OK
            if not toggling:
                return OK
            name = last_shown(reg) or (reg.names[0] if reg.names else None)
            if name is None:
                return flash(reg, None)
            return show(reg, name)
    except store.LockError as e:
        log.error(str(e))
        return FAILED


def cycle(reg: Registry, direction: str) -> int:
    """Show the next (or previous) running coordinator in menu order, wrapping, skipping the
    stopped ones. With none shown, start from the last shown (or the first): after hiding one,
    the first press brings back what was just there. None running: flash and return 1."""
    if direction not in ("next", "prev"):
        log.error(f"cycle: expected next or prev, got {direction!r}")
        return USAGE
    step = 1 if direction == "next" else -1
    try:
        with store.lock("switch"):
            tree = wm.look()
            found = strip.scan(reg, tree)
            names = [c.name for c in strip.visible(reg, found)]
            if not any(n in found.running for n in names):
                return flash(reg, None)
            current = next(
                (
                    reg.resolve(w.instance)
                    for w in tree.crew(shown_only=True)
                    if reg.resolve(w.instance) in names
                ),
                None,
            )
            if current is not None:
                start = names.index(current) + step
            else:
                last = last_shown(reg)
                start = names.index(last) if last in names else 0
            for k in range(len(names)):
                name = names[(start + step * k) % len(names)]
                if name in found.running:
                    return show(reg, name, tree=tree)
            return flash(reg, None)  # pragma: no cover - the any() above found one
    except store.LockError as e:
        log.error(str(e))
        return FAILED


# ---------------------------------------------------------------- the dock


def width(arg: str | None = None, step: str | None = None) -> int:
    """Print the dock's visible width, or set it: N, +N, -N (clamped to 640-2560), or move the
    panel's inner edge `left`/`right` by N (default 128), whose sign depends on the side."""
    if arg is None:
        value = store.width()
        if not say(str(value)):
            log.error(f"width: could not print the width ({value}) to stdout")
            return FAILED
        return OK
    if arg in conf.SIDES:
        step = str(conf.WIDTH_STEP) if step is None else step
        if not step.isdecimal():
            log.error(f"width: expected a step N after {arg!r}, got {step!r}")
            return FAILED
    elif not (arg.lstrip("+-").isdecimal() and arg.count("+") + arg.count("-") <= 1) or step:
        log.error(f"width: expected +N, -N, N, left [N] or right [N], got {arg!r}")
        return FAILED
    try:
        with store.lock("dock"):
            current, side = store.width(), store.side()
            if arg in conf.SIDES:
                moved = int(step or conf.WIDTH_STEP)
                value = current - moved if arg == side else current + moved
            elif arg[0] in "+-":
                value = current + int(arg)
            else:
                value = int(arg)
            value = store.clamp(value)
            try:
                store.set_width(value)
            except OSError as e:
                path = conf.state_dir() / "width"
                log.error(f"width: cannot write {value} to {path}: {e.strerror}")
                return FAILED
            if not wm.redock(value, side):
                log.error(f"width: set to {value}, but a shown coordinator was not re-docked")
                return FAILED
    except store.LockError as e:
        log.error(str(e))
        log.error("width: cannot take the dock lock")
        return FAILED
    # The new width is printed for a terminal; sxhkd's stdout can be a pty that has gone away
    # (EIO), and the width is set by then, so a failed print is not a failed command.
    if not say(str(value)):
        log.debug(f"width: stdout not writable, {value} not printed")
    return OK


def side(arg: str | None = None) -> int:
    """Print the dock side, or set it to left or right, re-docking a shown coordinator."""
    if arg is None:
        value = store.side()
        if not say(value):
            log.error(f"side: could not print the side ({value}) to stdout")
            return FAILED
        return OK
    if arg not in conf.SIDES:
        log.error(f"side: expected left or right, got {arg!r}")
        return FAILED
    try:
        with store.lock("dock"):
            try:
                store.set_side(arg)
            except OSError as e:
                log.error(f"side: cannot write {arg} to {conf.state_dir() / 'side'}: {e.strerror}")
                return FAILED
            if not wm.redock(store.width(), arg):
                log.error(f"side: set to {arg}, but a shown coordinator was not re-docked")
                return FAILED
    except store.LockError as e:
        log.error(str(e))
        log.error("side: cannot take the dock lock")
        return FAILED
    if not say(arg):
        log.debug(f"side: stdout not writable, {arg} not printed")
    return OK


# ---------------------------------------------------------------- listing and stopping


def windows() -> list[str]:
    """One line per crew window: its instance, hidden or visible, and its node."""
    return [
        f"{w.instance:<14} {'hidden' if w.hidden else 'visible':<8} {w.node}"
        for w in wm.look().crew()
    ]


def wait_gone(reg: Registry, names: list[str], timeout: float | None = None) -> str | None:
    """Wait for the windows of these coordinators to close; the name of one still open."""
    timeout = conf.launch_timeout() if timeout is None else timeout
    deadline = time.monotonic() + timeout
    while True:
        still = next(
            (reg.resolve(w.instance) for w in wm.look().crew() if reg.resolve(w.instance) in names),
            None,
        )
        if still is None or time.monotonic() >= deadline:
            return still
        time.sleep(0.1)


def stopped(reg: Registry, names: list[str]) -> int:
    """The desktop half of a stop, run by the brain's stop script once it has ended the
    sessions: drop their activity, wait for their windows to close, give back any strip a shown
    one held and refresh the strip. Needs no DISPLAY. 1 if a window is still open."""
    if not names:
        log.error("stopped: expected a name")
        return USAGE
    targets = []
    for name in names:
        if not valid_name(name):
            log.error(f"stopped: invalid coordinator name: {name!r}")
            return USAGE
        # Its activity may be under either name.
        store.clear_activity(name)
        resolved = reg.resolve(name)
        store.clear_activity(resolved)
        targets.append(resolved)
    still = wait_gone(reg, targets)
    try:
        with store.lock("switch"):
            wm.unpad()
    except store.LockError as e:
        log.warning(str(e))
    refresh(reg)
    if still is not None:
        log.error(
            f"{still}: window still open {conf.launch_timeout():g}s after its session was stopped"
        )
        return FAILED
    return OK


def notify_waiting(reg: Registry, name: str, body: str) -> int:
    """Run detached by `crew status` when a coordinator starts waiting: a notification, unless
    its window is the shown and focused one, whose click shows it (never starts or hides it)."""
    if shutil.which("notify-send") is None:
        return OK
    tree = wm.look()
    win = find(tree, reg, name)
    if win is not None and not win.hidden and tree.focused(win):
        return OK
    body = " ".join(body.split()) or "Waiting for input"
    if len(body) > conf.NOTIFY_BODY_MAX:
        body = body[: conf.NOTIFY_BODY_MAX - 1] + "…"
    body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    try:
        # S603/S607: notify-send with crew's fixed options; it blocks until clicked or closed.
        done = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "notify-send",
                f"--app-name={conf.window_class()}",
                "--action=default=Show",
                f"--hint=string:x-dunst-stack-tag:crew-{name}",
                f"{name} needs you",
                body,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        log.warning(f"{name}: cannot notify: {e.strerror}")
        return OK
    if done.stdout.strip() == "default":
        return summon(reg, name)
    return OK

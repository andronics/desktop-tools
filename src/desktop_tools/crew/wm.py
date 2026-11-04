"""bspwm, as crew sees it: one `bspc wm -d` per look, and the dock's placement.

coord asked bspc and xprop once per window; the dump has every window's class, instance, flags,
border and floating rectangle, and every monitor's and desktop's padding and gap, in one call, and
needs no DISPLAY (crew's `stopped` runs from a detached child of a Claude session).

Placement follows coord's `_coord-place`, measured there against bspwm's gap model: the panel is
`width` wide including its border, inset by the window gap from the monitor's edge and from the
top and bottom padding, and the side's padding is `width + gap`, so tiled windows keep the gap
from it as from each other. The new side is padded before the old one is released, so re-docking
never lets tiled windows reflow across the strip. bspc moves and resizes floating windows only
relatively, hence the deltas.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator

from desktop_tools.crew import conf, log

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Any

TIMEOUT = 3.0


def node_id(value: int) -> str:
    """bspwm's own spelling of an id, as `bspc query` prints it and `bspc subscribe` reports."""
    return f"0x{value:08X}"


def parse_id(text: str) -> int | None:
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


class Window:
    """A client window. Plain classes here, not dataclasses: see registry.Coordinator."""

    __slots__ = ("border", "cls", "floating", "hidden", "id", "instance", "monitor", "rect")

    def __init__(
        self,
        id: int,  # bspwm's own name for it
        cls: str,
        instance: str,
        hidden: bool,
        floating: bool,
        monitor: int,
        border: int,
        rect: tuple[int, int, int, int],  # the floating rectangle: x, y, width, height
    ) -> None:
        self.id, self.cls, self.instance, self.hidden = id, cls, instance, hidden
        self.floating, self.monitor, self.border, self.rect = floating, monitor, border, rect

    @property
    def node(self) -> str:
        return node_id(self.id)


class Monitor:
    __slots__ = ("desk_padding", "focused_node", "gap", "id", "layout", "name", "padding", "rect")

    def __init__(
        self,
        id: int,  # bspwm's own name for it
        name: str,
        rect: tuple[int, int, int, int],
        padding: dict[str, int],
        gap: int,  # the focused desktop's window gap
        desk_padding: dict[str, int],
        layout: str,
        focused_node: int | None,
    ) -> None:
        self.id, self.name, self.rect, self.padding = id, name, rect, padding
        self.gap, self.desk_padding, self.layout = gap, desk_padding, layout
        self.focused_node = focused_node

    @property
    def node(self) -> str:
        return node_id(self.id)


class Tree:
    __slots__ = ("focused_monitor", "monitors", "windows")

    def __init__(self) -> None:
        self.windows: list[Window] = []
        self.monitors: dict[int, Monitor] = {}
        self.focused_monitor: int | None = None

    def focused(self, win: Window) -> bool:
        """Whether `win` is the focused window of the focused monitor's desktop."""
        mon = self.monitors.get(self.focused_monitor or -1)
        return mon is not None and mon.focused_node == win.id

    def crew(self, shown_only: bool = False) -> list[Window]:
        """crew's windows (its class, or coord's until those close)."""
        classes = conf.classes()
        return [w for w in self.windows if w.cls in classes and not (shown_only and w.hidden)]


# ---------------------------------------------------------------- reading


def _rect(data: Any) -> tuple[int, int, int, int]:
    d = data if isinstance(data, dict) else {}
    return (
        int(d.get("x", 0)),
        int(d.get("y", 0)),
        int(d.get("width", 0)),
        int(d.get("height", 0)),
    )


def _pad(data: Any) -> dict[str, int]:
    d = data if isinstance(data, dict) else {}
    return {k: int(d.get(k, 0) or 0) for k in ("top", "right", "bottom", "left")}


def _leaves(node: Any) -> Iterator[dict[str, Any]]:
    stack = [node]
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        if isinstance(n.get("client"), dict):
            yield n
        stack.extend((n.get("secondChild"), n.get("firstChild")))


def parse(data: Any) -> Tree:
    tree = Tree()
    if not isinstance(data, dict):
        return tree
    tree.focused_monitor = data.get("focusedMonitorId")
    for m in data.get("monitors") or []:
        if not isinstance(m, dict):
            continue
        desks = [d for d in m.get("desktops") or [] if isinstance(d, dict)]
        focused = next((d for d in desks if d.get("id") == m.get("focusedDesktopId")), None)
        f = focused or {}
        gap = f.get("windowGap", m.get("windowGap", 0))
        tree.monitors[int(m["id"])] = Monitor(
            id=int(m["id"]),
            name=str(m.get("name", "")),
            rect=_rect(m.get("rectangle")),
            padding=_pad(m.get("padding")),
            gap=int(gap or 0),
            desk_padding=_pad(f.get("padding")),
            layout=str(f.get("layout", "tiled")),
            focused_node=f.get("focusedNodeId") or None,
        )
        for d in desks:
            for n in _leaves(d.get("root")):
                c = n["client"]
                tree.windows.append(
                    Window(
                        id=int(n["id"]),
                        cls=str(c.get("className", "")),
                        instance=str(c.get("instanceName", "")),
                        hidden=bool(n.get("hidden")),
                        floating=c.get("state") == "floating",
                        monitor=int(m["id"]),
                        border=int(c.get("borderWidth", 0) or 0),
                        rect=_rect(c.get("floatingRectangle")),
                    )
                )
    return tree


def bspc(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        # S603/S607: bspc with crew's own fixed arguments, found on PATH.
        return subprocess.run(  # noqa: S603
            ["bspc", *args],  # noqa: S607
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def run(*args: str) -> bool:
    done = bspc(*args)
    return done is not None and done.returncode == 0


def dump() -> Tree | None:
    """The whole tree, or None when bspwm can't be asked."""
    done = bspc("wm", "-d")
    if done is None or done.returncode != 0:
        return None
    try:
        return parse(json.loads(done.stdout))
    except (ValueError, KeyError, TypeError):
        return None


def look() -> Tree:
    """The tree, or an empty one (no windows) when bspwm can't be asked."""
    return dump() or Tree()


def gapless_monocle() -> bool:
    done = bspc("config", "gapless_monocle")
    return done is not None and done.returncode == 0 and done.stdout.strip() == "true"


# ---------------------------------------------------------------- placing


def place(win: Window, width: int, side: str, monitor: int | None = None) -> bool:
    """Dock `win` to the `side` edge of `monitor` (default: the focused one, moving it there)
    and reserve the strip. False, logged, when it can't."""
    tree = look()
    mon_id = monitor if monitor is not None else tree.focused_monitor
    if mon_id is None or mon_id not in tree.monitors:
        log.error(f"place: no focused monitor for {win.node}")
        return False
    mon = tree.monitors[mon_id]
    if win.monitor != mon_id:
        if not run("node", win.node, "--to-monitor", mon.node):
            log.error(f"place: cannot move {win.node} to monitor {mon.node}")
            return False
        # Moving it translates its floating rectangle: read it again.
        tree = look()
        win = next((w for w in tree.windows if w.id == win.id), win)
        mon = tree.monitors.get(mon_id, mon)
    mx, my, mw, mh = mon.rect
    top, bottom = mon.padding["top"], mon.padding["bottom"]
    dtop, dbottom = mon.desk_padding["top"], mon.desk_padding["bottom"]
    gap = max(mon.gap, 0)
    if mon.layout == "monocle" and gapless_monocle():
        gap = 0
    bw = win.border
    fx, fy, fw, fh = win.rect
    if side == "left":
        x, other = mx + gap, "right"
    else:
        x, other = mx + mw - gap - width, "left"
    y = my + top + dtop + gap
    w = width - 2 * bw
    h = mh - top - bottom - dtop - dbottom - 2 * gap - 2 * bw
    # A failed move or resize leaves the panel off its strip until the guard's next re-dock, so
    # it is logged but not fatal; the padding is what keeps tiled windows out of the strip.
    if (w, h) != (fw, fh) and not run(
        "node", win.node, "--resize", "bottom_right", str(w - fw), str(h - fh)
    ):
        log.warning(f"place: cannot resize {win.node} to {w}x{h}")
    if (x, y) != (fx, fy) and not run("node", win.node, "--move", str(x - fx), str(y - fy)):
        log.warning(f"place: cannot move {win.node} to {x},{y}")
    pad = width + gap
    if not run("config", "-m", mon.node, f"{side}_padding", str(pad)):
        log.error(f"place: cannot set {side}_padding {pad} on {mon.node}")
        return False
    if mon.padding[other] != 0 and not run("config", "-m", mon.node, f"{other}_padding", "0"):
        log.error(f"place: cannot release {other}_padding on {mon.node}")
        return False
    return True


def redock(width: int, side: str) -> bool:
    """Re-place every shown crew window on its own monitor."""
    ok = True
    for win in look().crew(shown_only=True):
        if not place(win, width, side, win.monitor):
            log.error(f"redock: cannot place {win.instance} ({win.node}) at {width} on the {side}")
            ok = False
    return ok


def unpad() -> None:
    """Give the strip back on every monitor no crew window is shown on, whichever side it was
    on. Assumes left_padding and right_padding are otherwise 0, as bspwmrc sets them."""
    tree = look()
    held = {w.monitor for w in tree.crew(shown_only=True)}
    for mon in tree.monitors.values():
        if mon.id in held:
            continue
        for side in ("left", "right"):
            if mon.padding[side] != 0 and not run("config", "-m", mon.node, f"{side}_padding", "0"):
                log.warning(f"unpad: cannot release {side}_padding on {mon.node}")


def hide(win: Window) -> bool:
    return run("node", win.node, "--flag", "hidden=on")

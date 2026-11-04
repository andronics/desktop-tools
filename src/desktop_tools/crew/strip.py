"""The bar strip: one cell per coordinator, pushed to barctl's `crew` module (dotfiles record
0003 Part C). crew never talks to polybar: barctl draws the cells, colours them from the theme
and wraps them in its click tags, and polybar's hook is `barctl render crew`.

A cell's tier is its coordinator's activity: `unavailable` not running (dim), `idle` running
(fg_dim), `active` busy (accent), `alert` waiting for input (urgent); a shown coordinator's cell is
underlined. Running means its window or its tmux session exists; the activity file of one that
isn't running is stale and removed here. The push carries a time to live, so a strip whose
hooks have stopped (a crash) shows stale rather than busy for ever.

Standard library only: `crew bar` and every Claude hook's refresh run it.
"""

from __future__ import annotations

from desktop_tools.crew import conf, log, store, tmux, wm
from desktop_tools.crew.registry import Registry

MODULE = "crew"
SOURCE = "crew"
TIERS = {"off": "unavailable", "idle": "idle", "busy": "active", "waiting": "alert"}


class Scan:
    __slots__ = ("running", "shown")

    def __init__(self) -> None:
        self.running: set[str] = set()
        self.shown: set[str] = set()

    def activity(self, name: str) -> str:
        """off, idle, busy or waiting. A stale file (not running) is removed."""
        if name not in self.running:
            store.clear_activity(name)
            return "off"
        return store.activity(name) or "idle"


def scan(reg: Registry, tree: wm.Tree | None = None, sessions: set[str] | None = None) -> Scan:
    tree = wm.look() if tree is None else tree
    sessions = tmux.sessions() if sessions is None else sessions
    found = Scan()
    # Each coordinator's session as the registry names it, or a former name's.
    owner = {s: c.name for c in reg.coordinators for s in c.sessions}
    for s in sessions:
        if s in owner:
            found.running.add(owner[s])
        elif s.endswith("-coordinator"):
            found.running.add(reg.resolve(s.removesuffix("-coordinator")))
    for w in tree.crew():
        name = reg.resolve(w.instance)
        found.running.add(name)
        if not w.hidden:
            found.shown.add(name)
    return found


def segments(reg: Registry, found: Scan) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for c in reg.coordinators:
        cell: dict[str, object] = {
            "id": c.name,
            "tier": TIERS[found.activity(c.name)],
            "glyph": f" {c.icon} ",
        }
        if c.name in found.shown:
            cell["underline"] = True
        out.append(cell)
    return out


def push(reg: Registry, found: Scan | None = None) -> bool:
    """Push the strip to barctl. False, logged, when barctl won't take it; a strip with no
    `crew` module in barctl's modules.toml is not an error (the bar doesn't have it yet)."""
    from desktop_tools.barctl import ops

    found = scan(reg) if found is None else found
    try:
        ops.push(
            MODULE,
            {},
            whole={"segments": segments(reg, found)},
            ttl=conf.bar_ttl() or None,
            source=SOURCE,
        )
    except ops.Failure as e:
        if e.code == ops.NOT_FOUND:
            log.debug(f"bar: {e}")
            return True
        log.error(f"bar: barctl refused the strip: {e}")
        return False
    except Exception as e:
        log.error(f"bar: cannot push the strip: {type(e).__name__}: {e}")
        return False
    return True


def line() -> str:
    """What polybar shows for the strip, as barctl renders it."""
    from desktop_tools.barctl import ops

    try:
        return ops.render_line(MODULE)
    except ops.Failure:
        return ""

"""Writing a module's state: the one call barctl's sources and `push` share (record 0003 §B6).

A state is written only when its content changed, and the module poked only when what it
shows changed, so a source can report every event and the bar redraws only on a real change.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import Module, shown_tier


def shown(module: Module, state: st.State | None, now: float | None = None) -> tuple[object, ...]:
    """What the bar shows of a module's state, for its display: equal means no poke."""
    if state is None:
        return ()
    now = time.time() if now is None else now
    stale = bool(state.get("expires")) and float(state["expires"]) <= now
    alerting = bool(state.get("alert_until")) and float(state["alert_until"]) > now
    glyph = module.glyph_for(shown_tier(state, now), state)[0]
    parts: tuple[object, ...]
    if module.display == "icon":
        parts = (glyph, state.get("count"))
    elif module.display == "text":
        parts = (state.get("label"),)
    else:
        parts = (glyph, state.get("count"), state.get("label"))
    segments = tuple(
        (
            s.get("id"),
            s.get("tier"),
            s.get("glyph"),
            s.get("label"),
            s.get("alert_until"),
            bool(s.get("underline")),
        )
        for s in state.get("segments") or []
    )
    return (state.get("tier"), *parts, segments, stale, alerting)


def store(
    module: Module,
    new: st.State,
    poke: Callable[[str], object],
    now: float | None = None,
) -> bool:
    """Write a module's new state if its content changed, and poke it if what it shows changed.
    Returns whether it was written."""
    now = time.time() if now is None else now
    old = st.read(module.name)
    if st.content(old) == st.content(new):
        return False
    new = {**new, "updated": now}
    st.write(module.name, new)
    if shown(module, old, now) != shown(module, new, now):
        poke(module.name)
    return True


class Writer:
    """How a source sets its modules: tier, glyph, label and target, nothing else. An alert
    someone set on the module is kept."""

    def __init__(self, modules: dict[str, Module], poke: Callable[[str], object]) -> None:
        self.modules, self.poke = modules, poke

    def set(
        self,
        name: str,
        source: str,
        tier: str,
        *,
        glyph: str | None = None,
        label: str = "",
        target: str | None = None,
        detail: str | None = None,
    ) -> bool:
        module = self.modules.get(name)
        if module is None:
            return False
        new: st.State = {"tier": tier, "source": source}
        if glyph is not None:
            new["glyph"] = glyph
        if label:
            new["label"] = label
        if target:
            new["target"] = target
        if detail:
            new["detail"] = detail
        old = st.read(name)
        if old and old.get("alert_until"):
            new["alert_until"] = old["alert_until"]
        return store(module, new, self.poke)

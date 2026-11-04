"""A module's text for polybar: its state, coloured from the theme's roles by tier, wrapped in
action tags that run `barctl click` (dotfiles record 0003 §B2).

Text is text: `%{` in anything a writer gave is escaped to `%%{`, and the colour and action tags
are barctl's own, so no pusher can put a command into a click. Standard library only: polybar
runs this on every poke (`hook-0 = barctl render <module>`).
"""

from __future__ import annotations

import time

from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import BUTTONS, Module
from desktop_tools.common import theme

METADATA_MAX = 40


def escape(text: str) -> str:
    """polybar reads %{ as the start of a format tag; %%{ is a literal one."""
    return text.replace("%{", "%%{")


def compose(display: str, glyph: str, label: str, count: int) -> str:
    """The plain text: icon is the glyph then the count (above 0), text is the label."""
    icon = " ".join(p for p in (glyph, str(count) if count > 0 else "") if p)
    if display == "icon":
        return icon
    if display == "text":
        return label
    return " ".join(p for p in (icon, label) if p)


def blink_on(now: float) -> bool:
    """Which half of a blink it is: the same answer for every render in the same half-second."""
    return int(now / st.BLINK) % 2 == 0


def colour(tier: str, alert_until: float | None, now: float, controller: bool) -> str:
    """The tier whose role colours the text: urgent while alerting (blinking with the
    controller, steady without it), else the state's own."""
    if alert_until and alert_until > now and (not controller or blink_on(now)):
        return "alert"
    return tier


def _actions(module: Module, text: str, segment: str | None = None) -> str:
    clicks = module.segment_clicks if segment is not None else module.clicks
    buttons = [b for b in BUTTONS if b in clicks]
    if "right" not in buttons and module.has_menu():
        buttons.append("right")
    suffix = f" --segment {segment}" if segment is not None else ""
    for button in sorted(buttons, key=BUTTONS.__getitem__):
        text = f"%{{A{BUTTONS[button]}:barctl click {module.name} {button}{suffix}:}}{text}%{{A}}"
    return text


def _paint(text: str, tier: str, colours: dict[str, str]) -> str:
    hex_ = colours.get(tier) or colours.get("unavailable")
    return f"%{{F{hex_}}}{text}%{{F-}}" if hex_ else text


def text_of(module: Module, state: st.State | None, now: float) -> tuple[str, str]:
    """(tier, plain text) of a module without segments, staleness applied."""
    if state is None:
        return "unavailable", module.glyph
    tier = str(state.get("tier") or "unavailable")
    glyph = str(state.get("glyph", module.glyph) or "")
    label = str(state.get("label") or "")
    count = state.get("count") or 0
    if state.get("expires") and float(state["expires"]) <= now:
        return "unavailable", glyph
    return tier, compose(module.display, glyph, label, int(count))


def render(
    module: Module,
    state: st.State | None,
    *,
    disabled: bool = False,
    now: float | None = None,
    colours: dict[str, str] | None = None,
    controller: bool | None = None,
) -> str:
    """The line polybar shows: empty when there is nothing to show."""
    if disabled:
        return ""
    now = time.time() if now is None else now
    if colours is None:
        colours = theme.roles(st.ROLES)
    if controller is None:
        controller = st.controller() is not None
    segments = (state or {}).get("segments")
    if segments:
        stale = bool(state and state.get("expires") and float(state["expires"]) <= now)
        module_alert = (state or {}).get("alert_until")
        cells = []
        for seg in segments:
            text = " ".join(p for p in (seg.get("glyph", ""), seg.get("label", "")) if p)
            if not text:
                continue
            tier = "unavailable" if stale else str(seg.get("tier") or "idle")
            until = seg.get("alert_until") or module_alert
            tier = colour(tier, None if stale else until, now, controller)
            cells.append(_actions(module, _paint(escape(text), tier, colours), seg["id"]))
        return module.separator.join(cells)
    tier, text = text_of(module, state, now)
    if not text:
        return ""
    until = (state or {}).get("alert_until")
    stale = bool(state and state.get("expires") and float(state["expires"]) <= now)
    tier = colour(tier, None if stale else until, now, controller)
    return _actions(module, _paint(escape(text), tier, colours))

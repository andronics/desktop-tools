"""A module's text for polybar: its state, coloured from the theme's roles by tier, wrapped in
action tags that run `barctl click` (dotfiles record 0003 §B2).

Text is text: `%{` in anything a writer gave is escaped to `%%{`, and the colour and action tags
are barctl's own, so no pusher can put a command into a click. Standard library only: polybar
runs this on every poke (`hook-0 = barctl render <module>`).

`display = "capsule"` (record 0003 §1, §3) is the player's "now playing" module: the play-state
icon, then the label in a fixed width, scrolling while it plays when it is longer, and the
track's progress as an underline under the first cells. Both are worked out here from the state
and the time, as the blink is, so the source writes once per real change; the controller's tick
pokes the capsule when its frame changes (`next_change`).

`display = "output"` (record 0003 §10) is the output segment beside it: the default sink's kind
glyph, its short name (or, for 5 seconds, a notice such as `<name> connected` in the active
accent), a Bluetooth sink's battery, then the volume glyph by level and the percentage; muted,
md-volume_off and the idle tier's colour. The controller's tick pokes it when a notice ends.
"""

from __future__ import annotations

import contextlib
import time

from desktop_tools.barctl import outputs
from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import BUTTONS, Module, shown_tier
from desktop_tools.common import theme

METADATA_MAX = 40
UNDERLINE_ROLE = "accent"  # a marked segment's underline: record 0001's "shown" accent
GAP = "   "  # between the end of a scrolling title and its start coming round again
# A zero-width space after a cut that ends in `%`: `%` then barctl's own `%{` tag would read as
# the escape `%%{`, and polybar would print the tag as text.
BREAK = "\u200b"


def cut(text: str, width: int) -> str:
    """At most `width` characters, the last an ellipsis when it was longer."""
    return text if len(text) <= width else text[: width - 1] + "…"


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


def _underline(text: str, colour: str | None) -> str:
    return f"%{{u{colour}}}%{{+u}}{text}%{{-u}}" if colour else f"%{{+u}}{text}%{{-u}}"


def text_of(module: Module, state: st.State | None, now: float) -> tuple[str, str]:
    """(tier, plain text) of a module without segments, staleness applied."""
    tier = shown_tier(state, now)
    glyph, _ = module.glyph_for(tier, state)
    if state is None:
        return "unavailable", glyph
    if tier == "unavailable" and state.get("expires") and float(state["expires"]) <= now:
        return "unavailable", glyph
    label = str(state.get("label") or "")
    if module.display == "capsule":
        frame, _ = capsule_frame(module, state, now)
        return tier, " ".join(p for p in (glyph, frame) if p)
    if module.display == "output":
        return tier, " ".join(p for p in output_parts(module, state, now) if p)
    count = state.get("count") or 0
    # The player's label is whole (the capsule scrolls it); text and both show 40 of it.
    return tier, compose(module.display, glyph, cut(label, METADATA_MAX), int(count))


# ---------------------------------------------------------------- the capsule


def _since(state: st.State) -> float:
    return float(state.get("label_since") or state.get("updated") or 0)


def scrolls(module: Module, state: st.State | None, now: float) -> bool:
    """A capsule's title scrolls only while playing, longer than its width, with scroll > 0."""
    if state is None or module.scroll <= 0 or shown_tier(state, now) != "active":
        return False
    return len(str(state.get("label") or "")) > module.width


def _cycle(module: Module, label: str) -> tuple[int, float, float]:
    """(steps in a pass, seconds of a pass, seconds of a pass and its rest)."""
    steps = len(label) + len(GAP)
    passing = steps / module.scroll
    return steps, passing, passing + module.scroll_rest


def scroll_offset(module: Module, state: st.State, now: float) -> int:
    """Cells the title has moved: one pass from the start round to the start again, at
    `scroll` cells a second, then `scroll_rest` seconds resting at the start, then again."""
    if not scrolls(module, state, now):
        return 0
    _, passing, cycle = _cycle(module, str(state.get("label") or ""))
    t = max(0.0, now - _since(state)) % cycle
    return int(t * module.scroll) if t < passing else 0


def fraction(state: st.State | None, now: float) -> float | None:
    """How far through the track: position (moved on by the time since while playing) over
    length, 0 to 1; None with no length (a stream) or no progress."""
    p = (state or {}).get("progress")
    if not isinstance(p, dict) or not p.get("length"):
        return None
    try:
        length, position = float(p["length"]), float(p.get("position") or 0)
        if p.get("playing"):
            position += max(0.0, now - float(p.get("at") or now)) * float(p.get("rate") or 0)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, position / length)) if length > 0 else None


def _cells(module: Module, part: float | None) -> int:
    return 0 if part is None else min(module.width, int(part * module.width + 0.5))


def capsule_frame(module: Module, state: st.State | None, now: float) -> tuple[str, int]:
    """(the text cells, padded to the width; how many are underlined): what a capsule shows
    beside its icon. Nothing with no player."""
    if state is None or shown_tier(state, now) == "unavailable":
        return "", 0
    label = str(state.get("label") or "")
    width = module.width
    if scrolls(module, state, now):
        offset = scroll_offset(module, state, now)
        text = (label + GAP + label)[offset : offset + width]
    else:
        text = cut(label, width)
    return text.ljust(width), _cells(module, fraction(state, now))


def next_change(module: Module, state: st.State | None, now: float) -> float | None:
    """When the capsule's frame next changes, for the controller's tick: the next scroll step
    while scrolling, else the next progress cell, never sooner than a second for progress
    alone; None when nothing moves (paused, no player, nothing to scroll or measure)."""
    if module.display != "capsule" or state is None:
        return None
    if shown_tier(state, now) == "unavailable":
        return None
    if scrolls(module, state, now):
        _, passing, cycle = _cycle(module, str(state.get("label") or ""))
        t = max(0.0, now - _since(state)) % cycle
        start = now - t
        if t < passing:
            # Every step redraws the whole capsule, its progress too: nothing else is needed.
            return start + (int(t * module.scroll) + 1) / module.scroll
        resting_until = start + cycle + 1 / module.scroll
    else:
        resting_until = None
    best = resting_until
    p = state.get("progress")
    part = fraction(state, now)
    if isinstance(p, dict) and p.get("playing") and part is not None:
        cells, rate = _cells(module, part), float(p.get("rate") or 0)
        if cells < module.width and rate > 0:
            length, position = float(p["length"]), float(p.get("position") or 0)
            boundary = (cells + 0.5) / module.width * length
            at = float(p.get("at") or now) + (boundary - position) / rate
            at = max(at, now + 1.0)
            best = at if best is None else min(best, at)
    return best


def _hex_paint(text: str, hex_: str | None) -> str:
    return f"%{{F{hex_}}}{text}%{{F-}}" if hex_ else text


def _safe(text: str) -> str:
    text = escape(text)
    return text + BREAK if text.endswith("%") else text


def capsule(
    module: Module, state: st.State | None, now: float, colours: dict[str, str], controller: bool
) -> str:
    """The capsule's line: the icon in the accent, the text in the tier's role colour, and the
    progress underline in the accent. The art's colour, with `accent = "art"`, is only ever the
    line's and the icon's, never the text's, so the theme's contrast rules hold."""
    tier = shown_tier(state, now)
    glyph, _ = module.glyph_for(tier, state)
    until = (state or {}).get("alert_until")
    shown = colour(tier, until, now, controller)
    accent = colours.get("underline")
    art = (state or {}).get("accent")
    if module.accent == "art" and isinstance(art, str):
        # A hand-written state file's bad colour: the role colour shows.
        with contextlib.suppress(st.StateError):
            accent = st.accent(art)
    icon_hex = accent if shown not in ("unavailable", "alert") else colours.get(shown)
    icon = _hex_paint(_safe(glyph), icon_hex) if glyph else ""
    text, cells = capsule_frame(module, state, now)
    if not text:
        return _actions(module, icon) if icon else ""
    lined, rest = text[:cells], text[cells:]
    body = (_underline(_safe(lined), accent) if lined else "") + _safe(rest)
    painted = _paint(body, shown, colours)
    return _actions(module, f"{icon} {painted}" if icon else painted)


# ---------------------------------------------------------------- the output segment


def output_parts(module: Module, state: st.State | None, now: float) -> tuple[str, str, str]:
    """(kind glyph, the name or the notice, the battery and volume): the output segment's plain
    text in its three parts. Only the glyph when unavailable (no pulse server)."""
    tier = shown_tier(state, now)
    glyph, _ = module.glyph_for(tier, state)
    if state is None or tier == "unavailable":
        return glyph, "", ""
    found = state.get("output")
    numbers: st.State = found if isinstance(found, dict) else {}
    name = st.notice_on(state, now) or str(state.get("label") or "")
    try:
        volume = int(numbers.get("volume") or 0)
        battery = numbers.get("battery")
        level = None if battery is None else int(battery)
    except (TypeError, ValueError):  # a hand-written state file's bad number: shown as none
        volume, level = 0, None
    vol = f"{outputs.volume_glyph(volume, tier == 'idle')} {volume}%".ljust(6)
    rest = " ".join(p for p in (outputs.battery_glyph(level), vol) if p)
    return glyph, name, rest


def output(
    module: Module, state: st.State | None, now: float, colours: dict[str, str], controller: bool
) -> str:
    """The output segment's line: the tier's role colour, the notice in the active accent."""
    tier = shown_tier(state, now)
    until = (state or {}).get("alert_until")
    shown = colour(tier, until, now, controller)
    glyph, name, rest = output_parts(module, state, now)
    notice = st.notice_on(state, now) if tier != "unavailable" else None
    if notice and shown != "alert":
        pieces = [
            _paint(_safe(glyph), shown, colours) if glyph else "",
            _paint(_safe(notice), "active", colours),
            _paint(_safe(rest), shown, colours) if rest else "",
        ]
        line = " ".join(p for p in pieces if p)
    else:
        text = " ".join(p for p in (glyph, name, rest) if p)
        line = _paint(_safe(text), shown, colours) if text else ""
    return _actions(module, line) if line else ""


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
        colours = theme.roles({**st.ROLES, "underline": UNDERLINE_ROLE})
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
            cell = _paint(escape(text), tier, colours)
            if seg.get("underline") and not stale:
                cell = _underline(cell, colours.get("underline"))
            cells.append(_actions(module, cell, seg["id"]))
        return module.separator.join(cells)
    if module.display == "capsule":
        return capsule(module, state, now, colours, controller)
    if module.display == "output":
        return output(module, state, now, colours, controller)
    tier, text = text_of(module, state, now)
    if not text:
        return ""
    until = (state or {}).get("alert_until")
    stale = bool(state and state.get("expires") and float(state["expires"]) <= now)
    tier = colour(tier, None if stale else until, now, controller)
    return _actions(module, _paint(escape(text), tier, colours))

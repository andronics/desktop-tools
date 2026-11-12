"""The capsule's transport row (record 0005 phase C): its cells, laid out in the capsule's own
width, and what pressing each one runs.

A left-click on the capsule's icon runs `barctl expand <capsule>`, which writes
`expanded_until`; while that is in the future (and `expand_for` is above 0), render draws this
row in place of the title, in the same cells, so nothing on the bar moves. The row is never in
the state, which stays the source's: render builds it from the state and the time.

The row: previous, play-pause, next, then loop (by the player's mode) and shuffle (on or off)
when the player gives them, each a glyph in up to three columns; then, with a known length and
a capsule at least SEEK_MIN cells wide, a seek bar of SEEK_CELLS cells, `━` up to the position
and `─` after it, cell `seek-<i>` seeking to i/16 of the length. With no length (a stream) or a
narrower capsule, back and forward buttons stand in for the seek bar: 10 s, or 30 s when `kind`
is spoken (record 0005 phase B).

Each cell is a segment: `barctl click <capsule> left --segment <id>` runs the capsule's
`segment_clicks.left`, which the dotfiles set to `barctl transport <capsule> {segment}`; that
maps the cell to one `playerctl -p <target>` argument list (`argv`). Standard library only:
render imports this on every poke.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PREVIOUS = "\U000f04ae"  # md-skip_previous
PLAY_PAUSE = "\U000f040e"  # md-play_pause
NEXT = "\U000f04ad"  # md-skip_next
# The player's loop mode -> (its glyph, the mode a press steps to): None, Track, Playlist, None.
LOOP = {
    "None": ("\U000f0457", "Track"),  # md-repeat_off
    "Track": ("\U000f0458", "Playlist"),  # md-repeat_once
    "Playlist": ("\U000f0456", "None"),  # md-repeat
}
SHUFFLE_ON = "\U000f049f"  # md-shuffle_variant
SHUFFLE_OFF = "\U000f049e"  # md-shuffle_disabled
BACK = {10: "\U000f0d2a", 30: "\U000f0d96"}  # md-rewind_10, md-rewind_30
FORWARD = {10: "\U000f0d71", 30: "\U000f0d06"}  # md-fast_forward_10, md-fast_forward_30
FILLED, EMPTY = "━", "─"  # the seek bar: ━ up to the position, ─ after it
SEEK_CELLS = 16
SEEK_MIN = 24  # a capsule narrower than this drops the seek bar for the back/forward buttons
BUTTON_COLUMNS = 3  # each button's glyph, centred in up to this many columns
STEP, SPOKEN_STEP = 10, 30  # seconds a back or forward press skips (spoken word: 30)
BUTTONS = ("previous", "play-pause", "next", "loop", "shuffle", "back", "forward")


@dataclass(frozen=True)
class Cell:
    """One cell of the row: its segment id (None for padding), its text, and how it is painted
    (`button`, `filled` or `empty` seek cells, `pad`)."""

    id: str | None
    text: str
    paint: str


def step(state: dict[str, Any] | None) -> int:
    """Seconds a back or forward press skips: 30 for spoken word, else 10."""
    return SPOKEN_STEP if (state or {}).get("kind") == "spoken" else STEP


def length(state: dict[str, Any] | None) -> float | None:
    """The track's length in seconds, or None (a stream, or no progress)."""
    p = (state or {}).get("progress")
    if not isinstance(p, dict):
        return None
    try:
        value = float(p.get("length") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def buttons(state: dict[str, Any] | None, seek: bool) -> list[tuple[str, str]]:
    """(segment id, glyph) of each button, in order; loop and shuffle only when the player
    gives them, back and forward only without the seek bar."""
    data = state or {}
    out = [("previous", PREVIOUS), ("play-pause", PLAY_PAUSE), ("next", NEXT)]
    loop = data.get("loop")
    if isinstance(loop, str) and loop in LOOP:
        out.append(("loop", LOOP[loop][0]))
    shuffle = data.get("shuffle")
    if isinstance(shuffle, bool):
        out.append(("shuffle", SHUFFLE_ON if shuffle else SHUFFLE_OFF))
    if not seek:
        seconds = step(data)
        out += [("back", BACK[seconds]), ("forward", FORWARD[seconds])]
    return out


def row(width: int, state: dict[str, Any] | None, part: float | None) -> list[Cell]:
    """The row's cells, exactly `width` characters together. `part` is how far through the
    track it is (render.fraction), None with no length."""
    seek = part is not None and length(state) is not None and width >= SEEK_MIN
    found = buttons(state, seek)
    room = width - (SEEK_CELLS + 1 if seek else 0)
    columns = max(1, min(BUTTON_COLUMNS, room // len(found)))
    cells = []
    for segment, glyph in found:
        left = (columns - 1) // 2
        cells.append(Cell(segment, " " * left + glyph + " " * (columns - 1 - left), "button"))
    used = columns * len(found)
    if seek and part is not None:
        cells.append(Cell(None, " ", "pad"))
        filled = min(SEEK_CELLS, int(part * SEEK_CELLS + 0.5))
        for i in range(SEEK_CELLS):
            on = i < filled
            cells.append(Cell(f"seek-{i}", FILLED if on else EMPTY, "filled" if on else "empty"))
        used += SEEK_CELLS + 1
    if used < width:
        cells.append(Cell(None, " " * (width - used), "pad"))
    return cells


def plain(cells: list[Cell]) -> str:
    return "".join(c.text for c in cells)


class UnknownCell(ValueError):
    """Not a cell of the transport row."""


def seek_index(cell: str) -> int | None:
    """i for `seek-<i>` (0 to 15), None for any other cell. Raises UnknownCell past 15."""
    if not cell.startswith("seek-"):
        return None
    digits = cell[len("seek-") :]
    if not digits.isdigit() or not 0 <= int(digits) < SEEK_CELLS:
        raise UnknownCell(f"no cell {cell!r} (seek-0 to seek-{SEEK_CELLS - 1})")
    return int(digits)


def argv(cell: str, state: dict[str, Any] | None) -> list[str] | None:
    """The one `playerctl -p <target>` argument list a press on the cell runs; None when there
    is nothing to act on (no target, a seek with no length, loop with no mode). Raises
    UnknownCell for a cell the row never has."""
    index = seek_index(cell)
    if index is None and cell not in BUTTONS:
        raise UnknownCell(f"no cell {cell!r} (one of {', '.join(BUTTONS)}, seek-<i>)")
    data = state or {}
    target = str(data.get("target") or "")
    if not target or data.get("tier") in (None, "unavailable"):
        return None
    p = ["playerctl", "-p", target]
    if index is not None:
        total = length(data)
        if total is None:
            return None
        return [*p, "position", f"{index / SEEK_CELLS * total:.1f}"]
    if cell in ("previous", "play-pause", "next"):
        return [*p, cell]
    if cell == "loop":
        loop = data.get("loop")
        return [*p, "loop", LOOP[loop][1]] if isinstance(loop, str) and loop in LOOP else None
    if cell == "shuffle":
        return [*p, "shuffle", "toggle"]  # playerctl 2.4: on, off or toggle
    sign = "-" if cell == "back" else "+"
    return [*p, "position", f"{step(data)}{sign}"]

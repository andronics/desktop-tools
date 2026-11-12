"""The player menu's rows (record 0003 §4): next, previous, loop and shuffle with their state,
the player choice, seeking, all on the player the capsule shows, and the output (§10).

The player is the `target` in barctl's state for `player-capsule`; then one read-only query,
`playerctl -p <target> metadata --format '{{status}}<US>{{loop}}<US>{{shuffle}}'` (TIMEOUT
seconds). Every row is an argument list with `-p <target>`, the instance from barctl's state,
never a shell string. With no player, or when the query fails or times out: `No player`,
which does nothing, and `Player…` (then MORE), so another can be chosen. The `Output` row is
always there: the kind glyph and short name barctl's `output-capsule` shows (no query), or
`Output…` when it has none; it opens `barmenu outputs`. The loop and shuffle
rows are hidden when the player gives none; the seek rows when no length is known. Nothing here
logs the player's state, and no row sets or clears COORDINATOR, CLAUDECODE or TESSERA_ACTOR
(§6): every command gets the bar's environment as it is.
"""

from __future__ import annotations

from desktop_tools.barctl import outputs
from desktop_tools.barctl import state as st
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.common import procs

MODULE = "player-capsule"
OUTPUT = "output-capsule"
US = "\x1f"
FORMAT = US.join(("{{status}}", "{{loop}}", "{{shuffle}}"))

NEXT = "\U000f04ad"  # md-skip_next
PREVIOUS = "\U000f04ae"  # md-skip_previous
LOOP = {
    "None": ("\U000f0457", "off", "Track"),  # md-repeat_off
    "Track": ("\U000f0458", "track", "Playlist"),  # md-repeat_once
    "Playlist": ("\U000f0456", "playlist", "None"),  # md-repeat
}
SHUFFLE_ON = "\U000f049f"  # md-shuffle_variant
SHUFFLE_OFF = "\U000f049e"  # md-shuffle_disabled
PLAYERS = "\U000f0411"  # md-playlist_play
BACK = "\U000f0d2a"  # md-rewind_10
FORWARD = "\U000f0d71"  # md-fast_forward_10
NONE = "\U000f038a"  # md-music_note_off
MORE = "\u203a"  # a single right angle quote: the row opens another menu


def shown() -> tuple[str, st.State]:
    """The capsule's player (empty with none) and its state."""
    data = st.read(MODULE) or {}
    if data.get("tier") in (None, "unavailable"):
        return "", data
    return str(data.get("target") or ""), data


def query(target: str) -> tuple[str, str, str] | None:
    """(status, loop, shuffle) of the player, or None when it can't be read."""
    out = procs.query(
        ["playerctl", "-p", target, "metadata", "--format", FORMAT], timeout=providers.TIMEOUT
    )
    fields = (out or "").rstrip("\n").split(US)
    if len(fields) != 3 or not fields[0]:
        return None
    status, loop, shuffle = (f.strip() for f in fields)
    return status, loop, shuffle


def players_row(target: str) -> Row:
    label = f"Player: {target.split('.', 1)[0]} {MORE}" if target else f"Player… {MORE}"
    return Row(PLAYERS, label, ["barmenu", "players"])


def output_row() -> Row:
    """`Output: <short name>` (then MORE) with the output's kind glyph, from barctl's state
    for the output segment; `Output…` when that state can't be read."""
    data = st.read(OUTPUT) or {}
    name, glyph = data.get("label"), data.get("glyph")
    if data.get("tier") in (None, "unavailable") or not isinstance(name, str) or not name:
        return Row(outputs.SPEAKER, f"Output… {MORE}", ["barmenu", "outputs"])
    shown = glyph if isinstance(glyph, str) and glyph else outputs.SPEAKER
    return Row(shown, f"Output: {name} {MORE}", ["barmenu", "outputs"])


def seekable(data: st.State) -> bool:
    progress = data.get("progress")
    return isinstance(progress, dict) and bool(progress.get("length"))


def rows() -> list[Row]:
    target, data = shown()
    found = query(target) if target else None
    if found is None:
        return [Row(NONE, "No player", []), players_row(""), output_row()]
    _status, loop, shuffle = found
    p = ["playerctl", "-p", target]
    out = [Row(NEXT, "Next", [*p, "next"]), Row(PREVIOUS, "Previous", [*p, "previous"])]
    if loop in LOOP:
        glyph, word, after = LOOP[loop]
        out.append(Row(glyph, f"Loop: {word}", [*p, "loop", after], current=loop != "None"))
    if shuffle.lower() in ("true", "false"):
        on = shuffle.lower() == "true"
        out.append(
            Row(
                SHUFFLE_ON if on else SHUFFLE_OFF,
                f"Shuffle: {'on' if on else 'off'}",
                [*p, "shuffle", "Off" if on else "On"],
                current=on,
            )
        )
    out.append(players_row(target))
    if seekable(data):
        out += [
            Row(BACK, "Back 10 s", [*p, "position", "10-"]),
            Row(FORWARD, "Forward 10 s", [*p, "position", "10+"]),
        ]
    out.append(output_row())
    return out

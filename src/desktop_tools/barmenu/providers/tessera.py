"""The tessera menu's rows (record 0002 §2): lock, unlock, copy a password or two-factor code,
pick, and the password store's sync state, with the key's lock state marked.

One query, `tessera status --json` (never decrypts, names only counts and states). It exits 1
when a check fails but still prints its JSON, so the output is read whatever the exit code.
Unreadable (missing, over the limit, not JSON), rows 1 and 2 are unmarked and say `Lock` and
`Unlock…`, rows 3 and 4 are hidden (their version can't be told) and row 6 is `Sync status…`.

No row runs `tessera sync`, `show`, `otp`, `names`, `log`, `health` or `pass`, and no entry name
passes through barmenu: `tessera pick` chooses it in its own rofi. barmenu never sets or clears
COORDINATOR, CLAUDECODE or TESSERA_ACTOR: tessera reads them to tell who is calling. When one is
set in barmenu's own environment, rows 1-5 become one `Not available` row (§6).
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.common import procs

LOCK = "\U000f033e"  # md-lock
UNLOCK = "\U000f033f"  # md-lock_open
KEY = "\U000f0306"  # md-key
TWO_FACTOR = "\U000f09af"  # md-two_factor_authentication
PICK = "\U000f07f5"  # md-form_textbox_password
SYNC = "\U000f04e6"  # md-sync
SYNC_ALERT = "\U000f04e7"  # md-sync_alert
UNAVAILABLE = "\U000f05d6"  # md-alert_circle_outline

# The first tessera release with `pick --password` and `pick --otp` (record 0002 §8, ask 1), as
# a tuple of numbers. None until it exists: rows 3 and 4 stay hidden.
PICK_FLAGS_FROM: tuple[int, ...] | None = None

AGENT_VARIABLES = ("COORDINATOR", "CLAUDECODE", "TESSERA_ACTOR")
CLOSE = 'read -sk1 "?Press any key to close"'
PROMPT = ["alacritty", "--class", "tessera-prompt", "-e", "zsh", "-fc"]
STATUS = ["tessera", "status", "--json"]
FIX = "fix at a terminal: `tessera status`"


def window(command: str) -> list[str]:
    """A command in a terminal window that stays open, on a failure, until a key is pressed:
    tessera's own check wants it at a terminal, and the reason can be read."""
    return [*PROMPT, f"{command} || {CLOSE}"]


def status() -> dict[str, Any] | None:
    """tessera's status, or None when it is unreadable."""
    out = procs.query(STATUS, timeout=providers.TIMEOUT, any_exit=True)
    try:
        data = json.loads(out) if out else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def version(data: dict[str, Any] | None) -> tuple[int, ...] | None:
    found = (data or {}).get("version")
    if not isinstance(found, str) or not re.fullmatch(r"\d+(\.\d+)*", found):
        return None
    return tuple(int(p) for p in found.split("."))


def age(last_fetch: object, now: datetime | None = None) -> str:
    """`20h` for an ISO time that long ago; empty when there is none or it can't be read."""
    if not isinstance(last_fetch, str):
        return ""
    try:
        then = datetime.fromisoformat(last_fetch.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = max(0, int(((now or datetime.now(UTC)) - then).total_seconds()))
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def sync_text(data: dict[str, Any]) -> str | None:
    """`level, 20h ago`, `ahead 2`, `diverged`, `first sync pending` or `failing`; None when
    the status has no readable sync section."""
    sync = data.get("sync")
    if not isinstance(sync, dict) or not isinstance(sync.get("state"), str):
        return None
    if sync.get("first_sync") not in (None, "done"):
        return "first sync pending"
    if sync.get("failing_since"):
        return "failing"
    state = str(sync["state"])
    if state == "ahead" and _count(sync.get("ahead")):
        return f"ahead {_count(sync['ahead'])}"
    if state == "behind" and _count(sync.get("behind")):
        return f"behind {_count(sync['behind'])}"
    ago = age(sync.get("last_fetch"))
    return f"{state}, {ago} ago" if state == "level" and ago else state


def sync_alerting(data: dict[str, Any]) -> bool:
    """Whether the sync check is anything but ok (a check missing counts as ok)."""
    for check in data.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == "sync":
            return check.get("state") != "ok"
    return False


def notification(data: dict[str, Any]) -> str:
    """One line per check, as `tessera status` prints them at a terminal: counts and states
    only. A check that is not ok ends with where to fix it."""
    lines = []
    for check in data.get("checks") or []:
        if not isinstance(check, dict):
            continue
        state = str(check.get("state", "?"))
        line = f"{state:<4} {check.get('name', '?')}  {check.get('detail', '')}"
        lines.append(line if state == "ok" else f"{line} ({FIX})")
    return "\n".join(lines) or str(data.get("summary", ""))


def sync_row(data: dict[str, Any] | None) -> Row:
    text = sync_text(data) if data else None
    if data is None or text is None:
        return Row(SYNC, "Sync status…", window("tessera status"))
    return Row(
        SYNC_ALERT if sync_alerting(data) else SYNC,
        f"Sync: {text}",
        ["dunstify", "-a", "tessera", "Password store", notification(data)],
    )


def tainted() -> bool:
    return any(v in os.environ for v in AGENT_VARIABLES)


def rows() -> list[Row]:
    data = status()
    sync = sync_row(data)
    if tainted():
        return [
            Row(
                UNAVAILABLE,
                "Not available: the bar runs in an agent's environment",
                [
                    "dunstify",
                    "-a",
                    "tessera",
                    "Password menu",
                    "The bar was started from an agent's or coordinator's session, so tessera "
                    "refuses its requests. Restart the bar from a clean session.",
                ],
            ),
            sync,
        ]
    lock = data.get("lock") if data else None
    locked, unlocked = lock == "locked", lock == "unlocked"
    waiting = _count((data or {}).get("waiting"))
    if data is None:
        unlock_label, lock_label = "Unlock…", "Lock"
    else:
        lock_label = "Locked"
        unlock_label = (
            "Unlocked" if unlocked else f"Unlock: {waiting} waiting…" if waiting else "Unlock…"
        )
    found = version(data)
    flags = PICK_FLAGS_FROM is not None and found is not None and found >= PICK_FLAGS_FROM
    out = [
        Row(LOCK, lock_label, window("tessera lock"), current=locked),
        Row(UNLOCK, unlock_label, window("tessera unlock"), current=unlocked),
    ]
    if flags:
        out += [
            Row(KEY, "Copy password…", ["tessera", "pick", "--password"]),
            Row(TWO_FACTOR, "Copy two-factor code…", ["tessera", "pick", "--otp"]),
        ]
    return [*out, Row(PICK, "Pick…", ["tessera", "pick"]), sync]

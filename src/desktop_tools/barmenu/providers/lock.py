"""The lock menu's rows (record 0001 §3): lock now, idle lock on, off, off for an hour, suspend
and forget the GPG passphrase, with the idle lock's state marked.

State comes from `lockscreen status --json`: `{"state": "armed" | "paused" | "not running",
"until": "<ISO time>" | null}`, `until` being when a timed pause ends. Unreadable, no row is
marked and "Idle lock on" runs `lockscreen hook-enable`.
"""

from __future__ import annotations

import json
from datetime import datetime

from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.common import procs

LOCK = "\U000f033e"  # md-lock
ON = "\U000f097f"  # md-lock_clock
OFF = "\U000f1671"  # md-lock_off
TIMED = "\U000f051f"  # md-timer_sand
SUSPEND = "\U000f0904"  # md-power_sleep
FORGET = "\U000f030a"  # md-key_remove

STATES = ("armed", "paused", "not running")


def status() -> tuple[str | None, datetime | None, bool]:
    """The idle lock's state (None when unreadable), when a timed pause ends, and whether a
    timed pause runs (true even when its end time can't be parsed)."""
    out = procs.query(["lockscreen", "status", "--json"], timeout=providers.TIMEOUT)
    try:
        data = json.loads(out) if out else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("state") not in STATES:
        return None, None, False
    state, until = str(data["state"]), data.get("until")
    if state != "paused" or until is None:
        return state, None, False
    try:
        end = datetime.fromisoformat(until) if isinstance(until, str) else None
    except ValueError:
        end = None
    return state, end, True


def rows() -> list[Row]:
    state, end, timed = status()
    if state == "not running":
        on = Row(ON, "Idle lock on (start it)", ["lockscreen", "hook-init"])
    else:
        on = Row(ON, "Idle lock on", ["lockscreen", "hook-enable"], current=state == "armed")
    # A naive time (no offset) is already local; astimezone() treats it so.
    timed_label = (
        f"Idle lock off until {end.astimezone():%H:%M}" if end else "Idle lock off for 1 hour"
    )
    return [
        Row(LOCK, "Lock now", ["lockscreen", "activate"]),
        on,
        Row(
            OFF,
            "Idle lock off",
            ["lockscreen", "hook-disable"],
            current=state == "paused" and not timed,
        ),
        Row(TIMED, timed_label, ["lockscreen", "hook-disable", "1h"], current=timed),
        Row(SUSPEND, "Suspend", ["power", "suspend"]),
        Row(FORGET, "Forget GPG passphrase", ["lockscreen", "forget-passphrase"]),
    ]

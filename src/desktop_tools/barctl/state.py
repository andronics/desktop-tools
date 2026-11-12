"""Module states and settings: what they hold and where they live (dotfiles record 0003 §B2-B3).

A module's state is one JSON object, the same whether barctl's own source or an outside pusher
wrote it:

    tier         unavailable | idle | active | alert
    glyph        the icon
    label        text beside or instead of it
    count        a number shown after the glyph when above 0
    detail       a longer line for people (status, show), never on the bar
    target       what a click acts on (the shown player, the sink)
    segments     cells of a module made of several, each {id, tier, glyph, label, alert_until,
                 underline}; underline (true) marks one, as crew marks the coordinator shown
    alert_until  epoch seconds: until then the module (or a segment) blinks to urgent
    expires      epoch seconds: past it the state is stale (push --ttl) and shows unavailable
    progress     a track's place (record 0003 §5): {position, length, rate, at, playing}, in
                 seconds (at in epoch seconds; length null when unknown), for the capsule's line
    accent       `#rrggbb`: the art's colour for the capsule's line and icon (accent = "art")
    label_since  epoch seconds: when the label last changed, for the capsule's scroll (a source
                 keeps it; a pusher's capsule scrolls from `updated`)
    output       the output segment's numbers (record 0003 §10): {volume, battery}, the default
                 sink's volume in percent and its Bluetooth battery (null when BlueZ gives none)
    notice       a short line the output segment shows in place of its name (`<name>
                 connected`), until `notice_until` (epoch seconds)
    status_at    epoch seconds: when the shown player's status last changed, or another player
                 became the shown one (record 0005 phase B: the capsule's fade clock)
    kind         `spoken` (a podcast or audiobook, record 0005 phase B) or empty: the player
                 menu's skip step and speed row
    source       who wrote it
    updated      epoch seconds

States live in `$XDG_RUNTIME_DIR/barctl/modules/<module>.json` (`$BARCTL_RUNTIME_DIR` for tests),
written whole and renamed into place, so a render never reads half of one; the runtime folder is
emptied at logout, so yesterday's state can't show as today's. Settings (disabled modules) live
in `$XDG_STATE_HOME/desktop-tools/barctl/settings.json` (`$BARCTL_SETTINGS_DIR`), which survives
logouts and is not the zsh controller's `~/.local/state/barctl`, left as it was for a rollback.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from desktop_tools.common import paths

TIERS = ("unavailable", "idle", "active", "alert")
ROLES = {"unavailable": "dim", "idle": "fg_dim", "active": "accent", "alert": "urgent"}
FIELDS = (
    "tier",
    "glyph",
    "label",
    "count",
    "detail",
    "target",
    "segments",
    "alert_until",
    "progress",
    "accent",
    "output",
    "notice",
    "notice_until",
    "status_at",
    "kind",
)
KINDS = ("", "spoken")
PROGRESS_FIELDS = ("position", "length", "rate", "at", "playing")
VOLUME_MAX = 1000  # percent: pulse allows past 100 (153 is the usual top); past this, a mistake
RATE_MAX = 16.0  # MPRIS lets a player say any rate; past this it is a mistake, not a speed
SEGMENT_FIELDS = ("id", "tier", "glyph", "label", "alert_until", "underline")
BLINK = 0.5  # seconds per half of a blink

State = dict[str, Any]


class StateError(ValueError):
    """A pushed state barctl can't take."""


def runtime() -> Path:
    explicit = os.environ.get("BARCTL_RUNTIME_DIR")
    return Path(explicit) if explicit else paths.runtime_dir() / "barctl"


def settings_dir() -> Path:
    explicit = os.environ.get("BARCTL_SETTINGS_DIR")
    return Path(explicit) if explicit else paths.state_home() / "desktop-tools" / "barctl"


def modules_dir() -> Path:
    return runtime() / "modules"


def state_path(module: str) -> Path:
    return modules_dir() / f"{module}.json"


def read(module: str) -> State | None:
    try:
        with open(state_path(module), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write(module: str, state: State) -> None:
    folder = modules_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = folder / f".{module}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, state_path(module))


def clear(module: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        state_path(module).unlink()


def stored() -> list[str]:
    """The modules that have a state file."""
    try:
        names = os.listdir(modules_dir())
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and not n.startswith("."))


def content(state: State | None) -> State:
    """A state without its bookkeeping (updated): equal contents need no write."""
    return {k: v for k, v in (state or {}).items() if k != "updated"}


def _str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise StateError(f"{key} must be text")
    # One line on the bar: polybar reads a hook's output up to the first newline.
    return value.replace("\r", " ").replace("\n", " ")


def _tier(value: object, where: str = "tier") -> str:
    if value not in TIERS:
        raise StateError(f"{where} must be one of {', '.join(TIERS)}")
    return str(value)


def _time(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateError(f"{key} must be epoch seconds")
    return float(value)


def _number(value: object, where: str, low: float, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateError(f"{where} must be a number")
    if value != value or value < low or (high is not None and value > high):  # NaN fails too
        span = f"{low:g} to {high:g}" if high is not None else f"{low:g} or more"
        raise StateError(f"{where} must be {span}")
    return float(value)


def progress(value: object) -> State:
    """A `progress` field, checked (record 0003 §5): any other shape is a StateError."""
    if not isinstance(value, dict):
        raise StateError("progress must be an object")
    length = value.get("length")
    out: State = {
        "position": _number(value.get("position", 0), "progress.position", 0),
        "length": None if length is None else _number(length, "progress.length", 0),
        "rate": _number(value.get("rate", 1.0), "progress.rate", 0, RATE_MAX),
        "at": _number(value.get("at"), "progress.at", 0),
    }
    playing = value.get("playing", False)
    if not isinstance(playing, bool):
        raise StateError("progress.playing must be true or false")
    out["playing"] = playing
    return out


def _whole(value: object, where: str, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high:
        raise StateError(f"{where} must be a whole number, 0 to {high}")
    return value


def output(value: object) -> State:
    """An `output` field, checked (record 0003 §10): any other shape is a StateError."""
    if not isinstance(value, dict):
        raise StateError("output must be an object")
    battery = value.get("battery")
    return {
        "volume": _whole(value.get("volume"), "output.volume", VOLUME_MAX),
        "battery": None if battery is None else _whole(battery, "output.battery", 100),
    }


def notice_on(state: State | None, now: float) -> str | None:
    """The notice the output segment shows now, or None when there is none or it ended."""
    data = state or {}
    text, until = data.get("notice"), data.get("notice_until")
    if not isinstance(text, str) or not text:
        return None
    if isinstance(until, bool) or not isinstance(until, (int, float)) or until <= now:
        return None
    return text


def accent(value: object) -> str:
    """`#` and six hex digits, so no colour can carry a polybar tag."""
    hexdigits = "0123456789abcdefABCDEF"
    if (
        not isinstance(value, str)
        or len(value) != 7
        or value[0] != "#"
        or not all(c in hexdigits for c in value[1:])
    ):
        raise StateError("accent must be # and six hex digits")
    return value.lower()


def validate(data: object) -> State:
    """A whole state from `push --json -`: the known fields, checked; anything else is dropped."""
    from desktop_tools.barctl.modules import valid_segment

    if not isinstance(data, dict):
        raise StateError("a state is a JSON object")
    out: State = {}
    if "tier" in data:
        out["tier"] = _tier(data["tier"])
    for key in ("glyph", "label", "detail", "target", "source", "notice"):
        value = _str(data, key)
        if value is not None:
            out[key] = value
    if "count" in data and data["count"] is not None:
        count = data["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise StateError("count must be a whole number, 0 or more")
        out["count"] = count
    if data.get("alert_until") is not None:
        out["alert_until"] = _time(data["alert_until"], "alert_until")
    if data.get("progress") is not None:
        out["progress"] = progress(data["progress"])
    if data.get("accent") is not None:
        out["accent"] = accent(data["accent"])
    if data.get("output") is not None:
        out["output"] = output(data["output"])
    if data.get("notice_until") is not None:
        out["notice_until"] = _time(data["notice_until"], "notice_until")
    if data.get("status_at") is not None:
        out["status_at"] = _time(data["status_at"], "status_at")
    if data.get("kind") is not None:
        if data["kind"] not in KINDS:
            raise StateError("kind must be spoken or empty")
        if data["kind"]:
            out["kind"] = str(data["kind"])
    if "segments" in data and data["segments"] is not None:
        segs = data["segments"]
        if not isinstance(segs, list):
            raise StateError("segments must be a list")
        clean = []
        seen = set()
        for i, seg in enumerate(segs):
            if not isinstance(seg, dict):
                raise StateError(f"segments[{i}] must be an object")
            sid = seg.get("id")
            if not isinstance(sid, str) or not valid_segment(sid) or sid in seen:
                raise StateError(f"segments[{i}].id must be a unique word ([A-Za-z0-9_.-])")
            seen.add(sid)
            item: State = {"id": sid, "tier": _tier(seg.get("tier", "idle"), f"segments[{i}].tier")}
            for key in ("glyph", "label"):
                value = _str(seg, key)
                if value is not None:
                    item[key] = value
            if seg.get("alert_until") is not None:
                item["alert_until"] = _time(seg["alert_until"], f"segments[{i}].alert_until")
            if "underline" in seg and seg["underline"] is not None:
                if not isinstance(seg["underline"], bool):
                    raise StateError(f"segments[{i}].underline must be true or false")
                if seg["underline"]:
                    item["underline"] = True
            clean.append(item)
        out["segments"] = clean
    return out


def duration(text: str) -> float:
    """Seconds in `90`, `30s`, `5m`, `1h`, `2d` or `1m30s`. Raises ValueError."""
    text = text.strip().lower()
    if not text:
        raise ValueError("empty duration")
    total, number = 0.0, ""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    for c in text:
        if c.isdigit() or c == ".":
            number += c
        elif c in units and number:
            total += float(number) * units[c]
            number = ""
        else:
            raise ValueError(f"not a duration: {text!r} (like 30s, 5m, 1h)")
    if number:
        total += float(number)
    return total


# ---------------------------------------------------------------- settings


def settings_path() -> Path:
    return settings_dir() / "settings.json"


def settings() -> dict[str, Any]:
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def disabled() -> set[str]:
    value = settings().get("disabled", [])
    return {v for v in value if isinstance(v, str)} if isinstance(value, list) else set()


def set_enabled(module: str, enabled: bool) -> bool:
    """Remember a module enabled or disabled. Returns whether that changed anything."""
    data = settings()
    off = disabled()
    before = set(off)
    if enabled:
        off.discard(module)
    else:
        off.add(module)
    if off == before:
        return False
    data["disabled"] = sorted(off)
    folder = settings_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = folder / f".settings.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, settings_path())
    return True


# ---------------------------------------------------------------- the controller's files


def pid_path() -> Path:
    return runtime() / "pid"


def controller() -> tuple[int, float] | None:
    """The running controller's pid and start time, or None."""
    try:
        pid_text, _, since = pid_path().read_text().partition("\n")
        pid = int(pid_text)
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    try:
        started = float(since.strip())
    except ValueError:
        started = 0.0
    return pid, started


def source_health_path(source: str) -> Path:
    return runtime() / "sources" / f"{source}.json"


def source_health(source: str) -> dict[str, Any]:
    try:
        with open(source_health_path(source), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

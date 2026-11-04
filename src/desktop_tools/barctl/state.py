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
FIELDS = ("tier", "glyph", "label", "count", "detail", "target", "segments", "alert_until")
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


def validate(data: object) -> State:
    """A whole state from `push --json -`: the known fields, checked; anything else is dropped."""
    from desktop_tools.barctl.modules import valid_segment

    if not isinstance(data, dict):
        raise StateError("a state is a JSON object")
    out: State = {}
    if "tier" in data:
        out["tier"] = _tier(data["tier"])
    for key in ("glyph", "label", "detail", "target", "source"):
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

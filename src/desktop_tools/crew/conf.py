"""crew's settings and folders, read from the environment on every call so tests can move them.

    CREW_CLASS             crew      the window class of crew's terminals
    CREW_OLD_CLASS         coord     a second class matched until coord's windows have closed
                                     (record 0019 §7); empty matches none
    CREW_ACTORS_DIR        /pool/local/actors   where the coordinators' homes are
    BRAIN_BIN              /mnt/brain/bin       where `meta` is; PATH when it isn't there (systemd
                                     units, polybar and sxhkd may not have the brain's bin)
    CREW_TMUX_SOCKET       unset     another tmux server: a path is -S, a name -L (tests)
    CREW_LAUNCH_TIMEOUT    10        seconds to wait for a window or a lock
    CREW_GUARD_SETTLE      0.2       seconds of quiet after a crew window's last event before
                                     the guard re-docks
    CREW_REGISTRY_MAX_AGE  300       seconds the registry's kept copy is used before meta is
                                     asked again (0: every start)
    CREW_BAR_TTL           86400     seconds a pushed strip holds before barctl shows it stale: a
                                     day, since a coordinator can wait hours for an answer
    CREW_MENU_THEME        unset     the full menu's rofi theme (a name in rofi/themes, or a path);
                                     unset, `crew`, else coord's `coord` until it is renamed
    CREW_CONFIRM_THEME     prompt    the rofi theme of the full menu's second level (the Yes/No
                                     questions are `life.confirm`'s, in `prompt`)

Folders: `$XDG_RUNTIME_DIR/crew/` (each coordinator's activity, the locks) and
`$XDG_STATE_HOME/crew/` (width, side, last shown, the registry's last good copy).
"""

from __future__ import annotations

import os
from pathlib import Path

from desktop_tools.common import paths

OWNER = "desktop-coordinator"
WIDTH_DEFAULT, WIDTH_MIN, WIDTH_MAX, WIDTH_STEP = 1280, 640, 2560, 128
SIDE_DEFAULT = "right"
SIDES = ("left", "right")
NOTIFY_BODY_MAX = 200


def _number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= 0 else default


def window_class() -> str:
    return os.environ.get("CREW_CLASS") or "crew"


def classes() -> tuple[str, ...]:
    """Every class whose windows are crew's: its own, then coord's until the alias goes."""
    old = os.environ.get("CREW_OLD_CLASS", "coord")
    own = window_class()
    return (own, old) if old and old != own else (own,)


def actors_dir() -> Path:
    return Path(os.environ.get("CREW_ACTORS_DIR") or "/pool/local/actors")


def meta() -> str:
    """The brain's `meta`: `$BRAIN_BIN/meta`, else whatever PATH finds."""
    found = Path(os.environ.get("BRAIN_BIN") or "/mnt/brain/bin") / "meta"
    return str(found) if os.access(found, os.X_OK) else "meta"


def tmux() -> list[str]:
    socket = os.environ.get("CREW_TMUX_SOCKET", "")
    if "/" in socket:
        return ["tmux", "-S", socket]
    if socket:
        return ["tmux", "-L", socket]
    return ["tmux"]


def launch_timeout() -> float:
    return _number("CREW_LAUNCH_TIMEOUT", 10.0)


def guard_settle() -> float:
    return _number("CREW_GUARD_SETTLE", 0.2)


def registry_max_age() -> float:
    return _number("CREW_REGISTRY_MAX_AGE", 300.0)


def bar_ttl() -> float:
    return _number("CREW_BAR_TTL", 86400.0)


def menu_themes() -> list[str]:
    explicit = os.environ.get("CREW_MENU_THEME")
    return [explicit] if explicit else ["crew", "coord"]


def confirm_theme() -> str:
    return os.environ.get("CREW_CONFIRM_THEME") or "prompt"


def runtime() -> Path:
    return paths.runtime_dir() / "crew"


def activity_dir() -> Path:
    return runtime() / "state"


def state_dir() -> Path:
    return paths.state_home() / "crew"


def coord_state_dir() -> Path:
    """coord's folder, read once for the one-time copy of width, side and last."""
    return paths.state_home() / "coord"

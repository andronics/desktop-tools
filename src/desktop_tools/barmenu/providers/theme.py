"""The theme menu's rows (record 0001 §2): the scheme picker named after the applied scheme,
wallpapers, the mode not in use, undo, reload and the default.

No row is marked: `theme pick` marks the applied scheme itself, with previews. One query,
`theme current --json`, gives both the scheme's title and the mode.
"""

from __future__ import annotations

import json

from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.common import procs

SCHEME = "\U000f08b5"  # md-palette_swatch
WALLPAPER = "\U000f02f9"  # md-image_multiple
RANDOM = "\U000f076e"  # md-dice_multiple
MODE = "\U000f050e"  # md-theme_light_dark
UNDO = "\U000f054c"  # md-undo
RELOAD = "\U000f0450"  # md-refresh
DEFAULT = "\U000f02dc"  # md-home


def current() -> tuple[str | None, str | None]:
    """The applied scheme's title and its mode (`dark` or `light`); None for what can't be read."""
    out = procs.query(["theme", "current", "--json"], timeout=providers.TIMEOUT)
    try:
        data = json.loads(out) if out else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return None, None
    title, mode = data.get("title"), data.get("mode")
    return (
        title.strip() if isinstance(title, str) and title.strip() else None,
        mode if mode in ("dark", "light") else None,
    )


def rows() -> list[Row]:
    title, mode = current()
    if mode == "dark":
        toggle = "Light mode"
    elif mode == "light":
        toggle = "Dark mode"
    else:
        toggle = "Toggle dark/light"
    return [
        Row(SCHEME, f"Scheme: {title}…" if title else "Scheme…", ["theme", "pick"]),
        Row(WALLPAPER, "Wallpaper…", ["theme", "pick", "wallpapers"]),
        Row(RANDOM, "Random wallpaper", ["theme", "random"]),
        Row(MODE, toggle, ["theme", "mode", "toggle"]),
        Row(UNDO, "Undo", ["theme", "undo"]),
        Row(RELOAD, "Reload", ["theme", "reload"]),
        Row(DEFAULT, "Default", ["theme", "apply", "default"]),
    ]

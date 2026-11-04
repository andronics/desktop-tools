"""The current theme's roles, read from the generated theme.zsh (the dotfiles' theming design).

The same lookup as `theme-roles` in the dotfiles' dotlib `_theme`: a key is looked up in
THEME_ROLE, then THEME_PALETTE, THEME_SIZE and THEME_METRIC of
`${THEME_STATE_DIR:-$XDG_STATE_HOME/theme}/current/theme.zsh`. No colour is written in this
repo: with no theme there are no roles, and callers draw without colour.

Parsed by hand, not with `re`: this runs on every bar redraw.
"""

from __future__ import annotations

import os
from pathlib import Path

from desktop_tools.common import paths

TABLES = ("THEME_ROLE", "THEME_PALETTE", "THEME_SIZE", "THEME_METRIC")


def theme_file() -> Path:
    state = os.environ.get("THEME_STATE_DIR") or str(paths.state_home() / "theme")
    return Path(state) / "current" / "theme.zsh"


def parse(text: str) -> dict[str, dict[str, str]]:
    """Every `typeset -gA NAME=( [key]='value' ... )` table in a generated theme.zsh."""
    tables: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("typeset -gA ") and line.endswith("=("):
            current = tables.setdefault(line[len("typeset -gA ") : -2], {})
        elif line == ")":
            current = None
        elif current is not None and line.startswith("[") and "]=" in line:
            key, _, value = line[1:].partition("]=")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            current[key] = value
    return tables


def roles(wanted: dict[str, str], path: Path | None = None) -> dict[str, str]:
    """key -> value for each `key: role` in wanted that the theme has; {} with no theme."""
    try:
        text = (path or theme_file()).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    tables = parse(text)
    out: dict[str, str] = {}
    for key, role in wanted.items():
        for table in TABLES:
            value = tables.get(table, {}).get(role)
            if value:
                out[key] = value
                break
    return out

"""Menu providers: a Python function per menu that gives its rows when the menu opens
(`provider = "<name>"` in menus.toml, record 0001 §1).

A provider reads state only through read-only queries (`procs.query`, TIMEOUT seconds). When a
query fails or times out it still returns its rows, unmarked and with the labels that name no
state, so the menu always opens.

The provider modules are imported when a menu opens, not when menus.toml is read, so loading
the menus (and `barmenu --help`) never runs a query.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desktop_tools.barmenu.menus import Row

NAMES = ("lock", "player", "players", "tessera", "theme")
TIMEOUT = 2.0  # seconds a provider's query may take before its menu opens without the state


def rows(name: str) -> list[Row]:
    """The rows the named provider gives now. Raises KeyError for a name not in NAMES."""
    if name not in NAMES:
        raise KeyError(name)
    module = importlib.import_module(f"{__name__}.{name}")
    found: list[Row] = module.rows()
    return found

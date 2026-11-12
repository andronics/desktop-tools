"""The default-printer picker (record 0004 §3): one row per queue, the default marked; picking
one runs `devices printer default <queue>` (the user's default, `lpoptions -d`)."""

from __future__ import annotations

from desktop_tools.barmenu.menus import Row
from desktop_tools.barmenu.providers.printer import PRINTER, read


def rows() -> list[Row]:
    r = read()
    if r is None:
        return [Row(PRINTER, "CUPS is not running", [])]
    return [
        Row(PRINTER, q.name, ["devices", "printer", "default", q.name], current=q.name == r.default)
        for q in r.queues
    ]

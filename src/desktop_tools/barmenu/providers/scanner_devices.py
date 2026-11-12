"""The scanner picker (record 0004 §3), with two or more scanners found: one row per scanner,
the chosen marked (`devices scanner pick <device>`), then Simple Scan."""

from __future__ import annotations

from desktop_tools.barmenu.menus import Row
from desktop_tools.barmenu.providers.scanner import PREVIEW, SCANNER, chosen
from desktop_tools.devices import sane


def rows() -> list[Row]:
    current = chosen()
    out = [
        Row(
            SCANNER,
            s.model,
            ["devices", "scanner", "pick", s.device],
            current=current is not None and s.device == current.device,
        )
        for s in sane.known()
    ]
    out.append(Row(SCANNER, "Find scanners…", ["devices", "scanner", "find"]))
    out.append(Row(PREVIEW, "Preview in Simple Scan", ["simple-scan"]))
    return out

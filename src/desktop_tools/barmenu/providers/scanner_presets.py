"""The scan presets picker (record 0004 §3): one row per preset, the chosen marked, then the
formats (the chosen marked). A preset sets the format too; a format picked afterwards overrides
it until another preset is picked."""

from __future__ import annotations

from desktop_tools.barmenu.menus import Row
from desktop_tools.devices import prefs

PRESET = "\U000f062e"  # md-tune
FORMAT = "\U000f0226"  # md-file_pdf_box


def rows() -> list[Row]:
    chosen, fmt = prefs.chosen_preset(), prefs.chosen_format()
    out = [
        Row(
            PRESET,
            f"{p.name} ({p.summary})",
            ["devices", "scan", "set", "--preset", p.name],
            current=p.name == chosen.name,
        )
        for p in prefs.PRESETS
    ]
    out += [
        Row(
            FORMAT,
            f"Format: {f.upper()}",
            ["devices", "scan", "set", "--format", f],
            current=f == fmt,
        )
        for f in prefs.FORMATS
    ]
    return out

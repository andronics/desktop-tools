"""The scan folder picker (record 0004 §3): Documents/Scans (the default), Desktop, Downloads,
and `Choose a folder…` (zenity's picker); the chosen one marked. Labels never show a full path."""

from __future__ import annotations

from desktop_tools.barmenu.menus import Row
from desktop_tools.devices import prefs

FOLDER = "\U000f0770"  # md-folder_open


def rows() -> list[Row]:
    chosen = prefs.chosen_folder()
    fixed = prefs.folders()
    out = [
        Row(FOLDER, label, ["devices", "scan", "set", "--to", str(path)], current=path == chosen)
        for label, path in fixed
    ]
    if chosen not in {path for _l, path in fixed}:
        out.append(Row(FOLDER, prefs.shown(chosen), [], current=True))
    out.append(Row(FOLDER, "Choose a folder…", ["devices", "scan", "set", "--choose"]))
    return out

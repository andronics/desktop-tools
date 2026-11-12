"""The printer menu's rows (record 0004 §3): the queue, pause or resume, the default (with two or
more queues), a test page, the printer's state, and its settings.

One IPP read when it opens (the local cupsd, providers.TIMEOUT seconds): the queues, the
default and its jobs. Whether a network printer is reachable is what barctl's printer source
last showed (the menu probes nothing). Unreadable, every row still shows, with labels that name
no state. Every action row runs `devices`, where the confirm, the words and the agent rule are;
the test page asks Yes/No there.
"""

from __future__ import annotations

from desktop_tools.barctl import state as st
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.devices import cups, ipp

MODULE = "printer"
QUEUE = "\U000f0279"  # md-format_list_bulleted
PAUSE = "\U000f03e4"  # md-pause
PLAY = "\U000f040a"  # md-play
STAR = "\U000f04ce"  # md-star
TEST = "\U000f0219"  # md-file_document
LAN = "\U000f0317"  # md-lan
PRINTER = "\U000f042a"  # md-printer
SETTINGS = "\U000f0707"  # md-printer_settings
DEVICES = ["devices", "printer"]


def read() -> cups.Reading | None:
    try:
        return cups.read(ipp.Client(timeout=providers.TIMEOUT))
    except (cups.CupsDown, ipp.IppError):
        return None


def away() -> bool:
    data = st.read(MODULE) or {}
    return data.get("tier") == "unavailable" and data.get("label") == "away"


def jobs_label(n: int) -> str:
    return "Queue: empty…" if n == 0 else f"Queue: {n} job{'s' if n != 1 else ''}…"


def rows() -> list[Row]:
    r = read()
    q = r.queue if r is not None else None
    out = [Row(QUEUE, jobs_label(len(r.jobs)) if r else "Queue…", ["barmenu", "printer-queue"])]
    if q is None:
        out.append(Row(PAUSE, "Pause or resume…", ["system-config-printer"]))
    elif q.state == cups.STOPPED:
        out.append(Row(PLAY, "Resume printing", [*DEVICES, "resume"]))
    else:
        out.append(Row(PAUSE, "Pause printing", [*DEVICES, "pause"]))
    if r is not None and q is not None and len(r.queues) > 1:
        out.append(Row(STAR, f"Default: {q.name}…", ["barmenu", "printer-default"]))
    out.append(Row(TEST, "Print a test page…", [*DEVICES, "test-page"]))
    if q is not None:
        low = cups.supplies(q)[1]
        if q.network:
            label = f"Network printer: {'away' if away() else 'reachable'}"
            glyph = LAN
        else:
            label, glyph = "USB printer", PRINTER
        if low:
            label += f" (ink low: {', '.join(low)})"
        out.append(Row(glyph, label, [*DEVICES, "status", "--notify"]))
    else:
        out.append(Row(PRINTER, "Printer state…", [*DEVICES, "status", "--notify"]))
    out.append(Row(SETTINGS, "Printer settings", ["system-config-printer"]))
    return out

"""The scanner menu's rows (record 0004 §3), eight at most: scan from the feeder (both sides,
when the scanner offers a duplex source), from the flatbed, the preset, the folder, Simple Scan
(or the scanner picker, with two or more), and the last scan's path and file.

It opens no device: the sources come from the cached `scanimage -A` listing (unknown before the
first scan, when the feeder and flatbed rows both show), the feeder's state from one eSCL status
read (providers.TIMEOUT, one try) or what barctl's scanner source last showed. Not found, rows
1-3 become one `Find scanners…` row. Every scan row runs `devices scan`; no label shows a full
path.
"""

from __future__ import annotations

from desktop_tools.barctl import state as st
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.menus import Row
from desktop_tools.devices import escl, prefs, sane, scan

MODULE = "scanner"
FEEDER = "\U000f011d"  # md-tray_arrow_up
DUPLEX = "\U000f1517"  # md-file_document_multiple
FLATBED = "\U000f02eb"  # md-image_area
PRESET = "\U000f062e"  # md-tune
FOLDER = "\U000f0770"  # md-folder_open
PREVIEW = "\U000f0208"  # md-eye
COPY = "\U000f018f"  # md-content_copy
OPEN = "\U000f0226"  # md-file_pdf_box
SCANNER_OFF = "\U000f090a"  # md-scanner_off
SCANNER = "\U000f06ab"  # md-scanner
NOT_FOUND = ("not found", "away", "no scanner")


def feeder(device: sane.Scanner | None) -> str:
    """loaded, empty or "" (unknown)."""
    if device is not None and device.instance:
        base = escl.base_from_conf(device.instance)
        if base:
            found = escl.status(base, timeout=providers.TIMEOUT, attempts=1)
            if found is not None:
                return found.feeder if found.feeder in ("loaded", "empty") else ""
    label = str((st.read(MODULE) or {}).get("label") or "")
    return "loaded" if label == "feeder loaded" else ""


def chosen() -> sane.Scanner | None:
    name = scan.scanner_name_only()
    if not name:
        return None
    return next((s for s in sane.known() if s.device == name), sane.Scanner(name, name))


def preset_label() -> str:
    p = prefs.chosen_preset()
    fmt = prefs.chosen_format()
    summary = p.summary if fmt == p.format else p.summary.rsplit(", ", 1)[0] + f", {fmt.upper()}"
    return f"Preset: {p.name} ({summary})…"


def rows() -> list[Row]:
    device = chosen()
    shown = str((st.read(MODULE) or {}).get("label") or "")
    known = sane.known()
    out: list[Row] = []
    if device is None or shown in NOT_FOUND:
        out.append(Row(SCANNER_OFF, "Find scanners…", ["devices", "scanner", "find"]))
    else:
        options = sane.cached_options(device.device)
        sources = options.sources if options is not None else ()
        state = feeder(device)
        if not sources or sane.pick_source(sources, "feeder"):
            extra = f" ({state})" if state else ""
            out.append(Row(FEEDER, f"Scan from feeder{extra}", ["devices", "scan", "feeder"]))
        if sources and sane.pick_source(sources, "duplex"):
            out.append(Row(DUPLEX, "Scan from feeder, both sides", ["devices", "scan", "duplex"]))
        if not sources or sane.pick_source(sources, "flatbed"):
            out.append(Row(FLATBED, "Scan from flatbed", ["devices", "scan", "flatbed"]))
    out.append(Row(PRESET, preset_label(), ["barmenu", "scanner-presets"]))
    folder = prefs.shown(prefs.chosen_folder())
    out.append(Row(FOLDER, f"Save to: {folder}…", ["barmenu", "scanner-folders"]))
    if len(known) >= 2:
        model = device.model if device is not None else "…"
        out.append(Row(SCANNER, f"Scanner: {model}…", ["barmenu", "scanner-devices"]))
    else:
        out.append(Row(PREVIEW, "Preview in Simple Scan", ["simple-scan"]))
    if scan.last() is not None:
        out.append(Row(COPY, "Copy last scan's path", ["devices", "scan", "copy-last"]))
        out.append(Row(OPEN, "Open last scan", ["devices", "scan", "open-last"]))
    return out

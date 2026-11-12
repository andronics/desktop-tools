"""The printer and scanner menus' rows (record 0004 §3): each state's rows and marks, the menu
unreadable, one queue (no default row), 0, 1 and 7 jobs, the duplex row only with a duplex
source, not found, two scanners, and the pickers' marks."""

from __future__ import annotations

from pathlib import Path

import pytest

from desktop_tools.barctl import state as st
from desktop_tools.barmenu import menus as bm
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.providers import (
    printer,
    printer_default,
    printer_queue,
    scanner,
    scanner_devices,
    scanner_folders,
    scanner_presets,
)
from desktop_tools.devices import cups, prefs, store
from tests.devices_fakes import FakeCups, job_attrs, printer_attrs

DEVICE = "airscan:e0:Office Scanner"


def labels(rows: list[bm.Row]) -> list[str]:
    return [r.label for r in rows]


def commands(rows: list[bm.Row]) -> list[object]:
    return [r.command for r in rows]


# ---------------------------------------------------------------- printer


def test_printer_rows_one_queue(cupsd: FakeCups) -> None:
    rows = printer.rows()
    assert labels(rows) == [
        "Queue: empty…",
        "Pause printing",
        "Print a test page…",
        "Network printer: reachable",
        "Printer settings",
    ]
    assert commands(rows) == [
        ["barmenu", "printer-queue"],
        ["devices", "printer", "pause"],
        ["devices", "printer", "test-page"],
        ["devices", "printer", "status", "--notify"],
        ["system-config-printer"],
    ]


def test_printer_rows_paused_two_queues_low_ink_away(cupsd: FakeCups) -> None:
    cupsd.printers = [
        printer_attrs("Office", state=cups.STOPPED, levels=(44, 10, 69, 72)),
        printer_attrs("Home", uri="usb://x"),
    ]
    cupsd.jobs["Office"] = [job_attrs(1)]
    st.write("printer", {"tier": "unavailable", "label": "away"})
    rows = printer.rows()
    assert labels(rows) == [
        "Queue: 1 job…",
        "Resume printing",
        "Default: Office…",
        "Print a test page…",
        "Network printer: away (ink low: cyan)",
        "Printer settings",
    ]
    assert rows[1].command == ["devices", "printer", "resume"]


def test_printer_rows_local(cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("Office", uri="usb://x")]
    assert labels(printer.rows())[3] == "USB printer"


def test_printer_rows_unreadable() -> None:
    rows = printer.rows()
    assert labels(rows) == [
        "Queue…",
        "Pause or resume…",
        "Print a test page…",
        "Printer state…",
        "Printer settings",
    ]
    assert not any(r.current for r in rows)


@pytest.mark.parametrize("n", [0, 1, 7])
def test_queue_rows(cupsd: FakeCups, n: int) -> None:
    import getpass

    me = getpass.getuser()
    cupsd.jobs["Office"] = [job_attrs(i, user=me, created=i) for i in range(1, n + 1)]
    rows = printer_queue.rows()
    if n == 0:
        assert labels(rows) == ["No jobs"] and rows[0].command == []
        return
    if n == 1:
        assert labels(rows)[0].startswith("#1  waiting  ")  # number, state, age
        assert rows[0].command == ["devices", "printer", "cancel", "1"]
        return
    assert labels(rows)[0].startswith("#7")  # newest first
    assert len(rows) == 6 + 2 and labels(rows)[6] == "…and 1 more"
    assert rows[-1].label == "Cancel all my jobs (7)…"
    assert rows[-1].command == ["devices", "printer", "cancel", "--all"]


def test_queue_rows_others_jobs_have_no_cancel(cupsd: FakeCups) -> None:
    cupsd.jobs["Office"] = [job_attrs(5, cups.JOB_PROCESSING, user="someone-else")]
    (row,) = printer_queue.rows()
    assert row.label == "#5  printing" and row.command == []


def test_queue_rows_unreadable() -> None:
    assert labels(printer_queue.rows()) == ["CUPS is not running"]
    assert labels(printer_default.rows()) == ["CUPS is not running"]


def test_default_rows(cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("Office"), printer_attrs("Home")]
    rows = printer_default.rows()
    assert [(r.label, r.current) for r in rows] == [("Office", True), ("Home", False)]
    assert rows[1].command == ["devices", "printer", "default", "Home"]


# ---------------------------------------------------------------- scanner


def known(*devices: str) -> None:
    store.write(
        store.scanners_path(),
        {"at": 1.0, "scanners": [{"device": d, "model": d.split(":")[-1]} for d in devices]},
    )


def test_scanner_rows_not_found() -> None:
    rows = scanner.rows()
    assert labels(rows) == [
        "Find scanners…",
        "Preset: Document (300 dpi, grey, PDF)…",
        "Save to: Documents/Scans…",
        "Preview in Simple Scan",
    ]
    assert rows[0].command == ["devices", "scanner", "find"]


def test_scanner_rows_found_unknown_sources() -> None:
    known(DEVICE)
    assert labels(scanner.rows())[:2] == ["Scan from feeder", "Scan from flatbed"]


def test_scanner_rows_duplex_loaded_and_last(tmp_path: Path) -> None:
    known(DEVICE)
    store.write(store.options_path(), {DEVICE: {"sources": ["Flatbed", "ADF", "ADF Duplex"]}})
    st.write("scanner", {"tier": "idle", "label": "feeder loaded"})
    (tmp_path / "s.pdf").write_text("")
    store.write(store.last_path(), {"path": str(tmp_path / "s.pdf")})
    rows = scanner.rows()
    assert labels(rows) == [
        "Scan from feeder (loaded)",
        "Scan from feeder, both sides",
        "Scan from flatbed",
        "Preset: Document (300 dpi, grey, PDF)…",
        "Save to: Documents/Scans…",
        "Preview in Simple Scan",
        "Copy last scan's path",
        "Open last scan",
    ]
    assert len(rows) <= 8
    assert rows[1].command == ["devices", "scan", "duplex"]


def test_scanner_rows_no_duplex_and_away() -> None:
    known(DEVICE)
    store.write(store.options_path(), {DEVICE: {"sources": ["Flatbed", "ADF"]}})
    assert "Scan from feeder, both sides" not in labels(scanner.rows())
    st.write("scanner", {"tier": "unavailable", "label": "away"})
    assert labels(scanner.rows())[0] == "Find scanners…"


def test_scanner_rows_two_scanners() -> None:
    known(DEVICE, "epsonds:libusb:001:004")
    rows = scanner.rows()
    assert "Scanner: Office Scanner…" in labels(rows)
    assert "Preview in Simple Scan" not in labels(rows)
    picks = scanner_devices.rows()
    assert [(r.label, r.current) for r in picks[:2]] == [
        ("Office Scanner", True),
        ("004", False),
    ]
    assert picks[1].command == ["devices", "scanner", "pick", "epsonds:libusb:001:004"]
    assert picks[-1].label == "Preview in Simple Scan"


def test_scanner_feeder_state_from_escl(monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop_tools.devices import escl

    known(DEVICE)
    monkeypatch.setattr(escl, "base_from_conf", lambda name, conf=None: "http://s.example/eSCL")
    monkeypatch.setattr(escl, "status", lambda *a, **k: escl.Status("Idle", "ScannerAdfEmpty"))
    assert labels(scanner.rows())[0] == "Scan from feeder (empty)"


def test_preset_and_format_rows() -> None:
    rows = scanner_presets.rows()
    assert [r.label for r in rows if r.current] == [
        "Document (300 dpi, grey, PDF)",
        "Format: PDF",
    ]
    prefs.remember(preset="Photo")
    prefs.remember(format="jpeg")
    rows = scanner_presets.rows()
    assert [r.label for r in rows if r.current] == [
        "Photo (600 dpi, colour, PNG)",
        "Format: JPEG",
    ]
    assert scanner.preset_label() == "Preset: Photo (600 dpi, colour, JPEG)…"
    assert rows[0].command == ["devices", "scan", "set", "--preset", "Document"]


def test_folder_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    rows = scanner_folders.rows()
    assert [(r.label, r.current) for r in rows] == [
        ("Documents/Scans", True),
        ("Desktop", False),
        ("Downloads", False),
        ("Choose a folder…", False),
    ]
    prefs.remember(folder="/srv/archive/scans")
    rows = scanner_folders.rows()
    assert [r.label for r in rows if r.current] == ["archive/scans"]
    assert all("/srv" not in r.label for r in rows)


def test_folder_from_user_dirs_and_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolate: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (isolate / "xdg" / "config" / "user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Docs"\n')
    assert prefs.default_folder() == tmp_path / "Docs" / "Scans"
    monkeypatch.setenv("DESKTOP_TOOLS_SCAN_DIR", str(tmp_path / "elsewhere"))
    assert prefs.default_folder() == tmp_path / "elsewhere"
    monkeypatch.setenv("DESKTOP_TOOLS_SCANNER", "airscan:e9:Set")
    assert prefs.chosen_scanner() == "airscan:e9:Set"
    assert prefs.shown(Path("/")) == "/"
    assert prefs.shown(tmp_path) == "Home"


def test_the_menus_name_their_providers() -> None:
    menus = bm.load()
    for name in ("printer", "printer-queue", "printer-default", "scanner"):
        assert menus[name].provider in providers.NAMES
    for name in ("scanner-presets", "scanner-folders", "scanner-devices"):
        assert menus[name].provider is not None

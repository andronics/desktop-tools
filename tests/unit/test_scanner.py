"""The scanner's readers and barctl's scanner source (record 0004 §1-2): `scanimage -L` and `-A`
from three backends, eSCL ScannerStatus fixtures, airscan.conf, DNS-SD lines, §1's scanner table,
the 10-minute cap on an unadvertised scanner's status, and progress only while a scan's lock is
held."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.sources import scanner as source_mod
from desktop_tools.barctl.sources.scanner import ScannerSource, view
from desktop_tools.barctl.store import Writer
from desktop_tools.devices import escl, mdns, prefs, sane, scan, store
from tests.devices_fakes import (
    SCANIMAGE_A_AIRSCAN,
    SCANIMAGE_A_EPSON,
    SCANIMAGE_A_FUJITSU,
    avahi_resolved,
    escl_status,
    wait_for,
)

DEVICE = "airscan:e0:Office Scanner"
REAL_RESOLVES = mdns.resolves  # kept before conftest's no_device_sockets stubs it

# ---------------------------------------------------------------- sane


def test_scanimage_list_without_addresses() -> None:
    text = (
        "device `airscan:e0:Office Scanner' is a eSCL Office Scanner ip=192.0.2.9\n"
        "device `epsonds:libusb:001:004' is a Epson DS-530 ESC/I-2\n"
        "noise\n"
    )
    found = sane.parse_list(text)
    assert [(s.device, s.model) for s in found] == [
        (DEVICE, "Office Scanner"),
        ("epsonds:libusb:001:004", "Epson DS-530 ESC/I-2"),
    ]
    assert found[0].network and found[0].instance == "Office Scanner"
    assert not found[1].network and found[1].instance == ""


@pytest.mark.parametrize(
    ("text", "feeder", "duplex", "flatbed", "modes"),
    [
        (SCANIMAGE_A_AIRSCAN, "ADF", "ADF Duplex", "Flatbed", ("Color", "Gray", "Lineart")),
        (SCANIMAGE_A_EPSON, "ADF Front", "ADF Duplex", "Flatbed", ("Color", "Gray", "Lineart")),
        (SCANIMAGE_A_FUJITSU, "ADF Front", "ADF Duplex", None, ("Color", "Gray", "Lineart")),
    ],
)
def test_sources_and_modes_from_three_backends(
    text: str, feeder: str, duplex: str, flatbed: str | None, modes: tuple[str, ...]
) -> None:
    options = sane.parse_options(text)
    assert sane.pick_source(options.sources, "feeder") == feeder
    assert sane.pick_source(options.sources, "duplex") == duplex
    assert sane.pick_source(options.sources, "flatbed") == flatbed
    got = tuple(sane.pick_mode(options.modes, k) for k in ("colour", "grey", "lineart"))
    assert got == modes
    assert 300 in options.resolutions


def test_find_and_options_are_cached(commands: Callable[..., Path]) -> None:
    log = commands(
        scanimage=(
            "if '-L' in args:\n"
            '    print("device `airscan:e0:Office Scanner\' is a eSCL Office Scanner "\n'
            '          "ip=192.0.2.9")\n'
            f"else:\n    print({SCANIMAGE_A_AIRSCAN!r})"
        )
    )
    assert sane.known() == []
    found = sane.find()
    assert found is not None and found[0].device == DEVICE
    assert sane.known() == found and sane.found_at() > 0
    assert "192.0.2.9" not in store.scanners_path().read_text()
    first = sane.options(DEVICE)
    again = sane.options(DEVICE)
    assert first == again and first is not None and "ADF Duplex" in first.sources
    runs = [c for c in json.loads("[" + ",".join(log.read_text().splitlines()) + "]")]
    assert [c[1:] for c in runs] == [["-L"], ["-d", DEVICE, "-A"]]  # -A once: cached
    sane.find()
    assert sane.cached_options(DEVICE) is None  # found again: read again


def test_find_without_sane() -> None:
    """scanimage is a tripwire here: it fails, which reads as SANE missing."""
    assert sane.find() is None
    assert sane.options(DEVICE) is None
    from tests.fakes import tripwires

    trip = Path(str(store.runtime())).parents[3] / "tripwires.log"
    if trip.exists():
        trip.unlink()  # this test reached the tripwire on purpose
    assert tripwires(trip.parent) == []


# ---------------------------------------------------------------- escl


@pytest.mark.parametrize(
    ("state", "adf", "feeder"),
    [
        ("Idle", "", ""),
        ("Processing", "", ""),
        ("Idle", "ScannerAdfLoaded", "loaded"),
        ("Idle", "ScannerAdfEmpty", "empty"),
        ("Idle", "ScannerAdfJam", "jam"),
        ("Idle", "ScannerAdfDoorOpen", "door"),
        ("Down", "", ""),
    ],
)
def test_escl_status_fixtures(state: str, adf: str, feeder: str) -> None:
    found = escl.parse(escl_status(state, adf))
    assert found is not None and found.state == state and found.feeder == feeder


def test_escl_not_a_status() -> None:
    assert escl.parse("<x/>") is None
    assert escl.parse("not xml") is None


def test_airscan_conf(tmp_path: Path) -> None:
    conf = tmp_path / "airscan.conf"
    conf.write_text(
        "[options]\n"
        '"Office Scanner" = http://192.0.2.1/eSCL/\n'
        "[devices]\n"
        "; a comment\n"
        '"Office Scanner" = http://192.0.2.9/eSCL/, escl\n'
        '"WSD One" = http://192.0.2.8/WSD, wsd\n'
    )
    assert escl.base_from_conf("Office Scanner", (conf,)) == "http://192.0.2.9/eSCL"
    assert escl.base_from_conf("WSD One", (conf,)) == ""
    assert escl.base_from_conf("Other", (conf, tmp_path / "missing")) == ""
    assert escl.base_from_txt("192.0.2.9", 80, "eSCL") == "http://192.0.2.9:80/eSCL"
    assert escl.base_from_txt("fe80::1", 443, "", secure=True) == "https://[fe80::1]:443"
    assert escl.host_of("http://Scanner.Example/eSCL") == "scanner.example"


def test_escl_status_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([None, escl_status("Idle", "ScannerAdfLoaded").encode()])
    monkeypatch.setattr(escl, "_get", lambda base, timeout: next(answers))
    found = escl.status("http://scanner.example/eSCL", retry=0)
    assert found is not None and found.feeder == "loaded"
    monkeypatch.setattr(escl, "_get", lambda base, timeout: None)
    assert escl.status("http://scanner.example/eSCL", retry=0) is None
    assert escl._get("ftp://x/eSCL", 1) is None  # only http(s)


# ---------------------------------------------------------------- mdns


def test_avahi_lines() -> None:
    changes: list[int] = []
    b = mdns.Browser(mdns.SCANNER_TYPES, lambda: changes.append(1))
    assert not b.line("+;eth0;IPv4;Office\\032Scanner;_uscan._tcp;local")
    resolved = avahi_resolved(
        "Office\\032Scanner", "_uscan._tcp", "office.local.", "192.0.2.9", 80, '"rs=eSCL" "ty=X"'
    )
    assert b.line(resolved)
    assert not b.line(resolved)  # the same again: no change
    (s,) = b.named("Office Scanner")
    assert (s.host, s.port, s.txt_value("rs")) == ("office.local", 80, "eSCL")
    assert b.has_host("office.local") and b.has_host("192.0.2.9") and not b.has_host("")
    assert b.line("-;eth0;IPv4;Office\\032Scanner;_uscan._tcp;local")
    assert b.all() == [] and not b.line("garbage") and not b.line("=;short")
    assert mdns.unescape("a\\059b") == "a;b"


def test_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def fail(*a: object) -> object:
        raise socket.gaierror("no")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert not REAL_RESOLVES("nowhere.example")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a: [1])
    assert REAL_RESOLVES("somewhere.example")


# ---------------------------------------------------------------- the scanner table (§1)

S = sane.Scanner(DEVICE, "Office Scanner")


def v(**kw: object) -> tuple[str, str, str, int]:
    base: dict[str, object] = {
        "sane_there": True,
        "device": S,
        "present": True,
        "away": False,
        "status": None,
        "progress": None,
        "scanning": False,
        "failed_until": 0.0,
        "now": 1000.0,
    }
    base.update(kw)
    return view(**base)  # type: ignore[arg-type]  # the test's keyword overrides


@pytest.mark.parametrize(
    ("kw", "want"),
    [
        ({}, ("idle", source_mod.SCANNER, "ready", 0)),
        (
            {"status": escl.Status("Idle", "ScannerAdfLoaded")},
            ("idle", source_mod.SCANNER, "feeder loaded", 0),
        ),
        (
            {"scanning": True, "progress": {"page": 3, "pages": 2}},
            ("active", source_mod.SCANNER, "scanning page 3", 2),
        ),
        ({"scanning": True, "progress": {}}, ("active", source_mod.SCANNER, "scanning", 0)),
        (
            {"progress": {"result": "jam"}, "failed_until": 2000.0},
            ("alert", source_mod.TRAY_ALERT, "feeder jammed", 0),
        ),
        (
            {"progress": {"result": "busy"}, "failed_until": 2000.0},
            ("alert", source_mod.SCANNER, "scan failed: busy", 0),
        ),
        (
            {"progress": {"result": "jam"}, "failed_until": 900.0},
            ("idle", source_mod.SCANNER, "ready", 0),
        ),
        (
            {"status": escl.Status("Idle", "ScannerAdfJam")},
            ("alert", source_mod.TRAY_ALERT, "feeder jammed", 0),
        ),
        (
            {"status": escl.Status("Idle", "ScannerAdfDoorOpen")},
            ("alert", source_mod.TRAY_ALERT, "cover open", 0),
        ),
        ({"present": False}, ("alert", source_mod.SCANNER_OFF, "not found", 0)),
        ({"present": False, "away": True}, ("unavailable", source_mod.SCANNER_OFF, "away", 0)),
        ({"status": escl.Status("Processing", "")}, ("active", source_mod.SCANNER, "scanning", 0)),
        ({"status": escl.Status("Down", "")}, ("alert", source_mod.SCANNER_OFF, "not ready", 0)),
        ({"device": None}, ("unavailable", source_mod.SCANNER_OFF, "no scanner", 0)),
        ({"sane_there": False}, ("unavailable", source_mod.SCANNER_OFF, "no scanner", 0)),
    ],
)
def test_the_scanner_table(kw: dict[str, object], want: tuple[str, str, str, int]) -> None:
    assert v(**kw) == want


# ---------------------------------------------------------------- the source


def make() -> tuple[ScannerSource, list[str]]:
    pokes: list[str] = []
    modules = {"scanner": mods.Module("scanner", source="scanner", display="icon")}
    src = ScannerSource(["scanner"], Writer(modules, pokes.append))
    return src, pokes


def known(*devices: str) -> None:
    store.write(
        store.scanners_path(),
        {"at": 1.0, "scanners": [{"device": d, "model": d.split(":")[-1]} for d in devices]},
    )


def shown() -> tuple[object, ...]:
    data = st.read("scanner") or {}
    return (data.get("tier"), data.get("label"), data.get("count"))


def test_unadvertised_status_at_most_every_ten_minutes(
    monkeypatch: pytest.MonkeyPatch, commands: Callable[..., Path]
) -> None:
    commands(scanimage="sys.exit(0)")
    known(DEVICE)
    src, _ = make()
    monkeypatch.setattr(escl, "base_from_conf", lambda name, conf=None: "http://s.example/eSCL")
    asked: list[str] = []
    answer: list[escl.Status | None] = [escl.Status("Idle", "ScannerAdfLoaded")]

    def status_of(base: str) -> escl.Status | None:
        asked.append(base)
        return answer[0]

    src.status_of = status_of
    clock = [5000.0]
    src.clock = lambda: clock[0]
    src.choose()
    src.presence(clock[0])
    src.write()
    assert shown() == ("idle", "feeder loaded", None)
    clock[0] += 60
    src.presence(clock[0])
    assert len(asked) == 1  # capped
    answer[0] = None
    src.resolves = lambda host: True
    clock[0] += source_mod.UNADVERTISED_EVERY
    src.presence(clock[0])
    src.write()
    assert shown() == ("alert", "not found", None) and len(asked) == 2
    src.resolves = lambda host: False
    clock[0] += source_mod.UNADVERTISED_EVERY
    src.presence(clock[0])
    src.write()
    assert shown() == ("unavailable", "away", None)
    assert "s.example" not in json.dumps(st.read("scanner"))


def test_advertised_presence_by_dns_sd(commands: Callable[..., Path]) -> None:
    commands(scanimage="sys.exit(0)")
    known(DEVICE)
    src, _ = make()
    src.status_of = lambda base: escl.Status("Idle", "")
    src.browser = mdns.Browser(mdns.SCANNER_TYPES, src.changed)
    src.choose()
    src.found_at = 1e12  # no rediscovery here
    src.browser.line(
        avahi_resolved(
            "Office Scanner", "_uscan._tcp", "office.local", "192.0.2.9", 80, '"rs=eSCL"'
        )
    )
    src.changed()
    src.write()
    assert shown() == ("idle", "ready", None)
    src.browser.line("-;eth0;IPv4;Office Scanner;_uscan._tcp;local")
    src.changed()
    src.write()
    assert shown() == ("unavailable", "away", None)


def test_progress_only_while_the_lock_is_held(commands: Callable[..., Path]) -> None:
    commands(scanimage="sys.exit(0)")
    known("epsonds:libusb:001:004")
    src, _ = make()
    clock = [100.0]
    src.clock = lambda: clock[0]
    src.choose()
    scan.report(phase="scanning", pages=2, page=3, result="")
    src.watch_scan(clock[0])
    assert src.progress is None  # no lock held: the file isn't read
    lock = scan.Lock()
    lock.acquire()
    try:
        assert scan.running()
        src.watch_scan(clock[0])
        src.present = True
        src.write()
        assert shown() == ("active", "scanning page 3", 2)
    finally:
        lock.release()
    scan.report(phase="failed", pages=0, result="empty", alert=True)
    src.watch_scan(clock[0])  # the end: read once more
    src.write()
    assert shown() == ("alert", "feeder empty", None)
    clock[0] += source_mod.FAILED_FOR + 1
    src.watch_scan(clock[0])
    src.write()
    assert shown() == ("idle", "ready", None)


@pytest.fixture
def followed(commands: Callable[..., Path]) -> Iterator[ScannerSource]:
    commands(
        scanimage=(
            'print("device `airscan:e0:Office Scanner\' is a eSCL Office Scanner ip=192.0.2.9")'
        ),
        **{"avahi-browse": "time.sleep(30)"},
    )
    src, _ = make()
    thread = threading.Thread(target=src.follow, daemon=True)
    thread.start()
    yield src
    src.stop()
    thread.join(3)
    assert not thread.is_alive()


def test_follow_discovers_then_watches(
    followed: ScannerSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert wait_for(lambda: followed.device is not None)
    assert followed.device is not None and followed.device.device == DEVICE
    prefs.remember(device="airscan:e1:Other")
    assert wait_for(
        lambda: followed.device is not None and followed.device.device.endswith("Other")
    )


def test_without_sane(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    src, _ = make()
    src.wake.set()
    src.follow()
    assert shown() == ("unavailable", "no scanner", None)
    src.gone()

"""scanner: the configured scanner's presence and state (record 0004 §1-2), without polling it.

Which scanner: DESKTOP_TOOLS_SCANNER, else the one picked in the menu, else the first that
`scanimage -L` finds (run at the source's start when none was found this session, and when
DNS-SD reports a new scanner, at most hourly). Presence by events: `avahi-browse` for eSCL's
`_uscan._tcp`/`_uscans._tcp` (the configured scanner's service coming or going); for a USB
scanner, `udevadm monitor` lines trigger a re-check (debounced USB_SETTLE seconds). A scanner
named in airscan.conf by address and not advertised is checked with one eSCL `ScannerStatus`
GET at start and at most every UNADVERTISED_EVERY seconds.

Status (eSCL scanners): `ScannerStatus` on DNS-SD changes and every SCANNING_STATUS seconds while
a scan of ours runs; never on a plain timer when idle. Our own scans' progress comes from
`devices/scan.json` in the runtime folder, read every second only while the scan's lock is held,
then once at the end; a failed scan alerts for FAILED_FOR seconds or until the next scan. The
one writer of the module is this source. The idle loop only looks at local files.
"""

from __future__ import annotations

import contextlib
import shutil
import threading
import time
from collections.abc import Callable, Sequence

from desktop_tools.barctl.sources.base import Source
from desktop_tools.barctl.store import Writer
from desktop_tools.common import procs
from desktop_tools.devices import escl, mdns, prefs, sane, scan, store

SCANNER = "\U000f06ab"  # md-scanner
SCANNER_OFF = "\U000f090a"  # md-scanner_off
TRAY_ALERT = "\U000f1295"  # md-tray_alert
FAILED_FOR = 600.0
UNADVERTISED_EVERY = 600.0
SCANNING_STATUS = 2.0
FIND_EVERY = 3600.0
USB_SETTLE = 2.0
IDLE_TICK = 2.0
BUSY_TICK = 1.0

# A failed scan's result word -> (glyph, label)
FAILED = {
    "empty": (TRAY_ALERT, "feeder empty"),
    "jam": (TRAY_ALERT, "feeder jammed"),
    "cover": (TRAY_ALERT, "cover open"),
    "busy": (SCANNER, "scan failed: busy"),
    "lost": (SCANNER_OFF, "scan failed: lost the scanner"),
    "unreachable": (SCANNER_OFF, "not found"),
    "failed": (SCANNER, "scan failed"),
}


def view(
    *,
    sane_there: bool,
    device: sane.Scanner | None,
    present: bool | None,
    away: bool,
    status: escl.Status | None,
    progress: dict[str, object] | None,
    scanning: bool,
    failed_until: float,
    now: float,
) -> tuple[str, str, str, int]:
    """(tier, glyph, label, count) for §1's scanner table."""
    if not sane_there:
        return "unavailable", SCANNER_OFF, "no scanner", 0
    if device is None:
        return "unavailable", SCANNER_OFF, "no scanner", 0
    if scanning:
        page = int(str((progress or {}).get("page") or 0) or 0)
        pages = int(str((progress or {}).get("pages") or 0) or 0)
        label = f"scanning page {page}" if page > 1 else "scanning"
        return "active", SCANNER, label, pages
    result = str((progress or {}).get("result") or "")
    if now < failed_until and result in FAILED:
        glyph, label = FAILED[result]
        return "alert", glyph, label, 0
    if status is not None and status.feeder == "jam":
        return "alert", TRAY_ALERT, "feeder jammed", 0
    if status is not None and status.feeder == "door":
        return "alert", TRAY_ALERT, "cover open", 0
    if present is False:
        if away:
            return "unavailable", SCANNER_OFF, "away", 0
        return "alert", SCANNER_OFF, "not found", 0
    if status is not None and status.state == "Processing":
        return "active", SCANNER, "scanning", 0
    if status is not None and status.state in ("Down", "Stopped"):
        return "alert", SCANNER_OFF, "not ready", 0
    label = "feeder loaded" if status is not None and status.feeder == "loaded" else "ready"
    return "idle", SCANNER, label, 0


class ScannerSource(Source):
    name = "scanner"
    commands = ("scanimage",)
    optional = ("avahi-browse",)

    def __init__(self, modules: Sequence[str], writer: Writer) -> None:
        super().__init__(modules, writer)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.clock: Callable[[], float] = time.time
        self.status_of: Callable[[str], escl.Status | None] = escl.status
        self.resolves: Callable[[str], bool] = mdns.resolves
        self.device: sane.Scanner | None = None
        self.base = ""  # the eSCL root, never logged or written
        self.present: bool | None = None
        self.away = False
        self.status: escl.Status | None = None
        self.status_at = -1e9
        self.progress: dict[str, object] | None = None
        self.scanning = False
        self.failed_until = 0.0
        self.found_mtime = 0.0
        self.found_at = -1e9
        self.browser: mdns.Browser | None = None
        self.usb: procs.Stream | None = None
        self.usb_due = 0.0
        self.services: set[str] = set()

    # ------------------------------------------------------------ which scanner

    def choose(self) -> None:
        """The scanner to show, from the setting, the menu's pick or the last discovery."""
        known = sane.known()
        wanted = prefs.chosen_scanner()
        device = next((s for s in known if s.device == wanted), None)
        if device is None and wanted:
            device = sane.Scanner(wanted, wanted.split(":")[-1])
        if device is None and known:
            device = known[0]
        if device != self.device:
            self.device, self.status, self.present = device, None, None
            self.base = self.conf_base(device)
            self.status_at = -1e9

    def conf_base(self, device: sane.Scanner | None) -> str:
        if device is None or not device.instance:
            return ""
        return escl.base_from_conf(device.instance)

    def discover(self) -> None:
        self.found_at = self.clock()
        sane.find()
        self.found_mtime = self.mtime()
        self.choose()

    @staticmethod
    def mtime() -> float:
        try:
            return store.scanners_path().stat().st_mtime
        except OSError:
            return 0.0

    # ------------------------------------------------------------ presence and status

    def advertised(self) -> list[mdns.Service]:
        if self.browser is None or self.device is None or not self.device.instance:
            return []
        return self.browser.named(self.device.instance)

    def ask_status(self, now: float) -> None:
        base = self.base
        services = self.advertised()
        if services:
            s = services[0]
            base = escl.base_from_txt(
                s.address, s.port, s.txt_value("rs"), secure=s.kind.startswith("_uscans")
            )
        if not base:
            return
        self.status_at = now
        self.status = self.status_of(base)
        if not services:  # unadvertised: the status GET is the presence check
            self.present = self.status is not None
            host = escl.host_of(base)
            self.away = not self.present and bool(host) and not self.resolves(host)

    def presence(self, now: float) -> None:
        """Present or not, from DNS-SD, the unadvertised check, or the last discovery."""
        if self.device is None:
            return
        services = self.advertised()
        if self.browser is not None and self.device.instance and services:
            self.present, self.away = True, False
            return
        if self.base:
            if now - self.status_at >= UNADVERTISED_EVERY:
                self.ask_status(now)
            return
        if self.browser is not None and self.device.network:
            self.present, self.away = False, True  # advertised scanners: gone means away
            return
        self.present = any(s.device == self.device.device for s in sane.known())

    def changed(self) -> None:
        """DNS-SD: a scanner service came or went."""
        if self.stopping:
            return
        with self.lock:
            names = {s.name for s in (self.browser.all() if self.browser else [])}
            new, self.services = names - self.services, names
            now = self.clock()
            ours = self.device.instance if self.device is not None else ""
            if new - {ours} and now - self.found_at >= FIND_EVERY:
                self.discover()  # a scanner SANE hasn't listed yet
            self.presence(now)
            if self.advertised():
                self.ask_status(now)
        self.wake.set()

    # ------------------------------------------------------------ our scans

    def watch_scan(self, now: float) -> None:
        running = scan.running()
        if running:
            self.progress = store.read(store.progress_path())
            if not self.scanning:
                self.failed_until = 0.0  # a new scan ends the last one's alert
            if now - self.status_at >= SCANNING_STATUS and (self.base or self.advertised()):
                self.ask_status(now)
        elif self.scanning:  # it just ended: once more
            self.progress = store.read(store.progress_path())
            if (self.progress or {}).get("alert"):
                self.failed_until = now + FAILED_FOR
            if self.base or self.advertised():
                self.ask_status(now)
        self.scanning = running

    # ------------------------------------------------------------ writing

    def write(self) -> None:
        with self.lock:
            now = self.clock()
            tier, glyph, label, count = view(
                sane_there=shutil.which("scanimage") is not None,
                device=self.device,
                present=self.present,
                away=self.away,
                status=self.status,
                progress=self.progress,
                scanning=self.scanning,
                failed_until=self.failed_until,
                now=now,
            )
            detail = self.device.model if self.device is not None else ""
            if self.browser is None and self.device is not None and self.device.network:
                detail += "; no avahi: presence checked on demand"
            for module in self.modules:
                self.writer.set(
                    module,
                    self.name,
                    tier,
                    glyph=glyph,
                    label=label,
                    count=count or None,
                    detail=detail or None,
                    alert_for=10.0 if tier == "alert" and self._new_alert(label) else None,
                    now=now,
                )

    _last_alert = ""

    def _new_alert(self, label: str) -> bool:
        new = label != self._last_alert
        self._last_alert = label
        return new

    # ------------------------------------------------------------ USB

    def _usb(self) -> None:
        try:
            self.usb = procs.Stream(["udevadm", "monitor", "--udev", "--subsystem-match=usb"])
        except OSError:
            return
        for _line in self.usb.lines():
            if self.stopping:
                return
            self.usb_due = self.clock() + USB_SETTLE
            self.wake.set()

    # ------------------------------------------------------------ following

    def follow(self) -> None:
        self._last_alert = ""
        if shutil.which("scanimage") is None:
            self.device = None
            self.write()
            self.wake.wait(3600)  # nothing to follow until SANE is installed: restarted later
            return
        with self.lock:
            self.choose()
            if self.device is None or not sane.known():
                self.discover()
            self.found_mtime = self.mtime()
        self.browser = mdns.Browser(mdns.SCANNER_TYPES, self.changed)
        if not self.browser.start():
            self.browser = None
        usb = None
        if self.device is not None and not self.device.network and shutil.which("udevadm"):
            usb = threading.Thread(target=self._usb, name="scanner-usb", daemon=True)
            usb.start()
        try:
            with self.lock:
                now = self.clock()
                self.presence(now)
                if self.advertised():
                    self.ask_status(now)
            while not self.stopping:
                with self.lock:
                    now = self.clock()
                    if self.mtime() != self.found_mtime:  # `devices scanner find` ran
                        self.found_mtime = self.mtime()
                        self.choose()
                        self.presence(now)
                    else:
                        self.choose()  # a pick in the menu
                    if self.usb_due and now >= self.usb_due:
                        self.usb_due = 0.0
                        self.discover()
                        self.presence(now)
                    self.watch_scan(now)
                    if not self.scanning:
                        self.presence(now)
                self.write()
                self.wake.wait(BUSY_TICK if self.scanning else IDLE_TICK)
                self.wake.clear()
        finally:
            if self.browser is not None:
                self.browser.stop()
                self.browser = None
            if self.usb is not None:
                self.usb.stop()
            if usb is not None:
                usb.join(2)

    def stop(self) -> None:
        super().stop()
        self.wake.set()
        with contextlib.suppress(Exception):
            if self.usb is not None:
                self.usb.stop()

    def gone(self) -> None:
        with self.lock:
            self.present = None
            self.write()

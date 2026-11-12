"""Fakes for the printer and scanner (record 0004 §9): a cupsd answering IPP on a Unix socket in
tmp_path, built from the test's printers and jobs, recording every request; and helpers for
avahi-browse lines and fake scanimage output.

No test reaches a real cupsd, printer or scanner: CUPS_SERVER points at this fake (or at a
socket nothing listens on), the desktop's CUPS and SANE commands are tripwires on PATH until a
test fakes them, and the `no_device_sockets` fixture (conftest, every test) fails a test that
connects to /run/cups/cups.sock or to port 631, 80 or 9100 of anything.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from desktop_tools.devices import ipp

Values = list[ipp.Value]


def attr(group: int, name: str, tag: int, *values: ipp.Value) -> ipp.Attribute:
    return ipp.Attribute(group, name, tag, list(values))


def printer_attrs(
    name: str = "Office",
    *,
    state: int = 3,
    reasons: tuple[str, ...] = ("none",),
    accepting: bool = True,
    uri: str = "ipp://printer.example/ipp/print",
    levels: tuple[int, ...] = (44, 71, 69, 72),
    lows: tuple[int, ...] = (16, 16, 16, 15),
    names: tuple[str, ...] = (),
) -> list[ipp.Attribute]:
    p = ipp.PRINTER
    out = [
        attr(p, "printer-name", ipp.NAME, name),
        attr(p, "printer-state", ipp.ENUM, state),
        attr(p, "printer-state-reasons", ipp.KEYWORD, *reasons),
        attr(p, "printer-is-accepting-jobs", ipp.BOOLEAN, accepting),
        attr(p, "device-uri", ipp.URI, uri),
    ]
    if levels:
        out.append(attr(p, "marker-levels", ipp.INTEGER, *levels))
        out.append(attr(p, "marker-low-levels", ipp.INTEGER, *lows))
    if names:
        out.append(attr(p, "marker-names", ipp.NAME, *names))
    return out


def job_attrs(
    job_id: int, state: int = 3, user: str = "me", created: int = 0, title: str = ""
) -> list[ipp.Attribute]:
    j = ipp.JOB
    out = [
        attr(j, "job-id", ipp.INTEGER, job_id),
        attr(j, "job-state", ipp.ENUM, state),
        attr(j, "job-state-reasons", ipp.KEYWORD, "none"),
        attr(j, "job-originating-user-name", ipp.NAME, user),
        attr(j, "time-at-creation", ipp.INTEGER, created),
    ]
    if title:  # a fake cupsd that sends a title anyway: it must never reach the bar
        out.append(attr(j, "job-name", ipp.NAME, title))
    return out


def response(
    status: int, request_id: int, attributes: list[ipp.Attribute], *more: list[ipp.Attribute]
) -> bytes:
    """An IPP answer, built with the encoder (the status in the operation's place): the
    operation group with `attributes`' own groups, then each of `more` as a group of its own
    (one per printer, job or event)."""
    head = [
        attr(ipp.OPERATION, "attributes-charset", ipp.CHARSET_TAG, "utf-8"),
        attr(ipp.OPERATION, "attributes-natural-language", ipp.LANGUAGE_TAG, "en"),
    ]
    groups: list[tuple[int, list[ipp.Attribute]]] = []
    for a in [*head, *attributes]:
        if not groups or groups[-1][0] != a.group:
            groups.append((a.group, []))
        groups[-1][1].append(a)
    groups += [(group[0].group, group) for group in more if group]
    return ipp.encode_groups(status, request_id, groups)


@dataclass
class Request:
    operation: int
    attrs: ipp.Attributes
    groups: list[tuple[int, ipp.Attributes]]
    raw: bytes


@dataclass
class FakeCups:
    """A cupsd on a Unix socket: CUPS-Get-Printers, CUPS-Get-Default, Get-Jobs and the
    subscription operations, from what the test sets."""

    path: Path
    printers: list[list[ipp.Attribute]] = field(default_factory=list)
    default: str = ""
    jobs: dict[str, list[list[ipp.Attribute]]] = field(default_factory=dict)
    subscribe_status: int = ipp.OK
    events: list[int] = field(default_factory=list)  # sequence numbers waiting to be sent
    interval: int = 1
    hold: float = 0.0  # seconds a Get-Notifications without events is held
    gone: bool = False  # the subscription lapsed
    requests: list[Request] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(self.path))
        self.sock.listen(16)
        self.sock.settimeout(0.1)
        self.stopping = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def ops(self) -> list[int]:
        return [r.operation for r in self.requests]

    def _serve(self) -> None:
        while not self.stopping:
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(5)
            data = b""
            try:
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    data += chunk
                head, _, body = data.partition(b"\r\n\r\n")
                length = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                while len(body) < length:
                    body += conn.recv(65536)
            except OSError:
                return
            answer = self.answer(body)
            reply = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/ipp\r\n"
                + f"Content-Length: {len(answer)}\r\nConnection: close\r\n\r\n".encode()
                + answer
            )
            try:
                conn.sendall(reply)
            except OSError:
                return

    def answer(self, body: bytes) -> bytes:
        import struct

        _maj, _min, operation, request_id = struct.unpack(">BBHI", body[:8])
        # The request's attributes, decoded as an answer would be (same layout).
        decoded = ipp.decode(body)
        groups = decoded.groups
        attrs: ipp.Attributes = {}
        for _g, a in groups:
            attrs.update(a)
        with self.lock:
            self.requests.append(Request(operation, attrs, groups, body))
        if operation == ipp.CUPS_GET_PRINTERS:
            return response(ipp.OK, request_id, [], *self.printers)
        if operation == ipp.CUPS_GET_DEFAULT:
            found = [p for p in self.printers if self._name(p) == self.default]
            if not found:
                return response(ipp.NOT_FOUND, request_id, [])
            return response(ipp.OK, request_id, found[0])
        if operation == ipp.GET_JOBS:
            uri = str((attrs.get("printer-uri") or [""])[0])
            name = uri.rsplit("/", 1)[-1]
            return response(ipp.OK, request_id, [], *self.jobs.get(name, []))
        if operation == ipp.CREATE_PRINTER_SUBSCRIPTIONS:
            if self.subscribe_status != ipp.OK:
                return response(self.subscribe_status, request_id, [])
            return response(
                ipp.OK,
                request_id,
                [attr(ipp.SUBSCRIPTION, "notify-subscription-id", ipp.INTEGER, 42)],
            )
        if operation == ipp.GET_NOTIFICATIONS:
            return self._notifications(request_id)
        if operation in (ipp.RENEW_SUBSCRIPTION, ipp.CANCEL_SUBSCRIPTION):
            return response(ipp.NOT_FOUND if self.gone else ipp.OK, request_id, [])
        return response(0x0501, request_id, [])

    def _notifications(self, request_id: int) -> bytes:
        if self.gone:
            return response(ipp.NOT_FOUND, request_id, [])
        end = time.monotonic() + self.hold
        while not self.events and time.monotonic() < end and not self.stopping:
            time.sleep(0.02)
        with self.lock:
            sent, self.events = self.events, []
        events = [
            [
                attr(ipp.EVENT, "notify-subscribed-event", ipp.KEYWORD, "job-created"),
                attr(ipp.EVENT, "notify-sequence-number", ipp.INTEGER, n),
            ]
            for n in sent
        ]
        interval = attr(ipp.OPERATION, "notify-get-interval", ipp.INTEGER, self.interval)
        return response(ipp.OK, request_id, [interval], *events)

    @staticmethod
    def _name(printer: list[ipp.Attribute]) -> str:
        return next((str(a.values[0]) for a in printer if a.name == "printer-name"), "")

    def event(self, *numbers: int) -> None:
        with self.lock:
            self.events.extend(numbers)

    def close(self) -> None:
        self.stopping = True
        self.sock.close()
        self.thread.join(1)


def wait_for(check: Callable[[], Any], timeout: float = 3.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = check()
        if found:
            return found
        time.sleep(0.02)
    return check()


def avahi_resolved(name: str, kind: str, host: str, address: str, port: int, txt: str = "") -> str:
    return f"=;eth0;IPv4;{name};{kind};local;{host};{address};{port};{txt}"


SCANIMAGE_A_AIRSCAN = """
All options specific to device `airscan:e0:Office Scanner':
  Standard:
    --resolution 75|100|150|200|300|600dpi [300]
    --mode Color|Gray [Color]
    --source Flatbed|ADF|ADF Duplex [Flatbed]
"""
SCANIMAGE_A_EPSON = """
All options specific to device `epsonds:libusb:001:004':
    --source Flatbed|ADF Front|ADF Duplex [Flatbed]
    --mode Lineart|Gray|Color [Color]
    --resolution 50..1200dpi [300]
"""
SCANIMAGE_A_FUJITSU = """
All options specific to device `fujitsu:fi-7160:1':
    --source ADF Front|ADF Back|ADF Duplex [ADF Front]
    --mode Lineart|Halftone|Gray|Color [Lineart]
    --resolution 50..600dpi [300]
"""
ESCL_STATUS = """<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerStatus xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
    xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.6</pwg:Version>
  <pwg:State>{state}</pwg:State>
  {adf}
</scan:ScannerStatus>
"""


def escl_status(state: str = "Idle", adf: str = "") -> str:
    return ESCL_STATUS.format(
        state=state, adf=f"<scan:AdfState>{adf}</scan:AdfState>" if adf else ""
    )


# A fake scanimage: `pages` TIFF files, then the SANE status line it ends with. The pages are
# not real TIFFs; the fake tiffcp, tiff2pdf and magick only join and copy bytes.
def fake_scanimage(pages: int, status: str = "", code: int | None = None) -> str:
    ends = repr(status)
    exit_code = code if code is not None else (0 if not status else 7)
    return (
        "import re\n"
        "batch = next((a.split('=', 1)[1] for a in args if a.startswith('--batch=')), None)\n"
        "out = args[args.index('--output-file') + 1] if '--output-file' in args else None\n"
        "if '-L' in args:\n"
        '    print("device `airscan:e0:Office Scanner\' is a eSCL Office Scanner ip=192.0.2.9")\n'
        "    sys.exit(0)\n"
        "if '-A' in args:\n"
        f"    print({SCANIMAGE_A_AIRSCAN!r})\n"
        "    sys.exit(0)\n"
        "open(here + '/scan.env', 'w').write(json.dumps(dict(os.environ)))\n"
        f"for n in range(1, {pages} + 1):\n"
        "    sys.stderr.write(f'Scanning page {n}\\n')\n"
        "    path = batch.replace('%03d', f'{n:03d}') if batch else out\n"
        "    open(path, 'wb').write(f'page{n};'.encode())\n"
        "    sys.stderr.write(f'Scanned page {n}. (scanner status = 5)\\n')\n"
        "    sys.stderr.flush()\n"
        f"if {ends}:\n"
        f"    sys.stderr.write('scanimage: sane_start: ' + {ends} + '\\n')\n"
        f"sys.exit({exit_code})\n"
    )


FAKE_TIFFCP = "open(args[-1], 'wb').write(b''.join(open(a, 'rb').read() for a in args[:-1]))"
FAKE_TIFF2PDF = (
    "o = args[args.index('-o') + 1]\nopen(o, 'wb').write(b'%PDF ' + open(args[-1], 'rb').read())"
)
FAKE_MAGICK = "open(args[1], 'wb').write(b'IMG ' + open(args[0], 'rb').read())"

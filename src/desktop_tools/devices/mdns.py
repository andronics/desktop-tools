"""DNS-SD presence from `avahi-browse -p -r -k <types>`, followed as a stream (record 0004 §2.4,
§2.2), and the TCP probe for a network printer avahi says nothing about.

`avahi-browse -p` prints `+` (found), `=` (resolved: host name, address, port, TXT) and `-`
(gone) lines, fields split by `;`. A Browser keeps the resolved services and calls its `changed`
callback when one comes or goes. Nothing here logs a service name, host or address.

The probe connects to port 631, then 80, with a 1 s timeout. Never port 9100: a connection to a
raw print port can feed a blank page.
"""

from __future__ import annotations

import contextlib
import shutil
import socket
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from desktop_tools.common import procs

PRINTER_TYPES = ("_ipp._tcp", "_printer._tcp", "_pdl-datastream._tcp")
SCANNER_TYPES = ("_uscan._tcp", "_uscans._tcp")
PROBE_PORTS = (631, 80)  # never 9100
PROBE_TIMEOUT = 1.0


@dataclass(frozen=True)
class Service:
    name: str  # the instance name (a scanner's, as sane-airscan names it)
    kind: str  # _uscan._tcp, …
    host: str  # lower case, without the trailing dot
    address: str
    port: int
    txt: tuple[str, ...]

    def txt_value(self, key: str) -> str:
        for item in self.txt:
            k, _, v = item.partition("=")
            if k.lower() == key.lower():
                return v
        return ""


def unescape(text: str) -> str:
    r"""avahi-browse -p escapes `;`, `\` and odd bytes as `\DDD` (decimal)."""
    out, i = bytearray(), 0
    raw = text.encode("utf-8", "replace")
    while i < len(raw):
        if raw[i : i + 1] == b"\\" and i + 3 < len(raw) + 1 and raw[i + 1 : i + 4].isdigit():
            out.append(int(raw[i + 1 : i + 4]) % 256)
            i += 4
        else:
            out.append(raw[i])
            i += 1
    return out.decode("utf-8", "replace")


def _txt(field: str) -> tuple[str, ...]:
    items = []
    for part in field.split('" "'):
        part = part.strip().strip('"')
        if part:
            items.append(part)
    return tuple(items)


def parse(line: str) -> tuple[str, tuple[str, str, str, str, str], Service | None] | None:
    """One line: (event, key, service). The key is (interface, protocol, name, type, domain);
    the service is given on `=` lines only. None for anything else."""
    fields = line.split(";")
    if len(fields) < 6 or fields[0] not in ("+", "=", "-"):
        return None
    key = (fields[1], fields[2], unescape(fields[3]), fields[4], fields[5])
    if fields[0] != "=":
        return fields[0], key, None
    if len(fields) < 9:
        return None
    try:
        port = int(fields[8])
    except ValueError:
        port = 0
    host = unescape(fields[6]).rstrip(".").lower()
    txt = _txt(";".join(fields[9:])) if len(fields) > 9 else ()
    return "=", key, Service(key[2], key[3], host, fields[7], port, txt)


class Browser:
    """The resolved services of some DNS-SD types, kept up to date from avahi-browse."""

    def __init__(self, types: Sequence[str], changed: Callable[[], object]) -> None:
        self.types = tuple(types)
        self.changed = changed
        self.services: dict[tuple[str, str, str, str, str], Service] = {}
        self.lock = threading.Lock()
        self.stream: procs.Stream | None = None
        self.thread: threading.Thread | None = None
        self.running = False
        self.stopping = False

    @staticmethod
    def available() -> bool:
        return shutil.which("avahi-browse") is not None

    def line(self, text: str) -> bool:
        """Take one line; returns whether the set of services changed."""
        found = parse(text)
        if found is None:
            return False
        event, key, service = found
        with self.lock:
            if event == "=" and service is not None:
                before = self.services.get(key)
                self.services[key] = service
                return before != service
            if event == "-":
                return self.services.pop(key, None) is not None
        return False

    def start(self) -> bool:
        """Follow avahi-browse in a thread; False when it isn't installed or can't start."""
        if not self.available():
            return False
        try:
            self.stream = procs.Stream(["avahi-browse", "-p", "-r", "-k", *self.types])
        except OSError:
            return False
        self.running = True
        self.thread = threading.Thread(target=self._follow, name="avahi-browse", daemon=True)
        self.thread.start()
        return True

    def _follow(self) -> None:
        assert self.stream is not None  # noqa: S101 - start() set it before starting us
        try:
            for text in self.stream.lines():
                if self.stopping:
                    return
                if self.line(text):
                    with contextlib.suppress(Exception):
                        self.changed()
        finally:
            self.running = False

    def stop(self) -> None:
        self.stopping = True
        if self.stream is not None:
            self.stream.stop()
        if self.thread is not None:
            self.thread.join(3)

    def all(self) -> list[Service]:
        with self.lock:
            return list(self.services.values())

    def has_host(self, host: str) -> bool:
        """A resolved service on this host name or address."""
        host = host.rstrip(".").lower()
        if not host:
            return False
        return any(s.host == host or s.address == host for s in self.all())

    def named(self, name: str) -> list[Service]:
        return [s for s in self.all() if s.name == name]


def probe(host: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """Whether the host takes a TCP connection on 631, else 80 (never 9100). A host that doesn't
    resolve is not reachable."""
    for port in PROBE_PORTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    return True

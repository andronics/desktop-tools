"""eSCL (AirScan) status: one read-only `GET <base>/ScannerStatus` (record 0004 §2.3).

The base is the scanner's eSCL root (`http://host[:port]/eSCL`), from its DNS-SD record (`rs`
in the TXT) or from sane-airscan's `airscan.conf` (`"<name>" = <url>, eSCL`). The answer gives
`pwg:State` (Idle, Processing, Testing, Stopped, Down) and `scan:AdfState` (ScannerAdfLoaded,
ScannerAdfEmpty, ScannerAdfJam, ScannerAdfDoorOpen, …). 3 s timeout, one retry: a sleeping
scanner wakes slowly. Nothing is scanned, and the base URL is never logged or shown.
"""

from __future__ import annotations

import http.client
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

TIMEOUT = 3.0
CONF = (Path("/etc/sane.d/airscan.conf"),)
CONF_LINE = re.compile(r'^\s*"([^"]+)"\s*=\s*(\S+?)\s*(?:,\s*(\w+))?\s*$')


@dataclass(frozen=True)
class Status:
    state: str  # Idle, Processing, Testing, Stopped, Down
    adf: str  # ScannerAdfLoaded, …; "" when the scanner says nothing of a feeder

    @property
    def feeder(self) -> str:
        """loaded, empty, jam, door, "" (unknown)."""
        a = self.adf.lower()
        if "loaded" in a:
            return "loaded"
        if "empty" in a:
            return "empty"
        if "jam" in a:
            return "jam"
        if "open" in a:
            return "door"
        return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse(xml: bytes | str) -> Status | None:
    """ScannerStatus XML; None when it isn't one."""
    try:
        # S314: the answer of a scanner on the local network, parsed by expat (no external
        # entities, and Python's expat limits entity expansion); the stdlib keeps the
        # dependency list as it is (record 0004 §5).
        root = ET.fromstring(xml)  # noqa: S314
    except ET.ParseError:
        return None
    if _local(root.tag) != "ScannerStatus":
        return None
    state = adf = ""
    for el in root.iter():
        name = _local(el.tag)
        if name == "State" and not state:
            state = (el.text or "").strip()
        elif name == "AdfState" and not adf:
            adf = (el.text or "").strip()
    return Status(state, adf)


def base_from_conf(name: str, conf: tuple[Path, ...] | None = None) -> str:
    """The eSCL URL airscan.conf gives this device name; "" when it names none."""
    for path in CONF if conf is None else conf:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        section = ""
        for line in lines:
            stripped = line.split(";", 1)[0].split("#", 1)[0].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip().lower()
                continue
            m = CONF_LINE.match(stripped)
            if section == "devices" and m and m.group(1) == name:
                kind = (m.group(3) or "escl").lower()
                return m.group(2).rstrip("/") if kind == "escl" else ""
    return ""


def base_from_txt(address: str, port: int, rs: str, secure: bool = False) -> str:
    host = f"[{address}]" if ":" in address else address
    scheme = "https" if secure else "http"
    path = "/" + rs.strip("/") if rs.strip("/") else ""
    return f"{scheme}://{host}:{port}{path}"


def host_of(base: str) -> str:
    try:
        return (urlsplit(base).hostname or "").lower()
    except ValueError:
        return ""


def _get(base: str, timeout: float) -> bytes | None:
    try:
        parts = urlsplit(base)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    conn = cls(parts.hostname, parts.port, timeout=timeout)
    try:
        conn.request("GET", parts.path.rstrip("/") + "/ScannerStatus")
        answer = conn.getresponse()
        data = answer.read()
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()
    return data if answer.status == 200 else None


def status(
    base: str, timeout: float = TIMEOUT, retry: float = 0.5, attempts: int = 2
) -> Status | None:
    """The scanner's status, or None when it doesn't answer (`attempts` times)."""
    for attempt in range(attempts):
        data = _get(base, timeout)
        if data is not None:
            return parse(data)
        if attempt + 1 < attempts:
            time.sleep(retry)
    return None

"""A minimal IPP/1.1 client for the local cupsd (record 0004 §2.1): the encoder, the decoder and
HTTP over the CUPS socket, stdlib only.

Only what the printer source and `devices printer status` ask: CUPS-Get-Printers, CUPS-Get-
Default, Get-Jobs, and the pull subscription's Create-Printer-Subscriptions, Get-Notifications,
Renew-Subscription and Cancel-Subscription. Every one reads, or is cupsd's own bookkeeping (a
subscription is no printer or queue setting); nothing here prints, cancels or pauses.

The server is `CUPS_SERVER` when set (a socket path, or host[:port]), else /run/cups/cups.sock
when it exists, else localhost:631. A decoded attribute is a list of values: int for integer
and enum, bool for boolean, str for the text kinds, bytes for the rest; a collection's members
are skipped (no request here needs one).
"""

from __future__ import annotations

import contextlib
import http.client
import os
import socket
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

VERSION = (1, 1)
CHARSET = "utf-8"
LANGUAGE = "en"
SOCKET = Path("/run/cups/cups.sock")
PORT = 631

# Operations.
GET_JOBS = 0x000A
CREATE_PRINTER_SUBSCRIPTIONS = 0x0016
RENEW_SUBSCRIPTION = 0x001A
CANCEL_SUBSCRIPTION = 0x001B
GET_NOTIFICATIONS = 0x001C
CUPS_GET_DEFAULT = 0x4001
CUPS_GET_PRINTERS = 0x4002

# Group tags.
OPERATION, JOB, END, PRINTER, UNSUPPORTED, SUBSCRIPTION, EVENT = (
    0x01,
    0x02,
    0x03,
    0x04,
    0x05,
    0x06,
    0x07,
)
GROUPS = frozenset({OPERATION, JOB, PRINTER, UNSUPPORTED, SUBSCRIPTION, EVENT})

# Value tags.
NO_VALUE = 0x13
INTEGER, BOOLEAN, ENUM = 0x21, 0x22, 0x23
BEGIN_COLLECTION, END_COLLECTION, MEMBER_NAME = 0x34, 0x37, 0x4A
TEXT, NAME, KEYWORD, URI, CHARSET_TAG, LANGUAGE_TAG, MIME = (
    0x41,
    0x42,
    0x44,
    0x45,
    0x47,
    0x48,
    0x49,
)
STRINGS = frozenset({0x41, 0x42, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49})
WITH_LANGUAGE = frozenset({0x35, 0x36})

# Status codes the callers tell apart.
OK = 0x0000
NOT_AUTHORIZED = 0x0403
NOT_FOUND = 0x0406
TOO_MANY_SUBSCRIPTIONS = 0x0415
STATUS_NAMES = {
    0x0000: "successful-ok",
    0x0001: "successful-ok-ignored-or-substituted-attributes",
    0x0002: "successful-ok-conflicting-attributes",
    0x0003: "successful-ok-ignored-subscriptions",
    0x0005: "successful-ok-too-many-events",
    0x0007: "successful-ok-events-complete",
    0x0400: "client-error-bad-request",
    0x0401: "client-error-forbidden",
    0x0402: "client-error-not-authenticated",
    0x0403: "client-error-not-authorized",
    0x0404: "client-error-not-possible",
    0x0406: "client-error-not-found",
    0x0414: "client-error-ignored-all-subscriptions",
    0x0415: "client-error-too-many-subscriptions",
    0x0500: "server-error-internal-error",
    0x0501: "server-error-operation-not-supported",
    0x0502: "server-error-service-unavailable",
    0x0507: "server-error-busy",
}

Value = int | bool | str | bytes
Attributes = dict[str, list[Value]]


class IppError(Exception):
    """cupsd couldn't be reached, answered something that isn't IPP, or refused the request
    (`status` is its status code; None when there was no IPP answer at all)."""

    def __init__(self, message: str, status: int | None = None, *, timed_out: bool = False) -> None:
        super().__init__(message)
        self.status, self.timed_out = status, timed_out


@dataclass
class Attribute:
    """One attribute to send: its group, name, value tag and values."""

    group: int
    name: str
    tag: int
    values: Sequence[Value]


@dataclass
class Response:
    status: int
    request_id: int
    groups: list[tuple[int, Attributes]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status < 0x0400

    def all(self, tag: int) -> list[Attributes]:
        """Every group of this kind, in order (one per printer, job or event)."""
        return [attrs for group, attrs in self.groups if group == tag]

    def first(self, tag: int) -> Attributes:
        found = self.all(tag)
        return found[0] if found else {}


def status_name(status: int) -> str:
    return STATUS_NAMES.get(status, f"0x{status:04x}")


# ---------------------------------------------------------------- encoding


def _value(tag: int, value: Value) -> bytes:
    if tag in (INTEGER, ENUM):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"tag 0x{tag:02x} takes an int")
        return struct.pack(">i", value)
    if tag == BOOLEAN:
        return b"\x01" if value else b"\x00"
    if tag == NO_VALUE:
        return b""
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    raise TypeError(f"tag 0x{tag:02x} takes text or bytes")


def encode(operation: int, request_id: int, attributes: Iterable[Attribute]) -> bytes:
    """An IPP request: version, operation, id, then the attributes by group, in the order given
    (a group's tag is written when it changes), then end-of-attributes."""
    groups: list[tuple[int, list[Attribute]]] = []
    for attr in attributes:
        if not groups or groups[-1][0] != attr.group:
            groups.append((attr.group, []))
        groups[-1][1].append(attr)
    return encode_groups(operation, request_id, groups)


def encode_groups(
    operation: int, request_id: int, groups: Iterable[tuple[int, Sequence[Attribute]]]
) -> bytes:
    """As encode, with each group given: two printers, jobs or events in a row are two groups
    of the same tag."""
    out = bytearray(struct.pack(">BBHI", *VERSION, operation, request_id))
    for tag, attrs in groups:
        out.append(tag)
        for attr in attrs:
            for i, value in enumerate(attr.values or [b""]):
                name = attr.name.encode("ascii") if i == 0 else b""
                data = _value(attr.tag, value)
                out += struct.pack(">BH", attr.tag, len(name)) + name
                out += struct.pack(">H", len(data)) + data
    out.append(END)
    return bytes(out)


def standard(printer_uri: str = "ipp://localhost/", user: str | None = None) -> list[Attribute]:
    """The operation attributes every request starts with."""
    attrs = [
        Attribute(OPERATION, "attributes-charset", CHARSET_TAG, [CHARSET]),
        Attribute(OPERATION, "attributes-natural-language", LANGUAGE_TAG, [LANGUAGE]),
        Attribute(OPERATION, "printer-uri", URI, [printer_uri]),
    ]
    attrs.append(Attribute(OPERATION, "requesting-user-name", NAME, [user or username()]))
    return attrs


def username() -> str:
    import getpass

    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return "nobody"


# ---------------------------------------------------------------- decoding


def _decoded(tag: int, data: bytes) -> Value:
    if tag in (INTEGER, ENUM) and len(data) == 4:
        return int(struct.unpack(">i", data)[0])
    if tag == BOOLEAN and len(data) == 1:
        return data != b"\x00"
    if tag in STRINGS:
        return data.decode("utf-8", "replace")
    if tag in WITH_LANGUAGE and len(data) >= 2:
        # language length, language, text length, text
        n = struct.unpack(">H", data[:2])[0]
        rest = data[2 + n :]
        if len(rest) >= 2:
            m = struct.unpack(">H", rest[:2])[0]
            return rest[2 : 2 + m].decode("utf-8", "replace")
    return data


def decode(data: bytes) -> Response:
    """An IPP response. Raises IppError when it is cut short or isn't IPP."""
    if len(data) < 8:
        raise IppError("not an IPP answer (too short)")
    _major, _minor, status, request_id = struct.unpack(">BBHI", data[:8])
    response = Response(status, request_id)
    i = 8
    attrs: Attributes | None = None
    name = ""
    depth = 0  # inside a collection: its members are skipped
    try:
        while i < len(data):
            tag = data[i]
            i += 1
            if tag == END:
                return response
            if tag in GROUPS:
                attrs = {}
                response.groups.append((tag, attrs))
                continue
            if tag < 0x10:
                raise IppError(f"unknown group tag 0x{tag:02x}")
            (n,) = struct.unpack(">H", data[i : i + 2])
            key = data[i + 2 : i + 2 + n].decode("utf-8", "replace")
            i += 2 + n
            (m,) = struct.unpack(">H", data[i : i + 2])
            value = data[i + 2 : i + 2 + m]
            if len(value) != m:
                raise IppError("not an IPP answer (cut short)")
            i += 2 + m
            if tag == BEGIN_COLLECTION:
                if depth == 0 and key:
                    name = key
                    if attrs is not None:
                        attrs.setdefault(name, [])
                depth += 1
                continue
            if tag == END_COLLECTION:
                depth = max(0, depth - 1)
                continue
            if depth:
                continue  # a collection's member: not needed here
            if key:
                name = key
            if attrs is None or not name:
                raise IppError("not an IPP answer (an attribute outside a group)")
            values = attrs.setdefault(name, [])
            if tag != NO_VALUE:
                values.append(_decoded(tag, value))
    except struct.error:
        raise IppError("not an IPP answer (cut short)") from None
    raise IppError("not an IPP answer (no end tag)")


# ---------------------------------------------------------------- transport


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


def server() -> tuple[str, str | int]:
    """("unix", path) or ("tcp", "host:port") for the cupsd to ask."""
    explicit = os.environ.get("CUPS_SERVER", "").strip()
    if explicit.startswith("/"):
        return "unix", explicit
    if explicit:
        host, _, port = explicit.rpartition(":") if ":" in explicit else (explicit, "", "")
        return "tcp", f"{host or explicit}:{port or PORT}"
    if SOCKET.exists():
        return "unix", str(SOCKET)
    return "tcp", f"localhost:{PORT}"


class Client:
    """Requests to one cupsd, each on a connection of its own (a held Get-Notifications never
    blocks a read). `close` from another thread ends a request that is waiting."""

    def __init__(self, timeout: float = 2.0) -> None:
        self.timeout = timeout
        self.request_id = 0
        self._open: http.client.HTTPConnection | None = None

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        kind, where = server()
        if kind == "unix":
            return _UnixConnection(str(where), timeout)
        host, _, port = str(where).rpartition(":")
        return http.client.HTTPConnection(host, int(port), timeout=timeout)

    def call(
        self,
        operation: int,
        attributes: Iterable[Attribute],
        *,
        path: str = "/",
        timeout: float | None = None,
    ) -> Response:
        """Send one request and decode the answer. Raises IppError when cupsd can't be reached
        or doesn't answer IPP; a refusal is a Response whose `ok` is False."""
        self.request_id += 1
        body = encode(operation, self.request_id, attributes)
        conn = self._connection(self.timeout if timeout is None else timeout)
        self._open = conn
        try:
            conn.request("POST", path, body, {"Content-Type": "application/ipp"})
            answer = conn.getresponse()
            data = answer.read()
            if answer.status != 200:
                raise IppError(f"cupsd answered HTTP {answer.status}")
        except TimeoutError:
            raise IppError("cupsd took too long", timed_out=True) from None
        except (OSError, http.client.HTTPException) as e:
            raise IppError(f"cupsd not answering: {type(e).__name__}") from None
        finally:
            self._open = None
            conn.close()
        return decode(data)

    def close(self) -> None:
        """End a request that is waiting (from another thread)."""
        conn = self._open
        if conn is not None and conn.sock is not None:
            with contextlib.suppress(OSError):
                conn.sock.shutdown(socket.SHUT_RDWR)


def keywords(attrs: Attributes, name: str) -> list[str]:
    return [str(v) for v in attrs.get(name, []) if isinstance(v, str)]


def integers(attrs: Attributes, name: str) -> list[int]:
    return [v for v in attrs.get(name, []) if isinstance(v, int) and not isinstance(v, bool)]


def text(attrs: Attributes, name: str, default: str = "") -> str:
    found = keywords(attrs, name)
    return found[0] if found else default


def integer(attrs: Attributes, name: str, default: int = 0) -> int:
    found = integers(attrs, name)
    return found[0] if found else default


def boolean(attrs: Attributes, name: str, default: bool = False) -> bool:
    found = [v for v in attrs.get(name, []) if isinstance(v, bool)]
    return found[0] if found else default

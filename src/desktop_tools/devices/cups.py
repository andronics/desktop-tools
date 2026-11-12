"""The printer's state from cupsd over IPP (record 0004 §1-2), and the tier the bar shows.

`read` makes three requests to the local cupsd (CUPS-Get-Printers, CUPS-Get-Default, Get-Jobs
on the default queue) and never asks for a job's name: a job is its number, state, reasons,
owner and age. `view` turns a reading, the queue's reachability and the low supplies already
alerted today into the tier, glyph, label, detail and count (§1's table). Nothing here logs a
queue's device URI, a host or a job title.

Supplies: `marker-levels` with `marker-names` when the printer gives them; without names (an
IPP Everywhere queue to this printer gives none), the four markers are named by the order the
printer reports them, M, C, Y, BK (Stephen, 2026-11-12).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from desktop_tools.devices import ipp

# printer-state
IDLE, PROCESSING, STOPPED = 3, 4, 5
# job-state
PENDING, HELD, JOB_PROCESSING, JOB_STOPPED = 3, 4, 5, 6
UNFINISHED = (PENDING, HELD, JOB_PROCESSING, JOB_STOPPED)
JOB_STATES = {
    PENDING: "waiting",
    HELD: "held",
    JOB_PROCESSING: "printing",
    JOB_STOPPED: "stopped",
}

LOCAL_SCHEMES = frozenset({"usb", "parallel", "serial", "hp", "file", "cups-pdf"})
NETWORK_SCHEMES = frozenset(
    {"socket", "ipp", "ipps", "http", "https", "lpd", "smb", "dnssd", "implicitclass"}
)
DEFAULT_MARKERS = ("M", "C", "Y", "BK")
MARKER_WORDS = {
    "M": "magenta",
    "C": "cyan",
    "Y": "yellow",
    "K": "black",
    "BK": "black",
    "PBK": "photo black",
    "LC": "light cyan",
    "LM": "light magenta",
}

PRINTER = "\U000f042a"  # md-printer
PRINTER_ALERT = "\U000f042c"  # md-printer_alert
TRAY_ALERT = "\U000f1295"  # md-tray_alert
WATER_ALERT = "\U000f1502"  # md-water_alert
PRINTER_OFF = "\U000f0e5d"  # md-printer_off: away
PRINTER_OFF_OUTLINE = "\U000f1785"  # md-printer_off_outline: no CUPS, no queue

PRINTER_ATTRS = (
    "printer-name",
    "printer-state",
    "printer-state-reasons",
    "printer-is-accepting-jobs",
    "device-uri",
    "marker-names",
    "marker-levels",
    "marker-low-levels",
    "marker-types",
)
# Never job-name: the title is not read (§7).
JOB_ATTRS = (
    "job-id",
    "job-state",
    "job-state-reasons",
    "job-originating-user-name",
    "time-at-creation",
)


class CupsDown(Exception):
    """cupsd isn't answering."""


@dataclass
class Marker:
    name: str  # the printer's (M, C, Y, BK), or by order
    level: int  # percent, -1 unknown
    low: int  # percent at which it is low (0: unknown)

    @property
    def word(self) -> str:
        return MARKER_WORDS.get(self.name.upper(), self.name.lower())


@dataclass
class Queue:
    name: str
    state: int
    reasons: list[str]
    accepting: bool
    uri: str
    markers: list[Marker] = field(default_factory=list)

    @property
    def scheme(self) -> str:
        return self.uri.split(":", 1)[0].lower() if ":" in self.uri else ""

    @property
    def network(self) -> bool:
        return self.scheme in NETWORK_SCHEMES

    @property
    def host(self) -> str:
        """The device URI's host, for the reachability check (never logged)."""
        if self.scheme in ("dnssd", "implicitclass"):
            return ""
        try:
            return (urlsplit(self.uri).hostname or "").lower()
        except ValueError:
            return ""


@dataclass
class Job:
    id: int
    state: int
    reasons: list[str]
    user: str
    created: int  # epoch seconds, 0 unknown

    @property
    def word(self) -> str:
        return JOB_STATES.get(self.state, "unknown")


@dataclass
class Reading:
    queues: list[Queue]
    default: str  # the default queue's name, "" when none
    jobs: list[Job]  # the default queue's unfinished jobs

    @property
    def queue(self) -> Queue | None:
        return next((q for q in self.queues if q.name == self.default), None)


def markers(attrs: ipp.Attributes) -> list[Marker]:
    levels = ipp.integers(attrs, "marker-levels")
    lows = ipp.integers(attrs, "marker-low-levels")
    names = ipp.keywords(attrs, "marker-names")
    if len(names) != len(levels):
        names = list(DEFAULT_MARKERS) if len(levels) == len(DEFAULT_MARKERS) else []
        names += [f"supply {i + 1}" for i in range(len(names), len(levels))]
    return [
        Marker(names[i], level, lows[i] if i < len(lows) else 0) for i, level in enumerate(levels)
    ]


def queue(attrs: ipp.Attributes) -> Queue:
    return Queue(
        ipp.text(attrs, "printer-name"),
        ipp.integer(attrs, "printer-state", IDLE),
        [r for r in ipp.keywords(attrs, "printer-state-reasons") if r != "none"],
        ipp.boolean(attrs, "printer-is-accepting-jobs", True),
        ipp.text(attrs, "device-uri"),
        markers(attrs),
    )


def user_default(home: Path | None = None) -> str:
    """The user's default (`lpoptions -d`, in ~/.cups/lpoptions), as `lp` honours it first."""
    path = (home or Path.home()) / ".cups" / "lpoptions"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        words = line.split()
        if len(words) >= 2 and words[0].lower() == "default":
            return words[1].split("/", 1)[0]
    return ""


def queue_uri(name: str) -> str:
    return f"ipp://localhost/printers/{name}"


def jobs(client: ipp.Client, name: str) -> list[Job]:
    found = client.call(
        ipp.GET_JOBS,
        [
            *ipp.standard(queue_uri(name)),
            ipp.Attribute(ipp.OPERATION, "which-jobs", ipp.KEYWORD, ["not-completed"]),
            ipp.Attribute(ipp.OPERATION, "requested-attributes", ipp.KEYWORD, list(JOB_ATTRS)),
        ],
    )
    if not found.ok:
        return []
    out = []
    for attrs in found.all(ipp.JOB):
        out.append(
            Job(
                ipp.integer(attrs, "job-id"),
                ipp.integer(attrs, "job-state"),
                ipp.keywords(attrs, "job-state-reasons"),
                ipp.text(attrs, "job-originating-user-name"),
                ipp.integer(attrs, "time-at-creation"),
            )
        )
    return [j for j in out if j.state in UNFINISHED]


def read(client: ipp.Client | None = None) -> Reading:
    """The queues, the default and its unfinished jobs. Raises CupsDown when cupsd doesn't
    answer."""
    client = client or ipp.Client()
    try:
        printers = client.call(
            ipp.CUPS_GET_PRINTERS,
            [
                *ipp.standard(),
                ipp.Attribute(
                    ipp.OPERATION, "requested-attributes", ipp.KEYWORD, list(PRINTER_ATTRS)
                ),
            ],
        )
        queues = [queue(a) for a in printers.all(ipp.PRINTER)] if printers.ok else []
        queues = [q for q in queues if q.name]
        default = user_default()
        if default not in {q.name for q in queues}:
            answer = client.call(
                ipp.CUPS_GET_DEFAULT,
                [
                    *ipp.standard(),
                    ipp.Attribute(
                        ipp.OPERATION, "requested-attributes", ipp.KEYWORD, ["printer-name"]
                    ),
                ],
            )
            default = ipp.text(answer.first(ipp.PRINTER), "printer-name") if answer.ok else ""
        if default not in {q.name for q in queues}:
            default = queues[0].name if len(queues) == 1 else ""
        found = jobs(client, default) if default else []
    except ipp.IppError as e:
        if e.status is None:
            raise CupsDown(str(e)) from None
        raise
    return Reading(queues, default, found)


# ---------------------------------------------------------------- the tier


def base(reason: str) -> str:
    """A state reason without CUPS's -error, -warning or -report suffix."""
    for suffix in ("-error", "-warning", "-report"):
        if reason.endswith(suffix) and reason != "offline-report":
            return reason[: -len(suffix)]
    return reason


PAPER = {
    "media-empty": "out of paper",
    "media-needed": "load paper",
    "media-jam": "paper jam",
    "input-tray-missing": "paper tray missing",
}
COVER = {"cover-open": "cover open", "door-open": "door open"}
EMPTY = ("marker-supply-empty", "toner-empty")
LOW = ("marker-supply-low", "toner-low")


@dataclass
class View:
    tier: str
    glyph: str
    label: str
    detail: str = ""
    count: int = 0
    target: str = ""
    lows: list[str] = field(default_factory=list)  # the low supplies, by word
    alerts: list[str] = field(default_factory=list)  # every alert reason, in words


def supplies(q: Queue) -> tuple[list[str], list[str]]:
    """(empty, low) supplies by word, from the levels and the state reasons."""
    reasons = {base(r) for r in q.reasons}
    empty = [m.word for m in q.markers if m.level == 0]
    low = [m.word for m in q.markers if 0 < m.level <= max(m.low, 0) and m.low > 0]
    if not empty and reasons & set(EMPTY):
        empty = ["ink"]
    if not low and reasons & set(LOW):
        low = ["ink"]
    return empty, low


def levels(q: Queue) -> str:
    """`magenta 44%, cyan 71%, …` (unknown levels left out)."""
    return ", ".join(f"{m.word} {m.level}%" for m in q.markers if m.level >= 0)


def _waiting(n: int) -> str:
    return f"{n} waiting"


def view(
    reading: Reading | None,
    *,
    reachable: bool = True,
    polling: str = "",
    low_new: Iterable[str] = (),
) -> View:
    """The printer module's tier, glyph, label, detail and count (§1). `reading` None means
    cupsd isn't answering. `low_new` are the low supplies not yet alerted today: they alert;
    the others show in the detail only."""
    if reading is None:
        return View("unavailable", PRINTER_OFF_OUTLINE, "CUPS not running")
    q = reading.queue
    if q is None:
        label = "no printer" if not reading.queues else "no default printer"
        return View("unavailable", PRINTER_OFF_OUTLINE, label)
    unfinished = reading.jobs
    count = len(unfinished)
    reasons = {base(r) for r in q.reasons}
    empty, low = supplies(q)
    notes = [n for n in (levels(q), polling) if n]
    out = View("idle", PRINTER, "ready", count=count, target=q.name, lows=low)

    alerts: list[tuple[str, str]] = []  # (glyph, words)
    if q.network and not reachable:
        if not unfinished:
            out.tier, out.glyph, out.label, out.count = "unavailable", PRINTER_OFF, "away", 0
            out.detail = "; ".join(["the printer can't be reached", *notes])
            return out
        alerts.append((PRINTER_ALERT, f"not reachable, {_waiting(count)}"))
    if q.state == STOPPED:
        alerts.append((PRINTER_ALERT, "paused"))
    if not q.accepting:
        alerts.append((PRINTER_ALERT, "not accepting jobs"))
    alerts += [(TRAY_ALERT, words) for r, words in PAPER.items() if r in reasons]
    alerts += [(PRINTER_ALERT, words) for r, words in COVER.items() if r in reasons]
    if empty:
        alerts.append((WATER_ALERT, "ink empty: " + ", ".join(empty)))
    if "marker-waste-full" in reasons or "marker-waste-almost-full" in reasons:
        alerts.append((WATER_ALERT, "waste ink full"))
    if "offline-report" in q.reasons or "offline" in reasons:
        alerts.append((PRINTER_ALERT, "printer offline"))
    held = sum(1 for j in unfinished if j.state == HELD)
    if held:
        alerts.append((PRINTER_ALERT, f"{held} held"))
    if any(j.state == JOB_STOPPED for j in unfinished):
        alerts.append((PRINTER_ALERT, "the printer refused the job; the queue may be paused"))
    fresh = [w for w in low if w in set(low_new)]
    if fresh:
        alerts.append((WATER_ALERT, "ink low: " + ", ".join(fresh)))
    if low and not fresh:
        notes.insert(0, "ink low: " + ", ".join(low))

    out.alerts = [w for _g, w in alerts]
    if alerts:
        out.tier, out.glyph, out.label = "alert", alerts[0][0], alerts[0][1]
        out.detail = "; ".join([*out.alerts, *notes])
        return out
    printing = any(j.state == JOB_PROCESSING for j in unfinished) or q.state == PROCESSING
    if unfinished:
        out.tier = "active"
        out.label = "printing" if printing else _waiting(count)
        extra = count - 1 if printing else 0
        if printing and extra:
            notes.insert(0, _waiting(extra))
    out.detail = "; ".join(notes)
    return out


def words(r: Reading | None, *, reachable: bool = True) -> list[str]:
    """The full state in lines, for the menu's info row and `devices printer status` (no
    device URI, host or job title)."""
    if r is None:
        return ["CUPS is not running"]
    q = r.queue
    if q is None:
        return ["No printer is set up" if not r.queues else "No default printer"]
    shown = view(r, reachable=reachable)
    kind = "network" if q.network else "local"
    lines = [
        f"Queue: {q.name} (default)",
        f"Kind: {kind}" + (f", {'reachable' if reachable else 'away'}" if q.network else ""),
        f"Accepting jobs: {'yes' if q.accepting else 'no'}",
        f"Paused: {'yes' if q.state == STOPPED else 'no'}",
        f"State: {shown.label}",
    ]
    reasons = sorted({base(x) for x in q.reasons} - {"none"})
    reasons = [x for x in reasons if not x.startswith("cups-")]
    if reasons:
        lines.append("Reasons: " + ", ".join(reasons))
    if q.markers:
        lines.append("Supplies: " + (levels(q) or "unknown"))
    lines.append(f"Jobs: {len(r.jobs)}")
    if len(r.queues) > 1:
        lines.append("Other queues: " + ", ".join(x.name for x in r.queues if x.name != q.name))
    return lines


def age(created: int, now: float | None = None) -> str:
    """`3 min ago`, `2 h ago`; `just now` under a minute; empty when unknown."""
    if created <= 0:
        return ""
    seconds = max(0, int((time.time() if now is None else now) - created))
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if seconds >= size:
            return f"{seconds // size} {unit} ago"
    return ""  # pragma: no cover - the loop always returns past a minute


# ---------------------------------------------------------------- the pull subscription (§2.2)

EVENTS = (
    "printer-state-changed",
    "printer-added",
    "printer-deleted",
    "printer-modified",
    "job-created",
    "job-state-changed",
    "job-completed",
)
LEASE = 3600  # seconds: a crashed source's subscription lapses within the hour
SERVER_URI = "ipp://localhost/"


class Refused(Exception):
    """cupsd wouldn't make the subscription: the source polls instead."""


def subscribe(client: ipp.Client) -> int:
    """Create-Printer-Subscriptions (ippget, §2.2's events, a one-hour lease): its id. Raises
    Refused, or ipp.IppError when cupsd doesn't answer."""
    answer = client.call(
        ipp.CREATE_PRINTER_SUBSCRIPTIONS,
        [
            *ipp.standard(SERVER_URI),
            ipp.Attribute(ipp.SUBSCRIPTION, "notify-pull-method", ipp.KEYWORD, ["ippget"]),
            ipp.Attribute(ipp.SUBSCRIPTION, "notify-events", ipp.KEYWORD, list(EVENTS)),
            ipp.Attribute(ipp.SUBSCRIPTION, "notify-lease-duration", ipp.INTEGER, [LEASE]),
        ],
    )
    found = ipp.integers(answer.first(ipp.SUBSCRIPTION), "notify-subscription-id")
    if not answer.ok or not found:
        raise Refused(ipp.status_name(answer.status))
    return found[0]


@dataclass
class Notifications:
    events: int  # how many arrived
    sequence: int  # the next sequence number to ask for
    interval: float  # seconds cupsd asks us to wait before asking again (0: it didn't say)
    gone: bool = False  # the subscription is no more (lapsed, or cupsd restarted)


def notifications(
    client: ipp.Client, subscription: int, sequence: int, timeout: float
) -> Notifications:
    """Get-Notifications with notify-wait: cupsd holds it until an event or its interval."""
    answer = client.call(
        ipp.GET_NOTIFICATIONS,
        [
            *ipp.standard(SERVER_URI),
            ipp.Attribute(ipp.OPERATION, "notify-subscription-ids", ipp.INTEGER, [subscription]),
            ipp.Attribute(ipp.OPERATION, "notify-sequence-numbers", ipp.INTEGER, [sequence]),
            ipp.Attribute(ipp.OPERATION, "notify-wait", ipp.BOOLEAN, [True]),
        ],
        timeout=timeout,
    )
    interval = float(ipp.integer(answer.first(ipp.OPERATION), "notify-get-interval", 0))
    if not answer.ok:
        return Notifications(0, sequence, interval, gone=answer.status == ipp.NOT_FOUND)
    events = answer.all(ipp.EVENT)
    numbers = [n for e in events for n in ipp.integers(e, "notify-sequence-number")]
    return Notifications(len(events), max([sequence - 1, *numbers]) + 1, interval)


def renew(client: ipp.Client, subscription: int) -> bool:
    """Renew-Subscription for another lease; False when cupsd no longer has it."""
    answer = client.call(
        ipp.RENEW_SUBSCRIPTION,
        [
            *ipp.standard(SERVER_URI),
            ipp.Attribute(ipp.OPERATION, "notify-subscription-id", ipp.INTEGER, [subscription]),
            ipp.Attribute(ipp.SUBSCRIPTION, "notify-lease-duration", ipp.INTEGER, [LEASE]),
        ],
    )
    return answer.ok


def cancel(client: ipp.Client, subscription: int) -> None:
    """Cancel-Subscription, quietly (it lapses within the hour anyway)."""
    with contextlib.suppress(ipp.IppError):
        client.call(
            ipp.CANCEL_SUBSCRIPTION,
            [
                *ipp.standard(SERVER_URI),
                ipp.Attribute(ipp.OPERATION, "notify-subscription-id", ipp.INTEGER, [subscription]),
            ],
        )

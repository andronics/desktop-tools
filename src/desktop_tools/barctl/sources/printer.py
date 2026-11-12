"""printer: the default CUPS queue's state (record 0004 §1-2), from IPP to the local cupsd.

Events first: one pull subscription (`ippget`, a one-hour lease renewed every RENEW_EVERY
seconds, cancelled when the source stops), then Get-Notifications with notify-wait in a loop, so
the source wakes on cupsd's events, not a timer. Any event re-reads the state, DEBOUNCE seconds
later, so a burst is one read. If cupsd refuses a subscription the source polls the same reads,
every POLL_IDLE seconds with no jobs and POLL_BUSY while jobs are unfinished, and its detail says
`polling: CUPS refused a subscription`.

Reachability, for a network queue: DNS-SD from `avahi-browse` (a resolved service on the
queue's host); when avahi says nothing of the host, a TCP connect to 631, then 80 (never 9100),
at most every PROBE_IDLE seconds idle and PROBE_BUSY while jobs wait, two failures in a row
before it is unreachable. Away with nothing waiting is `unavailable`; away with jobs, `alert`.

An alert that appears blinks once (ALERT_FOR seconds); a low supply alerts once per supply per
day, for LOW_SHOW seconds, then shows in the detail with the tier back to idle. Nothing here
prints, cancels or pauses, and no job title, device URI or host is written or logged.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from desktop_tools.barctl.sources.base import Source
from desktop_tools.barctl.store import Writer
from desktop_tools.devices import cups, ipp, mdns

DEBOUNCE = 0.5
POLL_IDLE = 30.0
POLL_BUSY = 5.0
HOLD = 70.0  # seconds a held Get-Notifications may take before it counts as "no events"
QUICK = 1.0  # an answer sooner than this with no events: cupsd didn't hold it, so wait
INTERVAL_MAX = 60.0
RENEW_EVERY = 1800.0
PROBE_IDLE = 300.0
PROBE_BUSY = 60.0
ALERT_FOR = 10.0
LOW_SHOW = 60.0
REFUSED = "polling: CUPS refused a subscription"


@dataclass
class Reach:
    """A network queue's host and what the probes said."""

    host: str = ""
    ok: bool = True  # reachable until two probes in a row fail
    failures: int = 0
    at: float = -1e9  # when it was last probed


class PrinterSource(Source):
    name = "printer"
    optional = ("avahi-browse",)

    def __init__(self, modules: Sequence[str], writer: Writer) -> None:
        super().__init__(modules, writer)
        self.client = ipp.Client(timeout=2.0)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.clock: Callable[[], float] = time.time
        self.probe: Callable[[str], bool] = mdns.probe
        self.reading: cups.Reading | None = None
        self.subscription: int | None = None
        self.sequence = 1
        self.renewed = 0.0
        self.polling = ""
        self.reach = Reach()
        self.browser: mdns.Browser | None = None
        self.low_seen: dict[str, str] = {}  # supply word -> the day it alerted
        self.low_until: dict[str, float] = {}
        self.alerting: set[str] = set()

    # ------------------------------------------------------------ reading and writing

    def reachable(self, q: cups.Queue, now: float, waiting: bool) -> bool:
        if not q.network or not q.host:
            return True
        if q.host != self.reach.host:
            self.reach = Reach(q.host)
        if self.browser is not None and self.browser.has_host(q.host):
            self.reach.ok, self.reach.failures = True, 0
            return True
        due = PROBE_BUSY if waiting or self.reach.failures else PROBE_IDLE
        if now - self.reach.at >= due:
            self.reach.at = now
            if self.probe(q.host):
                self.reach.ok, self.reach.failures = True, 0
            else:
                self.reach.failures += 1
                self.reach.ok = self.reach.failures < 2 and self.reach.ok
        return self.reach.ok

    def read(self) -> None:
        try:
            self.reading = cups.read(self.client)
        except (cups.CupsDown, ipp.IppError):
            self.reading = None

    def lows(self, reading: cups.Reading | None, now: float) -> list[str]:
        """The low supplies that alert now: each once a day, for LOW_SHOW seconds."""
        q = reading.queue if reading is not None else None
        if q is None:
            return []
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        out = []
        for word in cups.supplies(q)[1]:
            if self.low_seen.get(word) != today:
                self.low_seen[word] = today
                self.low_until[word] = now + LOW_SHOW
            if now < self.low_until.get(word, 0):
                out.append(word)
        return out

    def write(self) -> cups.View:
        with self.lock:
            now = self.clock()
            reading = self.reading
            q = reading.queue if reading is not None else None
            waiting = bool(reading and reading.jobs)
            reachable = self.reachable(q, now, waiting) if q is not None else True
            shown = cups.view(
                reading, reachable=reachable, polling=self.polling, low_new=self.lows(reading, now)
            )
            new = set(shown.alerts) - self.alerting
            self.alerting = set(shown.alerts)
            blink = ALERT_FOR if shown.tier == "alert" and new else None
            for module in self.modules:
                self.writer.set(
                    module,
                    self.name,
                    shown.tier,
                    glyph=shown.glyph,
                    label=shown.label,
                    count=shown.count or None,
                    target=shown.target or None,
                    detail=shown.detail or None,
                    alert_for=blink,
                    now=now,
                )
            return shown

    def refresh(self) -> None:
        with self.lock:
            self.read()
            self.write()

    # ------------------------------------------------------------ the subscription

    def subscribe(self) -> None:
        try:
            self.subscription = cups.subscribe(self.client)
        except cups.Refused:
            self.subscription, self.polling = None, REFUSED
            return
        except ipp.IppError:
            self.subscription = None  # cupsd down: polled until it answers, then asked again
            return
        self.sequence, self.renewed, self.polling = 1, self.clock(), ""

    def unsubscribe(self) -> None:
        if self.subscription is not None:
            cups.cancel(ipp.Client(timeout=1.0), self.subscription)
            self.subscription = None

    def renew(self) -> None:
        if self.subscription is None or self.clock() - self.renewed < RENEW_EVERY:
            return
        try:
            kept = cups.renew(self.client, self.subscription)
        except ipp.IppError:
            return
        if kept:
            self.renewed = self.clock()
        else:
            self.subscribe()

    def listen(self) -> bool:
        """One held Get-Notifications: whether to re-read the state."""
        assert self.subscription is not None  # noqa: S101 - the caller checked
        started = time.monotonic()
        try:
            got = cups.notifications(self.client, self.subscription, self.sequence, HOLD)
        except ipp.IppError as e:
            if e.timed_out:
                return False
            self.subscription = None  # cupsd went: poll until it is back
            return True
        self.sequence = got.sequence
        if got.gone:
            self.subscribe()
            return True
        if got.events:
            return True
        if time.monotonic() - started < QUICK:
            wait = min(max(got.interval, QUICK), INTERVAL_MAX) if got.interval else POLL_BUSY
            self.wake.wait(wait)
            self.wake.clear()
        return False

    # ------------------------------------------------------------ following

    def follow(self) -> None:
        with self.lock:
            self.reading, self.alerting, self.reach = None, set(), Reach()
            self.wake.clear()
        self.browser = mdns.Browser(mdns.PRINTER_TYPES, self.changed)
        if not self.browser.start():
            self.browser = None
        try:
            self.refresh()
            self.subscribe()
            while not self.stopping:
                if self.subscription is not None:
                    again = self.listen()
                    self.renew()
                else:
                    busy = bool(self.reading and self.reading.jobs)
                    self.wake.wait(POLL_BUSY if busy else POLL_IDLE)
                    self.wake.clear()
                    again = True
                    if self.reading is not None and not self.polling and not self.stopping:
                        self.subscribe()  # cupsd is back
                if self.stopping:
                    return
                if again:
                    self.wake.wait(DEBOUNCE)  # a burst of events is one read
                    self.wake.clear()
                    self.refresh()
                else:
                    self.write()  # the timers: a low supply's alert ends, a probe is due
        finally:
            self.unsubscribe()
            if self.browser is not None:
                self.browser.stop()
                self.browser = None

    def changed(self) -> None:
        """DNS-SD said a printer service came or went: the tier again, no IPP read."""
        if not self.stopping:
            self.write()

    def stop(self) -> None:
        super().stop()
        self.wake.set()
        self.client.close()

    def gone(self) -> None:
        with self.lock:
            self.reading = None
            self.write()

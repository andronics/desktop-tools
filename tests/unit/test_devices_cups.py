"""The IPP client and the printer's reading and tier (record 0004 §1-2), against a fake cupsd on
a Unix socket: the codec's bytes, each operation's request, §1's tier table row by row, the
supplies named M, C, Y, BK by order, and no job title asked for or shown."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from desktop_tools.devices import cups, ipp
from tests.devices_fakes import FakeCups, attr, job_attrs, printer_attrs

# ---------------------------------------------------------------- the codec


def test_encode_matches_the_bytes_by_hand() -> None:
    """CUPS-Get-Default as RFC 8010 lays it out, written out byte by byte."""
    got = ipp.encode(
        ipp.CUPS_GET_DEFAULT,
        7,
        [
            ipp.Attribute(ipp.OPERATION, "attributes-charset", ipp.CHARSET_TAG, ["utf-8"]),
            ipp.Attribute(ipp.OPERATION, "requested-attributes", ipp.KEYWORD, ["a", "bc"]),
        ],
    )
    want = (
        b"\x01\x01\x40\x01\x00\x00\x00\x07"  # 1.1, CUPS-Get-Default, request 7
        b"\x01"  # operation-attributes
        b"\x47\x00\x12attributes-charset\x00\x05utf-8"
        b"\x44\x00\x14requested-attributes\x00\x01a"
        b"\x44\x00\x00\x00\x02bc"  # an additional value: no name
        b"\x03"
    )
    assert got == want


def test_round_trip_and_value_kinds() -> None:
    data = ipp.encode(
        0x0000,
        1,
        [
            attr(ipp.OPERATION, "attributes-charset", ipp.CHARSET_TAG, "utf-8"),
            attr(ipp.PRINTER, "printer-state", ipp.ENUM, 5),
            attr(ipp.PRINTER, "printer-is-accepting-jobs", ipp.BOOLEAN, False),
            attr(ipp.PRINTER, "marker-levels", ipp.INTEGER, 44, -1),
            attr(ipp.PRINTER, "printer-name", ipp.NAME, "Office"),
            attr(ipp.JOB, "job-id", ipp.INTEGER, 3),
        ],
    )
    found = ipp.decode(data)
    assert found.ok and found.request_id == 1
    printer = found.first(ipp.PRINTER)
    assert printer["printer-state"] == [5]
    assert printer["printer-is-accepting-jobs"] == [False]
    assert printer["marker-levels"] == [44, -1]
    assert found.first(ipp.JOB) == {"job-id": [3]}
    assert ipp.text(printer, "printer-name") == "Office"
    assert ipp.boolean(printer, "missing", True) is True


def test_decode_skips_collections_and_reads_text_with_language() -> None:
    body = bytearray(struct.pack(">BBHI", 1, 1, 0, 9))
    body += b"\x04"
    body += b"\x34\x00\x0fmedia-col-ready\x00\x00"  # begCollection
    body += b"\x4a\x00\x00\x00\x0amedia-size"  # memberAttrName
    body += b"\x34\x00\x00\x00\x00"  # a nested collection
    body += b"\x21\x00\x00\x00\x04\x00\x00\x52\x08"
    body += b"\x37\x00\x00\x00\x00\x37\x00\x00\x00\x00"  # two endCollections
    lang = struct.pack(">H", 2) + b"en" + struct.pack(">H", 5) + b"hello"
    body += b"\x35\x00\x0cprinter-info" + struct.pack(">H", len(lang)) + lang
    body += b"\x13\x00\x08no-value\x00\x00"
    body += b"\x03"
    found = ipp.decode(bytes(body))
    printer = found.first(ipp.PRINTER)
    assert printer["media-col-ready"] == []
    assert printer["printer-info"] == ["hello"]
    assert printer["no-value"] == []


@pytest.mark.parametrize(
    "data",
    [b"\x01\x01", b"\x01\x01\x00\x00\x00\x00\x00\x01\x04\x21\x00\x05ab", b"\x01\x01" + b"\0" * 6],
)
def test_a_cut_answer_is_an_error(data: bytes) -> None:
    with pytest.raises(ipp.IppError):
        ipp.decode(data)


def test_unknown_group_and_attribute_outside_a_group() -> None:
    with pytest.raises(ipp.IppError):
        ipp.decode(b"\x01\x01\x00\x00\x00\x00\x00\x01\x09\x03")
    with pytest.raises(ipp.IppError):
        ipp.decode(b"\x01\x01\x00\x00\x00\x00\x00\x01\x21\x00\x01a\x00\x04\x00\x00\x00\x01\x03")


def test_encode_refuses_a_wrong_kind() -> None:
    with pytest.raises(TypeError):
        ipp.encode(1, 1, [ipp.Attribute(ipp.OPERATION, "x", ipp.INTEGER, ["text"])])
    with pytest.raises(TypeError):
        ipp.encode(1, 1, [ipp.Attribute(ipp.OPERATION, "x", ipp.KEYWORD, [3])])


def test_the_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CUPS_SERVER", "/x/cups.sock")
    assert ipp.server() == ("unix", "/x/cups.sock")
    monkeypatch.setenv("CUPS_SERVER", "print.example")
    assert ipp.server() == ("tcp", "print.example:631")
    monkeypatch.setenv("CUPS_SERVER", "print.example:8631")
    assert ipp.server() == ("tcp", "print.example:8631")
    monkeypatch.delenv("CUPS_SERVER")
    monkeypatch.setattr(ipp, "SOCKET", tmp_path / "missing.sock")
    assert ipp.server() == ("tcp", "localhost:631")
    (tmp_path / "here.sock").touch()
    monkeypatch.setattr(ipp, "SOCKET", tmp_path / "here.sock")
    assert ipp.server() == ("unix", str(tmp_path / "here.sock"))
    assert ipp.status_name(0x0403) == "client-error-not-authorized"
    assert ipp.status_name(0x0999) == "0x0999"


def test_no_cupsd_is_cups_down() -> None:
    """CUPS_SERVER is a socket nothing listens on (conftest)."""
    with pytest.raises(cups.CupsDown):
        cups.read()


# ---------------------------------------------------------------- reading


def test_read_against_the_fake(cupsd: FakeCups) -> None:
    cupsd.jobs["Office"] = [job_attrs(12, cups.JOB_PROCESSING), job_attrs(13)]
    found = cups.read()
    assert [q.name for q in found.queues] == ["Office"]
    assert found.default == "Office" and [j.id for j in found.jobs] == [12, 13]
    q = found.queue
    assert q is not None and q.network and q.host == "printer.example" and q.accepting
    assert [(m.name, m.word, m.level) for m in q.markers] == [
        ("M", "magenta", 44),
        ("C", "cyan", 71),
        ("Y", "yellow", 69),
        ("BK", "black", 72),
    ]
    ops = cupsd.ops()
    assert ops == [ipp.CUPS_GET_PRINTERS, ipp.CUPS_GET_DEFAULT, ipp.GET_JOBS]
    asked = [str(v) for r in cupsd.requests for v in r.attrs.get("requested-attributes", [])]
    assert "job-name" not in asked  # §2.1: the title is never asked for
    jobs = cupsd.requests[-1].attrs
    assert jobs["printer-uri"] == ["ipp://localhost/printers/Office"]
    assert jobs["which-jobs"] == ["not-completed"]


def test_marker_names_win_when_given(cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("Office", levels=(10, 50), lows=(15, 15), names=("K", "C"))]
    q = cups.read().queue
    assert q is not None and [m.word for m in q.markers] == ["black", "cyan"]
    cupsd.printers = [printer_attrs("Office", levels=(10, 50, 9), lows=(15, 15, 15))]
    q = cups.read().queue
    assert q is not None and [m.name for m in q.markers] == ["supply 1", "supply 2", "supply 3"]


def test_the_users_default_wins(
    cupsd: FakeCups, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`lpoptions -d` writes ~/.cups/lpoptions; lp honours it before cupsd's default."""
    cupsd.printers = [printer_attrs("Office"), printer_attrs("Home", uri="usb://Brand/Model")]
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".cups").mkdir()
    (tmp_path / ".cups" / "lpoptions").write_text("Dest Office\nDefault Home/duplex\n")
    found = cups.read()
    assert found.default == "Home"
    assert ipp.CUPS_GET_DEFAULT not in cupsd.ops()
    q = found.queue
    assert q is not None and not q.network and q.host == "brand"


def test_one_queue_is_the_default_without_one(cupsd: FakeCups) -> None:
    cupsd.default = ""
    assert cups.read().default == "Office"
    cupsd.printers = [printer_attrs("A"), printer_attrs("B")]
    assert cups.read().default == ""


# ---------------------------------------------------------------- the tier table (§1)


def reading(
    *, jobs: list[cups.Job] | None = None, queues: list[cups.Queue] | None = None, **q: object
) -> cups.Reading:
    base = {
        "name": "Office",
        "state": cups.IDLE,
        "reasons": [],
        "accepting": True,
        "uri": "ipp://printer.example/ipp/print",
        "markers": [cups.Marker(n, 60, 15) for n in cups.DEFAULT_MARKERS],
    }
    base.update(q)
    queue = cups.Queue(**base)  # type: ignore[arg-type]  # the test's keyword overrides
    return cups.Reading(queues or [queue], "Office", jobs or [])


def job(n: int, state: int = cups.PENDING, user: str = "me") -> cups.Job:
    return cups.Job(n, state, [], user, 0)


@pytest.mark.parametrize(
    ("r", "reachable", "tier", "glyph", "label", "count"),
    [
        (reading(), True, "idle", cups.PRINTER, "ready", 0),
        (reading(jobs=[job(1, cups.JOB_PROCESSING)]), True, "active", cups.PRINTER, "printing", 1),
        (reading(jobs=[job(1), job(2)]), True, "active", cups.PRINTER, "2 waiting", 2),
        (reading(state=cups.STOPPED), True, "alert", cups.PRINTER_ALERT, "paused", 0),
        (reading(accepting=False), True, "alert", cups.PRINTER_ALERT, "not accepting jobs", 0),
        (reading(reasons=["media-empty-error"]), True, "alert", cups.TRAY_ALERT, "out of paper", 0),
        (reading(reasons=["media-jam-error"]), True, "alert", cups.TRAY_ALERT, "paper jam", 0),
        (reading(reasons=["cover-open-error"]), True, "alert", cups.PRINTER_ALERT, "cover open", 0),
        (reading(reasons=["door-open"]), True, "alert", cups.PRINTER_ALERT, "door open", 0),
        (
            reading(markers=[cups.Marker("C", 0, 15)]),
            True,
            "alert",
            cups.WATER_ALERT,
            "ink empty: cyan",
            0,
        ),
        (
            reading(reasons=["toner-empty-error"], markers=[]),
            True,
            "alert",
            cups.WATER_ALERT,
            "ink empty: ink",
            0,
        ),
        (
            reading(reasons=["marker-waste-full-error"]),
            True,
            "alert",
            cups.WATER_ALERT,
            "waste ink full",
            0,
        ),
        (
            reading(reasons=["offline-report"]),
            True,
            "alert",
            cups.PRINTER_ALERT,
            "printer offline",
            0,
        ),
        (reading(jobs=[job(1, cups.HELD)]), True, "alert", cups.PRINTER_ALERT, "1 held", 1),
        (
            reading(jobs=[job(1, cups.JOB_STOPPED)]),
            True,
            "alert",
            cups.PRINTER_ALERT,
            "the printer refused the job; the queue may be paused",
            1,
        ),
        (
            reading(jobs=[job(1), job(2)]),
            False,
            "alert",
            cups.PRINTER_ALERT,
            "not reachable, 2 waiting",
            2,
        ),
        (reading(), False, "unavailable", cups.PRINTER_OFF, "away", 0),
        (
            reading(uri="usb://Brand/Model?serial=1"),
            False,
            "idle",
            cups.PRINTER,
            "ready",
            0,
        ),  # a local queue's reachability is CUPS's own
        (None, True, "unavailable", cups.PRINTER_OFF_OUTLINE, "CUPS not running", 0),
        (
            cups.Reading([], "", []),
            True,
            "unavailable",
            cups.PRINTER_OFF_OUTLINE,
            "no printer",
            0,
        ),
    ],
)
def test_the_tier_table(
    r: cups.Reading | None, reachable: bool, tier: str, glyph: str, label: str, count: int
) -> None:
    shown = cups.view(r, reachable=reachable)
    assert (shown.tier, shown.glyph, shown.label, shown.count) == (tier, glyph, label, count)


def test_low_supplies_alert_only_when_new() -> None:
    r = reading(markers=[cups.Marker("M", 60, 15), cups.Marker("C", 10, 15)])
    fresh = cups.view(r, low_new=["cyan"])
    assert (fresh.tier, fresh.glyph, fresh.label) == ("alert", cups.WATER_ALERT, "ink low: cyan")
    standing = cups.view(r)
    assert standing.tier == "idle" and standing.detail.startswith("ink low: cyan")
    assert "magenta 60%, cyan 10%" in standing.detail
    r = reading(reasons=["marker-supply-low-warning"], markers=[])
    assert cups.view(r).lows == ["ink"]


def test_the_detail_says_polling_and_more_waiting() -> None:
    r = reading(jobs=[job(1, cups.JOB_PROCESSING), job(2), job(3)])
    shown = cups.view(r, polling="polling: CUPS refused a subscription")
    assert shown.label == "printing" and shown.count == 3
    assert shown.detail.startswith("2 waiting") and "polling: CUPS refused" in shown.detail
    assert cups.view(reading(), reachable=False).detail.startswith("the printer can't be reached")


def test_words_for_people() -> None:
    lines = cups.words(reading(state=cups.STOPPED, reasons=["media-empty-error", "cups-x"]))
    assert "Paused: yes" in lines and "Reasons: media-empty" in lines
    assert "Supplies: magenta 60%, cyan 60%, yellow 60%, black 60%" in lines
    assert "Kind: network, reachable" in lines
    assert cups.words(None) == ["CUPS is not running"]
    assert cups.words(cups.Reading([], "", [])) == ["No printer is set up"]
    two = reading(
        queues=[cups.Queue("Office", 3, [], True, "usb://x"), cups.Queue("B", 3, [], True, "")]
    )
    assert "Other queues: B" in cups.words(two)
    assert cups.words(cups.Reading(two.queues, "", [])) == ["No default printer"]


def test_age() -> None:
    assert cups.age(0) == ""
    assert cups.age(100, now=130) == "just now"
    assert cups.age(100, now=100 + 180) == "3 min ago"
    assert cups.age(100, now=100 + 7200) == "2 h ago"
    assert cups.age(100, now=100 + 86400 * 2) == "2 d ago"


def test_reasons_lose_their_suffix() -> None:
    assert cups.base("media-empty-error") == "media-empty"
    assert cups.base("toner-low-warning") == "toner-low"
    assert cups.base("offline-report") == "offline-report"
    assert cups.base("cover-open") == "cover-open"


def test_hosts_of_device_uris() -> None:
    assert cups.Queue("a", 3, [], True, "socket://Printer.Example:9100").host == "printer.example"
    assert cups.Queue("a", 3, [], True, "dnssd://Name._ipp._tcp.local/").host == ""
    assert cups.Queue("a", 3, [], True, "usb://x").network is False
    assert cups.Queue("a", 3, [], True, "").scheme == ""


# ---------------------------------------------------------------- the subscription


def test_subscribe_listen_renew_cancel(cupsd: FakeCups) -> None:
    client = ipp.Client()
    sub = cups.subscribe(client)
    assert sub == 42
    made = cupsd.requests[-1]
    subscription = dict(made.groups[1][1])
    assert made.groups[1][0] == ipp.SUBSCRIPTION
    assert subscription["notify-pull-method"] == ["ippget"]
    assert subscription["notify-lease-duration"] == [3600]
    assert subscription["notify-events"] == list(cups.EVENTS)
    assert made.attrs["printer-uri"] == ["ipp://localhost/"]
    cupsd.event(5, 6)
    got = cups.notifications(client, sub, 1, timeout=2)
    assert (got.events, got.sequence, got.interval, got.gone) == (2, 7, 1.0, False)
    assert cupsd.requests[-1].attrs["notify-wait"] == [True]
    assert cupsd.requests[-1].attrs["notify-subscription-ids"] == [42]
    none = cups.notifications(client, sub, 7, timeout=2)
    assert none.events == 0 and none.sequence == 7
    assert cups.renew(client, sub)
    cups.cancel(client, sub)
    assert cupsd.ops()[-2:] == [ipp.RENEW_SUBSCRIPTION, ipp.CANCEL_SUBSCRIPTION]
    cupsd.gone = True
    assert cups.notifications(client, sub, 7, timeout=2).gone
    assert not cups.renew(client, sub)


def test_a_refused_subscription(cupsd: FakeCups) -> None:
    cupsd.subscribe_status = ipp.TOO_MANY_SUBSCRIPTIONS
    with pytest.raises(cups.Refused, match="too-many-subscriptions"):
        cups.subscribe(ipp.Client())


def test_a_held_request_that_times_out(cupsd: FakeCups) -> None:
    cupsd.hold = 2.0
    with pytest.raises(ipp.IppError) as e:
        cups.notifications(ipp.Client(), 42, 1, timeout=0.2)
    assert e.value.timed_out
    cups.cancel(ipp.Client(), 42)  # quiet whatever cupsd says

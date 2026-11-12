"""barctl's printer source (record 0004 §1-2) against the fake cupsd: events re-read the state,
the poll fallback when cupsd refuses a subscription, renew and cancel, reachability from DNS-SD
lines and the TCP probe (two failures before away), the once-a-day low supply, an alert that
blinks once, and no job title in the module's state."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.sources import printer as source_mod
from desktop_tools.barctl.sources.printer import PrinterSource, Reach
from desktop_tools.barctl.store import Writer
from desktop_tools.devices import cups, ipp, mdns
from tests.devices_fakes import FakeCups, avahi_resolved, job_attrs, printer_attrs, wait_for

REAL_PROBE = mdns.probe  # kept before conftest's no_device_sockets stubs it


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch, commands: Callable[..., Path]) -> None:
    """Short waits, and an avahi-browse that stays up saying nothing."""
    commands(**{"avahi-browse": "time.sleep(30)"})
    for name, value in (
        ("DEBOUNCE", 0.01),
        ("POLL_IDLE", 0.1),
        ("POLL_BUSY", 0.05),
        ("QUICK", 0.05),
        ("HOLD", 1.0),
    ):
        monkeypatch.setattr(source_mod, name, value)


def make(probe: bool = True) -> tuple[PrinterSource, list[str]]:
    pokes: list[str] = []
    modules = {"printer": mods.Module("printer", source="printer", display="icon")}
    src = PrinterSource(["printer"], Writer(modules, pokes.append))
    src.probe = lambda host: probe
    return src, pokes


@pytest.fixture
def running(cupsd: FakeCups, fast: None) -> Iterator[PrinterSource]:
    src, _ = make()
    thread = threading.Thread(target=src.follow, daemon=True)
    thread.start()
    wait_for(lambda: st.read("printer"))
    yield src
    src.stop()
    thread.join(3)
    assert not thread.is_alive()


def shown() -> tuple[object, ...]:
    data = st.read("printer") or {}
    return (data.get("tier"), data.get("label"), data.get("count"))


def test_ready_then_an_event_rereads(running: PrinterSource, cupsd: FakeCups) -> None:
    assert shown() == ("idle", "ready", None)
    assert ipp.CREATE_PRINTER_SUBSCRIPTIONS in cupsd.ops()
    assert (st.read("printer") or {}).get("target") == "Office"
    cupsd.jobs["Office"] = [job_attrs(7, cups.JOB_PROCESSING), job_attrs(8)]
    cupsd.event(1)
    assert wait_for(lambda: shown() == ("active", "printing", 2))
    detail = str((st.read("printer") or {}).get("detail"))
    assert "1 waiting" in detail and "magenta 44%" in detail


def test_stop_cancels_the_subscription(cupsd: FakeCups, fast: None) -> None:
    src, _ = make()
    thread = threading.Thread(target=src.follow, daemon=True)
    thread.start()
    wait_for(lambda: ipp.GET_NOTIFICATIONS in cupsd.ops())
    src.stop()
    thread.join(3)
    assert ipp.CANCEL_SUBSCRIPTION in cupsd.ops()
    assert src.subscription is None


def test_refused_subscription_polls(cupsd: FakeCups, fast: None) -> None:
    cupsd.subscribe_status = ipp.TOO_MANY_SUBSCRIPTIONS
    src, _ = make()
    thread = threading.Thread(target=src.follow, daemon=True)
    thread.start()
    try:
        assert wait_for(lambda: "polling" in str((st.read("printer") or {}).get("detail")))
        before = cupsd.ops().count(ipp.CUPS_GET_PRINTERS)
        assert wait_for(lambda: cupsd.ops().count(ipp.CUPS_GET_PRINTERS) > before + 1)
        assert ipp.GET_NOTIFICATIONS not in cupsd.ops()
        assert "CUPS refused a subscription" in str((st.read("printer") or {}).get("detail"))
    finally:
        src.stop()
        thread.join(3)


def test_cups_down_then_back(cupsd: FakeCups, fast: None, monkeypatch: pytest.MonkeyPatch) -> None:
    good = str(cupsd.path)
    monkeypatch.setenv("CUPS_SERVER", good + ".gone")
    src, _ = make()
    thread = threading.Thread(target=src.follow, daemon=True)
    thread.start()
    try:
        assert wait_for(lambda: shown() == ("unavailable", "CUPS not running", None))
        monkeypatch.setenv("CUPS_SERVER", good)
        assert wait_for(lambda: shown() == ("idle", "ready", None))
        assert wait_for(lambda: ipp.CREATE_PRINTER_SUBSCRIPTIONS in cupsd.ops())
    finally:
        src.stop()
        thread.join(3)


def test_a_lapsed_subscription_is_made_again(running: PrinterSource, cupsd: FakeCups) -> None:
    wait_for(lambda: ipp.GET_NOTIFICATIONS in cupsd.ops())
    cupsd.gone = True
    assert wait_for(lambda: cupsd.ops().count(ipp.CREATE_PRINTER_SUBSCRIPTIONS) >= 2)
    cupsd.gone = False


def test_renewed_every_half_hour(cupsd: FakeCups) -> None:
    src, _ = make()
    src.subscribe()
    assert src.subscription == 42
    src.renew()
    assert ipp.RENEW_SUBSCRIPTION not in cupsd.ops()
    src.renewed -= source_mod.RENEW_EVERY + 1
    src.renew()
    assert ipp.RENEW_SUBSCRIPTION in cupsd.ops()
    cupsd.gone = True
    src.renewed -= source_mod.RENEW_EVERY + 1
    src.renew()  # gone: subscribed again
    assert cupsd.ops().count(ipp.CREATE_PRINTER_SUBSCRIPTIONS) == 2


# ---------------------------------------------------------------- reachability


def test_two_failed_probes_before_away(cupsd: FakeCups) -> None:
    src, _ = make()
    results = iter([False, False, True])
    probed: list[str] = []

    def probe(host: str) -> bool:
        probed.append(host)
        return next(results)

    src.probe = probe
    clock = [1000.0]
    src.clock = lambda: clock[0]
    src.refresh()
    assert shown()[:2] == ("idle", "ready")  # one failure is not enough
    clock[0] += 10
    src.write()
    assert len(probed) == 1  # not due yet: 60 s after a failure
    clock[0] += 60
    src.write()
    assert shown()[:2] == ("unavailable", "away")
    clock[0] += 60
    src.write()
    assert shown()[:2] == ("idle", "ready")
    assert probed == ["printer.example"] * 3


def test_away_with_jobs_is_an_alert(cupsd: FakeCups) -> None:
    cupsd.jobs["Office"] = [job_attrs(1), job_attrs(2)]
    src, _ = make(probe=False)
    src.reach = Reach("printer.example", ok=False, failures=2, at=src.clock())
    src.refresh()
    assert shown() == ("alert", "not reachable, 2 waiting", 2)


def test_dns_sd_says_reachable_without_a_probe(cupsd: FakeCups) -> None:
    src, _ = make()
    src.probe = lambda host: pytest.fail("probed although DNS-SD resolved the host")
    browser = mdns.Browser(mdns.PRINTER_TYPES, lambda: None)
    src.browser = browser
    assert browser.line(avahi_resolved("Office", "_ipp._tcp", "Printer.Example.", "192.0.2.5", 631))
    src.refresh()
    assert shown()[:2] == ("idle", "ready")
    assert browser.line("-;eth0;IPv4;Office;_ipp._tcp;local")
    assert not browser.has_host("printer.example")


def test_the_probe_never_touches_9100(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    ports: list[int] = []

    def create(address: tuple[str, int], timeout: float = 0) -> object:
        ports.append(address[1])
        raise OSError("refused")

    monkeypatch.setattr(socket, "create_connection", create)
    assert not REAL_PROBE("printer.example")
    assert ports == [631, 80]


def test_local_queues_are_not_probed(cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("Office", uri="usb://Brand/Model")]
    src, _ = make()
    src.probe = lambda host: pytest.fail("a USB queue was probed")
    src.refresh()
    assert shown()[:2] == ("idle", "ready")


# ---------------------------------------------------------------- alerts


def test_an_alert_blinks_once_and_low_ink_once_a_day(cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("Office", levels=(44, 10, 69, 72))]
    src, _ = make()
    clock = [1_800_000_000.0]
    src.clock = lambda: clock[0]
    src.refresh()
    data = st.read("printer") or {}
    assert (data["tier"], data["label"]) == ("alert", "ink low: cyan")
    assert data["alert_until"] == pytest.approx(clock[0] + source_mod.ALERT_FOR)
    clock[0] += source_mod.LOW_SHOW + 1
    src.write()
    data = st.read("printer") or {}
    assert data["tier"] == "idle" and str(data["detail"]).startswith("ink low: cyan")
    clock[0] += 3600  # the same day: no new alert
    src.write()
    assert (st.read("printer") or {})["tier"] == "idle"
    clock[0] += 86400  # the next day: once more
    src.write()
    assert (st.read("printer") or {})["tier"] == "alert"


def test_a_standing_alert_does_not_blink_again(cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("Office", state=cups.STOPPED)]
    followed: list[str] = []
    modules = {"printer": mods.Module("printer", source="printer", display="icon")}
    src = PrinterSource(["printer"], Writer(modules, lambda m: None, followed.append))
    src.probe = lambda host: True
    clock = [1000.0]
    src.clock = lambda: clock[0]
    src.refresh()
    assert followed == ["printer"]
    first = (st.read("printer") or {})["alert_until"]
    clock[0] += 30
    src.refresh()
    assert (st.read("printer") or {})["alert_until"] == first
    assert followed == ["printer"]


def test_no_title_reaches_the_state(cupsd: FakeCups) -> None:
    """§7: a fake cupsd that sends job titles anyway: none reaches the bar's state."""
    marker = "SECRET-DOC-7f3a"
    cupsd.printers = [printer_attrs("Office", uri=f"ipp://{marker.lower()}.example/ipp")]
    cupsd.jobs["Office"] = [job_attrs(1, title=marker, user=marker)]
    src, _ = make()
    src.refresh()
    text = json.dumps(st.read("printer"))
    assert marker not in text and marker.lower() not in text


def test_gone_shows_cups_not_running(cupsd: FakeCups) -> None:
    src, _ = make()
    src.refresh()
    src.gone()
    assert shown()[:2] == ("unavailable", "CUPS not running")


def test_avahi_lines_from_the_stream(
    cupsd: FakeCups, fast: None, commands: Callable[..., Path]
) -> None:
    line = avahi_resolved("Office", "_ipp._tcp", "printer.example.", "192.0.2.5", 631)
    commands(**{"avahi-browse": f"print({line!r}, flush=True)\ntime.sleep(30)"})
    src, _ = make(probe=False)  # a probe would say away: DNS-SD must win
    thread = threading.Thread(target=src.follow, daemon=True)
    thread.start()
    try:
        assert wait_for(lambda: src.browser is not None and src.browser.has_host("printer.example"))
        src.write()
        assert shown()[:2] == ("idle", "ready")
    finally:
        src.stop()
        thread.join(3)


def test_doctor_reports_the_devices(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing action tools and a polling printer are reported as warnings, not failures."""
    from desktop_tools.barctl import doctor

    conf = isolate / "modules.toml"
    conf.write_text(
        '[modules.printer]\nsource = "printer"\n\n[modules.scanner]\nsource = "scanner"\n'
    )
    monkeypatch.setenv("BARCTL_CONFIG", str(conf))
    st.write("printer", {"tier": "idle", "detail": f"magenta 44%; {source_mod.REFUSED}"})
    found = {c["name"]: c for c in doctor.checks()}
    assert "source printer" not in found  # IPP needs nothing outside barctl
    assert found["source printer extras"]["state"] == "ok"  # avahi-browse: a tripwire is there
    assert found["source scanner"]["state"] == "ok"
    assert found["printer actions"]["state"] == "ok"  # the CUPS tools' tripwires are on PATH
    assert "system-config-printer" in found["printer actions"]["detail"]
    assert (
        found["scanner actions"]["state"] == "warn" and "magick" in found["scanner actions"]["fix"]
    )
    assert found["printer events"]["detail"] == "polling: CUPS refused a subscription"
    assert not doctor.problems([found["printer actions"], found["printer events"]])

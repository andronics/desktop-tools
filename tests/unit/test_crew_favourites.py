"""Record 0006: the strip, `crew cycle` and the scroll show favourites plus running coordinators;
the full menu and the verbs reach every one. No entry saying `favourite`: all are shown."""

from __future__ import annotations

from desktop_tools.barctl import state as bst
from desktop_tools.crew import registry, strip, switch
from desktop_tools.crew.registry import Registry
from tests.crew_fakes import Desk

NAMES = ("brain", "arbiter", "desktop", "media", "platform")


def reg_of(desk: Desk, **fav: bool) -> Registry:
    """Every name in NAMES; `fav` gives each named one its `favourite` (the others: absent)."""
    desk.coordinators(*NAMES, **{n: {"favourite": v} for n, v in fav.items()})
    return registry.load()


def running(desk: Desk, *names: str) -> None:
    for n in names:
        desk.session(f"{n}-coordinator")
        desk.window(n)


def strip_ids() -> list[str]:
    return [s["id"] for s in (bst.read("crew") or {}).get("segments", [])]


def test_favourite_is_read_and_defaults_false(desk: Desk) -> None:
    reg = reg_of(desk, brain=True, arbiter=False)
    assert [c.favourite for c in reg.coordinators] == [True, False, False, False, False]
    assert reg.favourites_told


def test_the_strip_shows_favourites_and_running_ones_in_menu_order(desk: Desk) -> None:
    reg = reg_of(desk, brain=True, arbiter=True, desktop=True, media=False, platform=False)
    running(desk, "platform")
    assert strip.push(reg) is True
    assert strip_ids() == ["brain", "arbiter", "desktop", "platform"]  # favourites run or not


def test_a_hidden_one_appears_when_it_starts_and_goes_when_it_stops(desk: Desk) -> None:
    reg = reg_of(desk, brain=True, media=False)
    strip.push(reg)
    assert strip_ids() == ["brain"]
    desk.session("media-coordinator")
    strip.push(reg)
    assert strip_ids() == ["brain", "media"]


def test_a_stopped_non_favourite_is_hidden_but_a_shown_one_never_is(desk: Desk) -> None:
    reg = reg_of(desk, brain=True, media=False)
    desk.window("media", hidden=False)  # shown, though its session is gone
    found = strip.scan(reg)
    assert [c.name for c in strip.visible(reg, found)] == ["brain", "media"]


def test_fallback_shows_all_when_no_entry_says_favourite(desk: Desk) -> None:
    reg = reg_of(desk)
    assert not reg.favourites_told
    strip.push(reg)
    assert strip_ids() == list(NAMES)


def test_cycle_skips_hidden_ones(desk: Desk) -> None:
    reg = reg_of(desk, brain=True, arbiter=True, desktop=True, media=False, platform=False)
    running(desk, "brain", "media")
    switch.summon(reg, "brain")
    assert switch.cycle(reg, "next") == 0
    assert desk.shown() == ["media"]
    assert switch.cycle(reg, "next") == 0
    assert desk.shown() == ["brain"]
    assert desk.launched() == []


def test_cycle_with_a_hidden_last_starts_from_the_first(desk: Desk) -> None:
    from desktop_tools.crew import store

    reg = reg_of(desk, brain=True, media=False)
    running(desk, "brain")
    store.set_last("media")  # not running, not a favourite: hidden
    assert switch.cycle(reg, "next") == 0
    assert desk.shown() == ["brain"]


def test_cycle_fallback_is_todays_behaviour(desk: Desk) -> None:
    reg = reg_of(desk)
    running(desk, "arbiter", "platform")
    switch.summon(reg, "arbiter")
    assert switch.cycle(reg, "next") == 0
    assert desk.shown() == ["platform"]


def test_the_registry_still_reaches_every_coordinator(desk: Desk) -> None:
    reg = reg_of(desk, brain=True, media=False)
    assert reg.names == list(NAMES)
    assert reg.get("media") is not None  # verbs resolve a hidden one

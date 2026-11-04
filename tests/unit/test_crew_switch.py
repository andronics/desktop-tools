"""crew's show, hide, toggle, cycle, launch, list and stopped against a fake bspwm, tmux and
meta. The show-only paths never start a coordinator (the brain coordinator's decision,
2026-11-04): they flash "<name> is stopped"; only `toggle --launch` runs `meta <name> launch`."""

from __future__ import annotations

import fcntl

import pytest

from desktop_tools.barctl import state as bst
from desktop_tools.crew import registry, store, switch
from desktop_tools.crew.registry import Registry
from tests.crew_fakes import MONITOR, Desk

GUARD = ["-m", "desktop_tools.crew", "guard"]


def reg_of(desk: Desk, *names: str, **extra: dict[str, object]) -> Registry:
    desk.coordinators(*names, **extra)
    return registry.load()


def guard_started(desk: Desk) -> bool:
    return any(argv[1:] == GUARD for argv in desk.detached)


def strip_tiers() -> dict[str, tuple[str, bool]]:
    data = bst.read("crew") or {}
    return {s["id"]: (s["tier"], bool(s.get("underline"))) for s in data.get("segments", [])}


# ---------------------------------------------------------------- showing


def test_toggle_shows_a_running_coordinator_docked(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "desktop")
    desk.window("desktop")
    assert switch.toggle(reg, "desktop") == 0
    win = desk.windows()["desktop"]
    assert not win["hidden"]
    # Docked right at 1280 wide (border 1 each side), the gap (5) inset; the strip reserved.
    assert win["rect"] == [3840 - 5 - 1280, 5, 1278, 2160 - 10 - 2]
    assert desk.padding() == {"top": 0, "right": 1285, "bottom": 0, "left": 0}
    assert store.last() == "desktop"
    assert guard_started(desk)
    assert strip_tiers() == {"brain": ("unavailable", False), "desktop": ("idle", True)}
    assert desk.launched() == []


def test_toggle_hides_the_shown_and_focused_one(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.window("desktop")
    switch.toggle(reg, "desktop")
    assert switch.toggle(reg, "desktop") == 0
    assert desk.shown() == []
    assert desk.padding()["right"] == 0
    assert strip_tiers() == {"desktop": ("idle", False)}


def test_toggle_on_a_shown_but_unfocused_one_focuses_it(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.window("desktop", hidden=False)
    assert switch.toggle(reg, "desktop") == 0
    assert desk.shown() == ["desktop"]
    assert desk.load()["monitors"][0]["focused_node"] == desk.windows()["desktop"]["id"]


def test_showing_one_hides_the_other(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "desktop")
    desk.window("brain", hidden=False)
    desk.window("desktop")
    assert switch.summon(reg, "desktop") == 0
    assert desk.shown() == ["desktop"]


def test_docked_left_releases_the_right(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.window("desktop")
    store.set_side("left")
    d = desk.load()
    d["monitors"][0]["padding"]["right"] = 99
    desk.save(d)
    assert switch.summon(reg, "desktop") == 0
    assert desk.windows()["desktop"]["rect"][0] == 5
    assert desk.padding() == {"top": 0, "right": 0, "bottom": 0, "left": 1285}


def test_a_session_without_a_window_is_attached_not_started(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    assert switch.toggle(reg, "desktop") == 0
    assert desk.shown() == ["desktop"]
    opened = [a for a in desk.detached if a[:1] == ["alacritty"]]
    assert opened == [
        [
            "alacritty",
            "--class",
            "crew,desktop",
            "--title",
            "crew - desktop",
            "-e",
            "tmux",
            "-L",
            "crew-test",
            "attach-session",
            "-t",
            "=desktop-coordinator",
        ]
    ]
    assert desk.launched() == []
    assert desk.notified() == []


def test_a_session_under_a_former_name_is_attached(desk: Desk) -> None:
    reg = reg_of(desk, "desktop", desktop={"old_names": ["dotfiles"]})
    desk.session("dotfiles-coordinator")
    assert switch.summon(reg, "desktop") == 0
    opened = next(a for a in desk.detached if a[:1] == ["alacritty"])
    assert opened[-1] == "=dotfiles-coordinator"


def test_coords_old_window_class_still_counts(desk: Desk) -> None:
    reg = reg_of(desk, "desktop", desktop={"old_names": ["dotfiles"]})
    desk.window("dotfiles", cls="coord")
    assert switch.toggle(reg, "desktop") == 0
    assert desk.shown() == ["dotfiles"]
    assert desk.calls("alacritty") == []


def test_the_window_never_comes(
    desk: Desk, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    desk.put("no-window", "")
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "0")
    assert switch.summon(reg, "desktop") == 1
    assert "desktop: no window after 0s" in capsys.readouterr().err


# ---------------------------------------------------------------- show-only paths: stopped


@pytest.mark.parametrize(
    "how",
    ["toggle", "show", "hide --toggle", "notification click"],
)
def test_show_only_paths_flash_stopped_and_start_nothing(
    desk: Desk, how: str, capsys: pytest.CaptureFixture[str]
) -> None:
    reg = reg_of(desk, "brain", "desktop")
    store.set_last("desktop")
    if how == "toggle":
        rc = switch.toggle(reg, "desktop")
    elif how == "show":
        rc = switch.summon(reg, "desktop")
    elif how == "hide --toggle":
        rc = switch.hide(reg, toggling=True)
    else:
        desk.put("notify-answer", "default")
        desk.calls()  # notify-send runs for real here: it is the fake
        rc = switch.notify_waiting(reg, "desktop", "a question")
        assert rc == 1
    assert rc == 1
    assert desk.launched() == []
    assert desk.calls("alacritty") == []
    assert [n[-2] for n in desk.notified()] == ["desktop is stopped"]
    assert "--hint=string:x-dunst-stack-tag:crew-stopped" in desk.notified()[0]
    assert "desktop is stopped" in capsys.readouterr().err
    assert bst.read("crew") is not None  # the bar was refreshed


def test_hide_toggle_with_no_last_uses_the_first(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "desktop")
    desk.window("brain")
    assert switch.hide(reg, toggling=True) == 0
    assert desk.shown() == ["brain"]


def test_hide_toggle_with_nothing_known_flashes(desk: Desk) -> None:
    assert switch.hide(Registry(), toggling=True) == 1
    assert [n[-2] for n in desk.notified()] == ["no coordinator running"]


def test_no_notify_send_is_fine(desk: Desk) -> None:
    (desk.base / "bin" / "notify-send").unlink()
    reg = reg_of(desk, "desktop")
    assert switch.summon(reg, "desktop") == 1
    assert desk.notified() == []


# ---------------------------------------------------------------- the deliberate path: launch


def test_toggle_launch_starts_a_stopped_one_through_meta(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    assert switch.toggle(reg, "desktop", launching=True) == 0
    assert desk.launched() == ["desktop"]
    assert desk.shown() == ["desktop"]
    assert desk.notified() == []


def test_toggle_launch_on_a_running_one_does_not_launch(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.window("desktop")
    assert switch.toggle(reg, "desktop", launching=True) == 0
    desk.session("desktop-coordinator")
    switch.toggle(reg, "desktop", launching=True)  # hides it
    assert desk.launched() == []


def test_launch_refused_because_already_running_attaches(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    c = reg.get("desktop")
    assert c is not None
    desk.put("launch-rc", "3")
    desk.session("desktop-coordinator")
    assert switch.launch(reg, c) is not None


@pytest.mark.parametrize(
    ("setup", "why"),
    [
        ("launch-rc=4", "meta desktop launch exited 4: meta desktop: refused"),
        ("launch-rc=3", "meta desktop launch exited 3"),
        ("no-meta", "meta is not on PATH"),
    ],
)
def test_launch_failures_alert(
    desk: Desk, setup: str, why: str, capsys: pytest.CaptureFixture[str]
) -> None:
    reg = reg_of(desk, "desktop")
    if setup == "no-meta":
        (desk.base / "bin" / "meta").unlink()
    else:
        name, value = setup.split("=")
        desk.put(name, value)
    assert switch.toggle(reg, "desktop", launching=True) == 1
    assert why in capsys.readouterr().err
    assert desk.notified()[0][-2:] == ["desktop: not started", desk.notified()[0][-1]]
    assert desk.calls("alacritty") == []


def test_launch_with_no_session_after_it(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    reg = reg_of(desk, "desktop")
    c = reg.get("desktop")
    assert c is not None
    desk.put("launch-rc", "0")
    (desk.base / "bin" / "meta").write_text("#!/bin/sh\nexit 0\n")
    assert switch.launch(reg, c) is None
    assert "no tmux session desktop-coordinator after meta launch" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["security", "Bad Name"])
def test_unknown_or_homeless_names_launch_nothing(
    desk: Desk, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """coordinators.zsh: launch-resolves-and-needs-home."""
    reg = reg_of(desk, "desktop")
    assert switch.toggle(reg, name, launching=True) == 1
    assert desk.launched() == []
    assert ("invalid coordinator name" if " " in name else "no coordinator 'security'") in (
        capsys.readouterr().err
    )


def test_a_former_name_launches_the_new_one(desk: Desk) -> None:
    reg = reg_of(desk, "desktop", desktop={"old_names": ["dotfiles"]})
    assert switch.toggle(reg, "dotfiles", launching=True) == 0
    assert desk.launched() == ["desktop"]


def test_no_alacritty_is_a_logged_failure(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    (desk.base / "bin" / "alacritty").unlink()
    assert switch.summon(reg, "desktop") == 1
    assert "alacritty is not on PATH" in capsys.readouterr().err


# ---------------------------------------------------------------- cycle


def running(desk: Desk, *names: str) -> None:
    for n in names:
        desk.session(f"{n}-coordinator")
        desk.window(n)


def test_cycle_skips_stopped_ones(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "platform", "media", "desktop")
    running(desk, "brain", "media")
    switch.summon(reg, "brain")
    assert switch.cycle(reg, "next") == 0
    assert desk.shown() == ["media"]
    assert switch.cycle(reg, "next") == 0  # wraps past desktop and platform, both stopped
    assert desk.shown() == ["brain"]
    assert switch.cycle(reg, "prev") == 0
    assert desk.shown() == ["media"]
    assert desk.launched() == [] and desk.notified() == []


def test_cycle_with_none_shown_brings_back_the_last(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "media", "desktop")
    running(desk, "brain", "media", "desktop")
    store.set_last("media")
    assert switch.cycle(reg, "next") == 0
    assert desk.shown() == ["media"]


def test_cycle_with_none_shown_and_the_last_stopped_steps_on(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "media", "desktop")
    running(desk, "brain")
    store.set_last("media")
    assert switch.cycle(reg, "prev") == 0
    assert desk.shown() == ["brain"]


def test_cycle_with_none_running_flashes(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "media")
    assert switch.cycle(reg, "next") == 1
    assert [n[-2] for n in desk.notified()] == ["no coordinator running"]
    assert desk.launched() == []


def test_cycle_direction_is_checked(desk: Desk) -> None:
    assert switch.cycle(reg_of(desk, "brain"), "up") == 2


# ---------------------------------------------------------------- hide, list, stopped, locks


def test_hide_hides_whichever_is_shown(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "desktop")
    desk.window("brain")
    switch.summon(reg, "brain")
    assert switch.hide(reg) == 0
    assert desk.shown() == []
    assert desk.padding()["right"] == 0
    assert switch.hide(reg) == 0  # nothing shown: nothing to do


def test_list(desk: Desk) -> None:
    desk.window("brain", hidden=False)
    desk.window("desktop", cls="coord")
    desk.window("firefox", cls="firefox")
    lines = switch.windows()
    assert lines == [
        "brain          visible  0x00C00001",
        "desktop        hidden   0x00C00002",
    ]


def test_stopped_drops_state_waits_and_gives_the_strip_back(desk: Desk) -> None:
    reg = reg_of(desk, "desktop", desktop={"old_names": ["dotfiles"]})
    store.set_activity("desktop", "busy")
    store.set_activity("dotfiles", "busy")
    d = desk.load()
    d["monitors"][0]["padding"]["right"] = 1285
    desk.save(d)
    assert switch.stopped(reg, ["dotfiles"]) == 0
    assert store.activity("desktop") == "" and store.activity("dotfiles") == ""
    assert desk.padding()["right"] == 0
    assert strip_tiers() == {"desktop": ("unavailable", False)}


def test_stopped_with_the_window_still_open(
    desk: Desk, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = reg_of(desk, "desktop")
    desk.window("desktop")
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "0.2")
    assert switch.stopped(reg, ["desktop"]) == 1
    assert (
        "desktop: window still open 0.2s after its session was stopped" in capsys.readouterr().err
    )


@pytest.mark.parametrize("names", [[], ["Bad"]])
def test_stopped_usage(desk: Desk, names: list[str]) -> None:
    assert switch.stopped(reg_of(desk, "desktop"), names) == 2


def test_stopped_needs_no_display(desk: Desk, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    reg = reg_of(desk, "desktop")
    assert switch.stopped(reg, ["desktop"]) == 0
    assert desk.calls("xprop") == []


def test_a_busy_switch_lock_is_a_logged_failure(
    desk: Desk, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = reg_of(desk, "desktop")
    desk.window("desktop")
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "0")
    path = store.lock_path("switch")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert switch.toggle(reg, "desktop") == 1
        assert switch.summon(reg, "desktop") == 1
        assert switch.hide(reg) == 1
        assert switch.cycle(reg, "next") == 1
    assert capsys.readouterr().err.count("switch lock busy after 0s") == 4
    assert desk.shown() == []


def test_place_failures_are_logged(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    reg = reg_of(desk, "desktop")
    desk.window("desktop")
    desk.fail("flag")
    assert switch.summon(reg, "desktop") == 1
    assert "desktop: cannot show 0x00C00001" in capsys.readouterr().err


def test_moves_to_the_focused_monitor(desk: Desk) -> None:
    from tests.crew_fakes import monitor

    d = desk.load()
    d["monitors"].append(monitor(0x00200003, "N", x=3840))
    desk.save(d)
    reg = reg_of(desk, "desktop")
    desk.window("desktop", monitor_id=0x00200003)
    assert switch.summon(reg, "desktop") == 0
    assert desk.windows()["desktop"]["monitor"] == MONITOR
    assert desk.padding(0x00200003)["right"] == 0


@pytest.mark.parametrize("toggling", [False, True])
def test_a_hide_that_fails_says_so_and_shows_nothing(
    desk: Desk, toggling: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    reg = reg_of(desk, "brain", "desktop")
    desk.window("brain", hidden=False)
    desk.window("desktop")
    store.set_last("desktop")
    desk.fail("flag")
    assert switch.hide(reg, toggling=toggling) == 1
    assert "hide: cannot hide brain (0x00C00001)" in capsys.readouterr().err
    assert desk.shown() == ["brain"]

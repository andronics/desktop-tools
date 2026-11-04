"""crew's lifecycle verbs against the fake meta (tests/crew_fakes.py): launch, stop, restart and
stop --all go only through `meta <name> launch|stop|restart`, meta's exit codes and reasons reach
the notification and the exit status, and the brain coordinator is never in stop --all."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from desktop_tools.crew import life, metacall, registry
from desktop_tools.crew.registry import Registry
from tests.crew_fakes import Desk


def reg_of(desk: Desk, *names: str, **extra: dict[str, Any]) -> Registry:
    desk.coordinators(*names, **extra)
    return registry.load()


def alerts(desk: Desk) -> list[tuple[str, str]]:
    return [
        (n[-2], n[-1]) for n in desk.notified() if "--hint=string:x-dunst-stack-tag:crew-alert" in n
    ]


# ---------------------------------------------------------------- launch


def test_launch_argv_and_starts_hidden(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "desktop")
    assert life.launch(reg, "desktop") == 0
    assert desk.lifecycle() == [["desktop", "launch"]]
    assert desk.sessions() == ["desktop-coordinator"]
    assert desk.shown() == []
    assert desk.calls("alacritty") == []


def test_launch_show_shows_it_docked(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    assert life.launch(reg, "desktop", showing=True) == 0
    assert desk.lifecycle() == [["desktop", "launch"]]
    assert desk.shown() == ["desktop"]


def test_launch_show_of_a_running_one_shows_it(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    desk.put("launch-rc", "3")
    assert life.launch(reg, "desktop", showing=True) == 0
    assert desk.shown() == ["desktop"]
    assert alerts(desk) == []


@pytest.mark.parametrize(("code", "means"), [(2, "usage"), (3, "refused"), (4, "failed")])
def test_launch_refusal_reaches_alert_and_exit(desk: Desk, code: int, means: str) -> None:
    reg = reg_of(desk, "desktop")
    desk.put("launch-rc", str(code))
    desk.put("launch-why", "not for this caller (claude): ask the brain coordinator")
    assert life.launch(reg, "desktop") == code
    assert alerts(desk) == [
        (
            "desktop: not started",
            f"meta desktop exited {code} ({means}): meta desktop: not for this caller (claude): "
            "ask the brain coordinator",
        )
    ]


def test_a_former_name_launches_the_new_one(desk: Desk) -> None:
    desk.coordinators("desktop", desktop={"old_names": ["dotfiles"]})
    assert life.launch(registry.load(), "dotfiles") == 0
    assert desk.lifecycle() == [["desktop", "launch"]]


@pytest.mark.parametrize("name", ["nobody", "Bad Name"])
def test_unknown_names_call_no_meta(desk: Desk, name: str) -> None:
    reg = reg_of(desk, "desktop")
    assert life.launch(reg, name) == 2
    assert life.stop(reg, name) == 2
    assert life.restart(reg, name) == 2
    assert desk.lifecycle() == []


def test_meta_missing_is_failed_and_alerted(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    (desk.base / "bin" / "meta").unlink()
    assert life.stop(reg, "desktop") == metacall.FAILED
    assert alerts(desk) == [
        ("desktop: not stopped", "meta desktop exited 4 (failed): meta is not on PATH")
    ]


# ---------------------------------------------------------------- stop


def test_stop_argv_and_ends_it(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    assert life.stop(reg, "desktop") == 0
    assert desk.lifecycle() == [["desktop", "stop"]]
    assert desk.sessions() == []
    assert alerts(desk) == []


def test_stop_force_argv(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    assert life.stop(reg, "desktop", force=True) == 0
    assert desk.lifecycle() == [["desktop", "stop", "--force", "--reason", life.FORCED]]


def test_stop_not_clean_gives_the_stop_scripts_reason(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    desk.put("stop-rc", "1")
    desk.put("stop-why", "no PAUSED heading since this session started")
    assert life.stop(reg, "desktop") == 1
    assert desk.sessions() == ["desktop-coordinator"]
    assert alerts(desk) == [
        (
            "desktop: not stopped",
            "meta desktop exited 1: no PAUSED heading since this session started",
        )
    ]


def test_stop_of_the_brain_is_left_to_meta(desk: Desk) -> None:
    """crew doesn't second-guess meta: it asks, and meta refuses (no terminal)."""
    reg = reg_of(desk, "brain")
    desk.session("brain-coordinator")
    desk.put("stop-rc", "3")
    desk.put("stop-why", "stop of the brain coordinator is Stephen's, at a terminal")
    assert life.stop(reg, "brain") == 3
    assert desk.lifecycle() == [["brain", "stop"]]
    assert alerts(desk)[0][1].endswith("is Stephen's, at a terminal")


def test_crew_stop_brain_on_the_command_line_is_never_confirmed(desk: Desk) -> None:
    """`--confirmed` is the menus' alone, after a Yes: `crew stop brain` never sends it."""
    reg_of(desk, "brain")
    for verb in ("stop", "restart"):
        desk.session("brain-coordinator")
        # S603: crew itself, a fixed argument list.
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "desktop_tools.crew", verb, "brain"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
    assert desk.lifecycle() == [["brain", "stop"], ["brain", "restart"]]


# ---------------------------------------------------------------- restart


def test_restart_of_a_hidden_one_leaves_it_hidden(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    desk.window("desktop")
    assert life.restart(reg, "desktop") == 0
    assert desk.lifecycle() == [["desktop", "restart"]]
    assert desk.sessions() == ["desktop-coordinator"]
    assert desk.shown() == []
    assert desk.calls("alacritty") == []


def test_restart_of_a_shown_one_shows_it_again(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    old = desk.window("desktop", hidden=False, focused=True)
    assert life.restart(reg, "desktop") == 0
    assert desk.lifecycle() == [["desktop", "restart"]]
    assert desk.shown() == ["desktop"]
    assert desk.windows()["desktop"]["id"] != old  # a new window, on the new session
    assert len(desk.calls("alacritty")) == 1


def test_restart_refused_shows_nothing(desk: Desk) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    desk.window("desktop", hidden=False, focused=True)
    desk.put("restart-rc", "1")
    desk.put("restart-why", "notes not clean")
    assert life.restart(reg, "desktop") == 1
    assert alerts(desk) == [("desktop: not restarted", "meta desktop exited 1: notes not clean")]
    assert desk.calls("alacritty") == []


def test_restart_does_not_reshow_a_window_that_stayed(
    desk: Desk, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = reg_of(desk, "desktop")
    desk.session("desktop-coordinator")
    desk.window("desktop", hidden=False, focused=True)
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "0")
    # meta restarts the session, but the old window doesn't close.
    (desk.base / "bin" / "meta").write_text("#!/bin/sh\nexit 0\n")
    assert life.restart(reg, "desktop") == 1
    assert desk.calls("alacritty") == []


# ---------------------------------------------------------------- stop --all


def test_stop_all_never_includes_the_brain(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "homelab", "desktop", "media")
    desk.session("brain-coordinator", "homelab-coordinator", "desktop-coordinator")
    assert life.stop_all(reg) == 0
    assert desk.lifecycle() == [
        ["homelab", "stop", "--check"],
        ["desktop", "stop", "--check"],
        ["homelab", "stop"],
        ["desktop", "stop"],
    ]
    assert desk.sessions() == ["brain-coordinator"]
    assert desk.calls("rofi") == []  # all clean: nothing to ask


def test_stop_all_with_only_the_brain_running_stops_nothing(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "desktop")
    desk.session("brain-coordinator")
    assert life.stop_all(reg) == 0
    assert desk.lifecycle() == []


def test_stop_all_counts_a_session_under_a_former_name(desk: Desk) -> None:
    desk.coordinators("desktop", desktop={"old_names": ["dotfiles"]})
    desk.session("dotfiles-coordinator")
    assert life.stop_all(registry.load()) == 0
    assert desk.lifecycle() == [["desktop", "stop", "--check"], ["desktop", "stop"]]


def test_stop_all_asks_once_and_yes_forces_the_unclean(desk: Desk) -> None:
    reg = reg_of(desk, "brain", "homelab", "desktop", "media")
    desk.session("homelab-coordinator", "desktop-coordinator", "media-coordinator")
    desk.put("check-rc-homelab", "1")
    desk.put("check-why-homelab", "no PAUSED heading")
    desk.put("check-rc-media", "1")
    desk.put("rofi-answer", "Yes")
    assert life.stop_all(reg) == 0
    rofi = desk.calls("rofi")
    assert len(rofi) == 1
    assert rofi[0][-2:] == ["-p", "notes not clean for homelab, media: stop all anyway?"]
    assert rofi[0][rofi[0].index("-selected-row") + 1] == "1"  # No is selected
    assert desk.lifecycle()[3:] == [
        ["homelab", "stop", "--force", "--reason", life.ALL_YES],
        ["desktop", "stop"],
        ["media", "stop", "--force", "--reason", life.ALL_YES],
    ]
    assert desk.sessions() == []


def test_stop_all_one_unclean_names_its_reason(desk: Desk) -> None:
    reg = reg_of(desk, "homelab", "desktop")
    desk.session("homelab-coordinator", "desktop-coordinator")
    desk.put("check-rc-homelab", "1")
    desk.put("check-why-homelab", "no PAUSED heading")
    desk.put("rofi-answer", "Yes")
    assert life.stop_all(reg) == 0
    assert desk.calls("rofi")[0][-1] == "homelab: no PAUSED heading: stop all anyway?"


@pytest.mark.parametrize("answer", ["No", None])
def test_stop_all_declined_stops_nothing(desk: Desk, answer: str | None) -> None:
    reg = reg_of(desk, "homelab", "desktop")
    desk.session("homelab-coordinator", "desktop-coordinator")
    desk.put("check-rc-homelab", "1")
    if answer:
        desk.put("rofi-answer", answer)
    assert life.stop_all(reg) == 1
    assert [c for c in desk.lifecycle() if "--check" not in c] == []
    assert desk.sessions() == ["homelab-coordinator", "desktop-coordinator"]


def test_stop_all_yes_asks_nothing(desk: Desk) -> None:
    reg = reg_of(desk, "homelab", "desktop")
    desk.session("homelab-coordinator", "desktop-coordinator")
    desk.put("check-rc-homelab", "1")
    assert life.stop_all(reg, yes=True) == 0
    assert desk.calls("rofi") == []
    assert desk.lifecycle()[2] == ["homelab", "stop", "--force", "--reason", life.ALL_FLAG]


def test_stop_all_one_refusal_stops_the_rest(desk: Desk) -> None:
    reg = reg_of(desk, "homelab", "desktop", "media")
    desk.session("homelab-coordinator", "desktop-coordinator", "media-coordinator")
    desk.put("stop-rc-desktop", "3")
    desk.put("stop-why-desktop", "outside tmux: close it with /exit")
    assert life.stop_all(reg) == 3
    assert desk.sessions() == ["desktop-coordinator"]
    assert alerts(desk) == [
        (
            "desktop: not stopped",
            "meta desktop exited 3 (refused): meta desktop: outside tmux: close it with /exit",
        )
    ]


def test_stop_all_without_rofi_is_a_no(desk: Desk) -> None:
    reg = reg_of(desk, "homelab")
    desk.session("homelab-coordinator")
    desk.put("check-rc", "1")
    (desk.base / "bin" / "rofi").unlink()
    assert life.stop_all(reg) == 1
    assert desk.sessions() == ["homelab-coordinator"]


# ---------------------------------------------------------------- meta's one line


@pytest.mark.parametrize(
    ("stdout", "stderr", "why"),
    [
        ('t by=meta result=refused why="a \\"b\\" c"\n', "", 'a "b" c'),
        ("t by=meta result=kill-failed why=gone\n", "warn\n", "gone"),
        ("", "meta x: first\nmeta x: second\n", "meta x: second"),
        (
            "x: launched in tmux session x-coordinator\n",
            "",
            "x: launched in tmux session x-coordinator",
        ),
        ("", "", ""),
    ],
)
def test_reason(stdout: str, stderr: str, why: str) -> None:
    assert metacall.reason(stdout, stderr) == why


@pytest.mark.parametrize("third", [False, True])
def test_stop_all_leaves_out_every_one_only_stephen_ends(desk: Desk, third: bool) -> None:
    """From the registry's `ended_by`: the brain, the arbiter and any other that carries it."""
    by_stephen = {"ended_by": "stephen"}
    extra = {"brain": by_stephen, "arbiter": by_stephen, **({"media": by_stephen} if third else {})}
    reg = reg_of(desk, "brain", "arbiter", "media", "desktop", **extra)
    desk.session(*(f"{n}-coordinator" for n in ("brain", "arbiter", "media", "desktop")))
    assert life.stop_all(reg) == 0
    ended = [c[0] for c in desk.lifecycle() if c[1:] == ["stop"]]
    assert ended == (["desktop"] if third else ["media", "desktop"])

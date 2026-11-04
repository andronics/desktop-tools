"""`crew status` (the Claude hooks), the strip pushed to barctl (tests/coordinators.zsh's bar-tiers
and scan cases) and the waiting notification."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from desktop_tools.barctl import state as bst
from desktop_tools.crew import hook, registry, store, strip, switch, wm
from tests.crew_fakes import Desk
from tests.fakes import FakeBar, run

CREW = [sys.executable, "-m", "desktop_tools.crew"]


class Pipe(io.StringIO):
    def isatty(self) -> bool:
        return False


def fire(desk: Desk, event: str, sub: str = "desktop", *args: str, **data: object) -> int:
    payload = {"cwd": f"{desk.actors}/{sub}", "hook_event_name": event, **data}
    return hook.run(list(args), Pipe(json.dumps(payload)))


def detached_verbs(desk: Desk) -> list[list[str]]:
    return [a[3:] for a in desk.detached if a[1:3] == ["-m", "desktop_tools.crew"]]


@pytest.fixture
def coords(desk: Desk) -> Desk:
    desk.coordinators("brain", "desktop", desktop={"old_names": ["dotfiles"]})
    registry.load()  # the kept copy the hook reads
    return desk


@pytest.mark.parametrize(
    ("event", "data", "state"),
    [
        ("UserPromptSubmit", {}, "busy"),
        ("PostToolUse", {}, "busy"),
        ("PostToolUseFailure", {}, "busy"),
        ("PreToolUse", {"tool_name": "AskUserQuestion"}, "waiting"),
        ("Notification", {"notification_type": "permission_prompt"}, "waiting"),
        ("Notification", {"notification_type": "elicitation_dialog"}, "waiting"),
        ("Notification", {"notification_type": "elicitation_url_dialog"}, "waiting"),
        ("Notification", {"notification_type": "agent_needs_input"}, "waiting"),
        ("Stop", {}, "idle"),
        ("StopFailure", {}, "idle"),
        ("SessionStart", {}, "idle"),
    ],
)
def test_events_to_states(coords: Desk, event: str, data: dict[str, str], state: str) -> None:
    assert fire(coords, event, **data) == 0
    assert store.activity("desktop") == state
    assert ["bar", "--quiet"] in detached_verbs(coords)


@pytest.mark.parametrize(
    ("event", "data"),
    [
        ("PreToolUse", {"tool_name": "Bash"}),
        ("Notification", {"notification_type": "idle_prompt"}),
        ("SomethingNew", {}),
    ],
)
def test_events_that_change_nothing(coords: Desk, event: str, data: dict[str, str]) -> None:
    store.set_activity("desktop", "busy")
    assert fire(coords, event, **data) == 0
    assert store.activity("desktop") == "busy"
    assert coords.detached == []


def test_session_end_removes_the_state(coords: Desk) -> None:
    fire(coords, "Stop")
    fire(coords, "SessionEnd")
    assert not store.activity_path("desktop").exists()
    coords.detached.clear()
    fire(coords, "SessionEnd")  # nothing there: no change, no refresh
    assert coords.detached == []


def test_only_a_change_refreshes(coords: Desk) -> None:
    fire(coords, "UserPromptSubmit")
    fire(coords, "PostToolUse")
    fire(coords, "PostToolUse")
    assert detached_verbs(coords) == [["bar", "--quiet"]]


def test_waiting_notifies_with_the_question(coords: Desk) -> None:
    question = {"questions": [{"question": "Merge   the\nPR?"}]}
    fire(coords, "PreToolUse", tool_name="AskUserQuestion", tool_input=question)
    assert detached_verbs(coords)[0] == ["notify", "desktop", "--", "Merge the PR?"]
    fire(coords, "Stop")
    fire(coords, "Notification", notification_type="permission_prompt", message="Allow rm?")
    assert ["notify", "desktop", "--", "Allow rm?"] in detached_verbs(coords)
    fire(coords, "Stop")
    fire(coords, "Notification", notification_type="permission_prompt")
    assert detached_verbs(coords)[-2] == ["notify", "desktop", "--", "Waiting for input"]


def test_the_event_argument_overrides(coords: Desk) -> None:
    fire(coords, "Stop", "desktop", "UserPromptSubmit")
    assert store.activity("desktop") == "busy"


def test_a_subfolder_and_a_former_name_count(coords: Desk) -> None:
    fire(coords, "UserPromptSubmit", "desktop/work/crew-core")
    assert store.activity("desktop") == "busy"
    fire(coords, "Stop", "dotfiles")
    assert store.activity("desktop") == "idle"


@pytest.mark.parametrize("cwd", ["/home/elsewhere", "{actors}/unknown", "{actors}/", "{actors}"])
def test_other_sessions_are_ignored(coords: Desk, cwd: str) -> None:
    payload = {"cwd": cwd.format(actors=coords.actors), "hook_event_name": "UserPromptSubmit"}
    assert hook.run([], Pipe(json.dumps(payload))) == 0
    assert not store.activity_path("unknown").exists()
    assert coords.detached == []


@pytest.mark.parametrize("raw", ["", "not json", '"cwd" "/x/"', '["cwd"]', '{"cwd": 3}'])
def test_junk_on_stdin_is_ignored(coords: Desk, raw: str) -> None:
    raw = raw.replace("/x/", f"{coords.actors}/")
    assert hook.run([], Pipe(raw)) == 0
    assert coords.detached == []


def test_a_terminal_on_stdin_is_ignored(coords: Desk) -> None:
    class Tty(Pipe):
        def isatty(self) -> bool:
            return True

    assert hook.run([], Tty("{}")) == 0


def test_an_unwritable_state_is_quiet(coords: Desk) -> None:
    from desktop_tools.crew import conf

    conf.runtime().mkdir(parents=True, exist_ok=True)
    conf.activity_dir().write_text("not a folder")
    assert fire(coords, "UserPromptSubmit") == 0
    assert coords.detached == []


def test_crew_status_as_the_hook_runs_it(coords: Desk) -> None:
    payload = json.dumps({"cwd": f"{coords.actors}/brain", "hook_event_name": "UserPromptSubmit"})
    done = run([*CREW, "status"], input=payload)
    assert (done.returncode, done.stdout) == (0, "")
    assert store.activity("brain") == "busy"


def test_status_never_fails_the_hook(coords: Desk, monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop_tools.crew import fast

    def boom(args: list[str], stdin: object = None) -> int:
        raise RuntimeError("bad")

    monkeypatch.setattr(hook, "run", boom)
    assert fast.status([]) == 0


# ---------------------------------------------------------------- the strip


def test_bar_tiers(desk: Desk, theme: dict[str, str], bar: FakeBar) -> None:
    """coordinators.zsh: bar-tiers. A session per state; desktop isn't running."""
    desk.coordinators("brain", "homelab", "media", "desktop", brain={"bar_glyph": "U+F09D1"})
    reg = registry.load()
    desk.session("brain-coordinator", "homelab-coordinator", "media-coordinator")
    store.set_activity("homelab", "busy")
    store.set_activity("media", "waiting")
    store.set_activity("desktop", "busy")  # stale: not running
    desk.window("media", hidden=False)
    assert strip.push(reg) is True
    data = bst.read("crew") or {}
    assert [(s["id"], s["tier"], s.get("underline", False)) for s in data["segments"]] == [
        ("brain", "idle", False),
        ("homelab", "active", False),
        ("media", "alert", True),
        ("desktop", "unavailable", False),
    ]
    # A day: a coordinator waiting hours for an answer still shows it (record 0003's ttl).
    assert data["source"] == "crew" and data["expires"] - data["updated"] >= 86400 - 5
    assert not store.activity_path("desktop").exists()
    line = strip.line()
    assert "%{A1:barctl click crew left --segment brain:}" in line
    assert f"%{{F{theme['idle']}}} \U000f09d1 %{{F-}}" in line
    assert f"%{{F{theme['active']}}} h %{{F-}}" in line
    assert f"%{{u{theme['active']}}}%{{+u}}%{{F{theme['alert']}}} m %{{F-}}%{{-u}}" in line
    assert f"%{{F{theme['unavailable']}}} d %{{F-}}" in line
    assert bar.wait(1) == ["crew"]


def test_scan_counts_a_former_names_session(desk: Desk) -> None:
    """coordinators.zsh: scan-old-session-as-new."""
    desk.coordinators("desktop", desktop={"old_names": ["dotfiles"]})
    desk.session("dotfiles-coordinator", "notacoordinator")
    found = strip.scan(registry.load())
    assert found.running == {"desktop"}


def test_a_bar_without_the_crew_module_is_not_an_error(
    desk: Desk,
    isolate: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = isolate / "modules.toml"
    config.write_text('[modules.other]\npusher = "crew"\n')
    monkeypatch.setenv("BARCTL_CONFIG", str(config))
    desk.coordinators("brain")
    assert strip.push(registry.load()) is True
    config.write_text('[modules.crew]\npusher = "someone"\n')
    assert strip.push(registry.load()) is False
    assert "barctl refused the strip" in capsys.readouterr().err
    config.write_text("not toml [")
    assert strip.push(registry.load()) is False
    assert strip.line() == ""


def test_crew_bar_prints_the_line(desk: Desk, theme: dict[str, str]) -> None:
    desk.coordinators("brain")
    done = run([*CREW, "bar"])
    assert done.returncode == 0
    assert "%{A1:barctl click crew left --segment brain:}" in done.stdout
    assert "%{A4:barctl click crew scroll-up --segment brain:}" in done.stdout
    assert run([*CREW, "bar", "--quiet"]).stdout == ""
    assert run([*CREW, "bar", "--loud"]).returncode == 2


# ---------------------------------------------------------------- the waiting notification


def test_notify_unless_shown_and_focused(desk: Desk) -> None:
    desk.coordinators("desktop")
    reg = registry.load()
    desk.window("desktop", hidden=False, focused=True)
    assert switch.notify_waiting(reg, "desktop", "hi") == 0
    assert desk.calls("notify-send") == []
    long = "<b>" + "x" * 300
    d = desk.load()
    d["monitors"][0]["focused_node"] = None
    desk.save(d)
    assert switch.notify_waiting(reg, "desktop", long) == 0
    call = desk.calls("notify-send")[0]
    assert call[1:5] == [
        "--app-name=crew",
        "--action=default=Show",
        "--hint=string:x-dunst-stack-tag:crew-desktop",
        "desktop needs you",
    ]
    assert call[5].startswith("&lt;b&gt;xxx") and call[5].endswith("…")


def test_the_notifications_click_shows_it(desk: Desk) -> None:
    desk.coordinators("desktop")
    reg = registry.load()
    desk.window("desktop")
    desk.put("notify-answer", "default")
    assert switch.notify_waiting(reg, "desktop", "") == 0
    assert desk.shown() == ["desktop"]
    assert desk.launched() == []


def test_no_notify_send_no_notification(desk: Desk) -> None:
    (desk.base / "bin" / "notify-send").unlink()
    desk.coordinators("desktop")
    assert switch.notify_waiting(registry.load(), "desktop", "x") == 0


def test_scan_against_a_real_tmux_on_its_own_socket(
    isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fake tmux's answers, checked once against a real tmux: its own server on a socket in
    tmp_path (-S), the cleanup naming it too, never the default server or TMUX_TMPDIR."""
    import shutil
    import subprocess

    # The binary itself: a wrapper earlier on the developer's PATH (a tmux guard) is not run.
    real = shutil.which("tmux", path="/usr/bin:/bin")
    if real is None:
        pytest.skip("no tmux installed")
    (isolate / "real" / "tmux").symlink_to(real)
    (isolate / "bin" / "tmux").unlink()  # the tripwire
    sock = isolate / "tmux.sock"
    monkeypatch.setenv("CREW_TMUX_SOCKET", str(sock))
    monkeypatch.delenv("TMUX", raising=False)
    base = [real, "-S", str(sock), "-f", "/dev/null"]
    try:
        subprocess.run(  # noqa: S603 - the test's own server
            [*base, "new-session", "-d", "-s", "crewtest-coordinator", "sleep 600"], check=True
        )
        reg = registry.Registry([registry.Coordinator("crewtest", isolate, "crewtest-coordinator")])
        assert strip.scan(reg, tree=wm.Tree()).running == {"crewtest"}
    finally:
        subprocess.run([*base, "kill-server"], check=False, capture_output=True)  # noqa: S603


def test_a_body_that_looks_like_an_option_still_notifies(desk: Desk) -> None:
    """The hook passes the text after `--`, so `crew notify` never reads it as an option."""
    desk.coordinators("desktop")
    done = run([*CREW, "notify", "desktop", "--", "--help"])
    assert done.returncode == 0 and "Usage" not in done.stdout
    assert desk.calls("notify-send")[0][-1] == "--help"


def test_scan_uses_the_registrys_session_name(desk: Desk) -> None:
    desk.coordinators("desktop", desktop={"tmux_session": "desk-main"})
    desk.session("desk-main")
    assert strip.scan(registry.load()).running == {"desktop"}

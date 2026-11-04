"""crew's menus (brain record 0019 §7a): the quick menu on each glyph, built from meta's real
`menu --json` (tests/fixtures, copied from the live `meta desktop menu --json` and `meta ventures
menu --json`, paths made generic), and the full two-level menu ported from coord.

Everything is fake: meta, rofi, alacritty, notify-send, xdg-open, code and xclip; tmux names its
own server. Detached children are recorded, not run (alacritty runs, to add its window)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from desktop_tools.crew import items, menus, registry, stopping
from desktop_tools.crew.registry import Registry
from tests.crew_fakes import ROFI_SEQ, XCLIP, Desk

FIXTURES = Path(__file__).parent.parent / "fixtures"
DESKTOP_MENU = json.loads((FIXTURES / "meta-menu-desktop.json").read_text())
VENTURES_MENU = json.loads((FIXTURES / "meta-menu-ventures.json").read_text())
DESKTOP_IDS = [i["id"] for i in DESKTOP_MENU["data"]["items"]]


@pytest.fixture
def menu_desk(desk: Desk, commands: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Desk:
    from desktop_tools.common import procs

    closed: list[bool] = []

    def close_inherited(fd_dir: str = "") -> list[int]:
        # The real one would close pytest's own pipes; that it is called is checked below.
        closed.append(True)
        return []

    monkeypatch.setattr(procs, "close_inherited", close_inherited)
    desk.closed = closed  # type: ignore[attr-defined]  # a test-only note on the fake
    commands(
        rofi=ROFI_SEQ, xclip=XCLIP, xdotool="sys.exit(1)", **{"xdg-open": "", "code": "", "less": ""}
    )
    return desk


def reg_of(desk: Desk, *names: str) -> Registry:
    desk.coordinators(*names)
    return registry.load()


def serve(desk: Desk, name: str, envelope: dict[str, Any]) -> None:
    desk.put(f"menu-{name}.json", json.dumps(envelope))


def answers(desk: Desk, *picks: str) -> None:
    """What rofi picks, call by call: a row index, Yes or No; "" is Escape."""
    desk.put("rofi-answers", "\n".join(picks))


def rofi_rows(desk: Desk, n: int) -> list[str]:
    return (desk.base / f"rofi-in.{n}").read_text().split("\n")


def rofi_calls(desk: Desk) -> list[list[str]]:
    return desk.calls("rofi")


def meta_calls(desk: Desk) -> list[list[str]]:
    return [c[1:] for c in desk.calls("meta") if c[1:3] != ["brain", "coordinators"]]


def clear_rofi(desk: Desk) -> None:
    for f in desk.base.glob("rofi-in.*"):
        f.unlink()


def index_of(desk: Desk, label: str, n: int = 0) -> str:
    rows = rofi_rows(desk, n)
    return str(next(i for i, r in enumerate(rows) if r.endswith(label)))


def quick_pick(desk: Desk, reg: Registry, name: str, label: str, *more: str) -> int:
    """Open the quick menu once to learn the rows, then again picking `label`."""
    clear_rofi(desk)
    answers(desk, "")
    assert menus.quick(reg, name) == 0
    pick = index_of(desk, label)
    clear_rofi(desk)
    answers(desk, pick, *more)
    return menus.quick(reg, name)


# ---------------------------------------------------------------- parsing meta's items


def test_parse_reads_metas_real_menu() -> None:
    found = items.parse(DESKTOP_MENU)
    assert found is not None
    assert [i.id for i in found] == DESKTOP_IDS
    kinds = {i.id: (i.kind, i.output, i.when, i.confirm) for i in found}
    assert kinds["stop"] == ("meta", "notify", "running", True)
    assert kinds["home"] == ("edit", "none", "always", False)
    assert kinds["status"] == ("meta", "view", "always", False)
    assert kinds["note"] == ("open", "none", "always", False)
    assert kinds["attach"] == ("copy", "notify", "always", False)
    inbox = next(i for i in found if i.id == "inbox")
    assert inbox.glyph == "\U000f02fa"
    assert inbox.args == ["brain", "inbox", "desktop"]
    assert found[0].lifecycle() == ("desktop", "stop")
    assert inbox.lifecycle() is None
    assert repr(inbox) == "Item('inbox')"


@pytest.mark.parametrize(
    "raw",
    [
        "not a dict",
        {"label": "no id", "run": {"meta": ["x"]}},
        {"id": "x", "label": "two runs", "run": {"meta": ["x"], "open": "https://a"}},
        {"id": "x", "label": "a shell string", "run": {"meta": "rm -rf /"}},
        {"id": "x", "label": "unknown kind", "run": {"shell": "ls"}},
        {"id": "x", "label": "bad output", "run": {"open": "https://a"}, "output": "loud"},
    ],
)
def test_parse_drops_what_crew_cannot_run(raw: object) -> None:
    good = {"id": "ok", "label": "OK", "run": {"open": "https://a"}}
    found = items.parse({"data": {"items": [raw, good, dict(good)]}})
    assert [i.id for i in found or []] == ["ok"]  # the repeat is dropped too


def test_parse_wrong_shape() -> None:
    assert items.parse({"data": []}) is None
    assert items.parse([]) is None


def test_when(tmp_path: Path) -> None:
    def item(when: str) -> items.Item:
        return items.Item("x", "X", "open", "https://a", when=when)

    assert items.applies(item("always"), False)
    assert items.applies(item("running"), True) and not items.applies(item("running"), False)
    assert items.applies(item("stopped"), False) and not items.applies(item("stopped"), True)
    assert items.applies(item(f"exists:{tmp_path}"), False)
    assert not items.applies(item(f"exists:{tmp_path / 'gone'}"), True)
    assert not items.applies(item("sometimes"), True)


# ---------------------------------------------------------------- the quick menu's rows


def test_quick_menu_rows_are_show_then_metas_in_order(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain", "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    answers(menu_desk, "")
    assert menus.quick(reg, "desktop") == 0  # Escape: nothing run
    rows = rofi_rows(menu_desk, 0)
    labels = [i["label"] for i in DESKTOP_MENU["data"]["items"]]
    assert rows[0] == "Show"
    assert [r.rsplit("</span> ", 1)[-1] for r in rows[1:]] == labels
    assert "Symbols Nerd Font Mono" in rows[5]  # Inbox has a glyph
    argv = rofi_calls(menu_desk)[0]
    assert argv[argv.index("-p") + 1] == "d desktop"  # barmenu's prompt: glyph, then title
    assert "-markup-rows" in argv and "-theme-str" in argv  # barmenu's rofi call and placement
    assert meta_calls(menu_desk) == [["desktop", "menu", "--json"]]
    assert menu_desk.closed == [True]  # type: ignore[attr-defined]  # polybar's pipes dropped


def test_quick_menu_for_a_stopped_one_offers_launch(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "ventures")
    serve(menu_desk, "ventures", VENTURES_MENU)
    assert quick_pick(menu_desk, reg, "ventures", "Launch") == 0
    assert rofi_rows(menu_desk, 0)[:2] == ["Show", "Launch"]
    assert menu_desk.launched() == ["ventures"]
    assert [n[-2:] for n in menu_desk.notified()][-1] == [
        "ventures: Launch",
        "ventures: launched in tmux session ventures-coordinator",
    ]


def test_quick_menu_judges_when_itself(menu_desk: Desk) -> None:
    """meta said running, but the session has gone since: Stop and Restart aren't offered."""
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    answers(menu_desk, "")
    menus.quick(reg, "desktop")
    rows = rofi_rows(menu_desk, 0)
    assert "Stop" not in rows and "Restart" not in rows
    assert rows[1] == "Open home in VS Code"


def test_quick_menu_reads_hide_when_shown_and_focused(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.window("desktop", hidden=False, focused=True)
    serve(menu_desk, "desktop", DESKTOP_MENU)
    assert quick_pick(menu_desk, reg, "desktop", "Hide") == 0
    assert rofi_rows(menu_desk, 0)[0] == "Hide"
    assert menu_desk.shown() == []


def test_show_on_a_stopped_one_never_starts_it(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "ventures")
    serve(menu_desk, "ventures", VENTURES_MENU)
    assert quick_pick(menu_desk, reg, "ventures", "Show") == 1
    assert menu_desk.launched() == []
    assert any("ventures is stopped" in n for n in menu_desk.notified())


def test_quick_menu_with_meta_failing_falls_back(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop", "ventures")
    menu_desk.put("menu-rc-desktop", "4")
    menu_desk.put("menu-rc-ventures", "4")
    menu_desk.session("desktop-coordinator")
    answers(menu_desk, "")
    menus.quick(reg, "desktop")
    assert rofi_rows(menu_desk, 0) == ["Show", "Stop", "Restart", menus.UNAVAILABLE]
    answers(menu_desk, "", "")
    menus.quick(reg, "ventures")
    assert rofi_rows(menu_desk, 1) == ["Show", "Launch", menus.UNAVAILABLE]
    # Picking the line runs nothing.
    answers(menu_desk, "", "", "2")
    assert menus.quick(reg, "ventures") == 0
    assert menu_desk.launched() == []


def test_meta_garbage_is_a_failure(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.put("menu-desktop.json", "not json")
    answers(menu_desk, "")
    menus.quick(reg, "desktop")
    assert rofi_rows(menu_desk, 0)[-1] == menus.UNAVAILABLE


def test_quick_menu_unknown_coordinator(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    assert menus.quick(reg, "nobody") == 2
    assert menus.quick(reg, "Bad Name") == 2
    assert rofi_calls(menu_desk) == []


def test_many_repos_fold_into_a_list(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    envelope = json.loads(json.dumps(DESKTOP_MENU))
    repo = next(i for i in envelope["data"]["items"] if i["id"].startswith("repo-"))
    for n in range(3):
        envelope["data"]["items"].append(
            {**repo, "id": f"repo-x-{n}", "label": f"x/{n}", "run": {"open": f"https://x/{n}"}}
        )
    serve(menu_desk, "desktop", envelope)
    answers(menu_desk, "")
    menus.quick(reg, "desktop")
    rows = rofi_rows(menu_desk, 0)
    assert rows[-1] == "Repos on GitHub" and not any("x/0" in r for r in rows)
    answers(menu_desk, "", str(len(rows) - 1), "5")
    assert menus.quick(reg, "desktop") == 0
    assert rofi_rows(menu_desk, 2)[-1] == "x/2"
    assert ["xdg-open", "https://x/2"] in menu_desk.detached
    answers(menu_desk, "", str(len(rows) - 1), "5", str(len(rows) - 1), "")
    assert menus.quick(reg, "desktop") == 0  # Escape on the list: nothing


# ---------------------------------------------------------------- running each kind


def test_meta_view_opens_a_pager_in_a_crew_view_window(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    assert quick_pick(menu_desk, reg, "desktop", "Inbox") == 0
    assert ["brain", "inbox", "desktop"] in meta_calls(menu_desk)
    view = next(a for a in menu_desk.detached if a[:1] == ["alacritty"])
    assert view[1:3] == ["--class", "crew-view,desktop"]
    assert view[view.index("-e") + 1 :][:2] == ["less", "-R"]
    shown = Path(view[-1])
    assert shown.read_text().startswith("brain inbox desktop\n")
    assert shown.parent == items.view_dir()


def test_old_views_are_pruned(menu_desk: Desk) -> None:
    import os

    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    folder = items.view_dir()
    folder.mkdir(parents=True)
    old, fresh = folder / "old.txt", folder / "fresh.txt"
    old.write_text("x")
    fresh.write_text("x")
    os.utime(old, (1, 1))
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 0
    assert not old.exists() and fresh.exists()


def test_meta_notify_sends_the_first_lines(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    envelope = json.loads(json.dumps(DESKTOP_MENU))
    status = next(i for i in envelope["data"]["items"] if i["id"] == "status")
    status["output"] = "notify"
    serve(menu_desk, "desktop", envelope)
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 0
    title, body = menu_desk.notified()[-1][-2:]
    assert title == "desktop: Status"
    assert body.splitlines() == ["desktop status", "line 2", "line 3", "line 4", "line 5"]


def test_meta_none_says_nothing(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    envelope = json.loads(json.dumps(DESKTOP_MENU))
    next(i for i in envelope["data"]["items"] if i["id"] == "status")["output"] = "none"
    serve(menu_desk, "desktop", envelope)
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 0
    assert menu_desk.notified() == []


@pytest.mark.parametrize("label", ["Status", "Inbox"])
def test_a_failing_verb_always_notifies(menu_desk: Desk, label: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put(f"rc-{label.lower()}", "5")
    assert quick_pick(menu_desk, reg, "desktop", label) == 1
    title, body = menu_desk.notified()[-1][-2:]
    assert title == f"desktop: {label} failed"
    assert body.startswith("exit 5: meta ") and body.endswith("broke")
    assert not any(a[:1] == ["alacritty"] for a in menu_desk.detached)


def test_edit_opens_vs_code(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    assert quick_pick(menu_desk, reg, "desktop", "Open home in VS Code") == 0
    assert ["code", "/actors/desktop"] in menu_desk.detached
    assert menu_desk.notified() == []  # output none


def test_open_obsidian_and_https(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    assert quick_pick(menu_desk, reg, "desktop", "Actor note in Obsidian") == 0
    assert quick_pick(menu_desk, reg, "desktop", "andronics/desktop-tools") == 0
    opened = [a[1] for a in menu_desk.detached if a[:1] == ["xdg-open"]]
    assert opened == [
        "obsidian://open?path=%2Fvault%2FCoordinator.md",
        "https://github.com/andronics/desktop-tools",
    ]


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("open", "file:///etc/passwd"),
        ("open", "http://example.com"),
        ("open", "javascript:alert(1)"),
        ("open", "--help"),
        ("edit", "relative/path"),
        ("edit", "--install-extension=x"),
    ],
)
def test_other_schemes_and_paths_are_refused(menu_desk: Desk, kind: str, value: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(
        menu_desk,
        "desktop",
        {"data": {"items": [{"id": "x", "label": "Bad", "run": {kind: value}}]}},
    )
    assert quick_pick(menu_desk, reg, "desktop", "Bad") == 1
    assert not any(a[:1] in (["xdg-open"], ["code"]) for a in menu_desk.detached)
    assert menu_desk.notified()[-1][-2] == "desktop: Bad failed"


def test_a_missing_program_is_a_failure(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    (menu_desk.base / "bin" / "code").unlink()
    (menu_desk.base / "bin" / "alacritty").unlink()
    assert quick_pick(menu_desk, reg, "desktop", "Open home in VS Code") == 1
    assert menu_desk.notified()[-1][-1] == "exit 127: code is not on PATH"
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 1
    assert menu_desk.notified()[-1][-1] == "exit 127: alacritty is not on PATH"


def test_open_with_notify_says_what_it_opened(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    item = {"id": "g", "label": "Grafana", "run": {"open": "https://g"}, "output": "notify"}
    serve(menu_desk, "desktop", {"data": {"items": [item]}})
    assert quick_pick(menu_desk, reg, "desktop", "Grafana") == 0
    assert menu_desk.notified()[-1][-2:] == ["desktop: Grafana", "opened https://g"]


def test_copy_puts_the_text_on_the_clipboard_and_says_so(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    assert quick_pick(menu_desk, reg, "desktop", "Copy attach command") == 0
    assert (menu_desk.base / "clipboard").read_text() == "tmux attach -t desktop-coordinator"
    assert menu_desk.calls("xclip")[-1] == ["xclip", "-selection", "clipboard"]
    assert menu_desk.notified()[-1][-2:] == [
        "desktop: copied",
        "tmux attach -t desktop-coordinator",
    ]
    assert not any("attach" in c for c in menu_desk.calls("tmux"))  # crew ran no attach


def test_copy_failing(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("xclip-fail", "")
    assert quick_pick(menu_desk, reg, "desktop", "Copy attach command") == 1
    assert menu_desk.notified()[-1][-1] == "exit 1: Error: Can't open display"
    (menu_desk.base / "bin" / "xclip").unlink()
    assert quick_pick(menu_desk, reg, "desktop", "Copy attach command") == 1
    assert menu_desk.notified()[-1][-1].startswith("exit 127: xclip")


def test_a_confirmed_item_asks_first(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    item = {"id": "s", "label": "Status", "run": {"meta": ["desktop", "status"]}, "confirm": True}
    serve(menu_desk, "desktop", {"data": {"items": [item]}})
    assert quick_pick(menu_desk, reg, "desktop", "Status", "No") == 0
    assert ["desktop", "status"] not in meta_calls(menu_desk)
    question = rofi_calls(menu_desk)[-1]
    assert question[question.index("-p") + 1] == "desktop: Status?"
    assert question[question.index("-selected-row") + 1] == "1"  # No is selected
    assert quick_pick(menu_desk, reg, "desktop", "Status", "Yes") == 0
    assert ["desktop", "status"] in meta_calls(menu_desk)


def test_the_question_uses_the_prompt_theme(menu_desk: Desk, isolate: Path) -> None:
    themes = isolate / "xdg" / "config" / "rofi" / "themes"
    themes.mkdir(parents=True)
    (themes / "prompt.rasi").write_text("")
    assert not stopping.confirm("go?")
    argv = rofi_calls(menu_desk)[-1]
    assert argv[argv.index("-theme") + 1] == str(themes / "prompt.rasi")
    assert rofi_rows(menu_desk, 0) == ["Yes", "No"]


# ---------------------------------------------------------------- stop and restart


@pytest.mark.parametrize("verb", ["Stop", "Restart"])
def test_stop_asks_then_stops(menu_desk: Desk, verb: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    assert quick_pick(menu_desk, reg, "desktop", verb, "No") == 0
    assert [m for m in meta_calls(menu_desk) if m[1] == verb.lower()] == []
    menu_desk.session("desktop-coordinator")
    assert quick_pick(menu_desk, reg, "desktop", verb, "Yes") == 0
    assert meta_calls(menu_desk)[-1] == ["desktop", verb.lower()]
    done = "stopped" if verb == "Stop" else "restarted"
    assert menu_desk.notified()[-1][-2:] == [f"desktop: {done}", "desktop: stopped"]


@pytest.mark.parametrize("verb", ["Stop", "Restart"])
def test_unclean_notes_ask_again_and_yes_forces(menu_desk: Desk, verb: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("stop-rc-desktop", "1")
    assert quick_pick(menu_desk, reg, "desktop", verb, "Yes", "Yes") == 0
    v = verb.lower()
    assert meta_calls(menu_desk)[-2:] == [
        ["desktop", v],
        ["desktop", v, "--force", "--reason", f"Stephen: Yes to {v} anyway"],
    ]
    again = rofi_calls(menu_desk)[-1]
    assert again[again.index("-p") + 1] == f'desktop: no "PAUSED" notes: {v} anyway?'


def test_unclean_notes_and_no_stops_nothing(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("stop-rc-desktop", "1")
    assert quick_pick(menu_desk, reg, "desktop", "Stop", "Yes", "No") == 0
    assert not any("--force" in m for m in meta_calls(menu_desk))


@pytest.mark.parametrize(("code", "title"), [(3, "desktop: not stopped"), (4, "stop failed")])
def test_a_refused_or_failed_stop_notifies(menu_desk: Desk, code: int, title: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("stop-rc-desktop", str(code))
    assert quick_pick(menu_desk, reg, "desktop", "Stop", "Yes") == 1
    got_title, body = menu_desk.notified()[-1][-2:]
    assert title in got_title
    assert body == "meta desktop: stop is not for this caller"


def brain_menu() -> dict[str, Any]:
    text = json.dumps(DESKTOP_MENU).replace('"desktop"', '"brain"')
    envelope: dict[str, Any] = json.loads(text)
    for item in envelope["data"]["items"]:
        item["confirm"] = False  # even unconfirmed, the brain is asked about
    return envelope


def test_the_brain_is_always_asked_about(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain")
    menu_desk.session("brain-coordinator")
    serve(menu_desk, "brain", brain_menu())
    assert quick_pick(menu_desk, reg, "brain", "Stop", "No") == 0
    asked = rofi_calls(menu_desk)[-1]
    assert asked[asked.index("-p") + 1] == "the brain coordinator: stop it?"
    assert meta_calls(menu_desk)[-1] == ["brain", "stop", "--check"]
    assert quick_pick(menu_desk, reg, "brain", "Stop", "Yes") == 0
    assert meta_calls(menu_desk)[-1] == ["brain", "stop"]


def test_the_brain_with_unclean_notes_is_asked_with_why(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain")
    menu_desk.session("brain-coordinator")
    serve(menu_desk, "brain", brain_menu())
    menu_desk.put("check-rc-brain", "1")
    assert quick_pick(menu_desk, reg, "brain", "Restart", "No") == 0
    asked = rofi_calls(menu_desk)[-1]
    assert asked[asked.index("-p") + 1] == (
        "the brain coordinator: newest heading is RESUMED, not PAUSED: restart it anyway?"
    )
    assert quick_pick(menu_desk, reg, "brain", "Restart", "Yes") == 0
    assert meta_calls(menu_desk)[-1] == [
        "brain",
        "restart",
        "--force",
        "--reason",
        "Stephen: Yes to restart the brain coordinator anyway",
    ]


def test_why_reads_the_stop_scripts_lines() -> None:
    assert stopping.why("x\nbrain: notes are old\n", "brain") == "notes are old"
    assert stopping.why("t by=meta why=bare result=x", "brain") == "bare"
    assert stopping.why('t why="a \\"q\\" \\\\ b"', "d") == 'a "q" \\ b'
    assert stopping.why("", "d") == ""


# ---------------------------------------------------------------- the full menu


def test_full_menu_lists_every_coordinator_and_stop_all(
    menu_desk: Desk, theme: dict[str, str]
) -> None:
    reg = reg_of(menu_desk, "brain", "personal", "platform")
    menu_desk.session("brain-coordinator")
    menu_desk.window("platform", hidden=False)
    menu_desk.session("platform-coordinator")
    answers(menu_desk, "")
    assert menus.full(reg) == 0
    assert menu_desk.closed == [True]  # type: ignore[attr-defined]
    rows = rofi_rows(menu_desk, 0)
    assert len(rows) == 4
    assert "<u>b</u>rain" in rows[0] and "running" in rows[0]
    assert "<u>pe</u>rsonal" in rows[1] and "off" in rows[1]
    assert theme["unavailable"] in rows[1]
    assert "<u>pl</u>atform" in rows[2] and "running · open" in rows[2]
    assert "Stop all" in rows[3] and "2 running" in rows[3]
    argv = rofi_calls(menu_desk)[0]
    assert argv[argv.index("-selected-row") + 1] == "2"  # the shown one
    assert argv[argv.index("-a") + 1] == "2"
    assert argv[argv.index("-matching") + 1] == "prefix"


def test_full_menu_shows_a_running_one(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain", "desktop")
    menu_desk.window("desktop")
    answers(menu_desk, "1", "0")
    assert menus.full(reg) == 0
    level_two = rofi_calls(menu_desk)[1]
    assert level_two[level_two.index("-p") + 1] == "desktop (running)"
    assert rofi_rows(menu_desk, 1) == ["Show", "Stop", "Restart"]
    assert menu_desk.shown() == ["desktop"]


def test_full_menu_starts_a_stopped_one(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain", "desktop")
    answers(menu_desk, "1", "0")
    assert menus.full(reg) == 0
    assert rofi_rows(menu_desk, 1) == ["Start"]
    assert menu_desk.launched() == ["desktop"]


def test_full_menu_escape_on_level_two_goes_back(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain", "desktop")
    answers(menu_desk, "1", "", "")
    assert menus.full(reg) == 0
    back = rofi_calls(menu_desk)[2]
    assert back[back.index("-selected-row") + 1] == "1"  # back on the one just left


def test_full_menu_stop_asks_only_when_unclean(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain", "desktop")
    menu_desk.session("desktop-coordinator")
    answers(menu_desk, "1", "1")
    assert menus.full(reg) == 0
    assert meta_calls(menu_desk) == [["desktop", "stop"]]
    menu_desk.session("desktop-coordinator")
    menu_desk.put("stop-rc-desktop", "1")
    clear_rofi(menu_desk)
    # Restart, then No to the unclean question: back to level one, then Escape.
    answers(menu_desk, "1", "2", "No", "")
    assert menus.full(reg) == 0
    assert len(rofi_calls(menu_desk)) == 2 + 4


def test_full_menu_hide_label(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.window("desktop", hidden=False, focused=True)
    answers(menu_desk, "0", "")
    assert menus.full(reg) == 0
    assert rofi_rows(menu_desk, 1)[0] == "Hide"


def test_stop_all_asks_once_and_forces_the_unclean(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain", "desktop", "homelab", "media")
    menu_desk.session("brain-coordinator", "desktop-coordinator", "homelab-coordinator")
    menu_desk.put("check-rc-desktop", "1")
    answers(menu_desk, "4", "Yes")
    assert menus.full(reg) == 0
    asked = rofi_calls(menu_desk)[-1]
    assert asked[asked.index("-p") + 1] == (
        "desktop: newest heading is RESUMED, not PAUSED; the brain coordinator too: "
        "stop all anyway?"
    )
    assert meta_calls(menu_desk) == [
        ["desktop", "stop", "--check"],
        ["homelab", "stop", "--check"],
        ["brain", "stop", "--check"],
        ["desktop", "stop", "--force", "--reason", "Stephen: Yes to stop all anyway"],
        ["homelab", "stop"],
        ["brain", "stop"],  # the brain last
    ]


def test_stop_all_no_stops_nothing_and_goes_back(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop", "homelab")
    menu_desk.session("desktop-coordinator", "homelab-coordinator")
    menu_desk.put("check-rc-desktop", "1")
    menu_desk.put("check-rc-homelab", "1")
    answers(menu_desk, "2", "No", "")
    assert menus.full(reg) == 0
    asked = rofi_calls(menu_desk)[1]
    assert asked[asked.index("-p") + 1] == "notes not clean for desktop, homelab: stop all anyway?"
    assert all("--check" in m for m in meta_calls(menu_desk))
    assert len(rofi_calls(menu_desk)) == 3  # back to level one


def test_stop_all_clean_asks_nothing(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    menu_desk.put("stop-rc-desktop", "4")
    answers(menu_desk, "1")
    assert menus.full(reg) == 1  # the stop failed, and said so
    assert meta_calls(menu_desk)[-1] == ["desktop", "stop"]
    assert "stop failed" in menu_desk.notified()[-1][-2]


def test_stop_all_with_none_running(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    answers(menu_desk, "1")
    assert menus.full(reg) == 0
    assert menu_desk.notified()[-1][-2] == "no coordinator is running"


def test_full_menu_theme_falls_back_to_coords(
    isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    themes = isolate / "xdg" / "config" / "rofi" / "themes"
    themes.mkdir(parents=True)
    assert menus.menu_theme() == []
    (themes / "coord.rasi").write_text("")
    assert menus.menu_theme() == ["-theme", str(themes / "coord.rasi")]
    (themes / "crew.rasi").write_text("")
    assert menus.menu_theme() == ["-theme", str(themes / "crew.rasi")]
    monkeypatch.setenv("CREW_MENU_THEME", "coord")
    assert menus.menu_theme() == ["-theme", str(themes / "coord.rasi")]


def test_cells_colour_each_state() -> None:
    colours = {"dim": "#1", "idle": "#2", "busy": "#3", "waiting": "#4", "ink": "#5"}
    assert "foreground='#3'" in menus.cell("a", "G", "a", "busy", False, colours)
    waiting = menus.cell("a", "G", "a", "waiting", False, colours)
    assert "background='#4' foreground='#5'" in waiting and "waiting" in waiting
    assert "foreground='#2'" in menus.cell("a", "G", "a", "idle", False, colours)
    assert menus.cell("a&b", "<", "", "idle", False, {}).count("&amp;") == 1
    assert "foreground='#1'" in menus.stop_cell(0, colours)


# ---------------------------------------------------------------- no shell anywhere


def test_no_shell_in_crew() -> None:
    import desktop_tools.crew as pkg

    for path in Path(pkg.__file__).parent.glob("*.py"):
        text = path.read_text()
        for bad in ("shell=True", "os.system", "sh -c", '"sh", "-c"', '"zsh", "-c"'):
            assert bad not in text, f"{path.name}: {bad}"


def test_every_child_is_an_argument_list(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    for label in ("Status", "Open home in VS Code", "Actor note in Obsidian"):
        quick_pick(menu_desk, reg, "desktop", label)
    for argv in menu_desk.detached:
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        assert argv[0] not in ("sh", "zsh", "bash")


def test_copy_does_not_wait_for_xclips_lingering_child(
    menu_desk: Desk, commands: Callable[..., Path]
) -> None:
    """The real xclip forks a child that keeps serving the selection with what it inherited:
    crew must not wait on it."""
    import time

    commands(
        xclip="data = sys.stdin.read()\n"
        "if os.fork() == 0:\n"
        "    time.sleep(8)\n"
        "    os._exit(0)\n"
        "open(os.path.join(here, 'clipboard'), 'w').write(data)\n"
    )
    reg = reg_of(menu_desk, "desktop")
    c = reg.get("desktop")
    assert c is not None
    began = time.monotonic()
    assert items.run_copy(c, items.Item("a", "A", "copy", "hello")) == 0
    assert time.monotonic() - began < 4
    assert (menu_desk.base / "clipboard").read_text() == "hello"


def test_view_needs_its_pager_and_names_files_safely(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    c = reg.get("desktop")
    assert c is not None
    item = items.Item("../../x y", "X", "meta", ["desktop", "status"])
    assert items.view(c, item, "text") == 0
    shown = Path(next(a for a in menu_desk.detached if a[:1] == ["alacritty"])[-1])
    assert shown.parent == items.view_dir() and shown.name.startswith("desktop-______x_y-")
    (menu_desk.base / "bin" / "less").unlink()
    assert items.view(c, item, "text") == 1
    assert menu_desk.notified()[-1][-1] == "exit 127: less is not on PATH"

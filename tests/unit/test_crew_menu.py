"""crew's menus (brain record 0019 §7a): the quick menu on each glyph, built from meta's real
`menu --json` (tests/fixtures, copied from the live `meta desktop menu --json` and `meta ventures
menu --json`, paths made generic), and the full two-level menu ported from coord.

Everything is fake: meta, rofi, alacritty, notify-send, xdg-open, code and xclip; tmux names its
own server. Detached children are recorded, not run (alacritty runs, to add its window)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from desktop_tools.crew import items, life, menus, registry, stopping
from desktop_tools.crew.registry import Registry
from tests.crew_fakes import ROFI_SEQ, XCLIP, Desk

FIXTURES = Path(__file__).parent.parent / "fixtures"
DESKTOP_MENU = json.loads((FIXTURES / "meta-menu-desktop.json").read_text())
VENTURES_MENU = json.loads((FIXTURES / "meta-menu-ventures.json").read_text())
# meta's own folding: more than four repos come as one item holding them (`items`, no `run`).
PLATFORM_MENU = json.loads((FIXTURES / "meta-menu-platform.json").read_text())
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
        rofi=ROFI_SEQ,
        xclip=XCLIP,
        xdotool="sys.exit(1)",
        **{"xdg-open": "", "code": "", "less": ""},
    )
    return desk


def reg_of(desk: Desk, *names: str, **extra: dict[str, Any]) -> Registry:
    desk.coordinators(*names, **extra)
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
    """Launch is crew's lifecycle verb (`life.launch`): started hidden, the strip refreshed."""
    from desktop_tools.barctl import state as bst

    reg = reg_of(menu_desk, "ventures")
    serve(menu_desk, "ventures", VENTURES_MENU)
    assert quick_pick(menu_desk, reg, "ventures", "Launch") == 0
    assert rofi_rows(menu_desk, 0)[:2] == ["Show", "Launch"]
    assert menu_desk.launched() == ["ventures"]
    assert menu_desk.shown() == []
    strip = (bst.read("crew") or {}).get("segments", [])
    assert [(s["id"], s["tier"]) for s in strip] == [("ventures", "idle")]  # running now
    assert menu_desk.notified()[-1][-2:] == ["ventures: launched", "done"]


def test_a_refused_launch_notifies(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "ventures")
    serve(menu_desk, "ventures", VENTURES_MENU)
    menu_desk.put("launch-rc-ventures", "3")
    menu_desk.put("launch-why", "standby: no launch")
    assert quick_pick(menu_desk, reg, "ventures", "Launch") == 3
    assert menu_desk.notified()[-1][-2:] == [
        "ventures: not started",
        "meta ventures exited 3 (refused): meta ventures: standby: no launch",
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
    menu_desk.put(f"{label.lower()}-rc", "6")
    assert quick_pick(menu_desk, reg, "desktop", label) == 1
    title, body = menu_desk.notified()[-1][-2:]
    assert title == f"desktop: {label} failed"
    assert body.startswith("exit 6 (the module is broken): meta ") and body.endswith("broke")
    assert not any(a[:1] == ["alacritty"] for a in menu_desk.detached)


# meta's exit codes (brain record 0019): 0, 1 and 5 are results; 2, 3, 4 and 6 failures.


def status_as(desk: Desk, output: str) -> None:
    envelope = json.loads(json.dumps(DESKTOP_MENU))
    next(i for i in envelope["data"]["items"] if i["id"] == "status")["output"] = output
    serve(desk, "desktop", envelope)


def failures(desk: Desk) -> list[list[str]]:
    return [n for n in desk.notified() if n[-2].endswith(" failed")]


def test_exit_1_is_a_result_shown_with_a_warning(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("status-rc", "1")
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 0
    view = next(a for a in menu_desk.detached if a[:1] == ["alacritty"])
    warn = "⚠ desktop: Status: there is a problem"
    assert view[view.index("--title") + 1] == warn
    assert Path(view[-1]).read_text().splitlines()[:3] == [warn, "", "desktop status"]
    assert failures(menu_desk) == []


def test_exit_1_notify_is_warned_and_none_says_nothing(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.put("status-rc", "1")
    status_as(menu_desk, "notify")
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 0
    title, body = menu_desk.notified()[-1][-2:]
    assert title == "⚠ desktop: Status: there is a problem"
    assert body.splitlines()[0] == "desktop status"
    status_as(menu_desk, "none")
    before = len(menu_desk.notified())
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 0
    assert len(menu_desk.notified()) == before


def test_exit_4_with_only_stdout_gives_that_reason(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("status-rc", "4")
    menu_desk.put("status-stdout", "meta desktop: vault-query unreachable")
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 1
    assert menu_desk.notified()[-1][-2:] == [
        "desktop: Status failed",
        "exit 4 (failed): meta desktop: vault-query unreachable",
    ]
    assert not any(a[:1] == ["alacritty"] for a in menu_desk.detached)


@pytest.mark.parametrize("output", ["view", "notify", "none"])
def test_exit_5_is_a_not_found_notice(menu_desk: Desk, output: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    status_as(menu_desk, output)
    menu_desk.put("status-rc", "5")
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 0
    assert menu_desk.notified()[-1][-2:] == [
        "desktop: Status: not found",
        "meta desktop: status broke",
    ]
    assert failures(menu_desk) == []
    assert not any(a[:1] == ["alacritty"] for a in menu_desk.detached)


@pytest.mark.parametrize(("code", "means"), [(2, "usage"), (3, "refused")])
def test_refused_and_usage_say_so_with_the_reason(menu_desk: Desk, code: int, means: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    status_as(menu_desk, "none")
    menu_desk.put("status-rc", str(code))
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 1
    assert menu_desk.notified()[-1][-2:] == [
        "desktop: Status failed",
        f"exit {code} ({means}): meta desktop: status broke",
    ]


def test_a_failure_with_no_reason_never_says_a_dash(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("status-rc", "4")
    menu_desk.put("status-stdout", "")
    assert quick_pick(menu_desk, reg, "desktop", "Status") == 1
    assert menu_desk.notified()[-1][-1] == "exit 4 (failed): no reason given"


# ---------------------------------------------------------------- meta's second-level lists


def test_parse_reads_a_nested_list() -> None:
    found = items.parse(PLATFORM_MENU)
    assert found is not None
    repos = next(i for i in found if i.id == "repos")
    assert (repos.kind, repos.label, repos.when) == (items.LIST, "Repos on GitHub", "always")
    assert [i.label for i in repos.items] == [f"andronics/example-{n}" for n in range(1, 8)]
    assert all(i.kind == "open" for i in repos.items)


def test_a_nested_list_is_one_row_and_escape_goes_back(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "platform")
    serve(menu_desk, "platform", PLATFORM_MENU)
    answers(menu_desk, "")
    menus.quick(reg, "platform")
    rows = rofi_rows(menu_desk, 0)
    assert rows[-1] == "Repos on GitHub" and rows.count("Repos on GitHub") == 1
    assert not any("example" in r for r in rows)
    repos = str(len(rows) - 1)
    clear_rofi(menu_desk)
    answers(menu_desk, repos, "2")
    assert menus.quick(reg, "platform") == 0
    assert rofi_rows(menu_desk, 1) == [f"andronics/example-{n}" for n in range(1, 8)]
    assert ["xdg-open", "https://github.com/andronics/example-3"] in menu_desk.detached
    clear_rofi(menu_desk)
    answers(menu_desk, repos, "", "")  # Escape on the list: back to the first level, Escape
    assert menus.quick(reg, "platform") == 0
    assert rofi_rows(menu_desk, 2) == rows


def test_an_invalid_nested_item_is_dropped_and_the_rest_stay(
    capsys: pytest.CaptureFixture[str],
) -> None:
    envelope = json.loads(json.dumps(PLATFORM_MENU))
    repos = next(i for i in envelope["data"]["items"] if i["id"] == "repos")
    repos["items"].insert(1, {"id": "bad", "label": "Bad", "run": {"shell": "ls"}})
    found = items.parse(envelope) or []
    assert [i.id for i in next(i for i in found if i.id == "repos").items] == [
        f"repo-andronics-example-{n}" for n in range(1, 8)
    ]
    assert "menu: bad: run 'shell' is not something crew can run" in capsys.readouterr().err
    repos["items"].append({"id": "deeper", "label": "Deeper", "items": [repos["items"][0]]})
    found = items.parse(envelope) or []
    assert "deeper" not in [i.id for i in next(i for i in found if i.id == "repos").items]
    assert "menu: repos: deeper: a list in a list, dropped" in capsys.readouterr().err
    repos["items"] = [{"id": "bad", "label": "Bad"}]
    found = items.parse(envelope) or []
    assert "repos" not in [i.id for i in found] and "status" in [i.id for i in found]
    assert "menu: repos: a list with no items crew can run" in capsys.readouterr().err


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
    assert question[question.index("-mesg") + 1] == "desktop: Status?"
    assert question[question.index("-selected-row") + 1] == "1"  # No is selected
    assert quick_pick(menu_desk, reg, "desktop", "Status", "Yes") == 0
    assert ["desktop", "status"] in meta_calls(menu_desk)


def test_the_question_uses_the_confirm_theme(menu_desk: Desk, isolate: Path) -> None:
    themes = isolate / "xdg" / "config" / "rofi" / "themes"
    themes.mkdir(parents=True)
    (themes / "prompt.rasi").write_text("")
    (themes / "confirm.rasi").write_text("")
    assert not stopping.confirm("go?")
    argv = rofi_calls(menu_desk)[-1]
    assert argv[argv.index("-theme") + 1] == str(themes / "confirm.rasi")
    assert argv[argv.index("-mesg") + 1] == "go?"  # the question in full, over the rows
    assert argv[argv.index("-p") + 1] == "crew"
    assert argv[argv.index("-selected-row") + 1] == "1"  # No is selected
    assert {"-no-custom", "-i"} <= set(argv)
    assert argv[argv.index("-format") + 1] == "s"
    assert rofi_rows(menu_desk, 0)[:2] == ["Yes", "No"]


def test_without_confirm_the_question_falls_back_to_prompt(menu_desk: Desk, isolate: Path) -> None:
    themes = isolate / "xdg" / "config" / "rofi" / "themes"
    themes.mkdir(parents=True)
    (themes / "prompt.rasi").write_text("")
    answers(menu_desk, "Yes")
    assert stopping.confirm("go?")
    argv = rofi_calls(menu_desk)[-1]
    assert argv[argv.index("-theme") + 1] == str(themes / "prompt.rasi")
    assert argv[argv.index("-mesg") + 1] == "go?"
    (themes / "prompt.rasi").unlink()
    assert not stopping.confirm("go?")
    assert "-theme" not in rofi_calls(menu_desk)[-1]  # neither: rofi's own


def test_the_question_is_pango_escaped(menu_desk: Desk) -> None:
    assert not stopping.confirm("a <b> & c?")
    argv = rofi_calls(menu_desk)[-1]
    assert argv[argv.index("-mesg") + 1] == "a &lt;b&gt; &amp; c?"


# ---------------------------------------------------------------- stop and restart


@pytest.mark.parametrize("verb", ["Stop", "Restart"])
def test_stop_asks_then_stops(menu_desk: Desk, verb: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    v = verb.lower()
    assert quick_pick(menu_desk, reg, "desktop", verb, "No") == 0
    assert [m for m in meta_calls(menu_desk) if m[1] == v] == []
    assert quick_pick(menu_desk, reg, "desktop", verb, "Yes") == 0
    assert meta_calls(menu_desk)[-2:] == [["desktop", "stop", "--check"], ["desktop", v]]
    done = "stopped" if verb == "Stop" else "restarted"
    assert menu_desk.notified()[-1][-2:] == [f"desktop: {done}", "done"]


@pytest.mark.parametrize("verb", ["Stop", "Restart"])
def test_unclean_notes_ask_again_and_yes_forces(menu_desk: Desk, verb: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("check-rc-desktop", "1")
    menu_desk.put("check-why", "no PAUSED notes")
    v = verb.lower()
    assert quick_pick(menu_desk, reg, "desktop", verb, "Yes", "Yes") == 0
    assert meta_calls(menu_desk)[-2:] == [
        ["desktop", "stop", "--check"],
        ["desktop", v, "--force", "--reason", f"Stephen: Yes to {v} anyway"],
    ]
    again = rofi_calls(menu_desk)[-1]
    assert again[again.index("-mesg") + 1] == f"desktop: no PAUSED notes: {v} anyway?"


def test_unclean_notes_and_no_stops_nothing(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("check-rc-desktop", "1")
    assert quick_pick(menu_desk, reg, "desktop", "Stop", "Yes", "No") == 0
    assert meta_calls(menu_desk)[-1] == ["desktop", "stop", "--check"]


@pytest.mark.parametrize("verb", ["stop", "restart"])
def test_a_refused_forced_stop_notifies(menu_desk: Desk, verb: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("check-rc-desktop", "1")
    menu_desk.put(f"{verb}-rc-desktop", "4")
    assert quick_pick(menu_desk, reg, "desktop", verb.capitalize(), "Yes", "Yes") == 4
    done = "stopped" if verb == "stop" else "restarted"
    assert menu_desk.notified()[-1][-2] == f"desktop: not {done}"


@pytest.mark.parametrize(("code", "means"), [(3, "refused"), (4, "failed")])
def test_a_refused_or_failed_stop_notifies(menu_desk: Desk, code: int, means: str) -> None:
    reg = reg_of(menu_desk, "desktop")
    menu_desk.session("desktop-coordinator")
    serve(menu_desk, "desktop", DESKTOP_MENU)
    menu_desk.put("stop-rc-desktop", str(code))
    assert quick_pick(menu_desk, reg, "desktop", "Stop", "Yes") == code
    assert menu_desk.notified()[-1][-2:] == [
        "desktop: not stopped",
        f"meta desktop exited {code} ({means}): meta desktop: refused",
    ]


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
    assert asked[asked.index("-mesg") + 1] == "the brain coordinator: stop it?"
    assert meta_calls(menu_desk)[-1] == ["brain", "stop", "--check"]
    assert quick_pick(menu_desk, reg, "brain", "Stop", "Yes") == 0
    assert meta_calls(menu_desk)[-1] == ["brain", "stop", "--confirmed"]


@pytest.mark.parametrize("verb", ["stop", "restart"])
def test_confirmed_is_only_for_the_brain_and_only_on_yes(menu_desk: Desk, verb: str) -> None:
    reg = reg_of(menu_desk, "brain", "desktop")
    menu_desk.session("brain-coordinator", "desktop-coordinator")
    brain, desktop = reg.get("brain"), reg.get("desktop")
    assert brain is not None and desktop is not None
    answers(menu_desk, "No")
    assert stopping.end(reg, brain, verb, ask_first=False) == stopping.DECLINED  # the full menu's
    assert meta_calls(menu_desk) == [["brain", "stop", "--check"]]  # judged, nothing ended
    clear_rofi(menu_desk)
    answers(menu_desk, "Yes")
    assert stopping.end(reg, brain, verb, ask_first=False) == 0
    assert meta_calls(menu_desk)[-1] == ["brain", verb, "--confirmed"]
    clear_rofi(menu_desk)
    answers(menu_desk, "Yes")
    assert stopping.end(reg, desktop, verb, ask_first=True) == 0
    assert meta_calls(menu_desk)[-1] == ["desktop", verb]
    assert not any("--confirmed" in c for c in meta_calls(menu_desk) if c[0] != "brain")


def test_the_brain_with_unclean_notes_is_asked_with_why(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "brain")
    menu_desk.session("brain-coordinator")
    serve(menu_desk, "brain", brain_menu())
    menu_desk.put("check-rc-brain", "1")
    menu_desk.put("check-why", "newest heading is RESUMED, not PAUSED")
    assert quick_pick(menu_desk, reg, "brain", "Restart", "No") == 0
    asked = rofi_calls(menu_desk)[-1]
    assert asked[asked.index("-mesg") + 1] == (
        "the brain coordinator: newest heading is RESUMED, not PAUSED: restart it anyway?"
    )
    assert quick_pick(menu_desk, reg, "brain", "Restart", "Yes") == 0
    assert meta_calls(menu_desk)[-1] == [
        "brain",
        "restart",
        "--force",
        "--reason",
        "Stephen: Yes to restart the brain coordinator anyway",
        "--confirmed",
    ]


@pytest.mark.parametrize("verb", ["stop", "restart"])
def test_every_one_only_stephen_ends_is_asked_and_confirmed(menu_desk: Desk, verb: str) -> None:
    """The registry's `ended_by`: the brain, the arbiter and a third, with no crew change."""
    names = ("brain", "arbiter", "media", "desktop")
    by_stephen = {"ended_by": "stephen"}
    reg = reg_of(menu_desk, *names, brain=by_stephen, arbiter=by_stephen, media=by_stephen)
    menu_desk.session(*(f"{n}-coordinator" for n in names))
    for name in ("brain", "arbiter", "media"):
        c = reg.get(name)
        assert c is not None
        clear_rofi(menu_desk)
        answers(menu_desk, "No")
        assert stopping.end(reg, c, verb, ask_first=False) == stopping.DECLINED
        asked = rofi_calls(menu_desk)[-1]
        assert asked[asked.index("-mesg") + 1] == f"the {name} coordinator: {verb} it?"
        clear_rofi(menu_desk)
        answers(menu_desk, "Yes")
        assert stopping.end(reg, c, verb, ask_first=False) == 0
        assert meta_calls(menu_desk)[-1] == [name, verb, "--confirmed"]
    desktop = reg.get("desktop")
    assert desktop is not None
    clear_rofi(menu_desk)
    assert stopping.end(reg, desktop, verb, ask_first=False) == 0  # not asked: clean
    assert meta_calls(menu_desk)[-1] == ["desktop", verb]


# ------------------------------------------- Stop and Restart from a click (the click-test)

# crew's real waits, kept before make_desk zeroes them for speed (absent before the fix).
REAL_WAITS = {k: getattr(life, k) for k in ("SETTLE", "UNSHOWN") if hasattr(life, k)}


def platform_running(desk: Desk) -> Registry:
    reg = reg_of(desk, "platform")
    desk.session("platform-coordinator")
    serve(desk, "platform", PLATFORM_MENU)
    return reg


def unshown(desk: Desk) -> list[str]:
    path = desk.base / "rofi-unshown"
    return path.read_text().split() if path.exists() else []


def drawn(row: str) -> str:
    return row.rsplit("</span> ", 1)[-1]  # the label, without its glyph


@pytest.mark.parametrize("verb", ["Stop", "Restart"])
def test_a_question_opened_on_the_menus_click_is_still_asked(
    menu_desk: Desk, monkeypatch: pytest.MonkeyPatch, verb: str
) -> None:
    """The click-test: Stop from platform's quick menu did nothing. A rofi started the instant
    the menu's rofi closed closes at once (the menu's own click lands on it), which read as No:
    exit 0, meta never called. crew now waits for the click to land, so it is asked."""
    for name, value in REAL_WAITS.items():
        monkeypatch.setattr(life, name, value)
    reg = platform_running(menu_desk)
    menu_desk.put("rofi-race", "0.15")
    answers(menu_desk, "")
    assert menus.quick(reg, "platform") == 0
    pick = index_of(menu_desk, verb)
    clear_rofi(menu_desk)
    (menu_desk.base / "rofi-closed").unlink()  # the menu itself opens long after the last
    answers(menu_desk, pick, "Yes")
    assert menus.quick(reg, "platform") == 0
    assert unshown(menu_desk) == []
    v = verb.lower()
    assert meta_calls(menu_desk)[-2:] == [["platform", "stop", "--check"], ["platform", v]]


def platform_paths() -> list[tuple[str, ...]]:
    """Every row of platform's quick menu while it runs, as the labels picked to reach it."""
    found = items.parse(PLATFORM_MENU)
    assert found is not None
    paths: list[tuple[str, ...]] = [("Show",)]
    for i in found:
        if not items.applies(i, True):
            continue
        if i.kind == items.LIST:
            paths += [(i.label, s.label) for s in i.items if items.applies(s, True)]
        else:
            paths.append((i.label,))
    return paths


def test_the_paths_cover_every_drawn_row(menu_desk: Desk) -> None:
    reg = platform_running(menu_desk)
    answers(menu_desk, "")
    menus.quick(reg, "platform")
    tops = [drawn(r) for r in rofi_rows(menu_desk, 0)]
    paths = platform_paths()
    assert tops == list(dict.fromkeys(p[0] for p in paths))
    assert len(paths) > len(tops)  # Repos on GitHub holds rows of its own


@pytest.mark.parametrize("path", platform_paths(), ids=lambda p: "/".join(p))
def test_each_label_runs_its_own_item(
    menu_desk: Desk, monkeypatch: pytest.MonkeyPatch, path: tuple[str, ...]
) -> None:
    """The row picked by its label runs that row's item, never a neighbour's: rofi's index is
    read back against the very rows drawn."""
    from desktop_tools.crew import switch

    reg = platform_running(menu_desk)
    ran: list[tuple[str, ...]] = []

    def record(*what: str) -> int:
        ran.append(what)
        return 0

    monkeypatch.setattr(switch, "toggle", lambda reg, name, **kw: record("toggle"))
    monkeypatch.setattr(items, "run", lambda c, item: record("run", item.label))
    monkeypatch.setattr(
        stopping, "end", lambda reg, c, verb, *, ask_first: record(verb, str(ask_first))
    )
    picks: list[str] = []
    for depth, label in enumerate(path):
        clear_rofi(menu_desk)
        answers(menu_desk, *picks, "", "")  # learn this level's rows, then Escape out
        menus.quick(reg, "platform")
        rows = [drawn(r) for r in rofi_rows(menu_desk, depth)]
        assert rows.count(label) == 1, rows
        picks.append(str(rows.index(label)))
    ran.clear()
    clear_rofi(menu_desk)
    answers(menu_desk, *picks)
    assert menus.quick(reg, "platform") == 0
    found = items.parse(PLATFORM_MENU)
    assert found is not None
    flat = {i.label: i for i in found} | {s.label: s for i in found for s in i.items}
    if path == ("Show",):
        assert ran == [("toggle",)]
    elif (life_of := flat[path[-1]].lifecycle()) is not None:
        assert ran == [(life_of[1], str(flat[path[-1]].confirm))]
    else:
        assert ran == [("run", path[-1])]


@pytest.mark.parametrize("verb", ["Stop", "Restart"])
def test_a_question_that_fails_once_is_asked_again(
    menu_desk: Desk, capsys: pytest.CaptureFixture[str], verb: str
) -> None:
    reg = platform_running(menu_desk)
    menu_desk.put("rofi-fails", "1")
    assert quick_pick(menu_desk, reg, "platform", verb, "Yes") == 0
    assert unshown(menu_desk) == ["grab"]
    v = verb.lower()
    assert meta_calls(menu_desk)[-2:] == [["platform", "stop", "--check"], ["platform", v]]
    assert f"cannot ask (platform: {v} it?)" in capsys.readouterr().err  # the journal's warning


@pytest.mark.parametrize("verb", ["Stop", "Restart"])
def test_a_question_that_cannot_be_shown_is_no_no(
    menu_desk: Desk, capsys: pytest.CaptureFixture[str], verb: str
) -> None:
    """Twice unshown: Stephen is told it couldn't ask, nothing runs and crew exits 1."""
    reg = platform_running(menu_desk)
    menu_desk.put("rofi-fails", "2")
    assert quick_pick(menu_desk, reg, "platform", verb, "Yes") == 1
    assert unshown(menu_desk) == ["grab", "grab"]
    assert meta_calls(menu_desk)[-1] == ["platform", "menu", "--json"]  # nothing ended
    title, body = menu_desk.notified()[-1][-2:]
    assert title == "couldn't ask: Failed to grab keyboard after 500 times. Giving up."
    assert body == f"platform: {verb.lower()} it? Nothing was done."
    assert "cannot ask" in capsys.readouterr().err


def test_no_from_platforms_quick_menu_runs_nothing(menu_desk: Desk) -> None:
    reg = platform_running(menu_desk)
    for verb in ("Stop", "Restart"):
        assert quick_pick(menu_desk, reg, "platform", verb, "No") == 0
    assert meta_calls(menu_desk) == [["platform", "menu", "--json"]] * 4
    assert unshown(menu_desk) == []


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
    assert meta_calls(menu_desk) == [["desktop", "stop", "--check"], ["desktop", "stop"]]
    assert len(rofi_calls(menu_desk)) == 2  # no question: the notes were clean
    menu_desk.session("desktop-coordinator")
    menu_desk.put("check-rc-desktop", "1")
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


def test_stop_all_is_crews_stop_all(menu_desk: Desk) -> None:
    """The full menu's Stop all is `life.stop_all`: asks once, forces the unclean, leaves the
    brain coordinator (meta never stops it for crew)."""
    reg = reg_of(menu_desk, "brain", "desktop", "homelab", "media")
    menu_desk.session("brain-coordinator", "desktop-coordinator", "homelab-coordinator")
    menu_desk.put("check-rc-desktop", "1")
    menu_desk.put("check-why", "newest heading is RESUMED, not PAUSED")
    answers(menu_desk, "4", "Yes")
    assert menus.full(reg) == 0
    asked = rofi_calls(menu_desk)[-1]
    assert asked[asked.index("-mesg") + 1] == (
        "desktop: newest heading is RESUMED, not PAUSED: stop all anyway?"
    )
    assert meta_calls(menu_desk) == [
        ["desktop", "stop", "--check"],
        ["homelab", "stop", "--check"],
        ["desktop", "stop", "--force", "--reason", "Stephen: Yes to stop all anyway"],
        ["homelab", "stop"],
    ]


def test_stop_all_no_stops_nothing(menu_desk: Desk) -> None:
    reg = reg_of(menu_desk, "desktop", "homelab")
    menu_desk.session("desktop-coordinator", "homelab-coordinator")
    menu_desk.put("check-rc-desktop", "1")
    menu_desk.put("check-rc-homelab", "1")
    answers(menu_desk, "2", "No")
    assert menus.full(reg) == 1  # life.stop_all: declined is 1, nothing stopped
    asked = rofi_calls(menu_desk)[1]
    assert asked[asked.index("-mesg") + 1] == "notes not clean for desktop, homelab: stop all anyway?"
    assert all("--check" in m for m in meta_calls(menu_desk))


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


def test_a_question_closed_at_once_is_unshown_and_says_why(
    menu_desk: Desk, monkeypatch: pytest.MonkeyPatch, commands: Callable[..., Path]
) -> None:
    """No settle: each try opens on the last rofi's heels and closes unseen, twice."""
    monkeypatch.setattr(life, "UNSHOWN", REAL_WAITS["UNSHOWN"])
    menu_desk.put("rofi-race", "60")
    menu_desk.put("rofi-closed", repr(time.monotonic()))
    with pytest.raises(stopping.Unasked, match=r"^rofi closed after \d+ ms"):
        stopping.confirm("go?")
    assert unshown(menu_desk) == ["race", "race"]
    commands(rofi="sys.stderr.write('rofi: boom\\n'); sys.exit(2)")
    with pytest.raises(stopping.Unasked, match=r"^rofi exited 2: rofi: boom$"):
        stopping.confirm("go?")
    commands(rofi="sys.exit(1)")  # Escape after the question was seen: No
    monkeypatch.setattr(life, "UNSHOWN", 0.0)
    assert stopping.confirm("go?") is False

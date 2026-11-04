"""crew's registry (brain record 0019 §4): read from a fake `meta`, kept, fallen back to the kept
copy and then the homes; former names; the menu keys (tests/coordinators.zsh's names cases)."""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

import pytest

from desktop_tools.crew import registry as rg
from tests.crew_fakes import Desk

NEW = ["brain", "platform", "personal", "homelab", "network-tools", "media", "desktop"]
NEW += ["incubator", "security", "ventures"]


def test_reads_meta_in_menu_order_and_keeps_a_copy(desk: Desk) -> None:
    desk.coordinators("brain", "media")
    envelope = json.loads((desk.base / "registry.json").read_text())
    envelope["data"][0]["menu_order"], envelope["data"][1]["menu_order"] = 20, 10
    desk.put("registry.json", json.dumps(envelope))
    reg = rg.load()
    assert (reg.names, reg.source) == (["media", "brain"], "meta")
    assert rg.kept_path().is_file()
    assert desk.calls("meta") == [["meta", "brain", "coordinators", "--json"]]


def test_kept_copy_is_used_while_fresh(desk: Desk) -> None:
    desk.coordinators("brain")
    rg.load()
    desk.coordinators("brain", "media")
    assert rg.load().names == ["brain"]
    assert len(desk.calls("meta")) == 1


def test_old_kept_copy_asks_meta_again(desk: Desk, monkeypatch: pytest.MonkeyPatch) -> None:
    desk.coordinators("brain")
    rg.load()
    old = time.time() - 301
    os.utime(rg.kept_path(), (old, old))
    desk.coordinators("brain", "media")
    assert rg.load().names == ["brain", "media"]
    monkeypatch.setenv("CREW_REGISTRY_MAX_AGE", "0")
    rg.load()
    assert len(desk.calls("meta")) == 3


def test_hot_paths_never_ask_meta(desk: Desk) -> None:
    desk.coordinators("brain")
    assert rg.load(refresh=False).source == "homes"
    assert desk.calls("meta") == []


def test_meta_failing_falls_back_to_the_kept_copy(
    desk: Desk, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    desk.coordinators("brain", "media")
    rg.load()
    monkeypatch.setenv("CREW_REGISTRY_MAX_AGE", "0")
    desk.put("meta-rc", "4")
    reg = rg.load()
    assert (reg.names, reg.source) == (["brain", "media"], "kept")
    assert (
        "meta brain coordinators exited 4: meta brain: vault-query failed"
        in capsys.readouterr().err
    )


def test_no_copy_falls_back_to_the_homes(desk: Desk) -> None:
    desk.coordinators("media", "brain")
    desk.put("meta-rc", "6")
    (desk.actors / "bin").mkdir()  # not a home: no README.md
    reg = rg.load()
    assert (reg.names, reg.source) == (["brain", "media"], "homes")


def test_meta_missing_is_quiet(isolate: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (isolate / "bin" / "meta").unlink()  # not installed yet (no tripwire either)
    assert rg.load().coordinators == []
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "answer",
    ["not json", json.dumps({"other": 1}), json.dumps([]), json.dumps([{"name": "Bad Name"}])],
)
def test_bad_answers_are_not_kept(desk: Desk, answer: str) -> None:
    desk.coordinators("brain")
    desk.put("registry.json", answer)
    assert rg.load().source == "homes"
    assert not rg.kept_path().exists()


def test_meta_envelope_is_unwrapped(desk: Desk) -> None:
    entries = desk.coordinators("brain")
    wrapped = {
        "meta": 1,
        "centre": "brain",
        "verb": "coordinators",
        "data": {"coordinators": entries},
    }
    desk.put("registry.json", json.dumps(wrapped))
    assert rg.load().names == ["brain"]


def test_shown_after_all_moves_and_hidden_without_a_home(desk: Desk) -> None:
    """coordinators.zsh: shown-after-all-moves, security-hidden-no-home."""
    desk.coordinators(*NEW)
    assert rg.load().names == NEW
    desk.coordinators("brain", "security")
    (desk.actors / "security" / "README.md").unlink()
    (desk.actors / "security").rmdir()
    os.utime(rg.kept_path(), (0, 0))
    assert rg.load().names == ["brain"]


def test_former_names_resolve(desk: Desk) -> None:
    """coordinators.zsh: resolve. A former name is the coordinator it became; others as given."""
    desk.coordinators(
        "brain",
        "desktop",
        "media",
        desktop={"old_names": ["dotfiles"]},
        media={"old_names": ["apps"]},
    )
    reg = rg.load()
    got = {n: reg.resolve(n) for n in ("desktop", "dotfiles", "apps", "media", "brain", "bogus")}
    assert got == {
        "desktop": "desktop",
        "dotfiles": "desktop",
        "apps": "media",
        "media": "media",
        "brain": "brain",
        "bogus": "bogus",
    }
    desktop = reg.get("dotfiles")
    assert desktop is not None and desktop.sessions == (
        "desktop-coordinator",
        "dotfiles-coordinator",
    )


def test_former_names_lapse_after_their_date(desk: Desk) -> None:
    desk.coordinators(
        "desktop", desktop={"old_names": ["dotfiles"], "old_names_until": "2026-01-01"}
    )
    data = json.loads((desk.base / "registry.json").read_text())
    found = rg.parse(data, today=dt.date(2026, 11, 4))
    assert found is not None and found[0].old_names == ()
    found = rg.parse(data, today=dt.date(2025, 12, 1))
    assert found is not None and found[0].old_names == ("dotfiles",)


def test_glyphs_from_the_registry() -> None:
    """coordinators.zsh: icons. The glyph is bar_glyph's codepoint; none gives the first letter."""
    found = rg.parse(
        [
            {"name": "security", "bar_glyph": "U+F0306"},
            {"name": "ventures", "bar_glyph": "u+f1494"},
            {"name": "plain", "bar_glyph": "nonsense"},
            {"name": "bare"},
        ]
    )
    assert found is not None
    assert [c.icon for c in found] == ["\U000f0306", "\U000f1494", "p", "b"]


def test_parse_defaults_and_skips() -> None:
    found = rg.parse(
        [
            {"name": "brain", "menu_order": True, "home": "", "tmux_session": 3},
            {"name": "brain"},
            "not a dict",
            {
                "name": "x",
                "old_names": "not a list",
                "stopped_by_default": True,
                "status": "active",
            },
        ]
    )
    assert found is not None and [c.name for c in found] == ["brain", "x"]
    brain, x = found
    assert brain.session == "brain-coordinator" and brain.home.name == "brain"
    assert x.old_names == () and x.stopped_by_default and x.status == "active"


def test_keys_two_letters() -> None:
    """coordinators.zsh: keys-two-letters, keys-before-moves, keys-one-p-shown, keys-in-help."""
    assert list(rg.keys(NEW).values()) == ["b", "pl", "pe", "h", "n", "m", "d", "i", "s", "v"]
    old = ["brain", "template", "folio", "homelab", "metalayerlab", "apps", "dotfiles", "ideas"]
    assert list(rg.keys(old).values()) == ["b", "t", "f", "h", "m", "a", "d", "i"]
    assert list(rg.keys(["platform", "folio"]).values()) == ["p", "f"]
    assert "pl platform, pe personal" in rg.keys_help(NEW)
    assert rg.keys_help([]) == "none shown"
    assert rg.keys(["ab", "abc", ""]) == {"ab": "ab", "abc": "abc"}


def test_names_verb_lists_with_keys(desk: Desk) -> None:
    from typer.testing import CliRunner

    from desktop_tools.crew.app import app

    desk.coordinators("brain", "platform", "personal")
    out = CliRunner().invoke(app, ["names", "--keys"])
    assert out.exit_code == 0
    assert out.stdout.splitlines() == ["b brain", "pl platform", "pe personal"]


def test_a_copy_that_cant_be_kept_warns(desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    from desktop_tools.crew import conf

    desk.coordinators("brain")
    conf.state_dir().parent.mkdir(parents=True, exist_ok=True)
    conf.state_dir().write_text("not a folder")
    assert rg.load().names == ["brain"]
    assert "registry: cannot keep a copy in" in capsys.readouterr().err


def test_a_stale_answer_is_used_with_a_warning(
    desk: Desk, capsys: pytest.CaptureFixture[str]
) -> None:
    desk.coordinators("brain")
    envelope = json.loads((desk.base / "registry.json").read_text())
    envelope.update(stale=True, age_s=900)
    desk.put("registry.json", json.dumps(envelope))
    reg = rg.load()
    assert (reg.names, reg.source) == (["brain"], "meta")
    assert "registry: meta's answer is stale (900s old)" in capsys.readouterr().err


def test_the_live_registrys_answer_parses() -> None:
    """A copy of the live `meta brain coordinators --json` (2026-11-04): names, order, glyphs."""
    from pathlib import Path as P

    data = json.loads(
        (P(__file__).parent.parent / "fixtures" / "meta-coordinators.json").read_text()
    )
    found = rg.parse(data)
    assert found is not None
    assert [c.name for c in found] == NEW
    assert found[6].icon == "\U000f0493" and found[0].session == "brain-coordinator"

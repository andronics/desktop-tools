"""render: four tiers per module from the theme's roles (the zsh tests' cases), the text each
display shows, escaping, segments, alerts, stale pushes and the click tags."""

from __future__ import annotations

from pathlib import Path

import pytest

from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import render as rd
from desktop_tools.barctl import state as st

MODS = ("audio-level", "player-play-pause", "player-metadata")


def strip_actions(text: str) -> str:
    """The text without its action tags: %{A<n>:...:} and %{A}."""
    import re

    return re.sub(r"%\{A\d?:[^}]*:\}|%\{A\}", "", text)


@pytest.fixture
def modules() -> dict[str, mods.Module]:
    return mods.load()


@pytest.mark.parametrize("module", MODS)
@pytest.mark.parametrize("tier", st.TIERS)
def test_four_tiers_per_module(
    module: str, tier: str, theme: dict[str, str], modules: dict[str, mods.Module]
) -> None:
    """Ported from tests/barctl.zsh: render-<module>-<tier>."""
    state = {"tier": tier, "glyph": "text of", "label": f"text of {module}"}
    out = rd.render(modules[module], state, controller=False)
    text = {"icon": "text of", "text": f"text of {module}", "both": f"text of text of {module}"}[
        modules[module].display
    ]
    assert strip_actions(out) == f"%{{F{theme[tier]}}}{text}%{{F-}}"


def test_roles_distinct(theme: dict[str, str]) -> None:
    assert len(set(theme.values())) == 4


def test_no_state_shows_the_default_glyph_unavailable(
    theme: dict[str, str], modules: dict[str, mods.Module]
) -> None:
    out = strip_actions(rd.render(modules["audio-level"], None, controller=False))
    assert out == f"%{{F{theme['unavailable']}}}\U000f0581%{{F-}}"
    # player-metadata has no glyph: nothing to show, an empty line.
    assert rd.render(modules["player-metadata"], None, controller=False) == ""


def test_no_theme_draws_without_colour(modules: dict[str, mods.Module]) -> None:
    out = rd.render(modules["player-metadata"], {"tier": "active", "label": "x"}, controller=False)
    assert strip_actions(out) == "x"


def test_action_tags_run_barctl_click(
    theme: dict[str, str], modules: dict[str, mods.Module]
) -> None:
    out = rd.render(modules["audio-level"], {"tier": "active", "glyph": "g"}, controller=False)
    for n, button in ((1, "left"), (3, "right"), (4, "scroll-up"), (5, "scroll-down")):
        assert f"%{{A{n}:barctl click audio-level {button}:}}" in out
    assert out.count("%{A}") == 4
    # A module with a source gets the menu on right-click when right does nothing else.
    meta = rd.render(modules["player-metadata"], {"tier": "idle", "label": "x"}, controller=False)
    assert meta.startswith("%{A3:barctl click player-metadata right:}")


def test_text_is_escaped(modules: dict[str, mods.Module]) -> None:
    """Ported: player-escape. A pushed %{ can't open a tag."""
    state = {"tier": "active", "label": "x: %{F#ff0000}red %{A1:rm -rf ~:}"}
    out = rd.render(modules["player-metadata"], state, controller=False, colours={})
    assert "x: %%{F#ff0000}red %%{A1:rm -rf ~:}" in out
    assert "%{F#ff0000}" not in out.replace("%%{", "")


def test_compose() -> None:
    assert rd.compose("icon", "g", "label", 3) == "g 3"
    assert rd.compose("icon", "", "label", 0) == ""
    assert rd.compose("text", "g", "label", 3) == "label"
    assert rd.compose("both", "g", "35% ", 0) == "g 35% "
    assert rd.compose("both", "", "", 2) == "2"


def test_alert_blinks_with_the_controller_and_is_steady_without(
    theme: dict[str, str], modules: dict[str, mods.Module]
) -> None:
    m = modules["player-metadata"]
    state = {"tier": "idle", "label": "x", "alert_until": 1000.0}
    on, off = 100.0, 100.0 + st.BLINK
    assert rd.blink_on(on) and not rd.blink_on(off)
    assert theme["alert"] in rd.render(m, state, now=on, controller=True)
    assert theme["idle"] in rd.render(m, state, now=off, controller=True)
    assert theme["alert"] in rd.render(m, state, now=off, controller=False)
    # Past its end, no alert.
    assert theme["idle"] in rd.render(m, state, now=2000.0, controller=False)


def test_a_stale_push_shows_unavailable_with_its_glyph(theme: dict[str, str]) -> None:
    m = mods.Module("crew", pusher="crew", display="both")
    state = {"tier": "active", "glyph": "G", "label": "busy", "expires": 50.0, "alert_until": 99.0}
    out = rd.render(m, state, now=60.0, controller=False)
    assert out == f"%{{F{theme['unavailable']}}}G%{{F-}}"
    assert "busy" in rd.render(m, state, now=40.0, controller=False)
    # Unavailable but fresh: its alert still shows.
    fresh = {"tier": "unavailable", "glyph": "G", "expires": 500.0, "alert_until": 99.0}
    assert theme["alert"] in rd.render(m, fresh, now=60.0, controller=False)


def test_segments(theme: dict[str, str]) -> None:
    m = mods.Module(
        "crew",
        pusher="crew",
        separator="|",
        segment_clicks={"left": ["crew", "toggle", "{segment}"]},
    )
    state = {
        "segments": [
            {"id": "brain", "tier": "active", "glyph": "B"},
            {"id": "media", "tier": "alert", "glyph": "M", "label": "wait"},
            {"id": "empty", "tier": "idle"},
            {"id": "home", "tier": "idle", "glyph": "H", "alert_until": 500.0},
        ]
    }
    out = rd.render(m, state, now=100.0, controller=True)
    cells = out.split("|")
    assert len(cells) == 3
    assert (
        cells[0]
        == f"%{{A1:barctl click crew left --segment brain:}}%{{F{theme['active']}}}B%{{F-}}%{{A}}"
    )
    assert f"{theme['alert']}}}M wait" in cells[1]
    assert theme["alert"] in cells[2]  # its own alert, blinking on
    stale = rd.render(m, {**state, "expires": 50.0}, now=100.0, controller=False)
    assert theme["active"] not in stale and theme["alert"] not in stale


def test_disabled_is_blank(modules: dict[str, mods.Module]) -> None:
    assert rd.render(modules["audio-level"], {"tier": "active"}, disabled=True) == ""


def test_render_reads_the_files(theme: dict[str, str], isolate: Path) -> None:
    from desktop_tools.barctl import ops

    st.write("audio-level", {"tier": "idle", "glyph": "g", "label": "35% "})
    assert f"%{{F{theme['idle']}}}g 35% %{{F-}}" in ops.render_line("audio-level")
    assert ops.render_line("no-such-module") == ""
    st.set_enabled("audio-level", False)
    assert ops.render_line("audio-level") == ""
    with pytest.raises(ops.Failure):
        ops.render_line("../etc")

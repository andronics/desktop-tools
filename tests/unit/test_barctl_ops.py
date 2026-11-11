"""The verbs' behaviour: who may push what, what a push writes and pokes, alerts, clicks and
menus, reload, enable and disable, status, show and doctor."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from desktop_tools.barctl import doctor, ops
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.common import polybar, procs
from tests.fakes import FakeBar, calls

CREW = """
[modules.crew]
pusher = "crew"
display = "both"
glyph = "C"
[modules.crew.clicks]
left = ["crew", "toggle"]
[modules.crew.segment_clicks]
left = ["crew", "toggle", "{segment}"]
[[modules.crew.menu]]
label = "Status"
command = ["crew", "status", "{target}"]

[modules.audio-level]
source = "volume"
display = "both"

[modules.counter]
source = "counter"
"""


@pytest.fixture
def crew(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = isolate / "modules.toml"
    path.write_text(CREW)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    return path


def test_push_writes_and_pokes(crew: Path, bar: FakeBar) -> None:
    assert ops.push("crew", {"tier": "active", "label": "busy"}, source="crew", now=100.0)
    state = st.read("crew") or {}
    assert (state["tier"], state["label"], state["source"], state["updated"]) == (
        "active",
        "busy",
        "crew",
        100.0,
    )
    assert bar.wait(1) == ["crew"]
    # Given fields replace, others keep; nothing visible changed: written, no poke.
    bar.clear()
    assert ops.push("crew", {"detail": "a longer line"}, source="crew", now=101.0)
    assert (st.read("crew") or {})["label"] == "busy"
    assert bar.wait(1, timeout=0.3) == []
    # Nothing changed at all: nothing written.
    assert not ops.push("crew", {"detail": "a longer line"}, source="crew", now=102.0)
    assert (st.read("crew") or {})["updated"] == 101.0


def test_push_tells_the_controller_instead_of_poking(
    crew: Path, bar: FakeBar, monkeypatch: pytest.MonkeyPatch
) -> None:
    told: list[tuple[str, dict[str, object]]] = []

    def request(op: str, timeout: float = 1.0, **fields: object) -> dict[str, object]:
        told.append((op, fields))
        return {"ok": True}

    monkeypatch.setattr("desktop_tools.barctl.control.request", request)
    ops.push("crew", {"tier": "idle"}, source="crew")
    assert told == [("pushed", {"module": "crew"})]
    assert bar.wait(1, timeout=0.3) == []


@pytest.mark.parametrize(
    ("module", "source", "code"),
    [
        ("audio-level", "crew", ops.REFUSED),  # barctl's own source draws it
        ("crew", None, ops.REFUSED),  # nobody said who is pushing
        ("crew", "someone", ops.REFUSED),  # crew's to push
        ("nosuch", "crew", ops.NOT_FOUND),
        ("../x", "crew", ops.USAGE),
    ],
)
def test_push_refusals(crew: Path, module: str, source: str | None, code: int) -> None:
    with pytest.raises(ops.Failure) as e:
        ops.push(module, {"tier": "idle"}, source=source)
    assert e.value.code == code
    assert st.read(module if module != "../x" else "x") is None


def test_push_source_from_json_or_environment(
    crew: Path, bar: FakeBar, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops.push("crew", {}, whole={"source": "crew", "tier": "active"})
    monkeypatch.setenv("BARCTL_SOURCE", "crew")
    ops.push("crew", {"label": "x"})
    assert (st.read("crew") or {})["label"] == "x"


def test_push_whole_state_keeps_an_alert_and_ttl_restates(crew: Path, bar: FakeBar) -> None:
    now = time.time()
    st.write("crew", {"tier": "idle", "alert_until": now + 60, "label": "old"})
    whole = {"tier": "active", "segments": [{"id": "brain", "tier": "alert", "glyph": "B"}]}
    ops.push("crew", {}, whole=whole, ttl=30, source="crew", now=now)
    state = st.read("crew") or {}
    assert "label" not in state  # replaced whole
    assert state["alert_until"] == now + 60
    assert state["expires"] == now + 30
    assert state["segments"][0]["id"] == "brain"
    ops.push("crew", {"label": "again"}, source="crew", now=now + 1)
    assert "expires" not in (st.read("crew") or {})  # a push without a ttl holds


@pytest.mark.parametrize(
    "bad",
    [
        {"tier": "loud"},
        {"count": -1},
        {"count": True},
        {"label": 3},
        {"segments": "x"},
        {"segments": [{"id": "has space"}]},
        {"segments": [{"id": "a"}, {"id": "a"}]},
        {"segments": [3]},
        {"alert_until": "soon"},
    ],
)
def test_push_validation(crew: Path, bad: dict[str, object]) -> None:
    with pytest.raises(ops.Failure) as e:
        ops.push("crew", bad, source="crew")
    assert e.value.code == ops.USAGE


def test_validate_drops_unknown_fields_and_newlines() -> None:
    got = st.validate({"tier": "idle", "label": "a\nb", "evil": 1, "count": None})
    assert got == {"tier": "idle", "label": "a b"}
    with pytest.raises(st.StateError):
        st.validate([])


def test_durations() -> None:
    assert st.duration("90") == 90
    assert st.duration("1m30s") == 90
    assert st.duration("2h") == 7200
    assert st.duration("0") == 0
    for bad in ("", "soon", "m5"):
        with pytest.raises(ValueError):
            st.duration(bad)


def test_alert_without_controller(crew: Path, bar: FakeBar, launched: list[list[str]]) -> None:
    st.write("crew", {"tier": "idle", "segments": [{"id": "brain", "tier": "idle"}]})
    assert ops.alert("crew", 30, now=100.0) == "steady urgent (no controller to blink it)"
    assert (st.read("crew") or {})["alert_until"] == 130.0
    assert bar.wait(1) == ["crew"]
    assert "reload" in launched[0][-3] and launched[0][-1] == "crew"  # redrawn when it ends
    # A second alert extends the first; a shorter one doesn't cut it.
    ops.alert("crew", 10, now=101.0)
    assert (st.read("crew") or {})["alert_until"] == 130.0
    ops.alert("crew", 0, segment=None)
    assert "alert_until" not in (st.read("crew") or {})
    ops.alert("crew", 10, segment="brain", now=100.0)
    assert (st.read("crew") or {})["segments"][0]["alert_until"] == 110.0
    with pytest.raises(ops.Failure) as e:
        ops.alert("crew", 10, segment="nosuch")
    assert e.value.code == ops.NOT_FOUND


def test_alert_with_controller(crew: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "desktop_tools.barctl.control.request", lambda op, timeout=1.0, **f: {"ok": True}
    )
    assert ops.alert("crew", 5) == "blinking"
    assert ops.alert("crew", 0) == "stopped"


def test_click_fills_the_target(crew: Path, launched: list[list[str]]) -> None:
    st.write("crew", {"tier": "idle", "target": "brain"})
    assert ops.click("crew", "left") == ["crew", "toggle"]
    assert ops.click("crew", "left", segment="media") == ["crew", "toggle", "media"]
    assert ops.click("crew", "middle") is None  # nothing on that button
    assert launched == [["crew", "toggle"], ["crew", "toggle", "media"]]
    with pytest.raises(ops.Failure):
        ops.click("crew", "sideways")


def test_player_click_acts_on_the_shown_player(isolate: Path, launched: list[list[str]]) -> None:
    """The zsh version's gap: a click went to playerctl's default player."""
    st.write("player-play-pause", {"tier": "active", "target": "firefox.instance42"})
    assert ops.click("player-play-pause", "left") == ["player", "play-pause", "firefox.instance42"]
    st.write("player-play-pause", {"tier": "unavailable"})
    assert ops.click("player-play-pause", "left") is None  # no player: nothing to act on


def test_click_that_cant_start(crew: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(argv: list[str], env: object = None, cwd: object = None) -> int:
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(procs, "detach", broken)
    with pytest.raises(ops.Failure) as e:
        ops.click("crew", "left")
    assert e.value.code == ops.FAILED


def test_right_click_opens_the_menu(
    crew: Path, launched: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from desktop_tools.barmenu import menus as bm

    shown: list[bm.Menu] = []

    def choose(menu: bm.Menu, extra: list[str] | None = None) -> int:
        shown.append(menu)
        return 0

    monkeypatch.setattr(bm, "choose", choose)
    st.write("crew", {"tier": "idle", "target": "brain", "glyph": "G"})
    assert ops.click("crew", "right") == ["barctl", "menu", "crew"]
    assert [r.label for r in shown[0].rows] == ["Status"]
    assert shown[0].glyph == "G"
    assert launched == [["crew", "status", "brain"]]
    monkeypatch.setattr(bm, "choose", lambda menu, extra=None: None)
    assert ops.menu("crew") is None  # Escape


def test_menu_with_no_rows(
    isolate: Path, launched: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = isolate / "m.toml"
    path.write_text('[modules.lonely]\npusher = "x"\n')
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    assert ops.menu("lonely") is None
    assert ops.click("lonely", "right") is None


def test_reload_and_enable(crew: Path, bar: FakeBar) -> None:
    assert ops.reload() == ["audio-level", "counter", "crew"]
    assert ops.reload("crew") == ["crew"]
    assert bar.wait(4)[-1] == "crew"
    bar.clear()
    assert ops.enable("crew", False)
    assert st.disabled() == {"crew"}
    assert not ops.enable("crew", False)  # already
    assert ops.enable("crew", True)
    assert st.disabled() == set()
    assert bar.wait(3) == ["crew"] * 3
    with pytest.raises(ops.Failure):
        ops.reload("nosuch")


def test_hide_and_unhide(bar: FakeBar) -> None:
    assert ops.visibility(False) == {4242: True}
    assert ops.visibility(True) == {4242: True}
    assert [b for _, b in bar.messages] == ["hide", "show"]


def test_restart_starts_a_bar_when_none_runs(
    isolate: Path, monkeypatch: pytest.MonkeyPatch, commands: Callable[..., Path]
) -> None:
    log = commands(theme="pass")
    started: list[str] = []

    def start_bar(bar: str, **kw: object) -> polybar.RestartResult:
        started.append(bar)
        return polybar.RestartResult()

    monkeypatch.setattr(polybar, "start_bar", start_bar)
    monkeypatch.setenv("POLYBAR_BAR", "audio")
    assert ops.restart().ok
    assert started == ["audio"]
    assert calls(log) == [["theme", "ensure"]]


def test_restart_restarts_the_named_bar(
    isolate: Path, monkeypatch: pytest.MonkeyPatch, commands: Callable[..., Path]
) -> None:
    from tests.unit.test_polybar import fake_proc

    log = commands(theme="pass")
    fake_proc(isolate / "proc", 10, "polybar", argv=["polybar", "-q", "main"])
    fake_proc(isolate / "proc", 11, "polybar", argv=["polybar", "-q", "audio"])
    asked: list[list[int]] = []

    def restart(pids: list[int]) -> polybar.RestartResult:
        asked.append(list(pids))
        return polybar.RestartResult()

    monkeypatch.setattr(polybar, "restart", restart)
    ops.restart("audio")
    ops.restart()
    assert asked == [[11], [10, 11]]
    assert calls(log) == [["theme", "ensure"]] * 2


def test_status_shape(crew: Path, bar: FakeBar, isolate: Path) -> None:
    st.write(
        "crew", {"tier": "active", "label": "busy", "updated": time.time(), "alert_until": 2e9}
    )
    data = ops.status()
    assert set(data) >= {"summary", "state", "checks", "controller", "bars", "modules"}
    assert data["state"] == "fail"  # no controller
    assert data["controller"] == {"running": False, "pid": None, "since": None}
    assert data["bars"] == [{"pid": 4242, "answering": True}]
    crew_info = next(m for m in data["modules"] if m["name"] == "crew")
    assert (crew_info["tier"], crew_info["alerting"], crew_info["writer"]) == (
        "active",
        True,
        "crew",
    )
    assert {"name": "crew", "state": "warn", "detail": "alerting"} in data["checks"]
    json.dumps(data)  # the JSON shape is plain data


def test_status_with_a_controller(crew: Path, bar: FakeBar) -> None:
    import os

    st.runtime().mkdir(parents=True, exist_ok=True)
    st.pid_path().write_text(f"{os.getpid()}\n{time.time()}\n")
    st.source_health_path("volume").parent.mkdir(parents=True)
    st.source_health_path("volume").write_text('{"state": "failing"}')
    data = ops.status()
    assert data["controller"]["running"] and data["controller"]["since"]
    assert {"name": "source volume", "state": "fail", "detail": "failing"} in data["checks"]


def test_status_without_bars_or_config(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BARCTL_CONFIG", str(isolate / "missing.toml"))
    data = ops.status()
    names = [c["name"] for c in data["checks"] if c["state"] == "fail"]
    assert names == ["controller", "bars", "modules.toml"]


def test_show(crew: Path) -> None:
    st.write("crew", {"tier": "idle", "updated": 100.0, "expires": 200.0, "source": "crew"})
    info = ops.show("crew", now=150.0)
    assert info["pusher"] == "crew" and info["written_by"] == "crew"
    assert info["menu"][0]["label"] == "Status"
    assert info["expires"] and info["age_s"] == 50.0
    with pytest.raises(ops.Failure) as e:
        ops.show("nosuch")
    assert e.value.code == ops.NOT_FOUND


POLYBAR_INI = """
[module/base-ipc]
type = custom/ipc
initial = 1

[module/audio-level]
inherit = module/base-ipc
hook-0 = barctl render audio-level

[module/player-play-pause]
hook-0 = barctl render player-play-pause

[module/coord]
type = custom/ipc
hook-0 = coord bar

[module/stray]
hook-0 = barctl render stray

[module/wrong]
hook-0 = barctl render audio-level
"""


def test_doctor(
    isolate: Path, bar: FakeBar, theme: dict[str, str], commands: Callable[..., Path]
) -> None:
    commands(pactl="pass", playerctl="pass")
    ini = isolate / "xdg" / "config" / "polybar" / "modules"
    ini.mkdir(parents=True)
    (ini / "audio.ini").write_text(POLYBAR_INI)
    st.write("orphan", {"tier": "idle"})
    found = {c["name"]: c for c in doctor.checks()}
    assert found["controller"]["state"] == "fail"
    assert found["controller"]["fix"] == "systemctl --user start barctl.service"
    assert found["zsh controller"]["state"] == "ok"
    assert found["bar 4242"]["state"] == "ok"
    assert found["polybar module stray"]["detail"] == "not in modules.toml"
    assert found["polybar module wrong"]["detail"] == "its hook renders audio-level"
    assert found["module player-metadata"]["state"] == "fail"  # no polybar module renders it
    assert "polybar module coord" not in found  # not barctl's
    assert found["source volume"]["state"] == "ok"
    assert found["theme roles"]["state"] == "ok"
    assert found["state folder"]["state"] == "ok"
    assert found["state orphan"]["fix"].startswith("rm ")
    assert doctor.problems(list(found.values()))


def test_doctor_problems_and_warnings(
    crew: Path, isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(isolate / "empty"))
    st.write("crew", {"tier": "idle", "expires": 1.0})
    found = {c["name"]: c for c in doctor.checks()}
    assert found["bars"]["state"] == "fail"
    assert found["source counter"]["state"] == "warn"  # a reserved source, not built yet
    assert found["source volume"]["fix"] == "install pactl"
    assert found["state crew"]["detail"].startswith("stale")
    assert found["theme roles"]["state"] == "fail"


def test_doctor_spots_the_zsh_controller(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = isolate / "xdg" / "state" / "barctl"
    folder.mkdir()
    (folder / "pid").write_text("1\n")
    assert doctor.zsh_controller_running() is None  # pid 1 isn't zsh
    (folder / "pid").write_text("nonsense")
    assert doctor.zsh_controller_running() is None


def test_bad_config_is_failed(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = isolate / "m.toml"
    path.write_text("[modules.x\n")
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    with pytest.raises(ops.Failure) as e:
        ops.load()
    assert e.value.code == ops.FAILED
    assert ops.render_line("x") == ""


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("modules = 3", "[modules] must be a table"),
        ('[modules."Bad Name"]\nsource = "volume"', "not a module name"),
        ("[modules.x]", "exactly one of source and pusher"),
        ('[modules.x]\nsource = "volume"\npusher = "y"', "exactly one"),
        ('[modules.x]\nsource = "radio"', "unknown source"),
        ('[modules.x]\npusher = "Not OK"', "pusher must be"),
        ('[modules.x]\npusher = "y"\ndisplay = "huge"', "display is one of"),
        ('[modules.x]\npusher = "y"\nglyph = 3', "glyph must be a string"),
        ('[modules.x]\npusher = "y"\n[modules.x.clicks]\nwheel = ["a"]', "unknown button"),
        ('[modules.x]\npusher = "y"\nclicks = 3', "table of button"),
        ('[modules.x]\npusher = "y"\n[modules.x.clicks]\nleft = []', "non-empty list"),
        ('[modules.x]\npusher = "y"\nmenu = 3', "array of tables"),
        ('[modules.x]\npusher = "y"\nmenu = [3]', "must be a table"),
        ('[modules.x]\npusher = "y"\n[[modules.x.menu]]\ncommand = ["a"]', "needs a label"),
        ("[modules]\nx = 3", "must be a table"),
    ],
)
def test_config_errors(isolate: Path, toml: str, message: str) -> None:
    path = isolate / "m.toml"
    path.write_text(toml)
    with pytest.raises(mods.ConfigError, match=re.escape(message)):
        mods.load(path)


def test_config_override_and_packaged(isolate: Path) -> None:
    assert mods.config_path() == mods.PACKAGED
    override = isolate / "xdg" / "config" / "barctl" / "modules.toml"
    override.parent.mkdir()
    override.write_text('[modules.only]\npusher = "x"\n')
    assert mods.config_path() == override
    assert list(mods.load()) == ["only"]
    with pytest.raises(mods.ConfigError, match="No such file"):
        mods.load(isolate / "missing.toml")
    assert mods.load(mods.PACKAGED)["audio-level"].as_dict()["source"] == "volume"


# ---------------------------------------------------------------- glyph overrides (record 0002 §7)

TESSERA = """
[modules.tessera]
pusher = "tessera"
glyph = "D"
glyph_override = { idle = "I", active = "A" }

[modules.all]
pusher = "all"
glyph_override = "S"

[modules.plain]
pusher = "plain"
glyph = "D"
"""


@pytest.fixture
def overridden(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = isolate / "modules.toml"
    path.write_text(TESSERA)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    return path


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[modules.x]\npusher = "y"\nglyph_override = { sleepy = "z" }', "x.glyph_override.sleepy"),
        ('[modules.x]\npusher = "y"\nglyph_override = { idle = 3 }', "x.glyph_override.idle"),
        ('[modules.x]\npusher = "y"\nglyph_override = 3', "glyph_override must be a string"),
        ('[modules.x]\npusher = "y"\nglyph_override = ["a"]', "glyph_override must be a string"),
    ],
)
def test_glyph_override_errors_name_the_key(isolate: Path, toml: str, message: str) -> None:
    path = isolate / "m.toml"
    path.write_text(toml)
    with pytest.raises(mods.ConfigError, match=re.escape(message)):
        mods.load(path)


def test_glyph_override_parses(overridden: Path) -> None:
    found = mods.load(overridden)
    assert found["tessera"].glyph_override == {"idle": "I", "active": "A"}
    assert found["all"].glyph_override == "S"
    assert found["plain"].glyph_override is None
    assert found["tessera"].as_dict()["glyph_override"] == {"idle": "I", "active": "A"}


def test_packaged_modules_set_no_override() -> None:
    assert all(m.glyph_override is None for m in mods.load(mods.PACKAGED).values())


def test_shown_ignores_a_glyph_an_override_hides(overridden: Path) -> None:
    from desktop_tools.barctl import store

    found = mods.load(overridden)
    one, two = {"tier": "idle", "glyph": "P1"}, {"tier": "idle", "glyph": "P2"}
    # tessera overrides idle: a push that changes only the glyph is not a change
    assert store.shown(found["tessera"], one, 0) == store.shown(found["tessera"], two, 0)
    # ... but its alert tier has no override, so the pushed glyph still shows
    a1, a2 = {**one, "tier": "alert"}, {**two, "tier": "alert"}
    assert store.shown(found["tessera"], a1, 0) != store.shown(found["tessera"], a2, 0)
    assert store.shown(found["plain"], one, 0) != store.shown(found["plain"], two, 0)


def test_store_does_not_poke_for_a_hidden_glyph(overridden: Path) -> None:
    from desktop_tools.barctl import store

    found = mods.load(overridden)
    pokes: list[str] = []
    assert store.store(found["tessera"], {"tier": "idle", "glyph": "P1"}, pokes.append, now=1.0)
    assert pokes == ["tessera"]
    assert store.store(found["tessera"], {"tier": "idle", "glyph": "P2"}, pokes.append, now=2.0)
    assert pokes == ["tessera"]  # written, not poked
    assert store.store(found["plain"], {"tier": "idle", "glyph": "P1"}, pokes.append, now=1.0)
    assert store.store(found["plain"], {"tier": "idle", "glyph": "P2"}, pokes.append, now=2.0)
    assert pokes == ["tessera", "plain", "plain"]


def test_status_gives_the_glyph_source_and_the_pushed_glyph(overridden: Path, bar: FakeBar) -> None:
    now = time.time()
    st.write("tessera", {"tier": "idle", "glyph": "P", "updated": now})
    st.write("plain", {"tier": "idle", "glyph": "P", "updated": now})
    found = {m["name"]: m for m in ops.status(now)["modules"]}
    assert (found["tessera"]["glyph"], found["tessera"]["glyph_source"]) == ("I", "override-tier")
    assert found["tessera"]["glyph_pushed"] == "P"
    assert (found["plain"]["glyph"], found["plain"]["glyph_source"]) == ("P", "pushed")
    assert found["plain"]["glyph_pushed"] == "P"
    # no state: the override for unavailable, else the default; nothing pushed
    assert (found["all"]["glyph"], found["all"]["glyph_source"]) == ("S", "override")
    st.clear("plain")
    again = {m["name"]: m for m in ops.status(now)["modules"]}
    assert (again["plain"]["glyph"], again["plain"]["glyph_source"]) == ("D", "default")
    assert again["plain"]["glyph_pushed"] is None


def test_menu_prompt_uses_the_glyph_the_bar_shows(
    overridden: Path, launched: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from desktop_tools.barmenu import menus as bm

    path = overridden
    path.write_text(path.read_text() + '\n[[modules.tessera.menu]]\nlabel = "L"\ncommand = ["x"]\n')
    shown: list[bm.Menu] = []
    monkeypatch.setattr(bm, "choose", lambda menu, extra=None: shown.append(menu))
    st.write("tessera", {"tier": "idle", "glyph": "P"})
    ops.menu("tessera")
    assert shown[0].glyph == "I"


def test_doctor_lists_each_override(overridden: Path, bar: FakeBar) -> None:
    found = {c["name"]: c for c in doctor.checks()}
    assert found["glyph tessera"] == {
        "name": "glyph tessera",
        "state": "ok",
        "detail": "override for idle, active",
        "fix": "",
    }
    assert found["glyph all"]["detail"] == "override for idle, active, alert, unavailable"
    assert "glyph plain" not in found

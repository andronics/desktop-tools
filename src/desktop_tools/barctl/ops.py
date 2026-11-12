"""What barctl's verbs do, apart from parsing: shared by the fast path and the Typer app.

Each returns an exit code and leaves printing to its caller, except where noted. Exit codes are
the `meta` ones (brain record 0019): 0 ok, 1 a problem found, 2 usage, 3 refused, 4 failed,
5 not found.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from typing import Any

from desktop_tools.barctl import control, render, transport
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.store import store
from desktop_tools.common import polybar

OK, PROBLEM, USAGE, REFUSED, FAILED, NOT_FOUND = 0, 1, 2, 3, 4, 5


class Failure(Exception):
    """A verb that can't go on: its message and exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def load() -> dict[str, mods.Module]:
    try:
        return mods.load()
    except mods.ConfigError as e:
        raise Failure(str(e), FAILED) from None


def module(name: str, modules: dict[str, mods.Module] | None = None) -> mods.Module:
    if not mods.valid_name(name):
        raise Failure(f"not a module name: {name!r}", USAGE)
    found = (modules if modules is not None else load()).get(name)
    if found is None:
        raise Failure(f"unknown module {name!r} (barctl list shows them)", NOT_FOUND)
    return found


def notify(op: str, name: str) -> None:
    """Tell the controller a module changed; with no controller, poke the module here."""
    if control.request(op, module=name) is None:
        polybar.poke(name)


# ---------------------------------------------------------------- render


def render_line(name: str) -> str:
    """The text for polybar; empty when anything is missing."""
    if not mods.valid_name(name):
        raise Failure(f"not a module name: {name!r}", USAGE)
    try:
        found = mods.load().get(name)
    except mods.ConfigError:
        return ""
    if found is None:
        return ""
    return render.render(found, st.read(name), disabled=name in st.disabled())


# ---------------------------------------------------------------- push and alert


def push(
    name: str,
    fields: dict[str, Any],
    *,
    whole: dict[str, Any] | None = None,
    ttl: float | None = None,
    source: str | None = None,
    now: float | None = None,
) -> bool:
    """Set a module's state from an outside program. Returns whether it changed.

    Given fields replace, others keep; `whole` replaces the state (an alert in force is kept).
    A push restates how long it holds: without a ttl, an earlier ttl no longer applies."""
    now = time.time() if now is None else now
    found = module(name)
    who = source or (whole or {}).get("source") or os.environ.get("BARCTL_SOURCE") or ""
    if found.source:
        raise Failure(
            f"{name} is drawn by barctl's own {found.source} source; nothing else may push it",
            REFUSED,
        )
    if not who:
        raise Failure(f"say who is pushing {name}: --source {found.pusher}", REFUSED)
    if who != found.pusher:
        raise Failure(f"{name} is {found.pusher}'s to push, not {who}'s", REFUSED)
    try:
        clean = st.validate({**(whole or {}), **fields})
    except st.StateError as e:
        raise Failure(str(e), USAGE) from None
    old = st.read(name)
    base: st.State = {} if whole is not None else st.content(old)
    base.pop("expires", None)
    if whole is not None and old and old.get("alert_until") and "alert_until" not in clean:
        base["alert_until"] = old["alert_until"]
    new = {**base, **clean, "source": who}
    new.setdefault("tier", "idle")
    if ttl:
        new["expires"] = now + ttl
    if st.content(old) == st.content(new):
        return False
    changed: list[str] = []
    store(found, new, changed.append, now)
    if changed:
        notify("pushed", name)
    return True


def alert(name: str, seconds: float, segment: str | None = None, now: float | None = None) -> str:
    """Blink a module (or one segment) until the time is up; 0 stops it. A second alert
    extends the first. Returns what happened, for the caller to say."""
    now = time.time() if now is None else now
    found = module(name)
    data = st.read(name) or {}
    until = now + seconds if seconds > 0 else None
    if segment is not None:
        segs = data.get("segments") or []
        target = next((s for s in segs if s.get("id") == segment), None)
        if target is None:
            raise Failure(f"{name} has no segment {segment!r}", NOT_FOUND)
        holder = target
    else:
        holder = data
    if until is None:
        holder.pop("alert_until", None)
    else:
        holder["alert_until"] = max(until, float(holder.get("alert_until") or 0))
    data["updated"] = now
    st.write(found.name, data)
    if control.request("alert", module=name) is not None:
        return "blinking" if until else "stopped"
    polybar.poke(name)
    if until:
        _redraw_later(name, seconds)
        return "steady urgent (no controller to blink it)"
    return "stopped"


def _redraw_later(name: str, seconds: float) -> None:
    """With no controller, nothing would redraw the module when its alert ends: a detached
    `barctl reload <module>` does, after the time is up."""
    from desktop_tools.common import procs

    code = (
        "import sys, time; time.sleep(float(sys.argv[1])); "
        "from desktop_tools.barctl import ops; ops.reload(sys.argv[2])"
    )
    with contextlib.suppress(OSError):
        procs.detach([sys.executable, "-c", code, str(seconds + 0.1), name])


# ---------------------------------------------------------------- clicks and menus


def fill(command: list[str], state: st.State | None, segment: str | None) -> list[str] | None:
    """A command with {target} and {segment} filled in as whole arguments; None when one is
    asked for and there is none (no player shown: nothing to act on)."""
    target = str((state or {}).get("target") or "")
    out = []
    for arg in command:
        if "{target}" in arg:
            if not target:
                return None
            arg = arg.replace("{target}", target)
        if "{segment}" in arg:
            if not segment:
                return None
            arg = arg.replace("{segment}", segment)
        out.append(arg)
    return out


def click(name: str, button: str, segment: str | None = None) -> list[str] | None:
    """What a click on a module runs, started detached; None when the button does nothing.
    `right` with no command of its own opens the module's menu."""
    from desktop_tools.common import procs

    if button not in mods.BUTTONS:
        raise Failure(f"unknown button {button!r} (one of {', '.join(mods.BUTTONS)})", USAGE)
    found = module(name)
    clicks = found.clicks_for(segment)
    data = st.read(name)
    if button not in clicks:
        if button == "right" and found.has_menu():
            menu(name)
            return ["barctl", "menu", name]
        return None
    argv = fill(clicks[button], data, segment)
    if argv is None:
        return None
    try:
        procs.detach(argv)
    except OSError as e:
        raise Failure(f"{argv[0]}: {e.strerror}", FAILED) from None
    return argv


def menu_rows(found: mods.Module) -> list[mods.Row]:
    from desktop_tools.barctl.sources import SOURCES

    data = st.read(found.name)
    rows = list(found.menu)
    source = SOURCES.get(found.source or "")
    if source is not None:
        rows += source.menu_rows(found.name, data)
    return rows


def menu(name: str) -> mods.Row | None:
    """Open a module's right-click menu (barmenu, rofi) and run the pick, detached."""
    from desktop_tools.barmenu import menus as bm
    from desktop_tools.common import procs

    found = module(name)
    # rofi stays open a while, and this runs from a click: drop the bar's pipes first.
    procs.close_inherited()
    rows = menu_rows(found)
    if not rows:
        return None
    data = st.read(name)
    glyph = found.glyph_for(mods.shown_tier(data, time.time()), data)[0]
    picked = bm.choose(
        bm.Menu(
            name, glyph=glyph, title=name, rows=[bm.Row(r.glyph, r.label, r.command) for r in rows]
        )
    )
    if picked is None:
        return None
    row = rows[picked]
    argv = fill(row.command, data, None)
    if argv:
        try:
            procs.detach(argv)
        except OSError as e:
            raise Failure(f"{argv[0]}: {e.strerror}", FAILED) from None
    return row


# ---------------------------------------------------------------- the transport row


def _capsule(name: str) -> mods.Module:
    found = module(name)
    if found.display != "capsule":
        raise Failure(f"{name} is not a capsule: it has no transport row", USAGE)
    return found


def expand(
    name: str,
    seconds: float | None = None,
    off: bool = False,
    now: float | None = None,
) -> float | None:
    """Open a capsule's transport row (record 0005 phase C) for `seconds` (the capsule's
    `expand_for` when None), or fold it (`off`, or None seconds while it is open: the icon's
    second click). Writes `expanded_until`, as `alert` writes `alert_until`; the controller's
    tick redraws it when the time is up, or, with no controller, a detached reload does.
    Returns when it folds, None when it is folded. Exit 3 when `expand_for` is 0 (the row is
    off) and it was asked to open."""
    now = time.time() if now is None else now
    found = _capsule(name)
    data = st.read(name) or {}
    is_open = render.expanded(found, data, now)
    if seconds is None and not off:
        off = is_open
    if not off and found.expand_for <= 0:
        raise Failure(f"{name}: expand_for is 0, so its transport row is off", REFUSED)
    if seconds is None:
        seconds = float(found.expand_for)
    if seconds < 0 or seconds > mods.CAPSULE_KEYS["expand_for"][2]:
        raise Failure("--for is 0 to 30 seconds", USAGE)
    until = None if off or seconds == 0 else now + seconds
    if until is None and "expanded_until" not in data:
        return None
    if until is None:
        data.pop("expanded_until", None)
    else:
        data["expanded_until"] = until
    data["updated"] = now
    st.write(found.name, data)
    if control.request("expand", module=name) is None:
        polybar.poke(name)
        if until is not None:
            _redraw_later(name, seconds)
    return until


def transport_press(name: str, cell: str, now: float | None = None) -> list[str] | None:
    """A press on a cell of a capsule's transport row (record 0005 phase C): the one
    `playerctl -p <target>` argument list it maps to, run detached, then the row's count
    starts again while it is open. None (nothing run) with no target, or nothing to act on."""
    from desktop_tools.common import procs

    now = time.time() if now is None else now
    found = _capsule(name)
    data = st.read(name)
    try:
        argv = transport.argv(cell, data)
    except transport.UnknownCell as e:
        raise Failure(str(e), USAGE) from None
    if argv is None:
        return None
    try:
        procs.detach(argv)
    except OSError as e:
        raise Failure(f"{argv[0]}: {e.strerror}", FAILED) from None
    if render.expanded(found, data, now):
        expand(name, float(found.expand_for), now=now)
    return argv


# ---------------------------------------------------------------- the player's pin


def pin(name: str, instance: str | None, toggle: bool = False) -> str | None:
    """Show one player on a player module (and every module of its source) while it is
    listed; None goes back to the rank. The controller holds it (record 0003 §5). With
    `toggle`, a player that is already the pin is unpinned instead (record 0005 phase A: a
    second click on a chip undoes the first). Returns the pin."""
    found = module(name)
    if found.source != "player":
        raise Failure(f"{name} is not drawn by the player source: nothing to pin", USAGE)
    fields: dict[str, Any] = {"module": name, "instance": instance}
    if toggle:
        fields["toggle"] = True
    answer = control.request("pin", **fields)
    if answer is None:
        raise Failure("the controller is not running (systemctl --user start barctl)", FAILED)
    if not answer.get("ok"):
        error = str(answer.get("error") or "refused")
        raise Failure(error, NOT_FOUND if error.startswith("no player") else FAILED)
    pinned = answer.get("pinned")
    return pinned if isinstance(pinned, str) else None


def pins() -> dict[str, Any]:
    """source -> its pinned instance, from the running controller ({} without one)."""
    answer = control.request("ping")
    found = (answer or {}).get("pinned")
    return found if isinstance(found, dict) else {}


# ---------------------------------------------------------------- the bars


def reload(name: str | None = None) -> list[str]:
    """Re-read modules.toml (the controller too) and the theme, and redraw every module or one.
    Returns the modules poked."""
    modules = load()
    if name is not None:
        module(name, modules)
    control.request("reload")
    names = [name] if name else list(modules)
    for n in names:
        polybar.poke(n)
    return names


def theme_ensure() -> None:
    """`theme ensure` before a bar starts: polybar's config includes the generated theme."""
    import shutil

    from desktop_tools.common import procs

    if shutil.which("theme"):
        procs.query(["theme", "ensure"], timeout=30)


def restart(bar: str | None = None) -> polybar.RestartResult:
    """Restart the running bars (or the one named), or start it when none is running."""
    theme_ensure()
    pids = polybar.bar_pids()
    if bar is not None:
        pids = [p for p in pids if (lc := polybar.Launch.of(p)) and bar in lc.argv[1:]]
    if pids:
        return polybar.restart(pids)
    return polybar.start_bar(bar or os.environ.get("POLYBAR_BAR") or "main")


def visibility(show: bool) -> dict[int, bool]:
    return polybar.command("show" if show else "hide")


def enable(name: str, on: bool) -> bool:
    module(name)
    changed = st.set_enabled(name, on)
    if control.request("settings", module=name) is None:
        polybar.poke(name)
    return changed


# ---------------------------------------------------------------- reading


def module_info(found: mods.Module, now: float, off: set[str]) -> dict[str, Any]:
    data = st.read(found.name)
    tier, _ = render.text_of(found, data, now)
    glyph, glyph_source = found.glyph_for(mods.shown_tier(data, now), data)
    info: dict[str, Any] = {
        "name": found.name,
        "writer": found.writer,
        "kind": "source" if found.source else "pusher",
        "enabled": found.name not in off,
        "tier": tier if data else None,
        "glyph": glyph,
        "glyph_source": glyph_source,
        "glyph_pushed": (data or {}).get("glyph"),
        "label": (data or {}).get("label", ""),
        "count": (data or {}).get("count", 0),
        "detail": (data or {}).get("detail", ""),
        "target": (data or {}).get("target", ""),
        "age_s": round(now - float(data["updated"]), 1) if data and data.get("updated") else None,
        "alerting": bool(data and float(data.get("alert_until") or 0) > now),
        "stale": bool(data and data.get("expires") and float(data["expires"]) <= now),
    }
    if data and data.get("segments"):
        info["segments"] = data["segments"]
    return info


def iso(epoch: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def status(now: float | None = None) -> dict[str, Any]:
    """The controller, the bars and every module, in brain record 0019's status shape."""
    now = time.time() if now is None else now
    checks: list[dict[str, Any]] = []
    running = st.controller()
    if running:
        checks.append(
            {
                "name": "controller",
                "state": "ok",
                "detail": f"running (pid {running[0]})",
                "since": iso(running[1]) if running[1] else None,
            }
        )
    else:
        checks.append({"name": "controller", "state": "fail", "detail": "not running"})
    bars = []
    socks = polybar.sockets()
    for pid in sorted(set(polybar.bar_pids()) | set(socks)):
        reply = polybar.ping(pid)
        answering = reply is not None and reply.known
        bars.append({"pid": pid, "answering": answering})
        checks.append(
            {
                "name": f"bar {pid}",
                "state": "ok" if answering else "fail",
                "detail": "answering" if answering else "not answering IPC",
            }
        )
    if not bars:
        checks.append({"name": "bars", "state": "fail", "detail": "no polybar running"})
    try:
        modules = mods.load()
    except mods.ConfigError as e:
        modules = {}
        checks.append({"name": "modules.toml", "state": "fail", "detail": str(e)})
    off = st.disabled()
    infos = [module_info(m, now, off) for m in modules.values()]
    pinned = pins() if running and any(m.source == "player" for m in modules.values()) else {}
    for info, found in zip(infos, modules.values(), strict=True):
        if found.source == "player":
            info["pinned"] = pinned.get("player")
    for source in sorted({m.source for m in modules.values() if m.source}):
        health = st.source_health(source)
        if running and health.get("state") == "failing":
            checks.append({"name": f"source {source}", "state": "fail", "detail": "failing"})
        elif running and source in mods.BUILT:
            checks.append({"name": f"source {source}", "state": "ok", "detail": "running"})
    for info in infos:
        if info["alerting"]:
            checks.append({"name": info["name"], "state": "warn", "detail": "alerting"})
    worst = "ok"
    for c in checks:
        if c["state"] == "fail":
            worst = "fail"
        elif c["state"] == "warn" and worst == "ok":
            worst = "warn"
    problems = [c["name"] for c in checks if c["state"] == "fail"]
    summary = "all well" if not problems else "problems: " + ", ".join(problems)
    return {
        "summary": summary,
        "state": worst,
        "checks": checks,
        "controller": {
            "running": bool(running),
            "pid": running[0] if running else None,
            "since": iso(running[1]) if running and running[1] else None,
        },
        "bars": bars,
        "modules": infos,
    }


def show(name: str, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    found = module(name)
    info = module_info(found, now, st.disabled())
    data = st.read(name) or {}
    info.update(
        {
            "source": found.source,
            "pusher": found.pusher,
            "display": found.display,
            "clicks": found.clicks,
            "segment_clicks": {**found.segment_clicks, **found.cell_clicks},
            "menu": [r.as_dict() for r in found.menu],
            "dynamic_menu": found.source in mods.BUILT,
            "alert_until": iso(float(data["alert_until"])) if data.get("alert_until") else None,
            "expires": iso(float(data["expires"])) if data.get("expires") else None,
            "updated": iso(float(data["updated"])) if data.get("updated") else None,
            "written_by": data.get("source"),
        }
    )
    return info

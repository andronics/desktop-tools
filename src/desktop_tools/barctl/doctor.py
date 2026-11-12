"""`barctl doctor`: everything barctl needs, each with a fix to try (record 0003 §B5)."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.sources import SOURCES
from desktop_tools.common import paths, polybar, theme

Check = dict[str, Any]
# Set in an agent's or coordinator's session; the bar must never run with them (record 0003 §6).
AGENT_VARIABLES = (b"COORDINATOR", b"CLAUDECODE", b"TESSERA_ACTOR")


def _check(name: str, ok: bool, detail: str, fix: str = "", warn: bool = False) -> Check:
    state = "ok" if ok else "warn" if warn else "fail"
    return {"name": name, "state": state, "detail": detail, "fix": "" if ok else fix}


def polybar_config_dir() -> Path:
    explicit = os.environ.get("BARCTL_POLYBAR_CONFIG")
    return Path(explicit) if explicit else paths.config_home() / "polybar"


def ini_hooks(folder: Path) -> dict[str, str]:
    """module section -> its hook-0 command, from every .ini under the polybar config."""
    out: dict[str, str] = {}
    files = sorted(folder.rglob("*.ini")) if folder.is_dir() else []
    for file in files:
        section = None
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                inner = line[1:-1].strip()
                section = inner[len("module/") :] if inner.startswith("module/") else None
            elif section and line.split("=", 1)[0].strip() == "hook-0" and "=" in line:
                out[section] = line.split("=", 1)[1].strip()
    return out


def _writable(folder: Path) -> bool:
    probe = folder
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def zsh_controller_running() -> int | None:
    """The zsh controller's pid, if it is still running (read only: its folder is left as is)."""
    try:
        pid = int((paths.state_home() / "barctl" / "pid").read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return pid if b"zsh" in cmdline and polybar.alive(pid) else None


def agent_variables(pid: int) -> list[str]:
    """Which of AGENT_VARIABLES a process (the user's own) was started with: names only."""
    try:
        data = (polybar.proc_root() / str(pid) / "environ").read_bytes()
    except OSError:
        return []
    names = {entry.split(b"=", 1)[0] for entry in data.split(b"\0") if b"=" in entry}
    return [v.decode() for v in AGENT_VARIABLES if v in names]


def environment(controller: int | None, bars: list[int]) -> list[Check]:
    """One warning per process that runs in an agent's environment, naming the variable and
    never its value."""
    out = []
    for kind, pid in [("controller", controller)] + [("bar", b) for b in bars]:
        if pid is None:
            continue
        found = agent_variables(pid)
        if found:
            out.append(
                _check(
                    f"environment {kind} {pid}",
                    False,
                    "the bar runs in an agent's environment: restart it from a clean session"
                    f" ({', '.join(found)} set)",
                    "barctl restart, from a terminal outside any agent or coordinator session",
                    warn=True,
                )
            )
    return out


def checks(now: float | None = None) -> list[Check]:
    now = time.time() if now is None else now
    out: list[Check] = []
    start = "systemctl --user start barctl.service"

    running = st.controller()
    out.append(
        _check(
            "controller",
            running is not None,
            f"running (pid {running[0]})" if running else "not running",
            start,
        )
    )
    old = zsh_controller_running()
    out.append(
        _check(
            "zsh controller",
            old is None,
            f"the zsh barctl is still running (pid {old})" if old else "not running",
            "stop the zsh controller: the cut-over replaces it",
        )
    )

    pids = sorted(set(polybar.bar_pids()) | set(polybar.sockets()))
    if not pids:
        out.append(_check("bars", False, "no polybar running", "barctl restart"))
    out.extend(environment(running[0] if running else None, pids))
    for pid in pids:
        reply = polybar.ping(pid)
        if reply is None:
            out.append(_check(f"bar {pid}", False, "not answering IPC", "barctl restart"))
        else:
            out.append(
                _check(
                    f"bar {pid}",
                    reply.known,
                    f"answering, IPC protocol version {reply.version}",
                    "barctl falls back to polybar's own client; "
                    "teach common/polybar.py this version",
                    warn=True,
                )
            )

    try:
        modules = mods.load()
        out.append(_check("modules.toml", True, str(mods.config_path())))
    except mods.ConfigError as e:
        modules = {}
        out.append(_check("modules.toml", False, str(e), f"fix {mods.config_path()}"))

    for name, configured in modules.items():
        tiers = configured.override_tiers()
        if tiers:
            out.append(_check(f"glyph {name}", True, "override for " + ", ".join(tiers)))

    folder = polybar_config_dir()
    hooks = ini_hooks(folder)
    ours = {}
    for section, hook in hooks.items():
        words = hook.split()
        if len(words) == 3 and words[:2] == ["barctl", "render"]:
            ours[section] = words[2]
    for section, name in sorted(ours.items()):
        if name != section:
            out.append(
                _check(
                    f"polybar module {section}",
                    False,
                    f"its hook renders {name}",
                    f"hook-0 = barctl render {section}",
                )
            )
        elif name not in modules:
            out.append(
                _check(
                    f"polybar module {section}",
                    False,
                    "not in modules.toml",
                    f"add [modules.{section}] to modules.toml",
                )
            )
    for name in modules:
        if name not in ours.values():
            out.append(
                _check(
                    f"module {name}",
                    False,
                    f"no polybar module in {folder} renders it",
                    f"[module/{name}] with type = custom/ipc and hook-0 = barctl render {name}",
                )
            )
    if ours:
        out.append(_check("polybar config", True, f"{len(ours)} barctl modules in {folder}"))

    sources = sorted({m.source for m in modules.values() if m.source})
    for source in sources:
        kind = SOURCES.get(source)
        if kind is None:
            out.append(
                _check(f"source {source}", False, "not built yet", "a later barctl", warn=True)
            )
            continue
        missing = [c for c in kind.commands if shutil.which(c) is None]
        if kind.commands or not kind.optional:
            out.append(
                _check(
                    f"source {source}",
                    not missing,
                    "needs " + (", ".join(kind.commands) or "nothing outside barctl"),
                    "install " + ", ".join(missing),
                )
            )
        lacking = [c for c in kind.optional if shutil.which(c) is None]
        if kind.optional:
            out.append(
                _check(
                    f"source {source} extras",
                    not lacking,
                    "works better with " + ", ".join(kind.optional),
                    "install " + ", ".join(lacking) + " (without it: slower presence checks)",
                    warn=True,
                )
            )
    out += devices_checks(modules)

    art = sorted(m.name for m in modules.values() if m.display == "capsule" and m.accent == "art")
    if art:
        from desktop_tools.barctl import art as artwork

        missing = [c for c in artwork.COMMANDS if shutil.which(c) is None]
        out.append(
            _check(
                "art accent",
                not missing,
                f"{', '.join(art)} asks for the art's colour: needs curl, magick",
                "install " + ", ".join(missing) + ' (or accent = "role")',
                warn=True,
            )
        )

    output = sorted(m.name for m in modules.values() if m.display == "output")
    if output:
        missing = [c for c in ("busctl", "bluetoothctl") if shutil.which(c) is None]
        out.append(
            _check(
                "output segment",
                not missing,
                f"{', '.join(output)} shows a Bluetooth battery (busctl) and `barmenu outputs`"
                " connects devices (bluetoothctl)",
                "install " + ", ".join(missing) + " (systemd, bluez-utils)",
                warn=True,
            )
        )

    out.append(visualiser_check(modules))

    found = theme.roles(st.ROLES)
    out.append(
        _check(
            "theme roles",
            len(found) == len(st.ROLES),
            f"{len(found)} of {len(st.ROLES)} roles in {theme.theme_file()}",
            "theme ensure",
        )
    )

    for label, where in (("state folder", st.runtime()), ("settings folder", st.settings_dir())):
        out.append(_check(label, _writable(where), str(where), f"make {where} writable"))

    for name in st.stored():
        data = st.read(name) or {}
        if name not in modules:
            out.append(
                _check(
                    f"state {name}",
                    False,
                    "an orphan: no such module in modules.toml",
                    f"rm {st.state_path(name)}",
                )
            )
        elif data.get("expires") and float(data["expires"]) <= now:
            writer = modules[name].pusher or "its pusher"
            out.append(_check(f"state {name}", False, "stale: its ttl ran out", f"run {writer}"))
    return out


# What the printer's and scanner's actions run (record 0004 §4-§5): missing ones are reported,
# not failed, since the modules still show their state without them.
DEVICE_TOOLS = {
    "printer": ("lp", "cancel", "cupsenable", "cupsdisable", "lpoptions", "system-config-printer"),
    "scanner": ("tiffcp", "tiff2pdf", "magick", "xclip", "xdg-open", "zenity", "simple-scan"),
}


def devices_checks(modules: dict[str, mods.Module]) -> list[Check]:
    out = []
    for source, tools in DEVICE_TOOLS.items():
        names = sorted(m.name for m in modules.values() if m.source == source)
        if not names:
            continue
        lacking = [t for t in (*tools, "dunstify") if shutil.which(t) is None]
        out.append(
            _check(
                f"{source} actions",
                not lacking,
                f"{', '.join(names)}: the menu's actions run " + ", ".join(tools),
                "install " + ", ".join(lacking),
                warn=True,
            )
        )
        for name in names:
            detail = str((st.read(name) or {}).get("detail") or "")
            if "polling:" in detail:
                why = detail.split("polling:", 1)[1].split(";", 1)[0].strip()
                out.append(
                    _check(
                        f"{name} events",
                        False,
                        f"polling: {why}",
                        "check cupsd's MaxSubscriptions and its log",
                        warn=True,
                    )
                )
    return out


def visualiser_check(modules: dict[str, mods.Module]) -> Check:
    """The visualiser strip (record 0005 phase D): on or off, and why it is off."""
    asking = sorted(m.name for m in modules.values() if m.display == "capsule" and m.visualiser)
    switch = st.visualiser_switch()
    cava = shutil.which("cava") is not None
    if switch.get("on") is False:
        reason = str(switch.get("reason") or "switch")
        why = st.VISUALISER_REASONS.get(reason, reason)
        at = switch.get("at")
        since = f" since {time.strftime('%Y-%m-%d %H:%M', time.localtime(at))}" if at else ""
        fixes = {
            "budget": "it used more CPU than visualiser_budget allows: lower visualiser_fps,"
            " then barctl visualiser on",
            "cava-missing": "install cava, then barctl visualiser on",
            "cava-exits": "run cava by hand to see why it ends, then barctl visualiser on",
        }
        return _check(
            "visualiser",
            reason == "switch",
            f"off: {why}{since}",
            fixes.get(reason, "barctl visualiser on"),
            warn=True,
        )
    if not asking:
        return _check("visualiser", True, "off: no capsule has visualiser = true")
    return _check(
        "visualiser",
        cava,
        f"on for {', '.join(asking)}: needs cava",
        "install cava (or visualiser = false)",
        warn=True,
    )


def problems(found: list[Check]) -> bool:
    return any(c["state"] == "fail" for c in found)

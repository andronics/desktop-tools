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

    for name, found in modules.items():
        tiers = found.override_tiers()
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
        out.append(
            _check(
                f"source {source}",
                not missing,
                "needs " + ", ".join(kind.commands),
                "install " + ", ".join(missing),
            )
        )

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


def problems(found: list[Check]) -> bool:
    return any(c["state"] == "fail" for c in found)

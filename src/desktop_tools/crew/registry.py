"""The coordinator registry: who the coordinators are, in menu order (brain record 0019 §4).

crew keeps no list of its own. It asks `meta brain coordinators --json` and keeps the answer in
`$XDG_STATE_HOME/crew/coordinators.json`; when `meta` fails it uses that last good copy, and with
no copy at all, the homes in the actors folder (each folder holding a README.md), in name order,
so a broken vault never leaves the switchboard empty.

The hot paths (`crew bar`, `crew status`, run by polybar and nine Claude hooks) read only the kept
copy; every other verb asks `meta` again once the copy is older than `CREW_REGISTRY_MAX_AGE`
seconds (the same five minutes the `meta` core keeps its own copy for), since a key press
shouldn't wait on the vault each time.

A coordinator is shown only once its home exists, as coord did. A former name (`old_names`, until
`old_names_until`) resolves to the coordinator it was renamed to, so a session or a window left
under it is the same coordinator.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from desktop_tools.crew import conf, log

KEPT = "coordinators.json"
META_TIMEOUT = 5.0


def valid_name(name: str) -> bool:
    """A coordinator's short name: [a-z0-9][a-z0-9-]*, as coord checked it."""
    if not name or len(name) > 64 or not ("a" <= name[0] <= "z" or name[0].isdigit()):
        return False
    return all("a" <= c <= "z" or c.isdigit() or c == "-" for c in name)


def glyph_of(text: object) -> str:
    """`U+F0493` (how the registry writes a Nerd Font codepoint) as the character; "" if not."""
    if not isinstance(text, str):
        return ""
    code = text.strip().upper().removeprefix("U+")
    try:
        return chr(int(code, 16)) if code else ""
    except (ValueError, OverflowError):
        return ""


@dataclass(frozen=True)
class Coordinator:
    name: str
    home: Path
    session: str
    glyph: str = ""
    old_names: tuple[str, ...] = ()
    order: int = 0
    status: str = ""
    stopped_by_default: bool = False

    @property
    def sessions(self) -> tuple[str, ...]:
        """Its tmux session, then those of its former names: one may have been started under
        the other."""
        return (self.session, *(f"{old}-coordinator" for old in self.old_names))

    @property
    def icon(self) -> str:
        return self.glyph or self.name[0]


@dataclass
class Registry:
    coordinators: list[Coordinator] = field(default_factory=list)
    source: str = "homes"  # meta, kept or homes

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.coordinators]

    def get(self, name: str) -> Coordinator | None:
        name = self.resolve(name)
        return next((c for c in self.coordinators if c.name == name), None)

    def resolve(self, name: str) -> str:
        """The name a coordinator is shown under: `name` itself, or the one it was renamed to."""
        for c in self.coordinators:
            if c.name == name:
                return name
        for c in self.coordinators:
            if name in c.old_names:
                return c.name
        return name

    def keys(self) -> dict[str, str]:
        return keys(self.names)


def keys(names: list[str]) -> dict[str, str]:
    """What to type in the menu to filter to each: its first letter, or as many as make it
    unique among the names (pl platform, pe personal)."""
    out: dict[str, str] = {}
    for name in names:
        if not name:
            continue
        key = name
        for length in range(1, len(name) + 1):
            key = name[:length]
            if not any(o != name and o.startswith(key) for o in names):
                break
        out[name] = key
    return out


def keys_help(names: list[str]) -> str:
    found = keys(names)
    return ", ".join(f"{found[n]} {n}" for n in names if n in found) or "none shown"


# ---------------------------------------------------------------- parsing


def _entries(data: Any) -> list[Any] | None:
    """The list of coordinators in `meta`'s answer: a list, or one wrapped in the meta envelope
    (`data`) or under `coordinators`."""
    for _ in range(3):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            data = data.get("coordinators", data.get("data"))
        else:
            return None
    return data if isinstance(data, list) else None


def _until_passed(value: object, today: dt.date) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return dt.date.fromisoformat(value[:10]) < today
    except ValueError:
        return False


def parse(data: Any, today: dt.date | None = None) -> list[Coordinator] | None:
    """The coordinators in `meta brain coordinators --json`, in menu order; None if it isn't
    that shape. Entries without a usable name are dropped."""
    entries = _entries(data)
    if entries is None:
        return None
    today = today or dt.date.today()
    out: list[tuple[int, int, Coordinator]] = []
    seen: set[str] = set()
    for i, raw in enumerate(entries):
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not valid_name(name) or name in seen:
            continue
        seen.add(name)
        home = raw.get("home")
        session = raw.get("tmux_session")
        old = raw.get("old_names") or []
        olds = tuple(
            o
            for o in (old if isinstance(old, list) else [])
            if isinstance(o, str) and valid_name(o)
        )
        if _until_passed(raw.get("old_names_until"), today):
            olds = ()
        order = raw.get("menu_order")
        order = order if isinstance(order, int) and not isinstance(order, bool) else 10_000 + i
        status = raw.get("status")
        out.append(
            (
                order,
                i,
                Coordinator(
                    name=name,
                    home=Path(home) if isinstance(home, str) and home else conf.actors_dir() / name,
                    session=session
                    if isinstance(session, str) and session
                    else f"{name}-coordinator",
                    glyph=glyph_of(raw.get("bar_glyph")),
                    old_names=olds,
                    order=order,
                    status=status if isinstance(status, str) else "",
                    stopped_by_default=raw.get("stopped_by_default") is True,
                ),
            )
        )
    return [c for _, _, c in sorted(out, key=lambda t: (t[0], t[1]))]


def from_homes(folder: Path | None = None) -> list[Coordinator]:
    """The fallback: each home in the actors folder (a folder with a README.md), by name."""
    folder = folder or conf.actors_dir()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [
        Coordinator(name=n, home=folder / n, session=f"{n}-coordinator")
        for n in names
        if valid_name(n) and (folder / n / "README.md").is_file()
    ]


# ---------------------------------------------------------------- the kept copy


def kept_path() -> Path:
    return conf.state_dir() / KEPT


def _read_kept() -> tuple[list[Coordinator], float] | None:
    path = kept_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        age = time.time() - path.stat().st_mtime
    except (OSError, ValueError):
        return None
    found = parse(data)
    return (found, age) if found else None


def _keep(raw: Any) -> None:
    folder = conf.state_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = folder / f".{KEPT}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, kept_path())
    except OSError as e:
        log.warning(f"registry: cannot keep a copy in {folder}: {e.strerror}")
        with contextlib.suppress(OSError, UnboundLocalError):
            tmp.unlink()


def ask_meta() -> Any | None:
    """`meta brain coordinators --json`, parsed; None (with a warning) when it fails."""
    import subprocess

    argv = ["meta", "brain", "coordinators", "--json"]
    try:
        # S603/S607: a fixed argument list; `meta` is found on PATH, as the brain installs it.
        done = subprocess.run(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=META_TIMEOUT,
            check=False,
            env={**os.environ, "TOOL_STATS": "skip"},
        )
    except FileNotFoundError:
        log.debug("registry: meta is not on PATH")
        return None
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(f"registry: meta brain coordinators failed: {type(e).__name__}")
        return None
    if done.returncode != 0:
        why = (done.stderr.strip().splitlines() or [""])[0]
        log.warning(f"registry: meta brain coordinators exited {done.returncode}: {why}")
        return None
    try:
        data = json.loads(done.stdout)
    except ValueError:
        log.warning("registry: meta brain coordinators gave no JSON")
        return None
    if not parse(data):
        log.warning("registry: meta brain coordinators listed no coordinator")
        return None
    return data


def _shown(found: list[Coordinator]) -> list[Coordinator]:
    return [c for c in found if c.home.is_dir()]


def load(refresh: bool = True) -> Registry:
    """The registry: meta's answer (asked when `refresh` and the kept copy is old), else the kept
    copy, else the homes. Only coordinators with a home are in it."""
    kept = _read_kept()
    if refresh and (kept is None or kept[1] >= conf.registry_max_age()):
        raw = ask_meta()
        if raw is not None:
            _keep(raw)
            return Registry(_shown(parse(raw) or []), "meta")
        if kept is not None:
            log.debug("registry: using the last good copy")
    if kept is not None:
        return Registry(_shown(kept[0]), "kept")
    return Registry(from_homes(), "homes")

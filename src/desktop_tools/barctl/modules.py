"""modules.toml: every IPC module barctl draws, who writes it, how it shows and what its clicks do
(dotfiles record 0003 §B4).

    [modules.audio-level]
    source = "volume"            # one of barctl's own sources, or
    # pusher = "crew"            # the one outside program that may `barctl push` it
    display = "both"             # icon (glyph, then count), text (label) or both
    glyph = "\\U000F0581"         # shown before anything has written the module
    separator = " "              # between segments, for a module made of several cells

    [modules.audio-level.clicks] # button -> command; {target} and {segment} are filled in
    left = ["audio", "mute-toggle"]

    [[modules.audio-level.menu]] # right-click rows, before the source's own
    glyph = "\\U000F057E"
    label = "Mixer"
    command = ["pwvucontrol"]

The package ships a default for the live modules; `$XDG_CONFIG_HOME/barctl/modules.toml` (or the
file `$BARCTL_CONFIG` names) replaces it whole, since that file lists every module.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from desktop_tools.common import paths

SOURCES = ("volume", "player", "printer", "scanner", "vpn", "bluetooth", "counter")
BUILT = ("volume", "player")  # the others are reserved names: their sources come in later PRs
BUTTONS = {"left": 1, "middle": 2, "right": 3, "scroll-up": 4, "scroll-down": 5}
DISPLAYS = ("icon", "text", "both")
PACKAGED = Path(__file__).with_name("modules.toml")


class ConfigError(Exception):
    """modules.toml can't be read or says something barctl can't do."""


def valid_name(name: str) -> bool:
    """Module names become file names and polybar action names: [a-z0-9][a-z0-9-]*."""
    if not name or len(name) > 64 or not ("a" <= name[0] <= "z" or name[0].isdigit()):
        return False
    return all("a" <= c <= "z" or c.isdigit() or c == "-" for c in name)


def valid_segment(name: str) -> bool:
    """Segment ids go into polybar action tags: no space or colon."""
    return bool(name) and len(name) <= 64 and all(c.isalnum() or c in "_.-" for c in name)


class Row:
    """A menu row: a glyph (may be empty), a label and a command."""

    __slots__ = ("command", "glyph", "label")

    def __init__(self, glyph: str, label: str, command: list[str]) -> None:
        self.glyph, self.label, self.command = glyph, label, command

    def as_dict(self) -> dict[str, object]:
        return {"glyph": self.glyph, "label": self.label, "command": self.command}


class Module:
    __slots__ = (
        "clicks",
        "display",
        "glyph",
        "menu",
        "name",
        "pusher",
        "segment_clicks",
        "separator",
        "source",
    )

    def __init__(
        self,
        name: str,
        *,
        source: str | None = None,
        pusher: str | None = None,
        display: str = "icon",
        glyph: str = "",
        separator: str = " ",
        clicks: dict[str, list[str]] | None = None,
        segment_clicks: dict[str, list[str]] | None = None,
        menu: list[Row] | None = None,
    ) -> None:
        self.name, self.source, self.pusher = name, source, pusher
        self.display, self.glyph, self.separator = display, glyph, separator
        self.clicks = clicks or {}
        self.segment_clicks = segment_clicks or {}
        self.menu = menu or []

    @property
    def writer(self) -> str:
        return self.source or self.pusher or ""

    def has_menu(self) -> bool:
        return bool(self.menu) or self.source in BUILT

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source": self.source,
            "pusher": self.pusher,
            "display": self.display,
            "glyph": self.glyph,
            "clicks": self.clicks,
            "segment_clicks": self.segment_clicks,
            "menu": [r.as_dict() for r in self.menu],
        }


def config_path() -> Path:
    explicit = os.environ.get("BARCTL_CONFIG")
    if explicit:
        return Path(explicit)
    override = paths.config_home() / "barctl" / "modules.toml"
    return override if override.is_file() else PACKAGED


def _strings(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: a command is a non-empty list of strings")
    return [str(v) for v in value]


def _text(table: dict[str, object], key: str, where: str, default: str = "") -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{where}: {key} must be a string")
    return value


def _clicks(value: object, where: str) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: must be a table of button = command")
    out = {}
    for button, cmd in value.items():
        if button not in BUTTONS:
            raise ConfigError(f"{where}: unknown button {button!r} (one of {', '.join(BUTTONS)})")
        out[button] = _strings(cmd, f"{where}.{button}")
    return out


def parse(data: dict[str, object]) -> dict[str, Module]:
    table = data.get("modules", {})
    if not isinstance(table, dict):
        raise ConfigError("[modules] must be a table")
    out: dict[str, Module] = {}
    for name, raw in table.items():
        where = f"modules.{name}"
        if not valid_name(name):
            raise ConfigError(f"{where}: not a module name ([a-z0-9][a-z0-9-]*)")
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: must be a table")
        source, pusher = raw.get("source"), raw.get("pusher")
        if (source is None) == (pusher is None):
            raise ConfigError(f"{where}: give exactly one of source and pusher")
        if source is not None and source not in SOURCES:
            raise ConfigError(f"{where}: unknown source {source!r} (one of {', '.join(SOURCES)})")
        if pusher is not None and (not isinstance(pusher, str) or not valid_name(pusher)):
            raise ConfigError(f"{where}: pusher must be a program's name")
        display = _text(raw, "display", where, "icon")
        if display not in DISPLAYS:
            raise ConfigError(f"{where}: display is one of {', '.join(DISPLAYS)}")
        menu = []
        rows = raw.get("menu", [])
        if not isinstance(rows, list):
            raise ConfigError(f"{where}.menu: must be an array of tables")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ConfigError(f"{where}.menu[{i}]: must be a table")
            label = _text(row, "label", f"{where}.menu[{i}]")
            if not label:
                raise ConfigError(f"{where}.menu[{i}]: needs a label")
            menu.append(
                Row(
                    _text(row, "glyph", f"{where}.menu[{i}]"),
                    label,
                    _strings(row.get("command"), f"{where}.menu[{i}].command"),
                )
            )
        out[name] = Module(
            name,
            source=source if isinstance(source, str) else None,
            pusher=pusher if isinstance(pusher, str) else None,
            display=display,
            glyph=_text(raw, "glyph", where),
            separator=_text(raw, "separator", where, " "),
            clicks=_clicks(raw.get("clicks"), f"{where}.clicks"),
            segment_clicks=_clicks(raw.get("segment_clicks"), f"{where}.segment_clicks"),
            menu=menu,
        )
    return dict(sorted(out.items()))


def load(path: Path | None = None) -> dict[str, Module]:
    path = path or config_path()
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    try:
        return parse(data)
    except ConfigError as e:
        raise ConfigError(f"{path}: {e}") from None


def by_source(modules: dict[str, Module]) -> dict[str, list[str]]:
    """source -> the modules it draws, for the sources barctl has."""
    out: dict[str, list[str]] = {}
    for m in modules.values():
        if m.source:
            out.setdefault(m.source, []).append(m.name)
    return out

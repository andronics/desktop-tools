"""modules.toml: every IPC module barctl draws, who writes it, how it shows and what its clicks do
(dotfiles record 0003 §B4).

    [modules.audio-level]
    source = "volume"            # one of barctl's own sources, or
    # pusher = "crew"            # the one outside program that may `barctl push` it
    display = "both"             # icon (glyph, then count), text (label), both, or capsule and
                                 # output (record 0003: the player capsule, the output segment)
    glyph = "\\U000F0581"         # shown before anything has written the module
    glyph_override = "\\U000F099D" # wins over the pushed glyph: a string (every tier) or a table
    # glyph_override = { idle = "\\U000F099D", alert = "\\U000F0ECC" }  # per tier; others unchanged
    separator = " "              # between segments, for a module made of several cells
    # width, scroll, scroll_rest, accent: for display = "capsule" only (record 0003 §2)

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
DISPLAYS = ("icon", "text", "both", "capsule", "output")
ACCENTS = ("role", "art")
# The capsule's keys (record 0003 §2): (default, lowest, highest); read only for `capsule`.
CAPSULE_KEYS: dict[str, tuple[float, float, float]] = {
    "width": (32, 8, 80),
    "scroll": (2.0, 0, 4),
    "scroll_rest": (10.0, 0, 120),
}
TIERS = ("unavailable", "idle", "active", "alert")  # state.TIERS, kept here (no import cycle)
OVERRIDE_ORDER = ("idle", "active", "alert", "unavailable")  # how doctor lists a table's tiers
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
        "accent",
        "clicks",
        "display",
        "glyph",
        "glyph_override",
        "menu",
        "name",
        "pusher",
        "scroll",
        "scroll_rest",
        "segment_clicks",
        "separator",
        "source",
        "width",
    )

    def __init__(
        self,
        name: str,
        *,
        source: str | None = None,
        pusher: str | None = None,
        display: str = "icon",
        glyph: str = "",
        glyph_override: str | dict[str, str] | None = None,
        separator: str = " ",
        clicks: dict[str, list[str]] | None = None,
        segment_clicks: dict[str, list[str]] | None = None,
        menu: list[Row] | None = None,
        width: int = 32,
        scroll: float = 2.0,
        scroll_rest: float = 10.0,
        accent: str = "role",
    ) -> None:
        self.name, self.source, self.pusher = name, source, pusher
        self.width, self.scroll, self.scroll_rest, self.accent = width, scroll, scroll_rest, accent
        self.display, self.glyph, self.separator = display, glyph, separator
        self.glyph_override = glyph_override
        self.clicks = clicks or {}
        self.segment_clicks = segment_clicks or {}
        self.menu = menu or []

    @property
    def writer(self) -> str:
        return self.source or self.pusher or ""

    def override_tiers(self) -> list[str]:
        """The tiers a glyph override covers, in doctor's order (empty without one)."""
        if self.glyph_override is None:
            return []
        if isinstance(self.glyph_override, str):
            return list(OVERRIDE_ORDER)
        return [t for t in OVERRIDE_ORDER if t in self.glyph_override]

    def glyph_for(self, tier: str, state: dict[str, object] | None) -> tuple[str, str]:
        """The glyph the bar shows for the tier barctl shows, and which rule gave it (record
        0002 §7): the override's entry for the tier ("override-tier"), a string override
        ("override"), the state's own glyph ("pushed"), else the module's `glyph` ("default")."""
        override = self.glyph_override
        if isinstance(override, dict) and tier in override:
            return override[tier], "override-tier"
        if isinstance(override, str):
            return override, "override"
        if state is not None and "glyph" in state:
            return str(state["glyph"] or ""), "pushed"
        return self.glyph, "default"

    def has_menu(self) -> bool:
        return bool(self.menu) or self.source in BUILT

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "name": self.name,
            "source": self.source,
            "pusher": self.pusher,
            "display": self.display,
            "glyph": self.glyph,
            "clicks": self.clicks,
            "segment_clicks": self.segment_clicks,
            "menu": [r.as_dict() for r in self.menu],
        }
        if self.glyph_override is not None:
            out["glyph_override"] = self.glyph_override
        if self.display == "capsule":
            out.update(
                width=self.width,
                scroll=self.scroll,
                scroll_rest=self.scroll_rest,
                accent=self.accent,
            )
        return out


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


def shown_tier(state: dict[str, object] | None, now: float) -> str:
    """The tier barctl shows: the state's, `unavailable` when there is none or its ttl ran out."""
    if state is None:
        return "unavailable"
    if state.get("expires") and float(str(state["expires"])) <= now:
        return "unavailable"
    return str(state.get("tier") or "unavailable")


def _override(value: object, where: str) -> str | dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: glyph_override must be a string or a table of tier = glyph")
    out = {}
    for tier, glyph in value.items():
        if tier not in TIERS:
            raise ConfigError(f"{where}.{tier}: unknown tier (one of {', '.join(TIERS)})")
        if not isinstance(glyph, str):
            raise ConfigError(f"{where}.{tier}: a glyph is text")
        out[tier] = glyph
    return out


def _number(table: dict[str, object], key: str, where: str) -> float:
    default, low, high = CAPSULE_KEYS[key]
    value = table.get(key, default)
    whole = key == "width"
    if isinstance(value, bool) or not isinstance(value, int if whole else (int, float)):
        raise ConfigError(f"{where}: {key} must be {'a whole number' if whole else 'a number'}")
    if not low <= value <= high:
        raise ConfigError(f"{where}: {key} must be {low:g} to {high:g}")
    return float(value)


def _capsule(module: Module, raw: dict[str, object], where: str) -> Module:
    """The capsule's keys, checked, with their defaults; read only for `display = "capsule"`."""
    if module.display != "capsule":
        return module
    accent = _text(raw, "accent", where, "role")
    if accent not in ACCENTS:
        raise ConfigError(f"{where}: accent is one of {', '.join(ACCENTS)}")
    module.width = int(_number(raw, "width", where))
    module.scroll = _number(raw, "scroll", where)
    module.scroll_rest = _number(raw, "scroll_rest", where)
    module.accent = accent
    return module


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
        out[name] = _capsule(
            Module(
                name,
                source=source if isinstance(source, str) else None,
                pusher=pusher if isinstance(pusher, str) else None,
                display=display,
                glyph=_text(raw, "glyph", where),
                glyph_override=_override(raw.get("glyph_override"), f"{where}.glyph_override"),
                separator=_text(raw, "separator", where, " "),
                clicks=_clicks(raw.get("clicks"), f"{where}.clicks"),
                segment_clicks=_clicks(raw.get("segment_clicks"), f"{where}.segment_clicks"),
                menu=menu,
            ),
            raw,
            where,
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

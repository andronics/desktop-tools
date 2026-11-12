"""What the scanner menu remembers (record 0004 §3): the preset, the format, the folder and the
scanner, in `$XDG_STATE_HOME/desktop-tools/devices/scan.json`.

The settings `DESKTOP_TOOLS_SCANNER` (a SANE device name) and `DESKTOP_TOOLS_SCAN_DIR` (the
default folder) come through config.SETTINGS and win over what the menu remembers only where the
record says: the scanner setting over the menu's pick, the folder setting as the default
folder. The default folder is `<Documents>/Scans`, Documents from `user-dirs.dirs` (as
`xdg-user-dir DOCUMENTS` reads it), made on the first scan.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from desktop_tools.common import paths
from desktop_tools.devices import store


@dataclass(frozen=True)
class Preset:
    name: str
    resolution: int
    mode: str  # colour, grey, lineart
    format: str  # pdf, png, jpeg
    flatbed: bool = False  # suggested for the flatbed

    @property
    def summary(self) -> str:
        mode = {"colour": "colour", "grey": "grey", "lineart": "black and white"}[self.mode]
        return f"{self.resolution} dpi, {mode}, {self.format.upper()}"


PRESETS = (
    Preset("Document", 300, "grey", "pdf"),
    Preset("Colour document", 300, "colour", "pdf"),
    Preset("Text, smallest", 300, "lineart", "pdf"),
    Preset("Draft", 150, "grey", "pdf"),
    Preset("Photo", 600, "colour", "png", flatbed=True),
)
FORMATS = ("pdf", "png", "jpeg")
DEFAULT_PRESET = PRESETS[0].name


def preset(name: str | None) -> Preset | None:
    if name is None:
        return None
    wanted = name.strip().lower()
    return next((p for p in PRESETS if p.name.lower() == wanted), None)


def setting(key: str) -> str:
    """A desktop-tools setting's value ("" when unset or the config can't be read)."""
    from desktop_tools.config import SETTINGS, ConfigError

    try:
        return SETTINGS.resolve().str(key)
    except (ConfigError, OSError, KeyError, TypeError):
        return ""


def read() -> dict[str, object]:
    return store.read(store.prefs_path())


def remember(**fields: str | None) -> dict[str, object]:
    data = read()
    for key, value in fields.items():
        if value is None:
            continue
        data[key] = value
        if key == "preset":  # a preset sets the format too, until a format is picked
            data.pop("format", None)
    store.write(store.prefs_path(), data)
    return data


def chosen_preset() -> Preset:
    found = preset(str(read().get("preset") or ""))
    return found or PRESETS[0]


def chosen_format() -> str:
    fmt = str(read().get("format") or "")
    return fmt if fmt in FORMATS else chosen_preset().format


def documents() -> Path:
    home = Path.home()
    try:
        text = (paths.config_home() / "user-dirs.dirs").read_text(encoding="utf-8")
    except OSError:
        text = ""
    m = re.search(r'^XDG_DOCUMENTS_DIR="([^"]*)"', text, re.MULTILINE)
    if m:
        value = m.group(1).replace("$HOME", str(home))
        if value.startswith("/"):
            return Path(value)
    return home / "Documents"


def default_folder() -> Path:
    explicit = setting("scan_dir")
    return Path(os.path.expanduser(explicit)) if explicit else documents() / "Scans"


def folders() -> list[tuple[str, Path]]:
    """The folder menu's fixed choices: (label, path)."""
    home = Path.home()
    return [
        (shown(default_folder()), default_folder()),
        ("Desktop", home / "Desktop"),
        ("Downloads", home / "Downloads"),
    ]


def chosen_folder() -> Path:
    raw = read().get("folder")
    return Path(str(raw)) if isinstance(raw, str) and raw.startswith("/") else default_folder()


def shown(folder: Path) -> str:
    """A folder for a label: under home without it, else its last two parts; never a full
    path."""
    home = Path.home()
    try:
        inside = folder.relative_to(home)
        return "Home" if inside == Path() else str(inside)
    except ValueError:
        return "/".join(folder.parts[-2:]) if len(folder.parts) > 2 else folder.name or "/"


def chosen_scanner() -> str:
    """The SANE device: DESKTOP_TOOLS_SCANNER, else the menu's pick, else "" (discovery's
    first)."""
    return setting("scanner") or str(read().get("device") or "")

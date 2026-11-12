"""Where the devices keep what they remember (record 0004 §3, §5).

- `$XDG_STATE_HOME/desktop-tools/devices/scan.json`: the chosen preset, format, folder and
  scanner, kept across logouts.
- `$XDG_RUNTIME_DIR/desktop-tools/devices/`: the running scan's lock and progress (`scan.json`),
  the last scan this session (`last.json`), the scanners found (`scanners.json`), each scanner's
  sources and modes (`options.json`) and the scans' temporary folders. RAM, gone at logout.

Each file is written whole and renamed into place. A file that can't be read is empty.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from desktop_tools.common import paths


def runtime() -> Path:
    return paths.runtime_dir() / "desktop-tools" / "devices"


def state() -> Path:
    return paths.state_home() / "desktop-tools" / "devices"


def prefs_path() -> Path:
    return state() / "scan.json"


def progress_path() -> Path:
    return runtime() / "scan.json"


def lock_path() -> Path:
    return runtime() / "scan.lock"


def last_path() -> Path:
    return runtime() / "last.json"


def scanners_path() -> Path:
    return runtime() / "scanners.json"


def options_path() -> Path:
    return runtime() / "options.json"


def read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def update(path: Path, **fields: Any) -> dict[str, Any]:
    data = {**read(path), **fields}
    write(path, data)
    return data


def remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()

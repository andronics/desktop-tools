"""XDG folders, read from the environment on every call so tests can point them elsewhere."""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(name: str, default: str) -> Path:
    value = os.environ.get(name, "")
    # The XDG spec: a relative path is invalid and is ignored.
    return Path(value) if value.startswith("/") else Path.home() / default


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR", "")
    return Path(value) if value.startswith("/") else Path(f"/run/user/{os.getuid()}")

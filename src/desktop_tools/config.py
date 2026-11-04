"""Configuration.

Every setting can come from four places, and the first one that has it wins:

1. ``DESKTOP_TOOLS_<NAME>_FILE``: a file that holds the value (Docker / Kubernetes secrets)
2. ``DESKTOP_TOOLS_<NAME>``: an environment variable
3. the YAML config file (``DESKTOP_TOOLS_CONFIG``, default ``/etc/desktop-tools/config.yaml``)
4. the default in SETTINGS

``<NAME>`` is the dotted key in upper case, with the dots as underscores:
``listen.port`` is ``DESKTOP_TOOLS_LISTEN_PORT``.

The engine (lookup order, strict coercion, ``check=``, ``Secret``) is interpose's
(template-python decision 0003); this module holds the project's settings and its own rules.
Its contract with the template-owned files (``cli.py``, ``scripts/gen-wiki.py``): it exports
SETTINGS (each item has key, env, default, help, secret, is_list), CONFIG_ENV, Config (with
``sources``), ConfigError and ``load_config(path=None, environ=None)``.

To add a setting, add it to SETTINGS and to Config, and read it in load_config. A rule on one
value goes in the setting's ``check=``; a rule across settings goes in load_config. A list
setting (``is_list=True``, default ``""``) is a YAML list or a comma-separated string. A
``secret=True`` setting resolves to a ``Secret``: read it with ``resolved.secret(key)``, hold it
as one in Config and call ``reveal()`` where it's used, since ``str()`` gives ``********``. The
wiki's settings table is generated from SETTINGS (``scripts/gen-wiki.py``), so write its help as
you want users to read it. Values are never logged; only where each one came from is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from interpose.settings import ConfigError, Setting, Settings, one_of

__all__ = [
    "CONFIG_ENV",
    "DEFAULT_CONFIG_PATH",
    "ENV_PREFIX",
    "LOG_LEVELS",
    "SETTINGS",
    "Config",
    "ConfigError",
    "load_config",
]

ENV_PREFIX = "DESKTOP_TOOLS_"
DEFAULT_CONFIG_PATH = Path("/etc/desktop-tools/config.yaml")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

SETTINGS = Settings(
    ENV_PREFIX,
    (
        Setting(
            "log_level",
            "INFO",
            "Log level: `DEBUG`, `INFO`, `WARNING` or `ERROR`.",
            check=one_of(*LOG_LEVELS),
        ),
    ),
    default_path=DEFAULT_CONFIG_PATH,
)
CONFIG_ENV = SETTINGS.config_env


@dataclass(frozen=True)
class Config:
    log_level: str
    # Setting key -> where its value came from ("default", "file", an env var name).
    sources: Mapping[str, str] = field(default_factory=dict)


def load_config(path: Path | None = None, environ: Mapping[str, str] | None = None) -> Config:
    """Load the configuration. A missing config file is not an error: defaults apply."""
    resolved = SETTINGS.resolve(path, environ)
    # Each accessor gives its setting's type and raises TypeError for another kind: a secret=True
    # setting is resolved.secret(key), never resolved.str(key). one_of() gives the declared
    # spelling, so log_level is already one of LOG_LEVELS, the names logging wants.
    # Cross-setting rules go here; a rule on one value is its setting's check=.
    return Config(
        log_level=resolved.str("log_level"),
        sources=dict(resolved.sources),
    )

"""The `desktop-tools` command.

The wiki's CLI-Reference page is generated from this module (scripts/gen-wiki.py),
so command docstrings and option help are user documentation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from interpose.secret import MASK

from desktop_tools import __description__, __version__
from desktop_tools.config import CONFIG_ENV, SETTINGS, Config, ConfigError, load_config

app = typer.Typer(
    help=__description__,
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        envvar=CONFIG_ENV,
        help="Config file (default /etc/desktop-tools/config.yaml; missing is fine).",
        show_default=False,
    ),
]


def _load(path: Path | None) -> Config:
    try:
        return load_config(path)
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command("config")
def show_config(config: ConfigOption = None) -> None:
    """Print the effective configuration and where each value came from. Secrets: set or unset."""
    cfg = _load(config)
    values = {
        "log_level": cfg.log_level,
    }
    # A secret shows whether it is set, never its value: a Secret is truthy when it isn't
    # empty. Read from the resolved settings, so a secret Config holds needs no entry above.
    resolved = SETTINGS.resolve(config).values
    for setting in SETTINGS:
        shown: object = values.get(setting.key)
        if setting.secret:
            shown = f"{MASK} (set)" if resolved[setting.key] else "(unset)"
        typer.echo(f"{setting.key} = {shown}  ({cfg.sources[setting.key]})")


def main() -> None:
    app()

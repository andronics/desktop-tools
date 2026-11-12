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


def _mount() -> None:
    """Each tool as a sub-app (dotfiles record 0003 §A1): `desktop-tools barctl status` and
    `barctl status` are the same command."""
    from desktop_tools.barctl.app import app as barctl
    from desktop_tools.barmenu.cli import app as barmenu
    from desktop_tools.crew.app import app as crew
    from desktop_tools.devices.cli import app as devices

    app.add_typer(barctl, name="barctl")
    app.add_typer(barmenu, name="barmenu")
    app.add_typer(crew, name="crew")
    app.add_typer(devices, name="devices")


_mount()


@app.command()
def completions(
    shell: Annotated[str, typer.Argument(help="The shell: zsh.")],
    out: Annotated[Path, typer.Option("--out", help="The folder to write them into.")],
) -> None:
    """Write each tool's completion file (`_barctl_cmd`, `_barmenu_cmd`, `_crew_cmd`,
    `_devices_cmd`) for this
    version."""
    from desktop_tools import completions as comp

    if shell != "zsh":
        typer.echo(f"error: no completions for {shell!r} (only zsh)", err=True)
        raise typer.Exit(2)
    raise typer.Exit(comp.write(out, emit=typer.echo))


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
        "scanner": cfg.scanner,
        "scan_dir": cfg.scan_dir,
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

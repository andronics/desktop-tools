"""The `barmenu` command: `barmenu <menu>` opens a menu, `barmenu run <command...>` launches a
command detached from the bar, `barmenu list` names the menus (for completion).

Each menu is a subcommand, made from menus.toml when the app is built, as the zsh barmenu made a
function per table entry.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Annotated

import typer

from desktop_tools.barmenu import menus as bm

OWNER = "desktop-coordinator"


def _open(name: str) -> None:
    try:
        menu = bm.load()[name]
    except (bm.MenuError, KeyError) as e:
        typer.echo(f"barmenu: {e}", err=True)
        raise typer.Exit(2) from None
    try:
        bm.open_menu(menu)
    except OSError as e:
        typer.echo(f"barmenu: {e.strerror}", err=True)
        raise typer.Exit(4) from None


def _opener(name: str) -> Callable[[], None]:
    def command() -> None:
        _open(name)

    return command


def build(menus: dict[str, bm.Menu] | None = None) -> typer.Typer:
    """The app, with a subcommand per menu (from menus.toml unless given)."""
    app = typer.Typer(
        name="barmenu",
        help="The polybar menu buttons as rofi menus, opened above the pointer.",
        no_args_is_help=True,
        add_completion=False,
        pretty_exceptions_enable=False,
        context_settings={"help_option_names": ["-h", "--help"]},
        rich_markup_mode="markdown",  # reflows the help's paragraphs
    )
    if menus is None:
        try:
            menus = bm.load()
        except bm.MenuError as e:
            sys.stderr.write(f"barmenu: {e}\n")
            menus = {}
    for name, menu in menus.items():
        app.command(name, help=menu.description())(_opener(name))

    @app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
    def run_(
        command: Annotated[list[str], typer.Argument(help="The command and its arguments.")],
    ) -> None:
        """Run a command detached from the bar's pipes (setsid, no inherited descriptors)."""
        try:
            bm.run(command)
        except OSError as e:
            typer.echo(f"barmenu: {command[0]}: {e.strerror}", err=True)
            raise typer.Exit(4) from None

    @app.command("list")
    def list_() -> None:
        """Every menu's name, one per line (for completion)."""
        try:
            names = list(bm.load())
        except bm.MenuError as e:
            typer.echo(f"barmenu: {e}", err=True)
            raise typer.Exit(2) from None
        for name in names:
            typer.echo(name)

    return app


app = build()


def main() -> None:
    from desktop_tools.barctl.cli import HELP, OWNER, _verb
    from desktop_tools.common import journal

    argv = sys.argv[1:]

    def go() -> int:
        try:
            app(args=argv, prog_name="barmenu", standalone_mode=True)
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return 0  # pragma: no cover - standalone_mode always exits

    if not argv or HELP & set(argv):
        raise SystemExit(go())
    commands = [*bm.RESERVED, *(c.name or "" for c in app.registered_commands)]
    raise SystemExit(
        journal.run(go, tool="barmenu", owner=OWNER, commands=commands, command_of=_verb)
    )

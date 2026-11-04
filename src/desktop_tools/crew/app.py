"""crew's Typer app: every verb (brain record 0019 §7).

`status` and `bar` are here too, for `--help` and for `desktop-tools crew ...`; the `crew` command
runs them from `fast` without importing this module.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from desktop_tools.crew import fast, registry, switch
from desktop_tools.crew.out import say

app = typer.Typer(
    name="crew",
    help="The coordinator switchboard: one hidden terminal per Claude Code coordinator, docked "
    "left or right when shown (brain record 0019). Showing never starts a stopped coordinator; "
    "only `toggle --launch` (the bar glyph's left click) and `launch` do. Starting and stopping "
    "go only through `meta <name> launch|stop|restart`.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    rich_markup_mode="markdown",
)


class Direction(StrEnum):
    next = "next"
    prev = "prev"


class Side(StrEnum):
    left = "left"
    right = "right"


Name = Annotated[str, typer.Argument(help="A coordinator, as `crew names` lists them.")]


def _done(code: int) -> None:
    if code:
        raise typer.Exit(code)


@app.command()
def toggle(
    name: Name,
    launch: Annotated[
        bool,
        typer.Option("--launch", help="Start it if it is stopped (the bar glyph's left click)."),
    ] = False,
) -> None:
    """Hide a coordinator if it is shown and focused, else show it docked.

    A stopped coordinator is not started: crew says it is stopped and exits 1, unless --launch
    is given, which starts it through `meta <name> launch` and shows its window.
    """
    _done(switch.toggle(registry.load(), name, launching=launch))


@app.command()
def show(name: Name) -> None:
    """Show a coordinator docked, never hiding it and never starting it (exit 1 if stopped)."""
    _done(switch.summon(registry.load(), name))


@app.command()
def hide(
    toggle_: Annotated[
        bool,
        typer.Option(
            "--toggle", help="With none shown, show the last one shown (or the first), if running."
        ),
    ] = False,
) -> None:
    """Hide the shown coordinator, focused or not, and give its strip back."""
    _done(switch.hide(registry.load(), toggling=toggle_))


@app.command()
def cycle(direction: Annotated[Direction, typer.Argument(help="next or prev.")]) -> None:
    """Show the next or previous running coordinator in menu order, wrapping.

    Stopped ones are skipped. With none shown, the last one shown comes back (or the first).
    With none running, crew says so and exits 1.
    """
    _done(switch.cycle(registry.load(), direction.value))


@app.command("launch")
def launch_(
    name: Name,
    show_: Annotated[
        bool, typer.Option("--show", help="Then show it docked (also if it was running).")
    ] = False,
) -> None:
    """Start a coordinator through `meta <name> launch`, hidden unless --show.

    meta's refusals are meta's (already running, not for this caller, no home): crew says why in
    a notification and exits with meta's code.
    """
    from desktop_tools.crew import life

    _done(life.launch(registry.load(), name, showing=show_))


@app.command()
def stop(
    name: Annotated[
        str | None, typer.Argument(help="A coordinator, as `crew names` lists them.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="End it even if its resume notes are not clean.")
    ] = False,
    all_: Annotated[
        bool, typer.Option("--all", help="Every running coordinator but those only Stephen ends.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="With --all: don't ask, stop the unclean ones too.")
    ] = False,
) -> None:
    """Stop a coordinator through `meta <name> stop`, or all of them with --all.

    meta judges the resume notes and ends the session; not clean, it exits 1 and nothing ends,
    unless --force. --all checks each first (`meta <name> stop --check`) and, if any is not
    clean, asks once (rofi Yes/No) before stopping them all; declined, nothing stops. meta's
    exit code and reason reach the notification and crew's exit status.
    """
    from desktop_tools.crew import life

    if all_ == (name is not None) or (all_ and force) or (yes and not all_):
        typer.echo("crew stop: give one name [--force], or --all [--yes]", err=True)
        raise typer.Exit(2)
    reg = registry.load()
    _done(life.stop_all(reg, yes=yes) if all_ else life.stop(reg, str(name), force=force))


@app.command()
def restart(name: Name) -> None:
    """Restart a coordinator through `meta <name> restart`, shown again if it was shown.

    Hidden before, it stays hidden. meta's exit code and reason reach the notification and
    crew's exit status.
    """
    from desktop_tools.crew import life

    _done(life.restart(registry.load(), name))


# -N is a width, not an option.
@app.command(context_settings={"ignore_unknown_options": True})
def width(
    value: Annotated[
        str | None, typer.Argument(help="N, +N, -N, or left or right to move the inner edge.")
    ] = None,
    step: Annotated[str | None, typer.Argument(help="How far left or right moves it.")] = None,
) -> None:
    """Print the dock panel's visible width, or set it (640 to 2560), resizing a shown panel.

    `left` and `right` move the panel's inner edge (by 128, or N): docked right, left widens it;
    docked left, left narrows it. A width set but not printed (sxhkd's stdout gone) is not a
    failure.
    """
    _done(switch.width(value, step))


@app.command()
def side(value: Annotated[Side | None, typer.Argument(help="left or right.")] = None) -> None:
    """Print the dock side, or set it, re-docking a shown coordinator."""
    _done(switch.side(value.value if value else None))


@app.command()
def guard() -> None:
    """Keep the shown coordinator docked (started detached by every show; exits when none is).

    After a drag, a resize or a tiling, the panel goes back to floating at the stored side and
    width once bspwm's events settle. A singleton: a second one exits at once.
    """
    from desktop_tools.crew import guard as g

    _done(g.main())


@app.command()
def status(
    event: Annotated[str | None, typer.Argument(help="Overrides the hook's event name.")] = None,
) -> None:
    """Claude Code hook: read the hook's JSON on stdin and record the coordinator busy, idle or
    waiting. Always exits 0 and prints nothing.

    Only sessions under the actors folder count. Entering waiting raises a notification whose
    click shows the coordinator; every change refreshes the strip.
    """
    _done(fast.status([event] if event else []))


@app.command()
def bar(
    quiet: Annotated[bool, typer.Option("--quiet", help="Push only; print nothing.")] = False,
) -> None:
    """Push the strip (a cell per coordinator) to barctl's `crew` module and print its line.

    Tiers: dim not running, fg_dim idle, accent busy, urgent waiting; the shown one underlined.
    """
    _done(fast.bar(["--quiet"] if quiet else []))


@app.command("list")
def list_() -> None:
    """List crew's windows and whether each is hidden or visible."""
    for line in switch.windows():
        say(line)


@app.command()
def names(
    keys: Annotated[bool, typer.Option("--keys", help="Each with its menu key first.")] = False,
) -> None:
    """List the coordinators crew knows, in menu order, from the registry."""
    reg = registry.load()
    found = reg.keys()
    for name in reg.names:
        say(f"{found[name]} {name}" if keys else name)


@app.command()
def stopped(names_: Annotated[list[str], typer.Argument(metavar="NAMES...")]) -> None:
    """The desktop half of a stop, run by the brain's stop script after it ends a session.

    Drops the coordinator's state, waits for its window to close, gives the dock strip back and
    refreshes the strip. Works without DISPLAY. Exit 1 if a window is still open.
    """
    _done(switch.stopped(registry.load(), names_))


@app.command(hidden=True)
def notify(name: Name, body: Annotated[str, typer.Argument()] = "") -> None:
    """The waiting notification, run detached by `status`; its click shows the coordinator."""
    _done(switch.notify_waiting(registry.load(refresh=False), name, body))


@app.command()
def quick(name: Name) -> None:
    """Open one coordinator's quick menu above the pointer (its glyph's right click).

    Show or Hide first, then what `meta <name> menu --json` offers for it, in meta's order:
    Launch or Stop and Restart, its home in VS Code, status, inbox, resume notes and more. With
    meta failing, Show, Launch, Stop and Restart from crew's own state. Stop and Restart ask
    first; one only Stephen ends (the brain coordinator, the arbiter) is always asked about.
    """
    from desktop_tools.crew import menus

    _done(menus.quick(registry.load(), name))


@app.command()
def menu() -> None:
    """Open the full menu, each coordinator then its actions (middle click, super + c).

    Level one lists every coordinator with its state (type its key to filter, as `crew names
    --keys` lists them) and Stop all; level two offers Show or Hide, Start, Stop and Restart.
    Escape on level two, or No to a question, goes back to level one. Starting and stopping go
    through `meta`.
    """
    from desktop_tools.crew import menus

    _done(menus.full(registry.load()))

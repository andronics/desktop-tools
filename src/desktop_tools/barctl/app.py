"""barctl's Typer app: every verb (dotfiles record 0003 §B5).

`render` and `push` are here too, for `--help` and for `desktop-tools barctl ...`; the `barctl`
command runs them from `fast` without importing this module.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any

import typer

from desktop_tools.barctl import doctor as doc
from desktop_tools.barctl import fast, ops
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st

app = typer.Typer(
    name="barctl",
    help="The Polybar controller: it follows volume and media players, holds every IPC module's "
    "state, and is the only program that talks to polybar (dotfiles record 0003).",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    rich_markup_mode="markdown",  # reflows the help's paragraphs instead of keeping line breaks
)


class Button(StrEnum):
    left = "left"
    middle = "middle"
    right = "right"
    scroll_up = "scroll-up"
    scroll_down = "scroll-down"


class Tier(StrEnum):
    unavailable = "unavailable"
    idle = "idle"
    active = "active"
    alert = "alert"


Json = Annotated[bool, typer.Option("--json", help="JSON instead of text.")]
ModuleArg = Annotated[str, typer.Argument(help="A module, as `barctl list` names it.")]


def _fail(e: ops.Failure) -> typer.Exit:
    typer.echo(f"barctl: {e}", err=True)
    return typer.Exit(e.code)


def _dump(data: Any) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def status(as_json: Json = False) -> None:
    """Show the controller, the bars and every module.

    Whether the controller is running, each bar alive and answering, and every module's tier,
    glyph, label, count, writer and age. Exit 1 if the controller or a bar is down or a source
    is failing; a device being off is a tier, not a failure. --json gives brain record 0019's
    status shape.
    """
    data = ops.status()
    if as_json:
        _dump(data)
    else:
        c = data["controller"]
        since = f", since {c['since']}" if c["since"] else ""
        typer.echo(
            f"controller: running (pid {c['pid']}{since})"
            if c["running"]
            else "controller: not running"
        )
        for bar in data["bars"]:
            typer.echo(f"bar {bar['pid']}: {'answering' if bar['answering'] else 'NOT answering'}")
        if not data["bars"]:
            typer.echo("bars: none running")
        for m in data["modules"]:
            shown = m["glyph"] + " (override)" if m["glyph_source"].startswith("override") else ""
            text = " ".join(
                p
                for p in (shown or m["glyph"], str(m["count"]) if m["count"] else "", m["label"])
                if p
            )
            age = f"{m['age_s']:g}s" if m["age_s"] is not None else "-"
            flags = "".join(f" [{f}]" for f in ("alerting", "stale") if m[f]) + (
                "" if m["enabled"] else " [disabled]"
            )
            typer.echo(
                f"{m['name']:<18} {m['writer']:<8} {m['tier'] or 'none':<12} {age:>7}  "
                f"{text}{flags}"
            )
    raise typer.Exit(1 if data["state"] == "fail" else 0)


@app.command("list")
def list_modules(as_json: Json = False) -> None:
    """List every module, one per line, sorted.

    For completion. --json adds each one's source or pusher, display and whether it is enabled.
    """
    try:
        modules = ops.load()
    except ops.Failure as e:
        raise _fail(e) from None
    off = st.disabled()
    if as_json:
        _dump(
            [
                {
                    "name": m.name,
                    "source": m.source,
                    "pusher": m.pusher,
                    "display": m.display,
                    "enabled": m.name not in off,
                }
                for m in modules.values()
            ]
        )
    else:
        for name in modules:
            typer.echo(name)


@app.command()
def show(module: ModuleArg, as_json: Json = False) -> None:
    """Show one module in detail.

    Its state, detail, target, alert, writer, last change, clicks and menu rows. Exit 5 for an
    unknown module.
    """
    try:
        data = ops.show(module)
    except ops.Failure as e:
        raise _fail(e) from None
    if as_json:
        _dump(data)
        return
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        typer.echo(f"{key:<15} {value}")


@app.command()
def push(
    module: ModuleArg,
    tier: Annotated[Tier | None, typer.Option(help="The module's tier.")] = None,
    glyph: Annotated[str | None, typer.Option(help="Its icon.")] = None,
    label: Annotated[str | None, typer.Option(help="Text beside or instead of the icon.")] = None,
    count: Annotated[int | None, typer.Option(min=0, help="A count after the glyph.")] = None,
    detail: Annotated[str | None, typer.Option(help="A longer line for status and show.")] = None,
    target: Annotated[str | None, typer.Option(help="What a click acts on.")] = None,
    ttl: Annotated[
        str | None, typer.Option(help="How long the state holds (30s, 5m); then unavailable.")
    ] = None,
    source: Annotated[
        str | None, typer.Option(help="Who is pushing: the module's pusher ($BARCTL_SOURCE).")
    ] = None,
    from_json: Annotated[
        str | None,
        typer.Option("--json", help="`-`: read a whole state, segments included, from stdin."),
    ] = None,
) -> None:
    """Set a module's state: the only way another tool changes the bar.

    Given fields replace, others keep; --json - reads a whole state, segments included, from
    stdin. The module is redrawn only if what it shows changed. Exit 3 if the caller may not
    write that module, 5 for an unknown one.
    """
    args = [module]
    for key, value in (
        ("tier", tier.value if tier else None),
        ("glyph", glyph),
        ("label", label),
        ("count", None if count is None else str(count)),
        ("detail", detail),
        ("target", target),
        ("ttl", ttl),
        ("source", source),
        ("json", from_json),
    ):
        if value is not None:
            args.append(f"--{key}={value}")
    raise typer.Exit(fast.push(args))


@app.command()
def alert(
    module: ModuleArg,
    for_: Annotated[
        str, typer.Option("--for", help="How long: 30s, 1m; 0 stops the alert.")
    ] = "30s",
    segment: Annotated[str | None, typer.Option(help="Blink one segment only.")] = None,
) -> None:
    """Blink a module, or one segment, for a while.

    It blinks between its tier and urgent until the time is up (default 30s; --for 0 stops it).
    A second alert extends the first. Blinking needs the controller; without it, the module
    shows a steady urgent.
    """
    try:
        seconds = st.duration(for_)
    except ValueError as e:
        typer.echo(f"barctl alert: {e}", err=True)
        raise typer.Exit(2) from None
    try:
        typer.echo(ops.alert(module, seconds, segment))
    except ops.Failure as e:
        raise _fail(e) from None


@app.command()
def menu(module: ModuleArg) -> None:
    """Open a module's right-click menu.

    Its rows from modules.toml and the rows its source gives (the sinks, the players), drawn by
    barmenu (rofi) above the module.
    """
    try:
        ops.menu(module)
    except ops.Failure as e:
        raise _fail(e) from None


@app.command()
def click(
    module: ModuleArg,
    button: Annotated[Button, typer.Argument(help="left, middle, right, scroll-up, scroll-down.")],
    segment: Annotated[str | None, typer.Option(help="The segment clicked.")] = None,
) -> None:
    """Run what a click on a module does: every action tag calls this.

    The module's command for that button, with {target} filled in from its state (so a player
    click acts on the player the bar shows), started detached. `right` with no command of its
    own opens the module's menu.
    """
    try:
        ops.click(module, button.value, segment)
    except ops.Failure as e:
        raise _fail(e) from None


@app.command()
def reload(module: Annotated[str | None, typer.Argument(help="One module.")] = None) -> None:
    """Redraw every module, or one, without restarting polybar.

    Re-reads modules.toml (the controller too) and the theme roles, then pokes the modules.
    """
    try:
        ops.reload(module)
    except ops.Failure as e:
        raise _fail(e) from None


def _report(result: Any) -> None:
    for note in result.notes:
        typer.echo(f"barctl: {note}", err=True)
    for launch in result.dead:
        typer.echo(f"barctl: a bar exited on its config: {' '.join(launch.argv)}", err=True)
    if not result.ok:
        raise typer.Exit(1)


@app.command()
def restart(bar: Annotated[str | None, typer.Argument(help="One bar, by name.")] = None) -> None:
    """Restart the bars, or start one when none is running.

    Each bar restarts in place; one that froze or exited is relaunched from its own command
    line and environment. With no bar running, starts BAR ($POLYBAR_BAR, else main). Bars start
    with TOOL_STATS=skip.
    """
    _report(ops.restart(bar))


@app.command()
def theme() -> None:
    """Follow a new theme: what `theme apply` calls.

    Re-reads the theme roles, then restarts the bars, since polybar reads its ini colours only
    at start.
    """
    _report(ops.restart())


@app.command()
def enable(module: ModuleArg) -> None:
    """Show a module again and start its source.

    Remembered across logins.
    """
    try:
        ops.enable(module, True)
    except ops.Failure as e:
        raise _fail(e) from None


@app.command()
def disable(module: ModuleArg) -> None:
    """Blank a module and stop its source.

    Remembered across logins (a printer away for a month). The bar's layout isn't edited.
    """
    try:
        ops.enable(module, False)
    except ops.Failure as e:
        raise _fail(e) from None


def follow(
    names: list[str],
    as_json: bool,
    emit: Callable[[str], None],
    stop: Callable[[], bool],
    interval: float = 0.2,
) -> None:
    """Print each module's state when it changes, until stop() says so."""
    seen: dict[str, Any] = {}
    while True:
        current = set(names) if names else set(st.stored()) | set(seen)
        for name in sorted(current):
            data = st.read(name)
            if seen.get(name, ...) == data:
                continue
            seen[name] = data
            if as_json:
                emit(json.dumps({"module": name, "state": data}, ensure_ascii=False))
            else:
                d = data or {}
                text = " ".join(p for p in (str(d.get("glyph", "")), str(d.get("label", ""))) if p)
                stamp = time.strftime("%H:%M:%S")
                emit(f"{stamp} {name} {d.get('tier', 'gone') if data else 'gone'} {text}".rstrip())
        if stop():
            return
        time.sleep(interval)


@app.command()
def watch(
    modules: Annotated[list[str] | None, typer.Argument(help="Only these modules.")] = None,
    as_json: Json = False,
) -> None:
    """Follow state changes as they happen, until interrupted.

    One line (or JSON line) per change: for debugging, and for tools that want to react to the
    bar.
    """

    def emit(line: str) -> None:
        typer.echo(line)
        sys.stdout.flush()

    try:
        follow(list(modules or []), as_json, emit, lambda: False)
    except KeyboardInterrupt:
        raise typer.Exit(0) from None


@app.command("doctor")
def doctor_(as_json: Json = False) -> None:
    """Check everything barctl needs, each with a fix to try.

    One controller; every bar answering IPC, and its protocol version; the polybar config and
    modules.toml agreeing; each source's commands; the theme roles; the state folders; no stale
    or orphan states. Exit 1 on any problem.
    """
    found = doc.checks()
    if as_json:
        _dump(found)
    else:
        for c in found:
            fix = f"  (fix: {c['fix']})" if c["fix"] else ""
            typer.echo(f"{c['state']:<4} {c['name']}: {c['detail']}{fix}")
    raise typer.Exit(1 if doc.problems(found) else 0)


@app.command()
def run() -> None:
    """Run the controller (barctl.service runs it).

    One at a time; every enabled source, the control socket and the alert timers. Exits non-
    zero when a source can't be restarted, for systemd to restart it.
    """
    from desktop_tools.barctl.controller import AlreadyRunning, Controller

    try:
        controller = Controller()
    except mods.ConfigError as e:
        typer.echo(f"barctl: {e}", err=True)
        raise typer.Exit(4) from None
    try:
        code = controller.run()
    except AlreadyRunning as e:
        typer.echo(f"barctl: {e}", err=True)
        raise typer.Exit(1) from None
    raise typer.Exit(code)


@app.command()
def render(module: ModuleArg) -> None:
    """Print a module's text for polybar: its hook-0.

    Its state with colour and action tags, from the theme roles; an empty line, never an error,
    when anything is missing.
    """
    raise typer.Exit(fast.render([module]))


@app.command()
def hide() -> None:
    """Hide the bars (bsp-hide calls it)."""
    sent = ops.visibility(False)
    raise typer.Exit(0 if all(sent.values()) else 1)


@app.command()
def unhide() -> None:
    """Show the bars again (bsp-unhide calls it)."""
    sent = ops.visibility(True)
    raise typer.Exit(0 if all(sent.values()) else 1)

"""The `devices` command (record 0004 §4): the printer and the scanner, for the bar's menus and
clicks and for a terminal.

Every menu row and click runs this command, so the confirm, the words for each failure, the
notifications and the agent rule live here. Each action notifies its result in words
(`dunstify -a printer|scanner`) and exits 0, 1 (the device or CUPS refused; the words say why),
2 (usage) or 3 (an agent asked: the acting verbs refuse when COORDINATOR, CLAUDECODE or
TESSERA_ACTOR is set, §7; reading a variable is not setting it). Cancelling a job, cancelling
all and the test page ask Yes/No first, unless `--yes`; menu rows never pass it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from desktop_tools import devices
from desktop_tools.devices import cups, escl, ipp, mdns, notify, prefs, sane, scan

OK, FAILED, USAGE, AGENT = 0, 1, 2, 3
OWNER = "desktop-coordinator"
TEST_PAGE = Path("/usr/share/cups/data/default-testpage.pdf")
NOT_ALLOWED = "Not allowed: CUPS wants an administrator; use Printer settings"
NOT_RUNNING = "CUPS is not running"
VERBS = [
    "printer",
    "scanner",
    "scan",
    "status",
    "pause",
    "resume",
    "default",
    "cancel",
    "test-page",
    "find",
    "pick",
    "feeder",
    "duplex",
    "flatbed",
    "copy-last",
    "open-last",
    "set",
]

app = typer.Typer(
    name="devices",
    help="The printer and the scanner: status, the queue, pause and resume, scans (record 0004).",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
printer_app = typer.Typer(help="The default CUPS queue.", no_args_is_help=True)
scanner_app = typer.Typer(help="The scanner: its state and which one.", no_args_is_help=True)
scan_app = typer.Typer(
    help="Scan with the remembered preset: alone, from the feeder when the scanner says it is "
    "loaded, else the flatbed."
)
app.add_typer(printer_app, name="printer")
app.add_typer(scanner_app, name="scanner")
app.add_typer(scan_app, name="scan")

Yes = Annotated[bool, typer.Option("--yes", "-y", help="Don't ask first (tests, keybindings).")]
Json = Annotated[bool, typer.Option("--json", help="One JSON object.")]


def say(app_name: str, title: str, body: str = "", *, err: bool = False) -> None:
    """The result, in words: a notification and a line on the terminal."""
    notify.send(app_name, title, body)
    typer.echo(f"{title}: {body}" if body else title, err=err)


def refuse_agent(app_name: str) -> None:
    """Exit 3 for an agent (§7): the variables are read, never set or cleared."""
    if devices.agent() is not None:
        say(app_name, devices.REFUSED, "Restart the bar from a clean session.", err=True)
        raise typer.Exit(AGENT)


def ask(question: str, yes: bool, app_name: str) -> None:
    """The confirm (common/confirm.py), defaulting to No: exit 0 on No, 1 when unasked."""
    if yes:
        return
    from desktop_tools.common import confirm

    try:
        if confirm.confirm(
            question,
            prompt=app_name.capitalize(),
            settle=confirm.SETTLE,
            unshown=confirm.UNSHOWN,
            warn=lambda line: None,
            tell=lambda title, body: notify.send(app_name, title, body),
        ):
            return
    except confirm.Unasked:
        raise typer.Exit(FAILED) from None
    typer.echo("not done (No)")
    raise typer.Exit(OK)


def run(argv: Sequence[str]) -> tuple[int, str]:
    """A CUPS tool: (exit code, its stderr's last line). 127 when it is missing."""
    try:
        # S603: a fixed argument list; the queue and job come from cupsd's own answer or the
        # user's argument, never a shell string.
        done = subprocess.run(  # noqa: S603
            list(argv), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        return 127, f"{argv[0]} is not installed"
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, type(e).__name__
    lines = [line.strip() for line in done.stderr.splitlines() if line.strip()]
    return done.returncode, lines[-1] if lines else ""


def cups_words(said: str) -> str:
    low = said.lower()
    if any(w in low for w in ("not authorized", "forbidden", "unauthorized", "authentication")):
        return NOT_ALLOWED
    if any(w in low for w in ("connect", "not running", "scheduler")):
        return NOT_RUNNING
    return said or "CUPS refused"


def acted(app_name: str, argv: Sequence[str], done: str) -> None:
    code, said = run(argv)
    if code == 0:
        say(app_name, done)
        return
    say(app_name, "Not done", cups_words(said), err=True)
    raise typer.Exit(FAILED)


def reading() -> cups.Reading:
    try:
        return cups.read()
    except (cups.CupsDown, ipp.IppError):
        say("printer", NOT_RUNNING, err=True)
        raise typer.Exit(FAILED) from None


def default_queue(queue: str | None) -> str:
    if queue:
        return queue
    found = reading()
    if not found.default:
        say("printer", "No default printer", err=True)
        raise typer.Exit(FAILED)
    return found.default


# ---------------------------------------------------------------- printer


def printer_state(r: cups.Reading | None) -> dict[str, Any]:
    """`printer status --json`: counts, states and reason words; no URI, host or title."""
    q = r.queue if r is not None else None
    reachable = bool(q is None or not q.network or not q.host or mdns.probe(q.host))
    shown = cups.view(r, reachable=reachable)
    out: dict[str, Any] = {
        "tier": shown.tier,
        "label": shown.label,
        "detail": shown.detail,
        "jobs": [
            {"id": j.id, "state": j.word, "age": cups.age(j.created)} for j in (r.jobs if r else [])
        ],
    }
    if q is not None:
        out.update(
            queue=q.name,
            network=q.network,
            reachable=reachable,
            accepting=q.accepting,
            paused=q.state == cups.STOPPED,
            supplies=[{"name": m.word, "level": m.level} for m in q.markers],
        )
    out["lines"] = cups.words(r, reachable=reachable)
    return out


@printer_app.command("status")
def printer_status(
    as_json: Json = False,
    notify_: Annotated[bool, typer.Option("--notify", help="Also as a notification.")] = False,
) -> None:
    """The default queue's state: read-only, anyone may run it."""
    try:
        r: cups.Reading | None = cups.read()
    except (cups.CupsDown, ipp.IppError):
        r = None
    data = printer_state(r)
    if as_json:
        typer.echo(json.dumps(data, sort_keys=True))
    else:
        for line in data["lines"]:
            typer.echo(line)
    if notify_:
        notify.send("printer", "Printer", "\n".join(data["lines"]))
    raise typer.Exit(OK if r is not None else FAILED)


@printer_app.command("pause")
def pause(
    queue: Annotated[str | None, typer.Argument(help="The queue (default: the default).")] = None,
) -> None:
    """Pause printing on the queue (cupsdisable)."""
    refuse_agent("printer")
    acted("printer", ["cupsdisable", default_queue(queue)], "Printing paused")


@printer_app.command("resume")
def resume(
    queue: Annotated[str | None, typer.Argument(help="The queue (default: the default).")] = None,
) -> None:
    """Resume printing on the queue (cupsenable)."""
    refuse_agent("printer")
    acted("printer", ["cupsenable", default_queue(queue)], "Printing resumed")


@printer_app.command("default")
def default(queue: Annotated[str, typer.Argument(help="The queue to make your default.")]) -> None:
    """Make a queue your default (lpoptions -d: yours, not the system's)."""
    refuse_agent("printer")
    acted("printer", ["lpoptions", "-d", queue], f"Default printer: {queue}")


@printer_app.command("cancel")
def cancel(
    job: Annotated[int | None, typer.Argument(help="The job number.")] = None,
    all_: Annotated[bool, typer.Option("--all", help="Every job of yours on the queue.")] = False,
    yes: Yes = False,
) -> None:
    """Cancel a job, or all of yours on the default queue; asks first unless --yes."""
    refuse_agent("printer")
    if (job is None) == (not all_):
        typer.echo("devices: give a job number or --all", err=True)
        raise typer.Exit(USAGE)
    if job is not None:
        ask(f"Cancel job {job}?", yes, "printer")
        acted("printer", ["cancel", str(job)], f"Job {job} cancelled")
        return
    r = reading()
    mine = [j for j in r.jobs if j.user == ipp.username()]
    if not r.default or not mine:
        say("printer", "No jobs of yours to cancel")
        return
    ask(f"Cancel {len(mine)} job{'s' if len(mine) != 1 else ''}?", yes, "printer")
    acted("printer", ["cancel", "-u", ipp.username(), r.default], f"{len(mine)} jobs cancelled")


@printer_app.command("test-page")
def test_page(
    queue: Annotated[str | None, typer.Argument(help="The queue (default: the default).")] = None,
    yes: Yes = False,
) -> None:
    """Print CUPS's test page (it uses paper and ink); asks first unless --yes."""
    refuse_agent("printer")
    name = default_queue(queue)
    ask(f"Print a test page on {name}?", yes, "printer")
    acted("printer", ["lp", "-d", name, str(TEST_PAGE)], "Test page sent")


# ---------------------------------------------------------------- scanner


def scanner_state() -> dict[str, Any]:
    device = scan.scanner_name_only()
    found = next((s for s in sane.known() if s.device == device), None)
    model = found.model if found else (device.split(":")[-1] if device else "")
    base = escl.base_from_conf(sane.Scanner(device, model).instance) if device else ""
    status = escl.status(base) if base else None
    out: dict[str, Any] = {"scanner": model, "configured": bool(device)}
    if base:
        out.update(reachable=status is not None)
    if status is not None:
        out.update(state=status.state, feeder=status.feeder)
    return out


@scanner_app.command("status")
def scanner_status(as_json: Json = False) -> None:
    """The scanner's state (one eSCL status read when it has one): read-only, anyone."""
    data = scanner_state()
    if as_json:
        typer.echo(json.dumps(data, sort_keys=True))
        return
    if not data["configured"]:
        typer.echo("No scanner found yet (devices scanner find)")
        return
    typer.echo(f"Scanner: {data['scanner']}")
    if "reachable" in data:
        typer.echo(f"Reachable: {'yes' if data['reachable'] else 'no'}")
    if data.get("state"):
        typer.echo(
            f"State: {data['state']}" + (f", feeder {data['feeder']}" if data.get("feeder") else "")
        )


@scanner_app.command("find")
def find() -> None:
    """Look for scanners (scanimage -L, up to 15 s) and say what was found."""
    found = sane.find()
    if found is None:
        say("scanner", "SANE is not installed", err=True)
        raise typer.Exit(FAILED)
    if not found:
        say("scanner", "No scanner found")
        return
    names = ", ".join(s.model for s in found)
    say("scanner", f"Found {len(found)} scanner{'s' if len(found) != 1 else ''}", names)


@scanner_app.command("pick")
def pick(device: Annotated[str, typer.Argument(help="A SANE device name (scanimage -L).")]) -> None:
    """Use this scanner from now on (the menu's choice; DESKTOP_TOOLS_SCANNER wins)."""
    prefs.remember(device=device)
    typer.echo("ok")


# ---------------------------------------------------------------- scan


def clipboard(path: Path) -> bool:
    try:
        # S607: xclip from PATH with fixed options; it serves the selection itself.
        subprocess.run(
            ["xclip", "-selection", "clipboard"],  # noqa: S607
            input=str(path),
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def open_path(path: Path) -> None:
    from desktop_tools.common import procs

    try:
        procs.detach(["xdg-open", str(path)])
    except OSError:
        say("scanner", "Couldn't open it: xdg-open is missing", err=True)


def do_scan(kind: str, preset: str | None, fmt: str | None, to: Path | None) -> None:
    refuse_agent("scanner")
    try:
        job = scan.plan(kind, preset_name=preset, fmt=fmt, folder=to)
        result = scan.run(job)
    except scan.ScanError as e:
        say("scanner", "Scan not saved" if not e.usage else "Can't scan", str(e), err=True)
        raise typer.Exit(USAGE if e.usage else FAILED) from None
    copied = clipboard(result.path)
    body = scan.describe(result) + (". Path copied." if copied else ".")
    title = "Scan saved"
    if result.failure:
        title, body = "Scan partly saved", f"{result.failure}. {body}"
    typer.echo(f"{title}: {body}")
    picked = notify.ask("scanner", title, body, [("open", "Open"), ("folder", "Show folder")])
    if picked == "open":
        open_path(result.path)
    elif picked == "folder":
        open_path(result.folder)
    if result.failure:
        raise typer.Exit(FAILED)


Preset = Annotated[
    str | None, typer.Option("--preset", help="A preset's name (Document, Photo, …).")
]
Format = Annotated[str | None, typer.Option("--format", help="pdf, png or jpeg.")]
To = Annotated[Path | None, typer.Option("--to", help="The folder to save in.")]


@scan_app.callback(invoke_without_command=True)
def scan_auto(ctx: typer.Context) -> None:
    """Alone: the remembered preset, from the feeder when the scanner says it is loaded, else
    the flatbed (the scanner module's left-click)."""
    if ctx.invoked_subcommand is not None:
        return
    do_scan(scan.auto_kind(), None, None, None)


@scan_app.command("feeder")
def feeder(preset: Preset = None, fmt: Format = None, to: To = None) -> None:
    """Scan every page in the document feeder."""
    do_scan("feeder", preset, fmt, to)


@scan_app.command("duplex")
def duplex(preset: Preset = None, fmt: Format = None, to: To = None) -> None:
    """Scan every page in the feeder, both sides (a scanner with a duplex feeder)."""
    do_scan("duplex", preset, fmt, to)


@scan_app.command("flatbed")
def flatbed(preset: Preset = None, fmt: Format = None, to: To = None) -> None:
    """Scan one page from the flatbed."""
    do_scan("flatbed", preset, fmt, to)


@scan_app.command("copy-last")
def copy_last() -> None:
    """Copy the last scan's path (this session) to the clipboard."""
    found = scan.last()
    if found is None:
        say("scanner", "No scan yet this session", err=True)
        raise typer.Exit(FAILED)
    if clipboard(found):
        say("scanner", "Path copied", found.name)


@scan_app.command("open-last")
def open_last() -> None:
    """Open the last scan (this session)."""
    found = scan.last()
    if found is None:
        say("scanner", "No scan yet this session", err=True)
        raise typer.Exit(FAILED)
    open_path(found)


@scan_app.command("set")
def set_(
    preset: Preset = None,
    fmt: Format = None,
    to: To = None,
    choose: Annotated[bool, typer.Option("--choose", help="Pick the folder (zenity).")] = False,
) -> None:
    """Remember a preset, a format or a folder for the next scans (the menus' pickers)."""
    if preset is not None and prefs.preset(preset) is None:
        typer.echo(f"devices: no preset {preset!r}", err=True)
        raise typer.Exit(USAGE)
    if fmt is not None and fmt not in prefs.FORMATS:
        typer.echo(f"devices: not a format: {fmt} (pdf, png or jpeg)", err=True)
        raise typer.Exit(USAGE)
    folder = str(to.expanduser().resolve()) if to is not None else None
    if choose:
        code, picked = pick_folder()
        if code != 0 or not picked:
            raise typer.Exit(OK)  # closed: nothing changes
        folder = picked
    found = prefs.preset(preset) if preset else None
    prefs.remember(preset=found.name if found else None, format=fmt, folder=folder)
    typer.echo("ok")


def pick_folder() -> tuple[int, str]:
    try:
        # S607: zenity from PATH with fixed options.
        done = subprocess.run(
            ["zenity", "--file-selection", "--directory", "--title=Save scans in"],  # noqa: S607
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return 127, ""
    return done.returncode, done.stdout.strip()


# ---------------------------------------------------------------- main


def _verb(argv: list[str]) -> str | None:
    words = [a for a in argv if not a.startswith("-")]
    return words[1] if len(words) > 1 and words[1] in VERBS else (words[0] if words else None)


def run_app(argv: list[str]) -> int:
    def go() -> int:
        try:
            app(args=argv, prog_name="devices", standalone_mode=True)
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return 0  # pragma: no cover - standalone_mode always exits

    if not argv or {"-h", "--help"} & set(argv):
        return go()
    from desktop_tools.common import journal

    return journal.run(go, tool="devices", owner=OWNER, commands=VERBS, command_of=_verb)


def main() -> None:
    raise SystemExit(run_app(sys.argv[1:]))

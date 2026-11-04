"""crew's lifecycle verbs: launch, stop, restart and stop --all (brain record 0019 §3a, §7).

Each goes only through `meta <name> launch|stop|restart` (`metacall.run`). crew keeps none of
meta's rules: who may start or stop, the brain coordinator, the resume notes and the old names
are meta's, so crew passes meta's exit code and its one-line reason on to the notification and
to its own exit status, and second-guesses nothing. `crew stopped` (the stop script's desktop
tidy) is `switch.stopped`, unchanged.

- `launch <name> [--show]`: starts it hidden; `--show` then shows it docked (its window attaches
  to the session). Already running (meta's exit 3, with its session there) is shown with --show.
- `stop <name> [--force]`: meta judges the resume notes; --force ends it anyway, with a reason.
- `restart <name>`: meta stops and launches it; if it was shown, crew shows it again once the old
  window has closed (coord's Restart, "was shown" branch). If it was hidden, it stays hidden.
- `stop --all [--yes]`: every running coordinator but the brain coordinator. Each is checked with
  `meta <name> stop --check`; if any is not clean, crew asks once (a rofi Yes/No, or --yes),
  then stops the clean ones plainly and the others with --force. One that meta refuses doesn't
  stop the rest. As coord's "Stop all", less the brain, which meta never stops for crew.
"""

from __future__ import annotations

import shutil
import subprocess

from desktop_tools.common import paths
from desktop_tools.crew import log, metacall, switch, tmux, wm
from desktop_tools.crew.registry import Coordinator, Registry, valid_name

OK, FAILED, USAGE = 0, 1, 2
BRAIN = "brain"  # the one meta never stops for crew (record 0019 §3a): left out of stop --all
CONFIRM_THEME = "prompt"  # coord's confirm theme, ~/.config/rofi/themes/prompt.rasi
FORCED = "Stephen: crew stop --force"
ALL_YES = "Stephen: Yes to stop all anyway"
ALL_FLAG = "Stephen: crew stop --all --yes"


def _known(reg: Registry, name: str) -> Coordinator | None:
    if not valid_name(name):
        log.error(f"invalid coordinator name: {name!r}")
        return None
    c = reg.get(name)
    if c is None:
        log.error(f"no coordinator {name!r} (crew names lists them)")
    return c


def _failed(c: Coordinator, what: str, done: metacall.Result) -> int:
    """meta said no, or couldn't be run: the notification says why, crew exits with its code."""
    switch.alert(f"{c.name}: {what}", f"meta {c.name} exited {done.code}: {done.why}")
    return done.code


def _running(c: Coordinator, sessions: set[str]) -> bool:
    return any(s in sessions for s in c.sessions)


def confirm(question: str) -> bool:
    """Yes only on an explicit Yes, as coord's: No is selected, so Return on open, Escape, or
    rofi missing or failing all mean No."""
    if shutil.which("rofi") is None:
        log.error(f"cannot ask ({question}): rofi is not on PATH")
        return False
    theme = paths.config_home() / "rofi" / "themes" / f"{CONFIRM_THEME}.rasi"
    argv = ["rofi", "-dmenu", "-i", "-no-custom", "-format", "s", "-selected-row", "1"]
    argv += ["-theme", str(theme)] if theme.is_file() else []
    try:
        # S603/S607: rofi with crew's fixed options; it blocks until answered.
        done = subprocess.run(  # noqa: S603
            [*argv, "-p", question],
            input="Yes\nNo\n",
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        log.error(f"cannot ask ({question}): {e.strerror}")
        return False
    return done.returncode == 0 and done.stdout.strip() == "Yes"


# ---------------------------------------------------------------- one coordinator


def launch(reg: Registry, name: str, *, showing: bool = False) -> int:
    """`meta <name> launch`; with showing, then show it docked."""
    c = _known(reg, name)
    if c is None:
        return USAGE
    done = metacall.run(c.name, "launch")
    if showing and (done.ok or (done.code == 3 and _running(c, tmux.sessions()))):
        return switch.summon(reg, c.name)
    if not done.ok:
        return _failed(c, "not started", done)
    switch.refresh(reg)
    return OK


def stop(reg: Registry, name: str, *, force: bool = False) -> int:
    """`meta <name> stop`, or with force `--force --reason`: meta judges and ends it."""
    c = _known(reg, name)
    if c is None:
        return USAGE
    done = metacall.run(c.name, "stop", *(("--force", "--reason", FORCED) if force else ()))
    if not done.ok:
        return _failed(c, "not stopped", done)
    switch.refresh(reg)
    return OK


def restart(reg: Registry, name: str) -> int:
    """`meta <name> restart`, then shown again if it was shown. No lock is held across meta:
    the stop script's desktop tidy (`crew stopped`) takes the switch lock itself."""
    c = _known(reg, name)
    if c is None:
        return USAGE
    win = switch.find(wm.look(), reg, c.name)
    shown = win is not None and not win.hidden
    done = metacall.run(c.name, "restart")
    if not done.ok:
        return _failed(c, "not restarted", done)
    if not shown:
        switch.refresh(reg)
        return OK
    # The tidy has waited for the old window; this covers a tidy that couldn't run, so the old
    # window is never re-shown.
    still = switch.wait_gone(reg, [c.name])
    if still is not None:
        log.error(f"{still}: window still open, not shown again")
        return FAILED
    return switch.summon(reg, c.name)


# ---------------------------------------------------------------- all of them


def stop_all(reg: Registry, *, yes: bool = False) -> int:
    """Stop every running coordinator but the brain coordinator, asking once if any is not
    clean. Declined: 1, nothing stopped. Else 0, or the exit code of the first that failed."""
    sessions = tmux.sessions()
    targets = [c for c in reg.coordinators if c.name != BRAIN and _running(c, sessions)]
    if not targets:
        log.info("no coordinator is running (but the brain coordinator)")
        return OK
    unclean: dict[str, str] = {}
    for c in targets:
        check = metacall.run(c.name, "stop", "--check")
        if not check.ok:
            unclean[c.name] = check.why or f"its check exited {check.code}"
    if unclean and not yes:
        if len(unclean) == 1:
            ((only, why),) = unclean.items()
            question = f"{only}: {why}"
        else:
            question = f"notes not clean for {', '.join(unclean)}"
        if not confirm(f"{question}: stop all anyway?"):
            log.info("stop all: declined, nothing stopped")
            return FAILED
    code = OK
    for c in targets:
        forced = ("--force", "--reason", ALL_FLAG if yes else ALL_YES) if c.name in unclean else ()
        done = metacall.run(c.name, "stop", *forced)
        if not done.ok:
            failed = _failed(c, "not stopped", done)
            code = code or failed
    switch.refresh(reg)
    return code

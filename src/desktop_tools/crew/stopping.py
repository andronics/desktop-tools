"""Stopping and restarting from crew's menus, through `meta` (brain record 0019 §3a, §7a), and
the Yes/No question they ask, ported from coord's `_coord-end-asking` and `coord stop --all`.

Whether a coordinator may stop is the brain's stop script's call, behind `meta <name> stop`: it
judges the resume notes and exits 0 (stopped, or not running), 1 (notes not clean, nothing
ended), 3 (not its to end) or 4 (the kill failed). Notes that aren't clean are asked about
again with the script's reason, and Yes reruns with `--force --reason`. The brain coordinator is
always asked about, clean or not: it is ended only by Stephen.

The question is a rofi Yes/No in the `prompt` theme with No selected, so Return on open, Escape
or rofi failing all mean No.
"""

from __future__ import annotations

import re

from desktop_tools.crew import conf, items, switch, tmux
from desktop_tools.crew.registry import Coordinator, Registry

BRAIN = "brain"
DECLINED = -1  # Stephen said No: a menu goes back a level instead of closing
NOT_CLEAN = 1
WHY = re.compile(r' why=("((?:[^"\\]|\\.)*)"|(\S*))')


def theme(name: str) -> list[str]:
    from desktop_tools.barmenu import menus as bm

    return bm.theme_args(name)


def confirm(question: str) -> bool:
    """True only on an explicit Yes."""
    from desktop_tools.barmenu import menus as bm

    args = ["-i", "-no-custom", "-format", "s", "-selected-row", "1"]
    picked = bm.pick(["Yes", "No"], [*args, *theme(conf.confirm_theme()), "-p", question])
    return picked == "Yes"


def why(output: str, name: str) -> str:
    """The reason in the stop script's output: its last line, a stop.log line whose why="..."
    is taken, or a sentence ("<name>: <why>"), less the leading "<name>: "."""
    lines = [line for line in output.splitlines() if line.strip()]
    last = lines[-1].strip() if lines else ""
    last = last.removeprefix(f"{name}: ")
    m = WHY.search(last)
    if m is None:
        return last
    if m.group(2) is not None:
        return m.group(2).replace('\\"', '"').replace("\\\\", "\\")
    return m.group(3)


def _said(done: object) -> str:
    out = getattr(done, "stdout", "") or ""
    err = getattr(done, "stderr", "") or ""
    return "\n".join(t for t in (out.strip(), err.strip()) if t)


def check(name: str) -> tuple[bool, str]:
    """(clean, why not): `meta <name> stop --check`, which ends nothing."""
    done = items.meta([name, "stop", "--check"])
    return done.returncode == 0, why(_said(done), name)


def running(c: Coordinator, sessions: set[str] | None = None) -> bool:
    sessions = tmux.sessions() if sessions is None else sessions
    return any(s in sessions for s in c.sessions)


def _end(c: Coordinator, verb: str, reason: str = "", *, asking: bool = True) -> int:
    """`meta <name> stop|restart`, forced with the reason if one is given. Not clean and
    asking: asked again with the reason, and Yes forces it."""
    args = [c.name, verb] + (["--force", "--reason", reason] if reason else [])
    done = items.meta(args)
    said = _said(done)
    if done.returncode == 0:
        items.notify_lines(f"{c.name}: {'restarted' if verb == 'restart' else 'stopped'}", said)
        return switch.OK
    because = why(said, c.name)
    if done.returncode == NOT_CLEAN and asking and not reason:
        if not confirm(f"{c.name}: {because}: {verb} anyway?"):
            return DECLINED
        return _end(c, verb, f"Stephen: Yes to {verb} anyway", asking=False)
    if done.returncode in (NOT_CLEAN, 3):
        switch.alert(f"{c.name}: not {'restarted' if verb == 'restart' else 'stopped'}", because)
    else:
        switch.alert(f"{c.name}: {verb} failed (exit {done.returncode})", because or "-")
    return switch.FAILED


def end(c: Coordinator, verb: str, *, ask_first: bool) -> int:
    """Stop or restart one coordinator for a menu: 0 done, 1 failed (notified), DECLINED.
    `ask_first` is the item's own Yes/No (the quick menu's confirm); the brain is always asked,
    with its notes' state in the question."""
    if c.name == BRAIN:
        clean, because = check(BRAIN)
        if clean:
            if not confirm(f"the brain coordinator: {verb} it?"):
                return DECLINED
            return _end(c, verb)
        if not confirm(f"the brain coordinator: {because}: {verb} it anyway?"):
            return DECLINED
        return _end(c, verb, f"Stephen: Yes to {verb} the brain coordinator anyway")
    if ask_first and not confirm(f"{c.name}: {verb} it?"):
        return DECLINED
    return _end(c, verb)


def stop_all(reg: Registry) -> int:
    """Stop every running coordinator, the brain last (the one that would notice the others
    going): each is checked first, and one question names those whose notes aren't clean (and
    the brain, always); Yes stops them all, forcing the unclean ones.

    This is the menu's one seam for "Stop all": once `crew stop --all` lands on main, this
    function calls it instead."""
    sessions = tmux.sessions()
    order = [c for c in reg.coordinators if c.name != BRAIN]
    order += [c for c in reg.coordinators if c.name == BRAIN]
    targets = [c for c in order if running(c, sessions)]
    if not targets:
        switch.notify("no coordinator is running", "nothing to stop", "-t", "1500")
        return switch.OK
    unclean: dict[str, str] = {}
    for c in targets:
        clean, because = check(c.name)
        if not clean:
            unclean[c.name] = because
    question = ""
    if len(unclean) == 1:
        name, because = next(iter(unclean.items()))
        question = f"{name}: {because}"
    elif unclean:
        question = f"notes not clean for {', '.join(unclean)}"
    if any(c.name == BRAIN for c in targets):
        question = f"{question}; the brain coordinator too" if question else "the brain coordinator"
    if question and not confirm(f"{question}: stop all anyway?"):
        return DECLINED
    failed = False
    for c in targets:
        reason = "Stephen: Yes to stop all anyway" if c.name in unclean else ""
        if _end(c, "stop", reason, asking=False) != switch.OK:
            failed = True
    return switch.FAILED if failed else switch.OK

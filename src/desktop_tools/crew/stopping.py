"""Launch, stop and restart from crew's menus (brain record 0019 §7a items 2 to 4), on crew's
lifecycle verbs (`life`) and its one meta caller (`metacall`).

What the menus add to `life` is the asking, ported from coord's `_coord-end-asking`:

- Stop and Restart from the quick menu ask Yes/No first (meta's `confirm`); the full menu's, as
  coord's, ask only when needed.
- The resume notes are judged first (`meta <name> stop --check`). Not clean: asked again with the
  stop script's reason, and Yes forces it (`--force --reason`), as coord's Stop all does.
- A coordinator only Stephen ends (the registry's `ended_by`, `Coordinator.stephen_only`: the
  brain coordinator, the arbiter) is always asked about, clean or not, and only on that Yes does
  crew add `--confirmed` to its stop or restart: meta ends it only when Stephen confirmed it and
  the caller is no coordinator or agent (meta's own check, on the caller's environment, which
  crew passes on untouched). Never for any other coordinator.

Stop all is `life.stop_all`. The questions are `life.confirm`: rofi's `prompt` theme, No selected.
"""

from __future__ import annotations

from desktop_tools.crew import items, life, metacall, switch
from desktop_tools.crew.registry import Coordinator, Registry

DECLINED = -1  # Stephen said No: a menu goes back a level instead of closing
NOT_CLEAN = 1
DONE = {"launch": "launched", "stop": "stopped", "restart": "restarted"}


def confirm(question: str) -> bool:
    return life.confirm(question)


def check(name: str) -> metacall.Result:
    """`meta <name> stop --check`, which ends nothing: 0 clean, 1 not (with why)."""
    return metacall.run(name, "stop", "--check")


def _plain(reg: Registry, c: Coordinator, verb: str, *, confirmed: bool = False) -> int:
    """`confirmed`: Stephen said Yes to ending one only he ends (`--confirmed`)."""
    if verb == "launch":
        code = life.launch(reg, c.name)
    elif verb == "stop":
        code = life.stop(reg, c.name, confirmed=confirmed)
    else:
        code = life.restart(reg, c.name, confirmed=confirmed)
    if code == switch.OK:
        items.notify_lines(f"{c.name}: {DONE[verb]}", "done")
    return code


def _forced(reg: Registry, c: Coordinator, verb: str, reason: str) -> int:
    """Ended anyway, on Stephen's Yes: meta's stop or restart with `--force` and his reason
    (`life.stop` forces with its own reason, and a forced restart has no `life` verb)."""
    confirmed = ("--confirmed",) if c.stephen_only else ()  # reached only after Stephen's Yes
    done = metacall.run(c.name, verb, "--force", "--reason", reason, *confirmed)
    if not done.ok:
        switch.alert(
            f"{c.name}: not {DONE[verb]}", f"meta {c.name} {metacall.exited(done.code)}: {done.why}"
        )
        return done.code
    switch.refresh(reg)
    items.notify_lines(f"{c.name}: {DONE[verb]}", "done, notes not clean")
    return switch.OK


def end(reg: Registry, c: Coordinator, verb: str, *, ask_first: bool) -> int:
    """Launch, stop or restart one coordinator for a menu: 0 done, else meta's code (notified),
    or DECLINED. `ask_first` is the item's own Yes/No."""
    if verb == "launch":
        return _plain(reg, c, verb)
    only = c.stephen_only
    who = f"the {c.name} coordinator"
    if ask_first and not only and not confirm(f"{c.name}: {verb} it?"):
        return DECLINED
    judged = check(c.name)
    if judged.ok or judged.code != NOT_CLEAN:
        # Clean, or the check itself failed: the plain verb says what meta thinks.
        if only and not confirm(f"{who}: {verb} it?"):
            return DECLINED
        return _plain(reg, c, verb, confirmed=only)
    if not confirm(
        f"{who if only else c.name}: {judged.why}: {verb} {'it ' if only else ''}anyway?"
    ):
        return DECLINED
    reason = f"Stephen: Yes to {verb} {who + ' ' if only else ''}anyway"
    return _forced(reg, c, verb, reason)


def stop_all(reg: Registry) -> int:
    """The full menu's Stop all: `life.stop_all`, which asks once if any is not clean."""
    return life.stop_all(reg)

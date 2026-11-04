"""Launch, stop and restart from crew's menus (brain record 0019 §7a items 2 to 4), on crew's
lifecycle verbs (`life`) and its one meta caller (`metacall`).

What the menus add to `life` is the asking, ported from coord's `_coord-end-asking`:

- Stop and Restart from the quick menu ask Yes/No first (meta's `confirm`); the full menu's, as
  coord's, ask only when needed.
- The resume notes are judged first (`meta <name> stop --check`). Not clean: asked again with the
  stop script's reason, and Yes forces it (`--force --reason`), as coord's Stop all does.
- The brain coordinator is always asked about, clean or not.

Stop all is `life.stop_all`. The questions are `life.confirm`: rofi's `prompt` theme, No selected.
"""

from __future__ import annotations

from desktop_tools.crew import items, life, metacall, switch
from desktop_tools.crew.registry import Coordinator, Registry

BRAIN = "brain"
DECLINED = -1  # Stephen said No: a menu goes back a level instead of closing
NOT_CLEAN = 1
DONE = {"launch": "launched", "stop": "stopped", "restart": "restarted"}


def confirm(question: str) -> bool:
    return life.confirm(question)


def check(name: str) -> metacall.Result:
    """`meta <name> stop --check`, which ends nothing: 0 clean, 1 not (with why)."""
    return metacall.run(name, "stop", "--check")


def _plain(reg: Registry, c: Coordinator, verb: str) -> int:
    code = {"launch": life.launch, "stop": life.stop, "restart": life.restart}[verb](reg, c.name)
    if code == switch.OK:
        items.notify_lines(f"{c.name}: {DONE[verb]}", "done")
    return code


def _forced(reg: Registry, c: Coordinator, verb: str, reason: str) -> int:
    """Ended anyway, on Stephen's Yes. `life.stop` forces with its own reason; a forced restart
    has no `life` verb, so it is meta's restart with --force."""
    if verb == "stop":
        done = metacall.run(c.name, "stop", "--force", "--reason", reason)
    else:
        done = metacall.run(c.name, "restart", "--force", "--reason", reason)
    if not done.ok:
        switch.alert(f"{c.name}: not {DONE[verb]}", f"meta {c.name} exited {done.code}: {done.why}")
        return done.code
    switch.refresh(reg)
    items.notify_lines(f"{c.name}: {DONE[verb]}", "done, notes not clean")
    return switch.OK


def end(reg: Registry, c: Coordinator, verb: str, *, ask_first: bool) -> int:
    """Launch, stop or restart one coordinator for a menu: 0 done, else meta's code (notified),
    or DECLINED. `ask_first` is the item's own Yes/No."""
    if verb == "launch":
        return _plain(reg, c, verb)
    brain = c.name == BRAIN
    if ask_first and not brain and not confirm(f"{c.name}: {verb} it?"):
        return DECLINED
    judged = check(c.name)
    if judged.ok or judged.code != NOT_CLEAN:
        # Clean, or the check itself failed: the plain verb says what meta thinks.
        if brain and not confirm(f"the brain coordinator: {verb} it?"):
            return DECLINED
        return _plain(reg, c, verb)
    who = "the brain coordinator" if brain else c.name
    if not confirm(f"{who}: {judged.why}: {verb} {'it ' if brain else ''}anyway?"):
        return DECLINED
    reason = f"Stephen: Yes to {verb} {'the brain coordinator ' if brain else ''}anyway"
    return _forced(reg, c, verb, reason)


def stop_all(reg: Registry) -> int:
    """The full menu's Stop all: `life.stop_all`, which asks once if any is not clean."""
    return life.stop_all(reg)

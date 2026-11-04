"""The fast path: `crew status` and `crew bar` with the standard library only, before Typer is
imported (dotfiles record 0003 §A1). Nine Claude hooks run `status` on every prompt, tool and
stop, and each state change refreshes the strip with `bar`, so neither pays Typer's start-up nor
writes a run record; their errors still go to the journal, rate-limited by the helper.

`-h`/`--help` never comes here: cli.main hands those to Typer, which prints the help.
"""

from __future__ import annotations

import sys

USAGE_BAR = "usage: crew bar [--quiet]"


def bar(args: list[str]) -> int:
    """Push the strip to barctl and print the line barctl renders for it (nothing with
    --quiet, as the refreshes crew starts itself use)."""
    if any(a != "--quiet" for a in args):
        sys.stderr.write(USAGE_BAR + "\n")
        return 2
    from desktop_tools.crew import registry, strip, switch

    reg = registry.load(refresh=False)
    ok = strip.push(reg)
    if "--quiet" not in args:
        switch.say(strip.line())
    return 0 if ok else 1


def status(args: list[str]) -> int:
    from desktop_tools.crew import hook, log

    try:
        return hook.run(args[:1])
    except Exception as e:
        # A hook must never fail Claude's turn: log it for the owner and carry on.
        log.error(f"status: {type(e).__name__}: {e}")
        return 0


def main(args: list[str]) -> int:
    verb, rest = args[0], args[1:]
    return status(rest) if verb == "status" else bar(rest)

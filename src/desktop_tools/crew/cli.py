"""The `crew` command.

`status` and `bar` are handled here before Typer is imported, with the standard library only,
unless `-h` or `--help` is among their arguments (dotfiles record 0003 §A1). Every other verb
goes to the Typer app, wrapped in the journal helper: one run record per run (brain record 0017),
except for `--help`, which runs nothing, and `guard` and `notify`, which crew starts itself.
"""

from __future__ import annotations

import os
import sys

FAST = frozenset({"status", "bar"})
HELP = frozenset({"-h", "--help"})
VERBS = [
    "toggle",
    "show",
    "hide",
    "cycle",
    "width",
    "side",
    "guard",
    "status",
    "bar",
    "list",
    "names",
    "stopped",
    "notify",
]
QUIET = frozenset({"guard", "notify"})  # started by crew itself: no run record of their own
OWNER = "desktop-coordinator"
RESULTS = (0,)


def _verb(argv: list[str]) -> str | None:
    return next((a for a in argv if not a.startswith("-")), None)


def run_app(argv: list[str], prog: str = "crew") -> int:
    from desktop_tools.crew.app import app

    def main() -> int:
        try:
            app(args=argv, prog_name=prog, standalone_mode=True)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            if code == 2:
                from desktop_tools.common import journal

                journal.warning("usage error")
            return code
        return 0  # pragma: no cover - standalone_mode always exits

    if HELP & set(argv) or not argv:
        return main()
    from desktop_tools.common import journal

    saved = os.environ.get("TOOL_STATS")
    if _verb(argv) in QUIET:
        os.environ["TOOL_STATS"] = "skip"
    try:
        return journal.run(
            main, tool=prog, owner=OWNER, results=RESULTS, commands=VERBS, command_of=_verb
        )
    finally:
        if saved is None:
            os.environ.pop("TOOL_STATS", None)
        else:
            os.environ["TOOL_STATS"] = saved


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] in FAST and not HELP & set(argv):
        from desktop_tools.crew import fast

        raise SystemExit(fast.main(argv))
    raise SystemExit(run_app(argv))

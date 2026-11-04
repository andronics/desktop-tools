"""The `barctl` command.

`render` and `push` are handled here before Typer is imported, with the standard library only,
unless `-h` or `--help` is among their arguments (dotfiles record 0003 §A1). Every other verb
goes to the Typer app, wrapped in the journal helper: one run record per run (record 0017), except
for `--help`, which runs nothing, and `click`, which always counts, even under polybar's
TOOL_STATS=skip (§A8).
"""

from __future__ import annotations

import os
import sys

FAST = frozenset({"render", "push"})
HELP = frozenset({"-h", "--help"})
VERBS = [
    "status",
    "list",
    "show",
    "push",
    "alert",
    "menu",
    "click",
    "reload",
    "restart",
    "theme",
    "enable",
    "disable",
    "watch",
    "doctor",
    "run",
    "render",
    "hide",
    "unhide",
]
OWNER = "desktop-coordinator"
RESULTS = (0, 1, 5)  # the meta codes that are answers (brain record 0019)


def _verb(argv: list[str]) -> str | None:
    return next((a for a in argv if not a.startswith("-")), None)


def run_app(argv: list[str], prog: str = "barctl") -> int:
    from desktop_tools.barctl.app import app

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
    if _verb(argv) == "click":
        os.environ.pop("TOOL_STATS", None)
    try:
        return journal.run(
            main, tool=prog, owner=OWNER, results=RESULTS, commands=VERBS, command_of=_verb
        )
    finally:
        if saved is not None:
            os.environ["TOOL_STATS"] = saved


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] in FAST and not HELP & set(argv):
        from desktop_tools.barctl import fast

        raise SystemExit(fast.main(argv))
    raise SystemExit(run_app(argv))

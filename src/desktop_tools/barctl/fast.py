"""The fast path: `barctl render` and `barctl push` with the standard library only, before Typer is
imported (dotfiles record 0003 §A1). `render` runs on every poke of a module and `push` on every
Claude hook through crew, so neither pays Typer's 30 to 95 ms, and neither writes a run record
(§A8); their errors still go to the journal, rate-limited by the helper.

`-h`/`--help` never comes here: cli.main hands those to Typer, which prints the help.
"""

from __future__ import annotations

import sys
from typing import Any

USAGE_RENDER = "usage: barctl render <module>"
USAGE_PUSH = (
    "usage: barctl push <module> [--tier T] [--glyph G] [--label L] [--count N] [--detail D]"
    " [--target X] [--ttl D] [--source NAME] [--json -]"
)
PUSH_TEXT = ("tier", "glyph", "label", "detail", "target")


def _log_error(message: str) -> None:
    from desktop_tools.common import journal

    journal.setup("barctl", "desktop-coordinator", results=(0, 1, 5), argv=sys.argv[1:])
    journal.error(message)


def render(args: list[str]) -> int:
    """Print the module's line; an empty line, never an error, when anything is missing."""
    if len(args) != 1:
        sys.stderr.write(USAGE_RENDER + "\n")
        sys.stdout.write("\n")
        return 2
    from desktop_tools.barctl import modules as mods
    from desktop_tools.barctl import render as rd
    from desktop_tools.barctl import state as st

    name = args[0]
    if not mods.valid_name(name):
        sys.stderr.write(f"barctl: not a module name: {name!r}\n")
        sys.stdout.write("\n")
        return 2
    line = ""
    try:
        found = mods.load().get(name)
        if found is not None:
            line = rd.render(found, st.read(name), disabled=name in st.disabled())
    except Exception as e:
        _log_error(f"render {name}: {type(e).__name__}: {e}")
        line = ""
    sys.stdout.write(line + "\n")
    return 0


def parse_push(
    args: list[str],
) -> tuple[str, dict[str, Any], dict[str, Any] | None, float | None, str | None]:
    """(module, fields, whole state from stdin, ttl, source). Raises ValueError on bad usage."""
    import json

    from desktop_tools.barctl import state as st

    if not args or args[0].startswith("-"):
        raise ValueError("push needs a module")
    module, rest = args[0], args[1:]
    fields: dict[str, Any] = {}
    whole: dict[str, Any] | None = None
    ttl: float | None = None
    source: str | None = None
    i = 0
    while i < len(rest):
        token = rest[i]
        if not token.startswith("--"):
            raise ValueError(f"unexpected argument {token!r}")
        key, eq, value = token[2:].partition("=")
        if not eq:
            if i + 1 >= len(rest):
                raise ValueError(f"--{key} needs a value")
            value = rest[i + 1]
            i += 1
        i += 1
        if key in PUSH_TEXT:
            fields[key] = value
        elif key == "count":
            if not value.isdigit():
                raise ValueError("--count is a whole number, 0 or more")
            fields["count"] = int(value)
        elif key == "ttl":
            ttl = st.duration(value)
        elif key == "source":
            source = value
        elif key == "json":
            if value != "-":
                raise ValueError("--json takes - (the state on stdin)")
            data = json.loads(sys.stdin.read() or "{}")
            if not isinstance(data, dict):
                raise ValueError("the state on stdin must be a JSON object")
            whole = data
        else:
            raise ValueError(f"no such option: --{key}")
    return module, fields, whole, ttl, source


def push(args: list[str]) -> int:
    try:
        module, fields, whole, ttl, source = parse_push(args)
    except ValueError as e:
        sys.stderr.write(f"barctl push: {e}\n{USAGE_PUSH}\n")
        return 2
    from desktop_tools.barctl import ops

    try:
        ops.push(module, fields, whole=whole, ttl=ttl, source=source)
    except ops.Failure as e:
        sys.stderr.write(f"barctl push: {e}\n")
        if e.code not in (ops.USAGE, ops.REFUSED, ops.NOT_FOUND):
            _log_error(f"push: {e}")
        return e.code
    except Exception as e:
        sys.stderr.write(f"barctl push: {type(e).__name__}: {e}\n")
        _log_error(f"push: {type(e).__name__}: {e}")
        return 4
    return 0


def main(args: list[str]) -> int:
    verb, rest = args[0], args[1:]
    return render(rest) if verb == "render" else push(rest)

#!/usr/bin/env python3
"""Regenerate the zsh completions in completions/zsh/ from the Typer apps (dotfiles record 0003
§A6). The project's own script, not the template's.

    uv run scripts/gen-completions.py           # rewrite them
    uv run scripts/gen-completions.py --check   # fail if any is stale (tests/unit run it in CI)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "completions" / "zsh"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a file is stale")
    args = parser.parse_args(argv)
    from desktop_tools import completions

    return completions.write(OUT, check=args.check)


if __name__ == "__main__":
    sys.exit(main())

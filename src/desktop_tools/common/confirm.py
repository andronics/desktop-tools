"""A rofi Yes/No, shared by crew and `devices` (moved from crew.life by record 0004 §3).

Yes only on an explicit Yes: No is the selected row, so Return on open or Escape mean No. A
question that couldn't be shown is asked once more; shown neither time, the caller's `tell` is
called and `Unasked` raised, so nothing runs without a Yes and nothing reads it as No.

The question opens only once the click that picked it has landed (`settle`): a rofi started the
instant a menu's rofi closed takes that click's release as a click outside it and closes at
once, unseen. Each caller passes its own waits, so its tests can set them.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from desktop_tools.common import paths

# The Yes/No's rofi theme, the first found in ~/.config/rofi/themes: dotfiles' confirm.rasi (the
# question in full over two rows, nothing to type), else the one-line prompt.rasi it replaced.
THEMES = ("confirm", "prompt")
SETTLE = 0.3  # seconds a Yes/No waits for the click that picked it to land (barmenu's settle)
UNSHOWN = 0.25  # an unanswered Yes/No that closed sooner than this was never seen
# What rofi says when it can't show itself: its single-instance lock, a keyboard or pointer it
# couldn't grab, no display.
UNSHOWN_SAYS = ("already running", "Failed to grab", "Giving up", "open display")


class Unasked(Exception):
    """The Yes/No couldn't be shown, twice (the caller told): nothing is done. It is no No: the
    caller fails instead of going on."""


def theme() -> Path | None:
    themes = paths.config_home() / "rofi" / "themes"
    return next((t for n in THEMES if (t := themes / f"{n}.rasi").is_file()), None)


def ask(
    question: str, *, prompt: str, settle: float = SETTLE, unshown: float = UNSHOWN
) -> bool | str:
    """One Yes/No: True on Yes, False on No (Escape, Return on the selected No), else why it
    couldn't be shown. `prompt` is rofi's -p under the confirm theme, where the question is the
    -mesg and a long one wraps; prompt.rasi has no message, so there the question is the -p."""
    if shutil.which("rofi") is None:
        return "rofi is not on PATH"
    from desktop_tools.barmenu import menus as bm

    bm.settle(settle)
    argv = ["rofi", "-dmenu", "-i", "-no-custom", "-format", "s", "-selected-row", "1"]
    found = theme()
    argv += ["-theme", str(found)] if found else []
    shown = found is not None and found.stem == THEMES[0]
    mesg = question.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    started = time.monotonic()
    try:
        # S603/S607: rofi with fixed options; it blocks until answered.
        done = subprocess.run(  # noqa: S603
            [*argv, "-p", prompt if shown else question, "-mesg", mesg],
            input="Yes\nNo\n",
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        return f"rofi: {e.strerror}"
    took = time.monotonic() - started
    answer = done.stdout.strip()
    if done.returncode == 0 and answer:
        return answer == "Yes"
    said = [line.strip() for line in done.stderr.splitlines() if line.strip()]
    if done.returncode not in (0, 1):
        return f"rofi exited {done.returncode}" + (f": {said[-1]}" if said else "")
    failed = [line for line in said if any(m in line for m in UNSHOWN_SAYS)]
    if failed:
        return failed[-1]
    if took < unshown:
        return f"rofi closed after {took * 1000:.0f} ms, before it could be answered"
    return False


def confirm(
    question: str,
    *,
    prompt: str,
    warn: Callable[[str], object],
    tell: Callable[[str, str], object],
    settle: float = SETTLE,
    unshown: float = UNSHOWN,
) -> bool:
    """Ask, once more if it couldn't be shown; shown neither time, `tell(title, body)` and raise
    Unasked. `warn` takes a line for the caller's log."""
    got = ask(question, prompt=prompt, settle=settle, unshown=unshown)
    if isinstance(got, str):
        warn(f"cannot ask ({question}): {got}; asking again")
        got = ask(question, prompt=prompt, settle=settle, unshown=unshown)
    if isinstance(got, str):
        warn(f"cannot ask ({question}): {got}; nothing done")
        tell(f"couldn't ask: {got}", f"{question} Nothing was done.")
        raise Unasked(got)
    return got

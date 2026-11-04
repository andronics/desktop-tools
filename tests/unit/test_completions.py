"""The zsh completions: the committed files match the Typer apps (CI's `--check`, record 0003
§A6), they parse in zsh where it is installed, and they offer what the tools take."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from desktop_tools import completions
from tests import fakes
from tests.fakes import SYSTEM_PATH

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "completions" / "zsh"


def gen_script() -> object:
    spec = importlib.util.spec_from_file_location(
        "gen_completions", ROOT / "scripts" / "gen-completions.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_completions_are_current() -> None:
    """`uv run scripts/gen-completions.py --check`, run in CI by this test."""
    script = gen_script()
    assert script.main(["--check"]) == 0  # type: ignore[attr-defined]  # the script's main


def test_check_spots_a_stale_file(tmp_path: Path) -> None:
    lines: list[str] = []
    assert completions.write(tmp_path, check=True, emit=lines.append) == 1
    assert "stale" in lines[0]
    assert completions.write(tmp_path, emit=lines.append) == 0
    assert completions.write(tmp_path, check=True, emit=lines.append) == 0


def test_barctl_completion() -> None:
    text = (COMMITTED / "_barctl_cmd").read_text()
    assert text.startswith("#compdef barctl\n")
    assert completions.MARKER in text
    for verb in ("status", "push", "alert", "click", "hide", "unhide", "render"):
        assert f"'{verb}:" in text
    assert "TOOL_STATS=skip barctl list" in text
    assert "':module:_barctl_cmd_modules'" in text
    assert "(left middle right scroll-up scroll-down)" in text
    assert "(unavailable idle active alert)" in text
    assert "'*:module:_barctl_cmd_modules'" in text  # watch's modules
    assert "'::module:_barctl_cmd_modules'" in text  # reload's optional module
    assert "poke" not in text  # folded into reload


def test_barmenu_completion() -> None:
    text = (COMMITTED / "_barmenu_cmd").read_text()
    assert "TOOL_STATS=skip barmenu list" in text
    assert "'*::command:_normal'" in text
    assert "vpn" not in text  # menus come from the tool at TAB time, not this file


@pytest.mark.skipif(shutil.which("zsh", path=SYSTEM_PATH) is None, reason="zsh is not installed")
@pytest.mark.parametrize("name", ["_barctl_cmd", "_barmenu_cmd"])
def test_zsh_parses_it(name: str) -> None:
    zsh = shutil.which("zsh", path=SYSTEM_PATH) or "zsh"
    result = fakes.run([zsh, "-n", str(COMMITTED / name)])
    assert result.returncode == 0, result.stderr

"""barctl is the only program that talks to polybar (dotfiles record 0003 §B1): no file in the
package but common/polybar.py names `polybar-msg` or polybar's IPC socket."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "desktop_tools"
OWNER = SRC / "common" / "polybar.py"
# polybar-msg itself; the protocol's magic; the socket's name (ipc.<pid>.sock).
NAMES = ("polybar-msg", "polyipc", "ipc.")


def test_only_common_polybar_talks_to_polybar() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*")):
        if not path.is_file() or path == OWNER or path.suffix not in (".py", ".toml"):
            continue
        text = path.read_text(encoding="utf-8")
        for name in NAMES:
            if name in text:
                offenders.append(f"{path.relative_to(SRC)}: {name}")
    assert offenders == []


def test_the_owner_does() -> None:
    text = OWNER.read_text(encoding="utf-8")
    assert "polybar-msg" in text and "polyipc" in text

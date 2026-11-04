"""Shared fixtures.

Nothing a test runs can reach the live desktop: every XDG folder, barctl's state and settings,
the journal socket, the run store, /proc as barctl reads it and polybar's socket folder point
into the test's tmp_path (the `isolate` fixture, for every test). Fakes for polybar, the journal
and the desktop's commands live in tests/fakes.py.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from desktop_tools.config import ENV_PREFIX
from tests.crew_fakes import Desk, make_desk
from tests.fakes import (
    FakeBar,
    FakeJournal,
    fake_commands,
    lockdown_path,
    tripwires,
    write_theme,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the developer's own DESKTOP_TOOLS_* variables."""
    import os

    for name in list(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Every folder barctl, barmenu and the journal helper use, inside tmp_path."""
    home = tmp_path / "xdg"
    for sub in ("config", "state", "data", "cache"):
        (home / sub).mkdir(parents=True)
    runtime = home / "runtime"
    runtime.mkdir(mode=0o700)
    (tmp_path / "proc").mkdir()
    env = {
        "XDG_CONFIG_HOME": home / "config",
        "XDG_STATE_HOME": home / "state",
        "XDG_DATA_HOME": home / "data",
        "XDG_CACHE_HOME": home / "cache",
        "XDG_RUNTIME_DIR": runtime,
        "THEME_STATE_DIR": home / "state" / "theme",
        "TOOL_RUNS_DIR": tmp_path / "runs",
        "TOOL_JOURNAL_STAMPS": tmp_path / "stamps",
        "TOOL_JOURNAL_SOCKET": tmp_path / "no-journal.sock",
        "BARCTL_PROC": tmp_path / "proc",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    # The journal is off and no run is recorded unless a test turns them on (journal_sock).
    monkeypatch.setenv("TOOL_JOURNAL", "off")
    monkeypatch.setenv("TOOL_STATS", "skip")
    # PATH is built here: tripwires for every desktop command (they fail and log), then the
    # few real tools the fakes themselves use. A real `theme`, `polybar` or `pactl` is never
    # found; a test that needs one fakes it with `commands`.
    lockdown_path(tmp_path, monkeypatch)
    for key in (
        "BARCTL_RUNTIME_DIR",
        "BARCTL_SETTINGS_DIR",
        "BARCTL_CONFIG",
        "BARCTL_SOURCE",
        "BARMENU_CONFIG",
        "BARMENU_THEME",
        "BARCTL_POLYBAR_CONFIG",
        "CREW_ACTORS_DIR",
        "CREW_TMUX_SOCKET",
        "CREW_CLASS",
        "CREW_OLD_CLASS",
        "CREW_DEBUG",
        "COORDINATOR",
        "POLYBAR_BAR",
        "HOST_MONITOR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BARCTL_RETRY", "0.2")
    # crew never reads the real actors folder or tmux server in a test.
    monkeypatch.setenv("CREW_ACTORS_DIR", str(tmp_path / "no-actors"))
    monkeypatch.setenv("CREW_TMUX_SOCKET", "crew-test-unused")
    # Never the brain's real meta: unless a test fakes it, PATH's tripwire answers.
    monkeypatch.setenv("BRAIN_BIN", str(tmp_path / "no-brain-bin"))
    yield tmp_path
    tripped = tripwires(tmp_path)
    assert tripped == [], f"a test reached a desktop command it didn't fake: {tripped}"


@pytest.fixture
def theme(isolate: Path) -> dict[str, str]:
    """A current theme with the four tier roles; returns tier -> colour."""
    return write_theme(isolate / "xdg" / "state" / "theme")


@pytest.fixture
def bar(isolate: Path) -> Iterator[FakeBar]:
    """A fake polybar answering on its IPC socket."""
    fake = FakeBar(isolate / "xdg" / "runtime" / "polybar", pid=4242)
    yield fake
    fake.close()


@pytest.fixture
def journal_sock(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeJournal]:
    """A fake journal socket, with the journal and run records on."""
    fake = FakeJournal(isolate / "journal.sock")
    monkeypatch.setenv("TOOL_JOURNAL_SOCKET", str(fake.path))
    monkeypatch.setenv("TOOL_JOURNAL", "")
    monkeypatch.setenv("TOOL_STATS", "")
    yield fake
    fake.close()


@pytest.fixture
def commands(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Put fake commands first on PATH: commands(name=script_body, ...) -> the log file."""

    def make(**bodies: str) -> Path:
        return fake_commands(isolate, monkeypatch, bodies)

    return make


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """procs.detach recorded instead of run; close_inherited a no-op (it would close pytest's
    own pipes)."""
    from desktop_tools.common import procs

    seen: list[list[str]] = []

    def detach(argv: list[str], env: object = None, cwd: object = None) -> int:
        seen.append(list(argv))
        return 1

    monkeypatch.setattr(procs, "detach", detach)
    monkeypatch.setattr(procs, "close_inherited", lambda fd_dir="": [])
    return seen


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., Path]:
    """Write a config file and return its path."""

    def write(text: str) -> Path:
        path = tmp_path / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    return write


@pytest.fixture
def desk(
    isolate: Path, monkeypatch: pytest.MonkeyPatch, commands: Callable[..., Path]
) -> Iterator[Desk]:
    """crew's fake desktop: bspwm, tmux (its own server only), meta, alacritty, notify-send."""
    fake = make_desk(isolate, monkeypatch, commands)
    yield fake
    assert fake.bare_tmux() == [], "a tmux call didn't name its own server"

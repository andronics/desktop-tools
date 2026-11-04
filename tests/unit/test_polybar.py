"""polybar's IPC protocol, against a fake bar, and finding, restarting and starting bars against a
fake /proc. Nothing here reaches a real bar."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from desktop_tools.common import polybar
from tests.fakes import FakeBar, calls


def test_poke_sends_the_hook_action(bar: FakeBar) -> None:
    assert polybar.sockets() == {4242: bar.path}
    assert polybar.poke("audio-level") == {4242: True}
    assert bar.messages == [(polybar.TYPE_ACTION, "#audio-level.hook.0")]


def test_command_and_ping(bar: FakeBar) -> None:
    assert polybar.command("hide") == {4242: True}
    assert bar.messages[-1] == (polybar.TYPE_CMD, "hide")
    reply = polybar.ping(4242)
    assert reply is not None and reply.ok and reply.known and reply.version == 0
    assert "ok=True" in repr(reply)
    assert polybar.ping(999) is None


def test_an_error_answer(bar: FakeBar) -> None:
    bar.ok = False
    assert polybar.poke("x") == {4242: False}
    reply = polybar.send(bar.path, polybar.TYPE_ACTION, "#x.hook.0")
    assert (reply.ok, reply.message) == (False, "bad")


def test_no_bar_and_a_stale_socket(isolate: Path) -> None:
    assert polybar.sockets() == {}
    assert polybar.poke("x") == {}
    folder = isolate / "xdg" / "runtime" / "polybar"
    folder.mkdir()
    (folder / "ipc.77.sock").touch()  # a socket file nobody listens on
    (folder / "other.txt").touch()
    assert polybar.poke("x") == {77: False}
    assert polybar.ping(77) is None


def test_unknown_protocol_falls_back_to_polybar_msg(
    isolate: Path, commands: Callable[..., Path]
) -> None:
    log = commands(**{"polybar-msg": "pass"})
    fake = FakeBar(isolate / "xdg" / "runtime" / "polybar", pid=5, version=1)
    try:
        reply = polybar.ping(5)
        assert reply is not None and not reply.known
        assert polybar.poke("audio-level") == {5: True}
        assert calls(log)[-1] == ["polybar-msg", "-p", "5", "action", "#audio-level.hook.0"]
        assert polybar.command("restart") == {5: True}
        assert calls(log)[-1] == ["polybar-msg", "-p", "5", "cmd", "restart"]
    finally:
        fake.close()


def test_fallback_without_polybar_msg(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(isolate / "empty"))
    fake = FakeBar(isolate / "xdg" / "runtime" / "polybar", pid=6, version=3)
    try:
        assert polybar.poke("x") == {6: False}
    finally:
        fake.close()


def fake_proc(
    root: Path, pid: int, comm: str, ppid: int = 1, argv: list[str] | None = None
) -> None:
    d = root / str(pid)
    d.mkdir()
    (d / "comm").write_text(comm + "\n")
    (d / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {pid} 0\n")
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in (argv or [comm])) + b"\0")
    (d / "environ").write_bytes(b"HOST_MONITOR=DP-2\0DISPLAY=:0\0BROKEN\0")


def test_bars_children_and_launch(isolate: Path) -> None:
    root = isolate / "proc"
    fake_proc(root, 100, "polybar", argv=["polybar", "-q", "main"])
    fake_proc(root, 101, "sh", ppid=100)
    fake_proc(root, 200, "zsh")
    (root / "self").mkdir()
    assert polybar.bar_pids() == [100]
    assert polybar.children(100) == [101]
    launch = polybar.Launch.of(100)
    assert launch is not None
    assert launch.argv == ["polybar", "-q", "main"]
    assert launch.env == {"HOST_MONITOR": "DP-2", "DISPLAY": ":0"}
    assert polybar.Launch.of(999) is None
    assert polybar.bar_pids(isolate / "missing") == []


def test_restart_in_place(bar: FakeBar, isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_proc(isolate / "proc", 4242, "polybar", argv=["polybar", "main"])
    monkeypatch.setattr(polybar, "alive", lambda pid: True)
    result = polybar.restart(wait=1, sleep=lambda s: None)
    assert result.ok and result.restarted == [4242]
    assert (polybar.TYPE_CMD, "restart") in bar.messages


def test_restart_relaunches_a_frozen_bar(
    bar: FakeBar, isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_proc(isolate / "proc", 4242, "polybar", argv=["polybar", "main"])
    started: list[polybar.Launch] = []
    killed: list[int] = []
    monkeypatch.setattr(polybar, "alive", lambda pid: True)
    monkeypatch.setattr(polybar, "kill_bar", lambda pid, root=None: killed.append(pid))
    monkeypatch.setattr(polybar, "ping", lambda pid, timeout=2.0: None)  # frozen

    def starter(launch: polybar.Launch) -> int:
        started.append(launch)
        return 5000

    result = polybar.restart(wait=0, starter=starter, sleep=lambda s: None)
    assert killed == [4242]
    assert [s.argv for s in started] == [["polybar", "main"]]
    assert result.relaunched == [5000] and result.ok
    assert any("froze" in n for n in result.notes)


def test_restart_a_bar_that_wont_take_it_and_one_that_dies(
    isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_proc(isolate / "proc", 1, "polybar", argv=["polybar", "main"])
    monkeypatch.setattr(polybar, "kill_bar", lambda pid, root=None: None)
    monkeypatch.setattr(polybar, "alive", lambda pid: False)  # every bar dies
    result = polybar.restart(wait=0, starter=lambda launch: 77, sleep=lambda s: None)
    assert any("didn't take the restart" in n for n in result.notes)
    assert result.relaunched == [77]
    assert not result.ok  # the relaunched bar exited: its config is broken


def test_start_bar_when_none_runs(isolate: Path, commands: Callable[..., Path]) -> None:
    commands(bspc="print('DP-4')", polybar="pass")
    seen: list[polybar.Launch] = []

    def starter(launch: polybar.Launch) -> int:
        seen.append(launch)
        return os.getpid()  # alive

    result = polybar.start_bar("main", starter=starter, sleep=lambda s: None)
    assert result.ok and result.started == [os.getpid()]
    assert seen[0].argv[1:] == ["-q", "main"]
    assert seen[0].env["HOST_MONITOR"] == "DP-4"


def test_start_bar_failures(isolate: Path) -> None:
    def broken(launch: polybar.Launch) -> int:
        raise OSError(2, "No such file")

    result = polybar.start_bar("main", env={"HOST_MONITOR": "X"}, starter=broken)
    assert not result.ok and "couldn't start" in result.notes[0]


def test_start_records_tool_stats_skip(commands: Callable[..., Path], isolate: Path) -> None:
    out = isolate / "env.txt"
    commands(fakebar=f"open({str(out)!r}, 'w').write(os.environ.get('TOOL_STATS', ''))")
    pid = polybar.start(polybar.Launch(["fakebar"], {"PATH": os.environ["PATH"]}))
    os.waitpid(pid, 0)
    assert out.read_text() == "skip"


def test_kill_bar_and_alive(isolate: Path, commands: Callable[..., Path]) -> None:
    commands(sleeper="time.sleep(30)")
    pid = polybar.start(polybar.Launch(["sleeper"], dict(os.environ)))
    assert polybar.alive(pid)
    polybar.kill_bar(pid, isolate / "proc")
    os.waitpid(pid, 0)
    assert not polybar.alive(pid)

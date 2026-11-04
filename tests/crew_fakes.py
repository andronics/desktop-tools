"""Fakes for crew: a bspwm, a tmux, `meta`, alacritty and notify-send, as scripts on PATH that
log every call (tests/fakes.py's fake_commands) and keep their state in files under the test's
tmp_path. Nothing reaches a real window, session or coordinator.

- **bspc** keeps a small desktop in `wm.json` (monitors, windows) and answers `wm -d` in bspwm's
  own JSON shape, applies `node` flags, moves, resizes and states and `config` paddings, and
  plays `events` to `subscribe`. `wm.json`'s `fail` list makes one kind of call fail: `dump`,
  `padding`, `tomonitor`, `flag`, `move`, `resize`, `state`.
- **tmux** refuses (exit 98, logged as BARE) any call that doesn't name its own server first
  (`-L` or `-S`), so a test that would reach the live server fails instead. Sessions are lines
  in `sessions`.
- **meta** answers `brain coordinators --json` from `registry.json` (exit `meta-rc` if that file
  exists) and `<name> launch` by adding `<name>-coordinator` to `sessions` (exit `launch-rc`).
- **alacritty** adds a hidden floating window of its `--class` to `wm.json`, as bspwmrc's rule
  makes it (none when `no-window` exists).
- **notify-send** prints `notify-answer` if it exists (what a click on the action returns).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import calls

# Shared by the fakes: load and save wm.json under a lock, so alacritty and bspc never race.
_WM_IO = """
import fcntl
def load_wm():
    path = os.path.join(here, "wm.json")
    with open(path) as fh:
        return json.load(fh)
def save_wm(data):
    path = os.path.join(here, "wm.json")
    tmp = path + f".{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)
lockf = open(os.path.join(here, "wm.lock"), "w")
fcntl.flock(lockf, fcntl.LOCK_EX)
"""

BSPC = (
    _WM_IO
    + r"""
def ident(v):
    return int(v, 16) if v.lower().startswith("0x") else int(v)

def node(wid, w):
    return {"id": wid, "hidden": w["hidden"], "sticky": True,
            "client": {"className": w["cls"], "instanceName": w["instance"],
                       "borderWidth": w["border"],
                       "state": "floating" if w["floating"] else "tiled",
                       "floatingRectangle": dict(zip(("x", "y", "width", "height"), w["rect"]))},
            "firstChild": None, "secondChild": None}

def dump(d):
    mons = []
    for m in d["monitors"]:
        nodes = [node(w["id"], w) for w in d["windows"] if w["monitor"] == m["id"]]
        root = None
        for n in reversed(nodes):  # a right-leaning chain of internal nodes
            root = n if root is None else {"id": 0, "firstChild": n, "secondChild": root}
        desk = {"id": m["id"] * 100, "name": "1", "layout": m["layout"],
                "windowGap": m["gap"], "focusedNodeId": m.get("focused_node") or 0,
                "padding": {"top": m["desk_padding"]["top"], "bottom": m["desk_padding"]["bottom"],
                            "left": 0, "right": 0},
                "root": root}
        mons.append({"id": m["id"], "name": m["name"], "windowGap": m["gap"],
                     "rectangle": dict(zip(("x", "y", "width", "height"), m["rect"])),
                     "padding": m["padding"], "focusedDesktopId": m["id"] * 100,
                     "desktops": [desk]})
    return {"focusedMonitorId": d["focused_monitor"], "monitors": mons}

d = load_wm()
fail = set(d.get("fail", []))
def win(v):
    return next(w for w in d["windows"] if w["id"] == ident(v))
def mon(v):
    return next(m for m in d["monitors"] if m["id"] == ident(v))

if args[:2] == ["wm", "-d"]:
    if "dump" in fail:
        sys.exit(1)
    print(json.dumps(dump(d)))
    sys.exit(0)
if args[:1] == ["subscribe"]:
    events = os.path.join(here, "events")
    lines = open(events).read().splitlines() if os.path.exists(events) else []
    lockf.close()
    for line in lines:
        if line.startswith("sleep "):
            time.sleep(float(line.split()[1]))
        else:
            print(line, flush=True)
    sys.exit(0)
if args[:1] == ["config"]:
    if args[1:2] == ["gapless_monocle"]:
        print(d.get("gapless", "false"))
        sys.exit(0)
    if args[1] == "-m":
        m, key = mon(args[2]), args[3]
        side = key.removesuffix("_padding")
        if len(args) == 4:
            print(m["padding"][side])
            sys.exit(0)
        if "padding" in fail:
            sys.exit(1)
        m["padding"][side] = int(args[4])
        save_wm(d)
        sys.exit(0)
if args[:1] == ["node"]:
    w, op = win(args[1]), args[2]
    if op == "--flag":
        if "flag" in fail:
            sys.exit(1)
        w["hidden"] = args[3] == "hidden=on"
        if "--focus" in args:
            d["focused_monitor"] = w["monitor"]
            mon(str(w["monitor"]))["focused_node"] = w["id"]
    elif op == "--state":
        if "state" in fail:
            sys.exit(1)
        w["floating"] = args[3] == "floating"
    elif op == "--to-monitor":
        if "tomonitor" in fail:
            sys.exit(1)
        w["monitor"] = ident(args[3])
    elif op == "--move":
        if "move" in fail:
            sys.exit(1)
        w["rect"][0] += int(args[3]); w["rect"][1] += int(args[4])
    elif op == "--resize":
        if "resize" in fail:
            sys.exit(1)
        w["rect"][2] += int(args[4]); w["rect"][3] += int(args[5])
    save_wm(d)
    sys.exit(0)
sys.exit(1)
"""
)

TMUX = r"""
if not args or args[0] not in ("-L", "-S"):
    with open(os.path.join(here, "tmux-bare.log"), "a") as fh:
        fh.write(json.dumps(args) + "\n")
    sys.exit(98)
rest = args[2:]
path = os.path.join(here, "sessions")
names = open(path).read().split() if os.path.exists(path) else []
if rest[:1] == ["list-sessions"]:
    if not names:
        sys.exit(1)
    print("\n".join(names))
    sys.exit(0)
if rest[:1] == ["has-session"]:
    sys.exit(0 if rest[2].lstrip("=") in names else 1)
sys.exit(0)
"""

META = r"""
def rc(name, default=0):
    p = os.path.join(here, name)
    return int(open(p).read().strip()) if os.path.exists(p) else default
if args[:2] == ["brain", "coordinators"]:
    code = rc("meta-rc")
    if code:
        sys.stderr.write("meta brain: vault-query failed\n")
        sys.exit(code)
    print(open(os.path.join(here, "registry.json")).read())
    sys.exit(0)
if len(args) >= 2 and args[1] == "launch":
    code = rc("launch-rc")
    if code:
        sys.stderr.write(f"meta {args[0]}: refused\n")
        sys.exit(code)
    with open(os.path.join(here, "sessions"), "a") as fh:
        fh.write(f"{args[0]}-coordinator\n")
    sys.exit(0)
sys.exit(2)
"""

ALACRITTY = (
    _WM_IO
    + r"""
if os.path.exists(os.path.join(here, "no-window")):
    sys.exit(0)
cls, _, inst = args[args.index("--class") + 1].partition(",")
d = load_wm()
wid = max([w["id"] for w in d["windows"]] + [0x01000000]) + 1
d["windows"].append({"id": wid, "cls": cls, "instance": inst, "hidden": True, "floating": True,
                     "monitor": d["focused_monitor"], "border": 1, "rect": [0, 0, 800, 600]})
save_wm(d)
"""
)

NOTIFY = r"""
p = os.path.join(here, "notify-answer")
if os.path.exists(p):
    print(open(p).read().strip())
"""

MONITOR = 0x00200002


def monitor(mid: int = MONITOR, name: str = "M", x: int = 0) -> dict[str, Any]:
    return {
        "id": mid,
        "name": name,
        "rect": [x, 0, 3840, 2160],
        "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
        "gap": 5,
        "desk_padding": {"top": 0, "bottom": 0},
        "layout": "tiled",
        "focused_node": None,
    }


class Desk:
    """A fake desktop for crew: its coordinators, windows, sessions and every call made."""

    def __init__(self, base: Path, log: Path) -> None:
        self.base, self.log = base, log
        self.actors = base / "actors"
        self.actors.mkdir(exist_ok=True)
        self.save({"focused_monitor": MONITOR, "monitors": [monitor()], "windows": []})
        self.detached: list[list[str]] = []

    # ------------------------------------------------------------ files
    def load(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self.base / "wm.json").read_text())
        return data

    def save(self, data: dict[str, Any]) -> None:
        (self.base / "wm.json").write_text(json.dumps(data))

    def put(self, name: str, text: str) -> None:
        (self.base / name).write_text(text)

    # ------------------------------------------------------------ the registry
    def coordinators(self, *names: str, **extra: dict[str, Any]) -> list[dict[str, Any]]:
        """meta's answer for these names (homes made), in this order."""
        entries = []
        for i, name in enumerate(names):
            home = self.actors / name
            home.mkdir(exist_ok=True)
            (home / "README.md").write_text(name)
            entry = {
                "name": name,
                "slug": f"{name}-coordinator",
                "tmux_session": f"{name}-coordinator",
                "home": str(home),
                "menu_order": (i + 1) * 10,
                "bar_glyph": "",
                "old_names": [],
                "old_names_until": "2999-12-04",
                "note": f"{name} Coordinator",
                "note_path": f"/vault/{name} Coordinator.md",
                "centre": name,
                "status": "active",
                "stopped_by_default": False,
                "icon": "",
                "meta_module": "",
                "repos": [],
                **extra.get(name, {}),
            }
            entries.append(entry)
        # The envelope the live `meta brain coordinators --json` prints (brain PR 151).
        envelope = {
            "meta": 1,
            "centre": "brain",
            "verb": "coordinators",
            "generated": "2026-11-04T04:37:38+00:00",
            "cached": True,
            "age_s": 33,
            "stale": False,
            "data": entries,
        }
        self.put("registry.json", json.dumps(envelope))
        return entries

    # ------------------------------------------------------------ windows and sessions
    def window(
        self,
        instance: str,
        *,
        hidden: bool = True,
        focused: bool = False,
        cls: str = "crew",
        floating: bool = True,
        rect: tuple[int, int, int, int] = (100, 100, 800, 600),
        monitor_id: int = MONITOR,
    ) -> int:
        d = self.load()
        wid = int(max([w["id"] for w in d["windows"]] + [0x00C00000])) + 1
        d["windows"].append(
            {
                "id": wid,
                "cls": cls,
                "instance": instance,
                "hidden": hidden,
                "floating": floating,
                "monitor": monitor_id,
                "border": 1,
                "rect": list(rect),
            }
        )
        if focused:
            for m in d["monitors"]:
                if m["id"] == monitor_id:
                    m["focused_node"] = wid
            d["focused_monitor"] = monitor_id
        self.save(d)
        return wid

    def windows(self) -> dict[str, dict[str, Any]]:
        return {w["instance"]: w for w in self.load()["windows"]}

    def shown(self) -> list[str]:
        return [w["instance"] for w in self.load()["windows"] if not w["hidden"]]

    def padding(self, mid: int = MONITOR) -> dict[str, int]:
        m = next(m for m in self.load()["monitors"] if m["id"] == mid)
        return dict(m["padding"])

    def fail(self, *kinds: str) -> None:
        d = self.load()
        d["fail"] = list(kinds)
        self.save(d)

    def session(self, *names: str) -> None:
        with open(self.base / "sessions", "a") as fh:
            for n in names:
                fh.write(f"{n}\n")

    # ------------------------------------------------------------ what happened
    def calls(self, name: str | None = None) -> list[list[str]]:
        found = calls(self.log)
        return [c for c in found if name is None or c[0] == name]

    def launched(self) -> list[str]:
        """The coordinators `meta <name> launch` was asked to start."""
        return [c[1] for c in self.calls("meta") if c[2:3] == ["launch"]]

    def notified(self) -> list[list[str]]:
        return [c[1:] for c in self.detached if c[:1] == ["notify-send"]]

    def bare_tmux(self) -> list[str]:
        path = self.base / "tmux-bare.log"
        return path.read_text().splitlines() if path.exists() else []


def make_desk(
    isolate: Path,
    monkeypatch: pytest.MonkeyPatch,
    commands: Callable[..., Path],
) -> Desk:
    log = commands(bspc=BSPC, tmux=TMUX, meta=META, alacritty=ALACRITTY, **{"notify-send": NOTIFY})
    desk = Desk(isolate, log)
    monkeypatch.setenv("CREW_ACTORS_DIR", str(desk.actors))
    monkeypatch.setenv("CREW_TMUX_SOCKET", "crew-test")
    # meta is found as $BRAIN_BIN/meta first: the fake's folder.
    monkeypatch.setenv("BRAIN_BIN", str(log.parent / "bin"))
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "1")
    monkeypatch.setenv("CREW_GUARD_SETTLE", "0.05")
    for key in ("CREW_CLASS", "CREW_OLD_CLASS", "CREW_REGISTRY_MAX_AGE", "CREW_BAR_TTL"):
        monkeypatch.delenv(key, raising=False)

    from desktop_tools.common import procs

    def detach(argv: list[str], env: object = None, cwd: object = None) -> int:
        # alacritty runs (it adds its window), now, so a test sees the window; crew's own
        # children (the guard, the strip's refresh, the notification) are only recorded.
        desk.detached.append(list(argv))
        if argv[:1] == ["alacritty"]:
            import subprocess

            subprocess.run(argv, check=False)  # noqa: S603 - the fake, on the test's PATH
        return 1

    monkeypatch.setattr(procs, "detach", detach)
    return desk

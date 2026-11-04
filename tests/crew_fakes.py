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
  exists); `<name> launch` by adding `<name>-coordinator` to `sessions`; `<name> stop` by removing
  it and the window attached to it; `<name> restart` by both; `<name> stop --check` with 0. Each
  verb exits as `<verb>-rc-<name>` or `<verb>-rc` say (`check` for `--check`), giving the reason in
  `<verb>-why[-<name>]`: on stdout as the stop script's log line for 1, else on stderr; a 1 for
  `stop` or `restart` with `--force` ends it anyway.
- **rofi** prints `rofi-answer` if it exists (the row picked), else exits 1 (Escape). The menus'
  tests use `ROFI_SEQ` instead: one answer per call from `rofi-answers`, each call's rows kept.
- **meta** also answers `<name> menu --json` from `menu-<name>.json` (exit `menu-rc[-<name>]`) and
  any other verb with six lines echoing it (exit `<verb>-rc[-<name>]`: 1 keeps the six lines, as
  meta's "there is a problem" result; any other code two lines on stderr instead, or
  `<verb>-stdout` on stdout and nothing on stderr).
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

META = (
    _WM_IO
    + r"""
def rc(verb, name, default=0):
    for f in (f"{verb}-rc-{name}", f"{verb}-rc"):
        p = os.path.join(here, f)
        if os.path.exists(p):
            return int(open(p).read().strip())
    return default
def why(verb, name):
    for f in (f"{verb}-why-{name}", f"{verb}-why"):
        p = os.path.join(here, f)
        if os.path.exists(p):
            return open(p).read().strip()
    return "refused"
def sessions():
    p = os.path.join(here, "sessions")
    return open(p).read().split() if os.path.exists(p) else []
def end(name):
    # The session goes, and with it the window attached to it.
    keep = [s for s in sessions() if s != f"{name}-coordinator"]
    with open(os.path.join(here, "sessions"), "w") as fh:
        fh.write("".join(f"{s}\n" for s in keep))
    d = load_wm()
    d["windows"] = [w for w in d["windows"] if w["instance"] != name]
    save_wm(d)
def start(name):
    with open(os.path.join(here, "sessions"), "a") as fh:
        fh.write(f"{name}-coordinator\n")
lockf.close()
if args[:2] == ["brain", "coordinators"]:
    code = rc("meta", "brain")
    if code:
        sys.stderr.write("meta brain: vault-query failed\n")
        sys.exit(code)
    print(open(os.path.join(here, "registry.json")).read())
    sys.exit(0)
name, verb = (args + ["", ""])[:2]
if verb == "launch":
    code = rc("launch", name)
    if code:
        sys.stderr.write(f"meta {name}: {why('launch', name)}\n")
        sys.exit(code)
    start(name)
    print(f"{name}: launched in tmux session {name}-coordinator")
    sys.exit(0)
if verb == "stop" and "--check" in args:
    code = rc("check", name)
    if code == 1:
        print(f'2026-11-04T05:00:00+00:00 by=meta result=not-clean why="{why("check", name)}"')
        print(f"{name}: {why('check', name)}")
    elif code:
        sys.stderr.write(f"meta {name}: {why('check', name)}\n")
    sys.exit(code)
if verb in ("stop", "restart"):
    code = rc(verb, name)
    if code == 1 and "--force" in args:  # not clean, ended anyway, as the stop script does
        code = 0
    if code == 1:
        print(f'2026-11-04T05:00:00+00:00 by=meta result=refused why="{why(verb, name)}"')
    elif code:
        sys.stderr.write(f"meta {name}: {why(verb, name)}\n")
    if code:
        sys.exit(code)
    end(name)
    if verb == "restart":
        start(name)
    print(f"{name}: stopped")
    sys.exit(0)
if verb == "menu":
    code = rc("menu", name)
    if code:
        sys.stderr.write(f"meta {name}: menu failed\n")
        sys.exit(code)
    print(open(os.path.join(here, f"menu-{name}.json")).read())
    sys.exit(0)
if verb:  # a read-only verb: six lines echoing it, exit `<verb>-rc` (1 keeps the lines: a result)
    code = rc(verb, name)
    said = os.path.join(here, f"{verb}-stdout")
    if code not in (0, 1):
        if os.path.exists(said):  # its reason on stdout, nothing on stderr
            print(open(said).read().strip())
        else:
            sys.stderr.write(f"meta {name}: {verb} broke\nmore\n")
        sys.exit(code)
    print(f"{' '.join(args)}\nline 2\nline 3\nline 4\nline 5\nline 6")
    sys.exit(code)
sys.exit(2)
"""
)

ROFI = r"""
p = os.path.join(here, "rofi-answer")
sys.stdin.read()
if os.path.exists(p):
    print(open(p).read().strip())
    sys.exit(0)
sys.exit(1)
"""

# rofi answers from `rofi-answers`, one line per call in order (an empty line, or none left, is
# Escape), and keeps each call's rows in rofi-in.<n>. Two ways it can fail to be shown, neither
# using up an answer, each logged as a line in `rofi-unshown`:
# - `rofi-race` (seconds): started that soon after the last rofi closed, it closes at once with
#   exit 1 and nothing said, as the real one does when the menu's own click lands on it;
# - `rofi-fails` (a count): the next that many Yes/No questions fail as a grab failure does,
#   exit 1 and rofi's own line on stderr.
ROFI_SEQ = r"""
stamp = os.path.join(here, "rofi-closed")
def close(code, unshown=""):
    if unshown:
        open(os.path.join(here, "rofi-unshown"), "a").write(unshown + "\n")
    open(stamp, "w").write(repr(time.monotonic()))
    sys.exit(code)
sys_in = sys.stdin.read()
race = os.path.join(here, "rofi-race")
if os.path.exists(race) and os.path.exists(stamp):
    if time.monotonic() - float(open(stamp).read()) < float(open(race).read()):
        close(1, "race")
fails = os.path.join(here, "rofi-fails")
left = int(open(fails).read()) if os.path.exists(fails) else 0
if sys_in == "Yes\nNo\n" and left > 0:
    open(fails, "w").write(str(left - 1))
    sys.stderr.write("Failed to grab keyboard after 500 times. Giving up.\n")
    close(1, "grab")
path = os.path.join(here, "rofi-answers")
answers = open(path).read().split("\n") if os.path.exists(path) else []
n = len([f for f in os.listdir(here) if f.startswith("rofi-in.")])
open(os.path.join(here, f"rofi-in.{n}"), "w").write(sys_in)
answer = answers[n] if n < len(answers) else ""
if not answer:
    close(1)
print(answer)
close(0)
"""

# xclip keeps what it was given on stdin in `clipboard`.
XCLIP = r"""
if os.path.exists(os.path.join(here, "xclip-fail")):
    sys.stderr.write("Error: Can't open display\n")
    sys.exit(1)
open(os.path.join(here, "clipboard"), "w").write(sys.stdin.read())
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

    def lifecycle(self) -> list[list[str]]:
        """Every `meta <name> launch|stop|restart ...` call, without `meta` itself."""
        return [c[1:] for c in self.calls("meta") if c[2:3] in (["launch"], ["stop"], ["restart"])]

    def sessions(self) -> list[str]:
        path = self.base / "sessions"
        return path.read_text().split() if path.exists() else []

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
    log = commands(
        bspc=BSPC, tmux=TMUX, meta=META, alacritty=ALACRITTY, rofi=ROFI, **{"notify-send": NOTIFY}
    )
    desk = Desk(isolate, log)
    monkeypatch.setenv("CREW_ACTORS_DIR", str(desk.actors))
    monkeypatch.setenv("CREW_TMUX_SOCKET", "crew-test")
    # meta is found as $BRAIN_BIN/meta first: the fake's folder.
    monkeypatch.setenv("BRAIN_BIN", str(log.parent / "bin"))
    monkeypatch.setenv("CREW_LAUNCH_TIMEOUT", "1")
    monkeypatch.setenv("CREW_GUARD_SETTLE", "0.05")
    for key in ("CREW_CLASS", "CREW_OLD_CLASS", "CREW_REGISTRY_MAX_AGE", "CREW_BAR_TTL"):
        monkeypatch.delenv(key, raising=False)
    from desktop_tools.crew import life

    # The Yes/No's waits, off: a fake rofi answers at once, so its Escape would read as unshown.
    # The tests of those waits set them back (test_crew_menu's REAL_WAITS).
    monkeypatch.setattr(life, "SETTLE", 0.0, raising=False)
    monkeypatch.setattr(life, "UNSHOWN", 0.0, raising=False)

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

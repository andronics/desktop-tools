"""The quick menu's items: what `meta <name> menu --json` offers, and how crew runs one (brain
record 0019 §7a).

crew knows how to run an item, and nothing about which items exist. Each item is data:

    {"id": "inbox", "label": "Inbox", "glyph": "U+F02FA", "when": "always",
     "run": {"meta": ["brain", "inbox", "desktop"]}, "output": "view", "confirm": false}

- `run` is exactly one of `meta` (a `meta` verb, its arguments a list), `open` (a URL for
  `xdg-open`, `https://` and `obsidian://` only), `edit` (a path for `code`) or `copy` (text put on
  the clipboard with `xclip`). Nothing is ever a shell string: every child gets an argument list.
- `output`: `view` (the output in a floating alacritty of class `crew-view`, in a pager),
  `notify` (its first lines as a notification) or `none`. A failure always notifies, with the
  exit code and the first line on stderr.
- `when`: `always`, `running`, `stopped` or `exists:<path>`. meta judges it when it builds the
  menu; crew judges it again from its own state as the menu opens.

Launch, stop and restart go through `stopping` and crew's lifecycle verbs (`life`); this module
runs the rest.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from desktop_tools.crew import conf, log, metacall, switch
from desktop_tools.crew.registry import Coordinator, glyph_of

KINDS = ("meta", "open", "edit", "copy")
OUTPUTS = ("view", "notify", "none")
SCHEMES = ("https://", "obsidian://")
MENU_TIMEOUT = 5.0  # meta caches the menu for 30 seconds, so this is the uncached worst case
RUN_TIMEOUT = 60.0  # a meta verb's own: restart waits up to 30 seconds for the session to go
NOTIFY_LINES = 5
VIEW_KEEP = 3600.0  # seconds a view's text is kept, so its pager can still read it
VIEW_CLASS = "crew-view"
PAGER = ("less", "-R")


class Item:
    """One menu item as meta gives it. `value` is the meta arguments (a list) or the URL, path or
    text (a string)."""

    __slots__ = ("confirm", "glyph", "id", "kind", "label", "output", "value", "when")

    def __init__(
        self,
        id: str,
        label: str,
        kind: str,
        value: list[str] | str,
        *,
        glyph: str = "",
        when: str = "always",
        output: str = "none",
        confirm: bool = False,
    ) -> None:
        self.id, self.label, self.kind, self.value = id, label, kind, value
        self.glyph, self.when, self.output, self.confirm = glyph, when, output, confirm

    def __repr__(self) -> str:
        return f"Item({self.id!r})"

    @property
    def args(self) -> list[str]:
        """A meta item's arguments; [] for the other kinds."""
        return list(self.value) if isinstance(self.value, list) else []

    def lifecycle(self) -> tuple[str, str] | None:
        """(coordinator, verb) when this item launches, stops or restarts a coordinator."""
        args = self.args
        if self.kind == "meta" and len(args) == 2 and args[1] in ("launch", "stop", "restart"):
            return args[0], args[1]
        return None


def _item(raw: object) -> Item | None:
    """An item from meta's JSON, or None (logged) when it isn't one crew can run."""
    if not isinstance(raw, dict):
        return None
    ident, label, run = raw.get("id"), raw.get("label"), raw.get("run")
    if not isinstance(ident, str) or not ident or not isinstance(label, str) or not label:
        log.warning(f"menu: an item without an id or a label: {raw!r:.80}")
        return None
    if not isinstance(run, dict) or len(run) != 1:
        log.warning(f"menu: {ident}: run is not exactly one of {', '.join(KINDS)}")
        return None
    kind, value = next(iter(run.items()))
    if kind == "meta":
        ok = isinstance(value, list) and bool(value) and all(isinstance(a, str) for a in value)
    else:
        ok = kind in KINDS and isinstance(value, str) and bool(value)
    if not ok:
        log.warning(f"menu: {ident}: run {kind!r} is not something crew can run")
        return None
    output = raw.get("output", "none")
    when = raw.get("when", "always")
    if output not in OUTPUTS or not isinstance(when, str):
        log.warning(f"menu: {ident}: output {output!r} or when {when!r} not understood")
        return None
    return Item(
        ident,
        label,
        kind,
        list(value) if isinstance(value, list) else str(value),
        glyph=glyph_of(raw.get("glyph")),
        when=when,
        output=str(output),
        confirm=raw.get("confirm") is True,
    )


def parse(data: Any) -> list[Item] | None:
    """The items in `meta <name> menu --json` (its envelope, or `data` alone), in meta's order;
    None if it isn't that shape. An item crew can't run is dropped, as is a repeated id."""
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    out: list[Item] = []
    seen: set[str] = set()
    for entry in raw:
        item = _item(entry)
        if item is not None and item.id not in seen:
            seen.add(item.id)
            out.append(item)
    return out


def ask(name: str) -> list[Item] | None:
    """meta's items for coordinator `name`; None (logged) when meta fails."""
    done = meta([name, "menu", "--json"], timeout=MENU_TIMEOUT)
    if done.returncode != 0:
        log.warning(f"menu: meta {name} menu exited {done.returncode}: {first_line(done.stderr)}")
        return None
    try:
        found = parse(json.loads(done.stdout))
    except ValueError:
        found = None
    if found is None:
        log.warning(f"menu: meta {name} menu gave no items")
    return found


def applies(item: Item, running: bool) -> bool:
    """Whether the item is shown, judged now: meta judged it too, but crew's state is fresher."""
    if item.when == "always":
        return True
    if item.when == "running":
        return running
    if item.when == "stopped":
        return not running
    if item.when.startswith("exists:"):
        return Path(item.when.removeprefix("exists:")).exists()
    log.warning(f"menu: {item.id}: when {item.when!r} not understood, so not shown")
    return False


# ---------------------------------------------------------------- running


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def meta(args: list[str], timeout: float = RUN_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """`meta <args...>` through crew's one meta caller (`metacall`), output kept. When meta
    can't be run, its code (4) and reason come back the same shape, on stderr."""
    done = metacall.call(args, timeout)
    if isinstance(done, metacall.Result):
        return subprocess.CompletedProcess([conf.meta(), *args], done.code, "", done.why)
    return done


def failed(c: Coordinator, item: Item, code: int, stderr: str) -> int:
    """The one failure notice: exit code and the first stderr line."""
    switch.alert(f"{c.name}: {item.label} failed", f"exit {code}: {first_line(stderr) or '-'}")
    return switch.FAILED


def notify_lines(title: str, text: str) -> None:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()][:NOTIFY_LINES]
    body = "\n".join(lines) or "done"
    if len(body) > conf.NOTIFY_BODY_MAX:
        body = body[: conf.NOTIFY_BODY_MAX - 1] + "…"
    switch.notify(title, body, "--hint=string:x-dunst-stack-tag:crew-menu")


def view_dir() -> Path:
    return conf.runtime() / "view"


def _prune(folder: Path, now: float) -> None:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return
    for path in entries:
        try:
            if path.is_file() and now - path.stat().st_mtime > VIEW_KEEP:
                path.unlink()
        except OSError:
            continue


def view(c: Coordinator, item: Item, text: str) -> int:
    """The text in a floating terminal (class crew-view) with a pager. The text goes in a file
    in crew's runtime folder, which the pager reads; files older than an hour are dropped."""
    folder = view_dir()
    now = time.time()
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        _prune(folder, now)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in item.id)
        path = folder / f"{c.name}-{safe}-{os.getpid()}.txt"
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        return failed(c, item, 1, f"cannot write the view: {e.strerror}")
    argv = [
        "alacritty",
        "--class",
        f"{VIEW_CLASS},{c.name}",
        "--title",
        f"{c.name}: {item.label}",
        "-e",
        *PAGER,
        str(path),
    ]
    for needed in ("alacritty", PAGER[0]):
        if shutil.which(needed) is None:
            return failed(c, item, 127, f"{needed} is not on PATH")
    return switch.OK if switch.detach(argv) else failed(c, item, 126, "cannot start alacritty")


def run_meta(c: Coordinator, item: Item) -> int:
    done = meta(item.args)
    if done.returncode != 0:
        return failed(c, item, done.returncode, done.stderr)
    if item.output == "view":
        return view(c, item, done.stdout)
    if item.output == "notify":
        notify_lines(f"{c.name}: {item.label}", done.stdout)
    return switch.OK


def run_open(c: Coordinator, item: Item) -> int:
    url = str(item.value)
    if not url.startswith(SCHEMES):
        return failed(c, item, 2, f"not opened: only {' and '.join(SCHEMES)} links are")
    return start(c, item, ["xdg-open", url], f"opened {url}")


def run_edit(c: Coordinator, item: Item) -> int:
    path = str(item.value)
    if not path.startswith("/"):  # a relative path, or one read as an option
        return failed(c, item, 2, f"not opened: {path!r} is not an absolute path")
    return start(c, item, ["code", path], f"opened {path}")


def start(c: Coordinator, item: Item, argv: list[str], said: str) -> int:
    """A desktop program, detached; `notify` says what it did."""
    if shutil.which(argv[0]) is None:
        return failed(c, item, 127, f"{argv[0]} is not on PATH")
    if not switch.detach(argv):
        return failed(c, item, 126, f"cannot start {argv[0]}")
    if item.output == "notify":
        notify_lines(f"{c.name}: {item.label}", said)
    return switch.OK


def run_copy(c: Coordinator, item: Item) -> int:
    """The text onto the clipboard. xclip forks a child that stays to serve the selection and
    keeps whatever it inherited, so it gets no pipe but stdin: a pipe on stdout or stderr would
    only close when the next copy ends it. Its stderr goes to a file instead."""
    import tempfile

    text = str(item.value)
    argv = ["xclip", "-selection", "clipboard"]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        try:
            # S603: xclip with fixed arguments; the text goes on stdin, never in argv.
            proc = subprocess.Popen(  # noqa: S603
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=err,
                start_new_session=True,
                close_fds=True,
                text=True,
            )
        except OSError as e:
            return failed(c, item, 127, f"xclip: {e.strerror}")
        try:
            proc.communicate(text, timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return failed(c, item, 124, "xclip gave no answer in 5s")
        err.seek(0)
        said = err.read()
    if proc.returncode != 0:
        return failed(c, item, proc.returncode, said)
    # Copying always says what was copied (record 0019 §7a), whatever the output says.
    notify_lines(f"{c.name}: copied", text)
    return switch.OK


RUNNERS = {"meta": run_meta, "open": run_open, "edit": run_edit, "copy": run_copy}


def run(c: Coordinator, item: Item) -> int:
    """Run an item that isn't a stop or a restart; 0 done, 1 failed (notified)."""
    return RUNNERS[item.kind](c, item)

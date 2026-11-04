"""barmenu's menus and how they are shown: rofi, just above the clicked button.

Placement: polybar passes a click no coordinates, so the pointer is read with xdotool when the
menu opens and the window's bottom-left corner put there (less INSET, so the pointer sits over
the glyph column), clamped to the pointer's monitor; the theme's y-offset clears the bar. Without
a pointer the menu falls back to its side's bottom corner.

Bar clicks and polybar's pipes: polybar 3.7 opens its pipes without close-on-exec, so a click
handler can inherit another module's output pipe, and anything long-lived holding it can freeze
the bar's next restart. So `open_menu` first drops inherited pipes (procs.close_inherited)
before rofi starts, and the picked command runs detached in its own session on /dev/null.

Rows come from the TOML, from a provider (`provider = "<name>"`: a Python function in
barmenu/providers/ called when the menu opens, its rows before the static ones) or from a barctl
module's source (`dynamic`, appended). A row marked `current` is passed to rofi as active
(`-a`), which the bar-menu theme styles in the accent; the cursor still starts on the first row.
"""

from __future__ import annotations

import os
import re
import time
import tomllib
from pathlib import Path

from desktop_tools.barmenu import providers
from desktop_tools.common import paths, procs

PACKAGED = Path(__file__).with_name("menus.toml")
RESERVED = ("run", "list")  # barmenu's own commands
THEME = "bar-menu"
WIDTH = 360  # must match window.width in rofi/themes/bar-menu.rasi; passed again so both agree
INSET = 24  # pixels from the menu's left edge to the pointer
MARGIN = 8  # kept from the monitor's edge
ICON_FONT = "Symbols Nerd Font Mono"
MONITOR = re.compile(r"(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)\s+(\S+)$")


class MenuError(Exception):
    """menus.toml can't be read or says something barmenu can't do."""


class Row:
    __slots__ = ("command", "current", "glyph", "label")

    def __init__(
        self, glyph: str, label: str, command: str | list[str], *, current: bool = False
    ) -> None:
        self.glyph, self.label, self.command, self.current = glyph, label, command, current

    def argv(self) -> list[str]:
        """A shell command runs in `zsh -fc`, with the bar's environment, as it did."""
        return ["zsh", "-fc", self.command] if isinstance(self.command, str) else list(self.command)


class Menu:
    __slots__ = ("dynamic", "glyph", "name", "provider", "rows", "settle", "side", "title")

    def __init__(
        self,
        name: str,
        *,
        glyph: str = "",
        title: str = "",
        side: str = "left",
        settle: float = 0.0,
        rows: list[Row] | None = None,
        dynamic: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.name, self.glyph, self.title = name, glyph, title or name
        self.side, self.settle, self.rows, self.dynamic = side, settle, rows or [], dynamic
        self.provider = provider

    def description(self) -> str:
        """The CLI help: it names the provider instead of calling it, so --help runs no query."""
        parts = [f"rows from the {self.provider} provider"] if self.provider else []
        return f"{self.title} menu: " + ", ".join(parts + [r.label for r in self.rows])


def _row(raw: object, where: str) -> Row:
    if not isinstance(raw, dict):
        raise MenuError(f"{where}: a row is a table")
    label, glyph, command = raw.get("label"), raw.get("glyph", ""), raw.get("command")
    if not isinstance(label, str) or not label or not isinstance(glyph, str):
        raise MenuError(f"{where}: needs a label (and a glyph, if any, as text)")
    current = raw.get("current", False)
    if not isinstance(current, bool):
        raise MenuError(f"{where}: current is true or false")
    if isinstance(command, list) and command and all(isinstance(c, str) for c in command):
        return Row(glyph, label, [str(c) for c in command], current=current)
    if isinstance(command, str) and command:
        return Row(glyph, label, command, current=current)
    raise MenuError(f"{where}: command is a shell command or a list of arguments")


def parse(data: dict[str, object]) -> dict[str, Menu]:
    table = data.get("menus", {})
    if not isinstance(table, dict):
        raise MenuError("[menus] must be a table")
    out = {}
    for name, raw in table.items():
        where = f"menus.{name}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or name in RESERVED:
            raise MenuError(f"{where}: not a menu name ([a-z0-9-], not run or list)")
        if not isinstance(raw, dict):
            raise MenuError(f"{where}: must be a table")
        side = raw.get("side", "left")
        if side not in ("left", "right"):
            raise MenuError(f"{where}: side is left or right")
        settle = raw.get("settle", 0)
        if isinstance(settle, bool) or not isinstance(settle, (int, float)) or settle < 0:
            raise MenuError(f"{where}: settle is seconds")
        rows = raw.get("rows", [])
        if not isinstance(rows, list):
            raise MenuError(f"{where}: rows is an array")
        dynamic = raw.get("dynamic")
        if dynamic is not None and not isinstance(dynamic, str):
            raise MenuError(f"{where}: dynamic names a barctl module")
        provider = raw.get("provider")
        if provider is not None and provider not in providers.NAMES:
            raise MenuError(f"{where}: provider is one of " + ", ".join(providers.NAMES))
        if provider is not None and dynamic is not None:
            raise MenuError(f"{where}: a menu takes provider or dynamic, not both")
        glyph, title = raw.get("glyph", ""), raw.get("title", "")
        if not isinstance(glyph, str) or not isinstance(title, str):
            raise MenuError(f"{where}: glyph and title are text")
        out[name] = Menu(
            name,
            glyph=glyph,
            title=title,
            side=str(side),
            settle=float(settle),
            rows=[_row(r, f"{where}.rows[{i}]") for i, r in enumerate(rows)],
            dynamic=dynamic,
            provider=provider,
        )
    return out


def _read(path: Path) -> dict[str, Menu]:
    try:
        with open(path, "rb") as fh:
            return parse(tomllib.load(fh))
    except OSError as e:
        raise MenuError(f"{path}: {e.strerror}") from None
    except (tomllib.TOMLDecodeError, MenuError) as e:
        raise MenuError(f"{path}: {e}") from None


def override_path() -> Path:
    explicit = os.environ.get("BARMENU_CONFIG")
    return Path(explicit) if explicit else paths.config_home() / "barmenu" / "menus.toml"


def load() -> dict[str, Menu]:
    """The packaged menus, then the override's, which add menus or replace them whole."""
    menus = _read(PACKAGED)
    extra = override_path()
    if extra.is_file():
        menus.update(_read(extra))
    return dict(sorted(menus.items()))


# ---------------------------------------------------------------- rofi


def theme_args(name: str | None = None) -> list[str]:
    """-theme <file>, or nothing when it is missing (rofi would refuse to start). `name` is
    another theme (crew's `prompt`); by default the bar menu's, which BARMENU_THEME overrides."""
    theme = name or os.environ.get("BARMENU_THEME") or THEME
    path = (
        Path(theme) if "/" in theme else paths.config_home() / "rofi" / "themes" / f"{theme}.rasi"
    )
    return ["-theme", str(path)] if path.is_file() else []


def place(side: str) -> list[str]:
    """rofi arguments that put the window's bottom-left corner at the pointer, on the pointer's
    monitor; else the menu's side's bottom corner."""
    pointer = procs.query(["xdotool", "getmouselocation", "--shell"])
    monitors = procs.query(["xrandr", "--listactivemonitors"]) if pointer else None
    if pointer and monitors:
        values = dict(line.split("=", 1) for line in pointer.splitlines() if "=" in line)
        try:
            px, py = int(values.get("X", "0")), int(values.get("Y", "0"))
        except ValueError:
            px = py = -1
        for line in monitors.splitlines():
            m = MONITOR.search(line.strip())
            if not m:
                continue
            mw, mh, mx, my = (int(g) for g in m.groups()[:4])
            if mx <= px < mx + mw and my <= py < my + mh:
                x = min(px - mx - INSET, mw - WIDTH - MARGIN)
                x = max(x, MARGIN)
                return [
                    "-m",
                    m.group(5),
                    "-theme-str",
                    "window { location: south west; anchor: south west; "
                    f"x-offset: {x}px; width: {WIDTH}px; }}",
                ]
    if side == "right":
        return [
            "-theme-str",
            "window { location: south east; anchor: south east; "
            f"x-offset: -{MARGIN}px; width: {WIDTH}px; }}",
        ]
    return [
        "-theme-str",
        "window { location: south west; anchor: south west; "
        f"x-offset: {MARGIN}px; width: {WIDTH}px; }}",
    ]


def pango(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def lines(rows: list[Row]) -> list[str]:
    """The rows as rofi shows them: the glyph is part of the text (the theme has no icon
    column), so a row without one starts at the element's padding."""
    out = []
    for row in rows:
        label = pango(row.label)
        if row.glyph:
            out.append(f"<span font_family='{ICON_FONT}'>{pango(row.glyph)}</span> {label}")
        else:
            out.append(label)
    return out


def pick(rows: list[str], args: list[str]) -> str | None:
    """rofi -dmenu over these rows with these arguments: what it printed, or None on Escape, a
    failure or no rofi. The one rofi call barmenu and crew's menus share."""
    import subprocess

    try:
        # S603/S607: a fixed argument list; rofi is found on PATH like every bar command.
        result = subprocess.run(  # noqa: S603
            ["rofi", "-dmenu", *args],  # noqa: S607
            input="\n".join(rows),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    picked = result.stdout.strip()
    return picked if result.returncode == 0 and picked else None


def choose(menu: Menu, extra: list[str] | None = None) -> int | None:
    """Show the menu with rofi; the picked row's index, or None on Escape."""
    if not menu.rows:
        return None
    prompt = f"{menu.glyph} {menu.title}" if menu.glyph else menu.title
    active = [str(i) for i, row in enumerate(menu.rows) if row.current]
    args = [
        "-i",
        "-no-custom",
        "-markup-rows",
        "-format",
        "i",
        *theme_args(),
        *place(menu.side),
        "-p",
        prompt,
        *(["-a", ",".join(active)] if active else []),
        *(extra or []),
    ]
    picked = pick(lines(menu.rows), args)
    if picked is None or not picked.isdigit() or int(picked) >= len(menu.rows):
        return None
    return int(picked)


def with_provider(menu: Menu) -> Menu:
    """The menu with its provider's rows first, then its static rows. A provider never fails
    the menu: it gives state-free rows when its queries fail."""
    if not menu.provider:
        return menu
    return Menu(
        menu.name,
        glyph=menu.glyph,
        title=menu.title,
        side=menu.side,
        settle=menu.settle,
        rows=providers.rows(menu.provider) + menu.rows,
    )


def with_dynamic(menu: Menu) -> Menu:
    """The menu with the rows barctl's source gives for its `dynamic` module appended."""
    if not menu.dynamic:
        return menu
    from desktop_tools.barctl import modules as mods
    from desktop_tools.barctl import ops

    try:
        found = ops.module(menu.dynamic)
    except (ops.Failure, mods.ConfigError):
        return menu
    extra = [Row(r.glyph, r.label, r.command) for r in ops.menu_rows(found)[len(found.menu) :]]
    return Menu(
        menu.name,
        glyph=menu.glyph,
        title=menu.title,
        side=menu.side,
        settle=menu.settle,
        rows=menu.rows + extra,
    )


def open_menu(menu: Menu, extra: list[str] | None = None) -> Row | None:
    """Show a menu and launch the pick, detached. Escape runs nothing (and is no failure)."""
    procs.close_inherited()
    menu = with_dynamic(with_provider(menu))
    picked = choose(menu, extra)
    if picked is None:
        return None
    row = menu.rows[picked]
    settle(menu.settle)
    procs.detach(row.argv())
    return row


def settle(seconds: float) -> None:
    """Let a rofi that has just closed finish closing (its fade, the click that closed it)
    before what follows starts: a screenshot never catches it, a second rofi never gets its
    click. barmenu's picks and crew's Yes/No both wait here."""
    if seconds > 0:
        time.sleep(seconds)


def run(argv: list[str]) -> int:
    """Run a command detached from the bar's pipes (the power button's `barmenu run power menu`)."""
    procs.close_inherited()
    return procs.detach(argv)

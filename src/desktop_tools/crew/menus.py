"""crew's two rofi menus (brain record 0019 §7, §7a).

- **The quick menu** (`crew quick <name>`, a right click on a glyph): one level for one
  coordinator, above the pointer and in barmenu's look (barmenu's own rofi call, theme and
  placement). crew's own Show/Hide comes first, then meta's items in meta's order
  (`items.ask`); more than four repos fold into one "Repos on GitHub" row with a list of its
  own. With meta failing, crew draws Show/Hide, Launch, Stop and Restart from its own state, and a
  line saying the rest is unavailable.
- **The full menu** (`crew menu`, a middle click on the strip and `super + c`): coord's two
  levels, ported. The first lists every coordinator with its state (type its key to filter: `b`
  brain, `pl` platform) and Stop all; the second offers Show or Hide, Start, Stop, Restart.
  Escape on the second level, or No to a question, goes back to the first.

Both run from a click: they drop the pipes polybar left them first (procs.close_inherited), as
barmenu does, and every program they start is detached. Launch, Stop, Restart and Stop all go
through `stopping`, on crew's lifecycle verbs (`life`); the full menu's Start is `crew toggle
--launch`, which shows it too, as coord's Start did.
"""

from __future__ import annotations

from desktop_tools.crew import conf, items, log, registry, stopping, store, strip, switch, wm
from desktop_tools.crew.items import Item
from desktop_tools.crew.registry import Coordinator, Registry

REPOS_FOLD = 4  # more repos than this become a second-level list (record 0019 §7a, item 12)
UNAVAILABLE = "the rest is unavailable (meta failed)"
STOP_GLYPH = "\U000f0667"  # md-stop_circle_outline
CELL_SIZE = 36864  # pango size in 1024ths of a point: 36pt, about 48px
COLOUR_ROLES = {
    "dim": "dim",
    "idle": "fg_dim",
    "busy": "accent",
    "waiting": "urgent",
    "ink": "on_urgent",
}


class Row:
    """A quick-menu row: crew's own action or one of meta's items."""

    __slots__ = ("action", "glyph", "item", "label", "sub")

    def __init__(
        self,
        label: str,
        *,
        glyph: str = "",
        action: str = "item",
        item: Item | None = None,
        sub: list[Row] | None = None,
    ) -> None:
        self.label, self.glyph, self.action, self.item = label, glyph, action, item
        self.sub = sub or []


def _close_inherited() -> None:
    from desktop_tools.common import procs

    procs.close_inherited()


def _shown_and_focused(tree: wm.Tree, reg: Registry, name: str) -> bool:
    win = switch.find(tree, reg, name)
    return win is not None and not win.hidden and tree.focused(win)


def fallback(c: Coordinator, running: bool) -> list[Item]:
    """What crew can offer from its own state alone: record 0019 §7a items 2 to 4."""
    if not running:
        return [Item("launch", "Launch", "meta", [c.name, "launch"], output="notify")]
    return [
        Item("stop", "Stop", "meta", [c.name, "stop"], output="notify", confirm=True),
        Item("restart", "Restart", "meta", [c.name, "restart"], output="notify", confirm=True),
    ]


def quick_rows(c: Coordinator, found: list[Item] | None, running: bool, hide: bool) -> list[Row]:
    rows = [Row("Hide" if hide else "Show", action="toggle")]
    offered = (
        fallback(c, running) if found is None else [i for i in found if items.applies(i, running)]
    )
    repos = [i for i in offered if i.id.startswith("repo-") and i.kind == "open"]
    folded = len(repos) > REPOS_FOLD
    for item in offered:
        if folded and item in repos:
            if item is repos[0]:
                sub = [Row(i.label, glyph=i.glyph, item=i) for i in repos]
                rows.append(Row("Repos on GitHub", action="repos", sub=sub))
            continue
        rows.append(Row(item.label, glyph=item.glyph, item=item))
    if found is None:
        rows.append(Row(UNAVAILABLE, action="none"))
    return rows


def choose(c: Coordinator, rows: list[Row], title: str) -> Row | None:
    """The rows in barmenu's rofi, above the pointer; the one picked, or None on Escape."""
    from desktop_tools.barmenu import menus as bm

    menu = bm.Menu(
        c.name,
        glyph=c.icon,
        title=title,
        side="right",
        rows=[bm.Row(r.glyph, r.label, []) for r in rows],
    )
    picked = bm.choose(menu)
    return None if picked is None else rows[picked]


def act(reg: Registry, c: Coordinator, row: Row) -> int:
    if row.action == "toggle":
        return switch.toggle(reg, c.name)
    if row.action == "repos":
        picked = choose(c, row.sub, f"{c.name}: repos")
        return switch.OK if picked is None else act(reg, c, picked)
    if row.item is None:  # the "unavailable" line: nothing to run
        return switch.OK
    item = row.item
    life = item.lifecycle()
    target = reg.get(life[0]) if life else None
    if life and target is not None:
        return stopping.end(reg, target, life[1], ask_first=item.confirm)
    if item.confirm and not stopping.confirm(f"{c.name}: {item.label}?"):
        return stopping.DECLINED
    return items.run(c, item)


def quick(reg: Registry, name: str) -> int:
    """`crew quick <name>`: 0 done or closed, 1 failed (notified), 2 no such coordinator."""
    c = reg.get(name) if registry.valid_name(name) else None
    if c is None:
        log.error(f"no coordinator {name!r} (crew names lists them)")
        return switch.USAGE
    _close_inherited()
    tree = wm.look()
    found = strip.scan(reg, tree)
    running = c.name in found.running
    rows = quick_rows(c, items.ask(c.name), running, _shown_and_focused(tree, reg, c.name))
    picked = choose(c, rows, c.name)
    if picked is None:
        return switch.OK
    code = act(reg, c, picked)
    return switch.OK if code == stopping.DECLINED else code


# ---------------------------------------------------------------- the full menu


def _theme(name: str) -> list[str]:
    from desktop_tools.barmenu import menus as bm

    return bm.theme_args(name)


def menu_theme() -> list[str]:
    """CREW_MENU_THEME, else crew.rasi, else coord's coord.rasi until the dotfiles rename it."""
    for name in conf.menu_themes():
        found = _theme(name)
        if found:
            return found
    return []


def _pango(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _span(text: str, fg: str | None = None, bg: str | None = None) -> str:
    attrs = "".join(
        f" {k}='{v}'" for k, v in (("background", bg), ("foreground", fg)) if v is not None
    )
    return f"<span{attrs}>{text}</span>" if attrs else text


def cell(
    name: str, glyph: str, key: str, activity: str, shown: bool, colours: dict[str, str]
) -> str:
    """One level-one cell as pango: the glyph large and coloured as the strip colours it, the
    name with its key underlined, and its state small. rofi rows can't hold a newline, so the
    breaks are &#10;. The menu filters by prefix at every word start, so a state word must not
    start with a later coordinator's key: hence "off", not "not running", as coord had it."""
    big = f"<span font_family='Symbols Nerd Font Mono' size='{CELL_SIZE}'> {_pango(glyph)} </span>"
    label = {"off": "off", "busy": "busy", "waiting": "waiting"}.get(activity, "running")
    if activity == "off":
        big = _span(big, colours.get("dim"))
    elif activity == "busy":
        big = _span(big, colours.get("busy"))
    elif activity == "waiting":
        big = _span(big, colours.get("ink"), colours.get("waiting"))
    else:
        big = _span(big, colours.get("idle"))
    if shown:
        label += " · open"
    rest = _pango(name.removeprefix(key))
    named = f"<u>{_pango(key)}</u>{rest}" if key else _pango(name)
    return f"{big}&#10;{named}&#10;<span size='small' fgalpha='55%'>{label}</span>"


def stop_cell(count: int, colours: dict[str, str]) -> str:
    big = f"<span font_family='Symbols Nerd Font Mono' size='{CELL_SIZE}'> {STOP_GLYPH} </span>"
    big = _span(big, colours.get("idle" if count else "dim"))
    return f"{big}&#10;Stop all&#10;<span size='small' fgalpha='55%'>{count} running</span>"


def pick_coordinator(reg: Registry, current: str | None) -> str | None:
    """Level one: the coordinator picked, "--all" for Stop all, None on Escape. The cursor
    starts on `current` (the one just backed out of), else the shown one, else the last."""
    from desktop_tools.barmenu import menus as bm
    from desktop_tools.common import theme

    found = strip.scan(reg)
    colours = theme.roles(COLOUR_ROLES)
    keys = reg.keys()
    names = reg.names
    rows, active, count = [], [], 0
    for i, c in enumerate(reg.coordinators):
        activity = found.activity(c.name)
        count += activity != "off"
        rows.append(
            cell(c.name, c.icon, keys.get(c.name, ""), activity, c.name in found.shown, colours)
        )
        if c.name in found.shown:
            active.append(str(i))
    rows.append(stop_cell(count, colours))
    start = current or next((n for n in names if n in found.shown), None) or store.last()
    row = names.index(start) if start in names else 0
    args = ["-i", "-no-custom", "-markup-rows", "-format", "i", "-matching", "prefix"]
    args += [*menu_theme(), "-p", "Coordinator", "-selected-row", str(row)]
    if active:
        args += ["-a", ",".join(active)]
    picked = bm.pick(rows, args)
    if picked is None or not picked.isdigit() or int(picked) > len(names):
        return None
    return "--all" if int(picked) == len(names) else names[int(picked)]


def pick_action(reg: Registry, c: Coordinator) -> str | None:
    """Level two: toggle, start, stop or restart; None on Escape. A stopped one can only be
    started; a running one's first row reads Hide when a toggle would hide it."""
    from desktop_tools.barmenu import menus as bm

    tree = wm.look()
    activity = strip.scan(reg, tree).activity(c.name)
    state = {"off": "stopped", "waiting": "waiting on you", "busy": "running, busy"}.get(
        activity, "running"
    )
    if activity == "off":
        actions, labels = ["start"], ["Start"]
    else:
        shown = _shown_and_focused(tree, reg, c.name)
        actions, labels = (
            ["toggle", "stop", "restart"],
            ["Hide" if shown else "Show", "Stop", "Restart"],
        )
    args = ["-i", "-no-custom", "-format", "i", *_theme(conf.confirm_theme())]
    args += ["-p", f"{c.name} ({state})", "-selected-row", "0"]
    picked = bm.pick(labels, args)
    if picked is None or not picked.isdigit() or int(picked) >= len(actions):
        return None
    return actions[int(picked)]


def full(reg: Registry) -> int:
    """`crew menu`: 0 done or closed, 1 failed (notified). No to a question goes back."""
    _close_inherited()
    name: str | None = None
    while True:
        name = pick_coordinator(reg, name)
        if name is None:
            return switch.OK
        if name == "--all":
            name = None
            code = stopping.stop_all(reg)
        else:
            c = reg.get(name)
            action = pick_action(reg, c) if c is not None else None
            if c is None or action is None:
                continue
            if action == "toggle":
                code = switch.toggle(reg, c.name)
            elif action == "start":
                code = switch.toggle(reg, c.name, launching=True)
            else:
                code = stopping.end(reg, c, action, ask_first=False)
        if code != stopping.DECLINED:
            return code

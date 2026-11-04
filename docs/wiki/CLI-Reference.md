# CLI Reference

`desktop-tools --help` lists the commands. `desktop-tools <command> --help` shows a command's options.

## Commands

Generated from the code: don't edit, run `uv run scripts/gen-wiki.py`.

<!-- generated:start cli -->
### `desktop-tools barctl alert`

Blink a module, or one segment, for a while.

It blinks between its tier and urgent until the time is up (default 30s; --for 0 stops it).
A second alert extends the first. Blinking needs the controller; without it, the module
shows a steady urgent.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |

| Option | Environment variable | Description |
|---|---|---|
| `--for` |  | How long: 30s, 1m; 0 stops the alert. |
| `--segment` |  | Blink one segment only. |

### `desktop-tools barctl click`

Run what a click on a module does: every action tag calls this.

The module's command for that button, with {target} filled in from its state (so a player
click acts on the player the bar shows), started detached. `right` with no command of its
own opens the module's menu.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |
| `BUTTON` | left, middle, right, scroll-up, scroll-down. |

| Option | Environment variable | Description |
|---|---|---|
| `--segment` |  | The segment clicked. |

### `desktop-tools barctl disable`

Blank a module and stop its source.

Remembered across logins (a printer away for a month). The bar's layout isn't edited.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |

### `desktop-tools barctl doctor`

Check everything barctl needs, each with a fix to try.

One controller; every bar answering IPC, and its protocol version; the polybar config and
modules.toml agreeing; each source's commands; the theme roles; the state folders; no stale
or orphan states. Exit 1 on any problem.

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | JSON instead of text. |

### `desktop-tools barctl enable`

Show a module again and start its source.

Remembered across logins.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |

### `desktop-tools barctl hide`

Hide the bars (bsp-hide calls it).

### `desktop-tools barctl list`

List every module, one per line, sorted.

For completion. --json adds each one's source or pusher, display and whether it is enabled.

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | JSON instead of text. |

### `desktop-tools barctl menu`

Open a module's right-click menu.

Its rows from modules.toml and the rows its source gives (the sinks, the players), drawn by
barmenu (rofi) above the module.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |

### `desktop-tools barctl push`

Set a module's state: the only way another tool changes the bar.

Given fields replace, others keep; --json - reads a whole state, segments included, from
stdin. The module is redrawn only if what it shows changed. Exit 3 if the caller may not
write that module, 5 for an unknown one.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |

| Option | Environment variable | Description |
|---|---|---|
| `--tier` |  | The module's tier. |
| `--glyph` |  | Its icon. |
| `--label` |  | Text beside or instead of the icon. |
| `--count` |  | A count after the glyph. |
| `--detail` |  | A longer line for status and show. |
| `--target` |  | What a click acts on. |
| `--ttl` |  | How long the state holds (30s, 5m); then unavailable. |
| `--source` |  | Who is pushing: the module's pusher ($BARCTL_SOURCE). |
| `--json` |  | `-`: read a whole state, segments included, from stdin. |

### `desktop-tools barctl reload`

Redraw every module, or one, without restarting polybar.

Re-reads modules.toml (the controller too) and the theme roles, then pokes the modules.

| Argument | Description |
|---|---|
| `MODULE` | One module. |

### `desktop-tools barctl render`

Print a module's text for polybar: its hook-0.

Its state with colour and action tags, from the theme roles; an empty line, never an error,
when anything is missing.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |

### `desktop-tools barctl restart`

Restart the bars, or start one when none is running.

Each bar restarts in place; one that froze or exited is relaunched from its own command
line and environment. With no bar running, starts BAR ($POLYBAR_BAR, else main). Bars start
with TOOL_STATS=skip.

| Argument | Description |
|---|---|
| `BAR` | One bar, by name. |

### `desktop-tools barctl run`

Run the controller (barctl.service runs it).

One at a time; every enabled source, the control socket and the alert timers. Exits non-
zero when a source can't be restarted, for systemd to restart it.

### `desktop-tools barctl show`

Show one module in detail.

Its state, detail, target, alert, writer, last change, clicks and menu rows. Exit 5 for an
unknown module.

| Argument | Description |
|---|---|
| `MODULE` | A module, as `barctl list` names it. |

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | JSON instead of text. |

### `desktop-tools barctl status`

Show the controller, the bars and every module.

Whether the controller is running, each bar alive and answering, and every module's tier,
glyph, label, count, writer and age. Exit 1 if the controller or a bar is down or a source
is failing; a device being off is a tier, not a failure. --json gives brain record 0019's
status shape.

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | JSON instead of text. |

### `desktop-tools barctl theme`

Follow a new theme: what `theme apply` calls.

Re-reads the theme roles, then restarts the bars, since polybar reads its ini colours only
at start.

### `desktop-tools barctl unhide`

Show the bars again (bsp-unhide calls it).

### `desktop-tools barctl watch`

Follow state changes as they happen, until interrupted.

One line (or JSON line) per change: for debugging, and for tools that want to react to the
bar.

| Argument | Description |
|---|---|
| `MODULES` | Only these modules. |

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | JSON instead of text. |

### `desktop-tools barmenu layout`

Layout menu: DEFAULT, EVEN, GRID HORIZONTAL, GRID VERTICAL, TALL LEFT, TALL RIGHT, WIDE TOP, WIDE BOTTOM

### `desktop-tools barmenu list`

Every menu's name, one per line (for completion).

### `desktop-tools barmenu run`

Run a command detached from the bar's pipes (setsid, no inherited descriptors).

| Argument | Description |
|---|---|
| `COMMAND` | The command and its arguments. |

### `desktop-tools barmenu screenshot`

Screenshot menu: FULLSCREEN, GEOMETRY, SELECTION, WINDOW, DELAYED…

### `desktop-tools barmenu session`

Session menu: QUIT, COMPOSITOR

### `desktop-tools barmenu settings`

Settings menu: BSPWM, POLYBAR, DOTFILES, SXHKD

### `desktop-tools barmenu vpn`

VPN menu: CONNECT, Disconnect, Information

### `desktop-tools completions`

Write each tool's completion file (`_barctl_cmd`, `_barmenu_cmd`) for this version.

| Argument | Description |
|---|---|
| `SHELL` | The shell: zsh. |

| Option | Environment variable | Description |
|---|---|---|
| `--out` |  | The folder to write them into. |

### `desktop-tools config`

Print the effective configuration and where each value came from. Secrets: set or unset.

| Option | Environment variable | Description |
|---|---|---|
| `--config`, `-c` | `DESKTOP_TOOLS_CONFIG` | Config file (default /etc/desktop-tools/config.yaml; missing is fine). |

### `desktop-tools version`

Print the version.
<!-- generated:end cli -->

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Failure while running |
| 2 | Bad usage or invalid configuration |
| 3 | Refused |
| 4 | Failed: broken config, a command that can't start |
| 5 | Not found |

barctl uses the `meta` codes (brain record 0019): 1 is an answer ("a problem found": `status`, `doctor`), 3 a refusal
(`push` to a module the caller may not write), 4 a failure (`modules.toml` broken, a command that can't start), 5 not
found (an unknown module).

```sh
barctl push crew --source crew --tier alert --label waiting --ttl 10m
barctl alert crew --for 1m
barctl click player-play-pause left     # what the module's action tag runs
barmenu vpn
barmenu run power menu                  # a command detached from the bar's pipes
```

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

Write each tool's completion file (`_barctl_cmd`, `_barmenu_cmd`, `_crew_cmd`) for this
version.

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

### `desktop-tools crew bar`

Push the strip (a cell per coordinator) to barctl's `crew` module and print its line.

Tiers: dim not running, fg_dim idle, accent busy, urgent waiting; the shown one underlined.

| Option | Environment variable | Description |
|---|---|---|
| `--quiet` |  | Push only; print nothing. |

### `desktop-tools crew cycle`

Show the next or previous running coordinator in menu order, wrapping.

Stopped ones are skipped. With none shown, the last one shown comes back (or the first).
With none running, crew says so and exits 1.

| Argument | Description |
|---|---|
| `DIRECTION` | next or prev. |

### `desktop-tools crew guard`

Keep the shown coordinator docked (started detached by every show; exits when none is).

After a drag, a resize or a tiling, the panel goes back to floating at the stored side and
width once bspwm's events settle. A singleton: a second one exits at once.

### `desktop-tools crew hide`

Hide the shown coordinator, focused or not, and give its strip back.

| Option | Environment variable | Description |
|---|---|---|
| `--toggle` |  | With none shown, show the last one shown (or the first), if running. |

### `desktop-tools crew launch`

Start a coordinator through `meta <name> launch`, hidden unless --show.

meta's refusals are meta's (already running, not for this caller, no home): crew says why in
a notification and exits with meta's code.

| Argument | Description |
|---|---|
| `NAME` | A coordinator, as `crew names` lists them. |

| Option | Environment variable | Description |
|---|---|---|
| `--show` |  | Then show it docked (also if it was running). |

### `desktop-tools crew list`

List crew's windows and whether each is hidden or visible.

### `desktop-tools crew menu`

Open the full menu, each coordinator then its actions (middle click, super + c).

Level one lists every coordinator with its state (type its key to filter, as `crew names
--keys` lists them) and Stop all; level two offers Show or Hide, Start, Stop and Restart.
Escape on level two, or No to a question, goes back to level one. Starting and stopping go
through `meta`.

### `desktop-tools crew names`

List the coordinators crew knows, in menu order, from the registry.

| Option | Environment variable | Description |
|---|---|---|
| `--keys` |  | Each with its menu key first. |

### `desktop-tools crew notify`

The waiting notification, run detached by `status`; its click shows the coordinator.

| Argument | Description |
|---|---|
| `NAME` | A coordinator, as `crew names` lists them. |
| `BODY` |  |

### `desktop-tools crew quick`

Open one coordinator's quick menu above the pointer (its glyph's right click).

Show or Hide first, then what `meta <name> menu --json` offers for it, in meta's order:
Launch or Stop and Restart, its home in VS Code, status, inbox, resume notes and more. With
meta failing, Show, Launch, Stop and Restart from crew's own state. Stop and Restart ask
first; the brain coordinator is always asked about.

| Argument | Description |
|---|---|
| `NAME` | A coordinator, as `crew names` lists them. |

### `desktop-tools crew restart`

Restart a coordinator through `meta <name> restart`, shown again if it was shown.

Hidden before, it stays hidden. meta's exit code and reason reach the notification and
crew's exit status.

| Argument | Description |
|---|---|
| `NAME` | A coordinator, as `crew names` lists them. |

### `desktop-tools crew show`

Show a coordinator docked, never hiding it and never starting it (exit 1 if stopped).

| Argument | Description |
|---|---|
| `NAME` | A coordinator, as `crew names` lists them. |

### `desktop-tools crew side`

Print the dock side, or set it, re-docking a shown coordinator.

| Argument | Description |
|---|---|
| `VALUE` | left or right. |

### `desktop-tools crew status`

Claude Code hook: read the hook's JSON on stdin and record the coordinator busy, idle or
waiting. Always exits 0 and prints nothing.

Only sessions under the actors folder count. Entering waiting raises a notification whose
click shows the coordinator; every change refreshes the strip.

| Argument | Description |
|---|---|
| `EVENT` | Overrides the hook's event name. |

### `desktop-tools crew stop`

Stop a coordinator through `meta <name> stop`, or all of them with --all.

meta judges the resume notes and ends the session; not clean, it exits 1 and nothing ends,
unless --force. --all checks each first (`meta <name> stop --check`) and, if any is not
clean, asks once (rofi Yes/No) before stopping them all; declined, nothing stops. meta's
exit code and reason reach the notification and crew's exit status.

| Argument | Description |
|---|---|
| `NAME` | A coordinator, as `crew names` lists them. |

| Option | Environment variable | Description |
|---|---|---|
| `--force` |  | End it even if its resume notes are not clean. |
| `--all` |  | Every running coordinator but the brain coordinator. |
| `--yes`, `-y` |  | With --all: don't ask, stop the unclean ones too. |

### `desktop-tools crew stopped`

The desktop half of a stop, run by the brain's stop script after it ends a session.

Drops the coordinator's state, waits for its window to close, gives the dock strip back and
refreshes the strip. Works without DISPLAY. Exit 1 if a window is still open.

| Argument | Description |
|---|---|
| `NAMES...` |  |

### `desktop-tools crew toggle`

Hide a coordinator if it is shown and focused, else show it docked.

A stopped coordinator is not started: crew says it is stopped and exits 1, unless --launch
is given, which starts it through `meta <name> launch` and shows its window.

| Argument | Description |
|---|---|
| `NAME` | A coordinator, as `crew names` lists them. |

| Option | Environment variable | Description |
|---|---|---|
| `--launch` |  | Start it if it is stopped (the bar glyph's left click). |

### `desktop-tools crew width`

Print the dock panel's visible width, or set it (640 to 2560), resizing a shown panel.

`left` and `right` move the panel's inner edge (by 128, or N): docked right, left widens it;
docked left, left narrows it. A width set but not printed (sxhkd's stdout gone) is not a
failure.

| Argument | Description |
|---|---|
| `VALUE` | N, +N, -N, or left or right to move the inner edge. |
| `STEP` | How far left or right moves it. |

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

crew keeps coord's codes: 0 done, 1 failed or refused (a stopped coordinator shown without `--launch`, a lock busy, a
width that couldn't be written: each says why on stderr), 2 bad usage. `crew status` always exits 0.

```sh
crew toggle --launch desktop            # the glyph's left click: starts it if stopped
crew cycle next                         # the next running coordinator
crew width left                         # move the panel's inner edge left
barctl push crew --source crew --tier alert --label waiting --ttl 10m
barctl alert crew --for 1m
barctl click player-play-pause left     # what the module's action tag runs
barmenu vpn
barmenu run power menu                  # a command detached from the bar's pipes
```

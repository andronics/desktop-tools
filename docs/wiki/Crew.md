# Crew

`crew` is the coordinator switchboard: one hidden terminal per Claude Code coordinator, shown one at a time, docked
to the left or right edge of the screen. It replaces the dotfiles' zsh `coord` (brain record 0019 §7); `coord` stays
live until the cut-over, and for 30 days after it as an alias.

## What it does

- **Show and hide.** `crew toggle <name>` shows a coordinator docked, or hides it if it is the shown and focused one.
  `crew show <name>` only shows. `crew hide` hides whichever is shown; `crew hide --toggle` brings back the last one
  shown when none is. `crew cycle next|prev` steps through the running ones in menu order, wrapping.
- **Showing never starts a coordinator.** A coordinator is running when its window or its tmux session exists. A
  running one with no window gets a window that attaches to its session. A stopped one is not started: crew shows a
  short "<name> is stopped" notification and exits 1. `cycle` skips stopped ones. Only `crew toggle --launch <name>`
  (what a left click on a coordinator's glyph in the bar runs) and `crew launch` start one, through
  `meta <name> launch`.
- **Start, stop and restart.** crew starts and stops coordinators only through `meta <name> launch|stop|restart`
  (record 0019 §3a), never with tmux itself. `crew launch <name>` starts one hidden; `--show` then shows it docked.
  `crew stop <name>` has meta judge its resume notes and end it; `--force` ends it even when they are not clean.
  `crew restart <name>` stops and starts it, and shows it again if it was shown (else it stays hidden).
  `crew stop --all` stops every running coordinator but the brain coordinator: it checks each first
  (`meta <name> stop --check`) and, if any is not clean, asks once with a rofi Yes/No (No selected) before stopping
  them all, the unclean ones with `--force`; `--yes` skips the question. Declined, nothing stops; one that meta
  refuses doesn't stop the rest.
- **meta's rules are meta's.** Who may start or stop which coordinator, the brain coordinator, the resume notes and
  the old names are all decided by meta; crew passes on its answer. A refusal shows a notification with meta's exit
  code and its one-line reason (`desktop: not stopped` / `meta desktop exited 1: <why>`), and crew exits with that
  code: 1 not clean (nothing ended), 2 usage or no home, 3 refused, 4 failed (also when meta can't be run).
- **The dock.** `crew width [N|+N|-N|left [N]|right [N]]` prints or sets the panel's width (640 to 2560, default
  1280); `left` and `right` move its inner edge by 128 or N. `crew side [left|right]` prints or sets the side. While a
  coordinator is shown, its strip of the screen is reserved with bspwm's padding, so tiled windows move aside.
- **The guard.** Every show starts `crew guard`, which puts the panel back after it is dragged, resized or tiled, once
  bspwm's events settle (and never during a drag). It exits once nothing is shown.
- **The strip.** Each coordinator is a cell in the bar: dim when stopped, faint when idle, accent when busy, urgent
  when waiting for an answer, underlined when shown. crew pushes it to barctl's `crew` module; barctl draws it.
- **The Claude hooks.** `crew status` reads a Claude Code hook's JSON on stdin and records the coordinator busy,
  idle or waiting. Entering waiting raises a notification whose click shows it.
- **The stop script's tidy.** `crew stopped <name>` drops a stopped coordinator's state, waits for its window to
  close and gives its strip back. The stop script runs it after it ends a session, so `crew stop` and `crew restart`
  hold no lock while meta runs.

## Where it gets the coordinators

From the registry, never from a list of its own: `meta brain coordinators --json` (record 0019 §4), kept in
`$XDG_STATE_HOME/crew/coordinators.json` and asked again when that copy is five minutes old. When `meta` fails crew
uses the kept copy, and with no copy, the homes in `/pool/local/actors` (each folder with a `README.md`), so a broken
vault never empties the switchboard. A coordinator shows only once its home exists. A coordinator's former names
(`old_names`, until `old_names_until`) still find it, its session and its window. `crew names --keys` lists them with
the menu's filter keys (`b brain`, `pl platform`, `pe personal`).

## Files

| Path | What |
|---|---|
| `$XDG_STATE_HOME/crew/width`, `side`, `last` | The dock's width and side, and the last coordinator shown. The first time crew runs it copies coord's (`$XDG_STATE_HOME/coord/`) where it has none, once |
| `$XDG_STATE_HOME/crew/coordinators.json` | The registry's last good copy |
| `$XDG_RUNTIME_DIR/crew/state/<name>` | idle, busy or waiting, from the hooks |
| `$XDG_RUNTIME_DIR/crew/<lock>.lock` | `switch` (show and hide), `dock` (width and side), `guard` (one guard) |

## Windows

Each coordinator's window is alacritty with class `crew` and the coordinator's name as its instance, running
`tmux attach-session -t =<name>-coordinator`; bspwmrc's rule (`bspc rule -a crew state=floating sticky=on
hidden=on`) makes it floating, sticky and hidden when it opens. Windows of class `coord` are matched too, until
coord's alias goes.

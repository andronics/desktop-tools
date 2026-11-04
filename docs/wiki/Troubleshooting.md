# Troubleshooting

## Diagnostics

- **Effective configuration:** `desktop-tools config` prints every setting and where it came from (default, file, env var). A secret shows only whether it is set (`******** (set)` or `(unset)`), never its value.
- **More logging:** `DESKTOP_TOOLS_LOG_LEVEL=DEBUG`.
- **The bar:** `barctl doctor` checks everything barctl needs and prints a fix for each problem; `barctl status` shows
  the controller, the bars and every module; `barctl watch` shows each change as it happens.
- **Errors and runs:** in the user journal, `journalctl --user -t barctl` or `-t crew` (brain record 0017).
- **crew:** `crew list` shows its windows, `crew names` the coordinators it knows, `CREW_DEBUG=1` its debug lines.

## Common problems

### A module stays dim, or shows an old value

The controller isn't running (`systemctl --user status barctl.service`), or its source's command is missing
(`barctl doctor` says which). A pushed module whose pusher died shows unavailable once its `--ttl` runs out.

### `barctl push` exits 3

The module is drawn by one of barctl's own sources, or belongs to another pusher, or the push didn't say who it is
(`--source <name>` or `$BARCTL_SOURCE`). One writer per module.

### Colours are missing

No current theme: `theme ensure`. barctl writes no colours of its own.

### The bar froze after a restart

`barctl restart` relaunches a bar that doesn't answer within `BARCTL_POLYBAR_WAIT` seconds. Something long-lived that a
click started may hold a polybar pipe: start it through `barctl click` or `barmenu run`, which detach it.

### The theme or lock menu shows no state

`Scheme…`, `Toggle dark/light`, or no lock row marked: the provider's query failed or took over 2 s, so the menu
opened with the rows that name no state. Run the query by hand: `theme current --json` or `lockscreen status --json`
(a dotfiles older than the lock menu has no `--json`).

### `error: cannot read DESKTOP_TOOLS_..._FILE`

The file named by a `_FILE` variable doesn't exist, or the process can't read it. Check the path inside the container or unit, and the file's owner and mode: the process runs as uid 1000 / the `desktop-tools` user.

### crew says "<name> is stopped"

That coordinator has no window and no tmux session, and showing never starts one. Start it with a left click on its
glyph in the bar (`crew toggle --launch <name>`), `crew launch <name> --show`, or `meta <name> launch`.

### crew says "<name>: not stopped" (or not started, not restarted)

meta refused, and the notification gives its exit code and reason. `1` means the coordinator's resume notes are not
clean, so nothing was ended: let it write its PAUSED notes, or `crew stop <name> --force`. `3` is a refusal that is
meta's to make (one only Stephen ends needs his Yes from a clean session, or the caller isn't allowed), `2` a
name with no home, `4` a failure (or meta couldn't be run). `meta <name> status` says more.

### The quick menu says "the rest is unavailable"

`meta <name> menu --json` failed, so crew shows only what it knows itself: Show, Launch, Stop and Restart. Run
`meta <name> menu --json` in a terminal to see why; the reason is also in `journalctl --user -t crew`.

### Stopping the brain coordinator from a menu says "not stopped"

After Yes, crew runs `meta brain stop --confirmed` (or `restart`), and meta takes `--confirmed` only when
`COORDINATOR`, `CLAUDECODE` and `TESSERA_ACTOR` are all unset. A refusal (`exited 3 (refused)`) means the bar or
sxhkd was started from a coordinator's or agent's environment: restart it from a clean session. A terminal works
too: `meta brain stop`. The same goes for the arbiter, and any coordinator the registry marks `ended_by: "stephen"`.

### A quick-menu item says "there is a problem" or "not found"

Neither is a failure. meta's exit 1 is a result whose answer is "there is a problem" (a `status` with a warning):
the output is shown with a ⚠ line first. Exit 5 is "not found". A failure says `failed` with the code and what it
means: `2 (usage)`, `3 (refused)`, `4 (failed)` or `6 (the module is broken)`, then meta's reason.

### crew's strip is missing from the bar

barctl has no `crew` module: `$XDG_CONFIG_HOME/barctl/modules.toml` replaces the packaged one whole, so it needs the
`[modules.crew]` table, and polybar a `custom/ipc` module whose hook is `barctl render crew`. `crew bar` prints what
the strip would show.

### `crew width left` from a key prints nothing

sxhkd's stdout may be a terminal that has gone; the width is still set (`crew width` prints it). Every failure says
why on stderr and in the journal.

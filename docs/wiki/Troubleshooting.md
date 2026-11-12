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

### The capsule shows no progress line

The player gives no length (a stream, a radio station, some browsers), or its position can't be read: `playerctl -p
<instance> metadata mpris:length` and `playerctl -p <instance> position` say which. With no length there is nothing to
measure, so no line. The line moves on by itself while playing and is re-read every 30 seconds, so a seek made in the
player shows within 30 seconds.

### The capsule shows only its icon, or is gone

With `fade_after` set, a capsule whose player has been paused or stopped that many minutes shows its icon alone;
playing again brings it back. With `glyph_override.unavailable = ""`, a capsule with no player draws nothing at all:
`playerctl -l` lists none. Take the key out (or set `fade_after = 0`) and `barctl restart` to undo either.

### `barmenu player` has no speed row, or the 10-second skips on a podcast

The spoken-word rows need `spoken = true` on the capsule and a track it recognises (an episode id or URL, a podcast or
audiobook genre, an `.m4b`/`.aax` file or a `Podcasts`/`Audiobooks` folder); a web podcast in a browser usually gives
none of these, so add the player's name to `spoken_players`. The speed row also needs the player's MPRIS
`MinimumRate` and `MaximumRate`: `busctl --user get-property org.mpris.MediaPlayer2.<instance> /org/mpris/MediaPlayer2
org.mpris.MediaPlayer2.Player Rate MinimumRate MaximumRate` shows them; a range of 1 to 1 hides it.

### The output segment shows no battery, or `barmenu outputs` has no connect rows

The battery comes from BlueZ's `Battery1` on the sink's device: `busctl --system get-property org.bluez <path>
org.bluez.Battery1 Percentage` says whether the headphones give one (many give none, or only with BlueZ's experimental
features on). It is read when the sink becomes the default and every 5 minutes, so a change shows within 5 minutes.
The connect and disconnect rows need `busctl` and BlueZ: `barctl doctor`'s `output segment` line names what is
missing. A device shows only when it is paired and its `Icon` starts with `audio-`.

### Headphones connected but the sound stays on the speakers

barctl never switches the default sink (design record 0003, open question 12): WirePlumber decides, and the segment
shows the 5-second `connected` notice and then the default it chose. Pick the headphones in `barmenu outputs`.

### The printer's detail says "polling: CUPS refused a subscription"

cupsd wouldn't make the printer source's pull subscription (often its `MaxSubscriptions` limit), so the source reads the
queue every 30 seconds (5 with jobs) instead of on events. `barctl doctor` shows it too. Check cupsd's log, then
`barctl restart`.

### A printer action says "Not allowed: CUPS wants an administrator"

cupsd refused the pause, resume or test page for your user. Use `Printer settings` (`system-config-printer`), or add
your user to a group in cupsd's `SystemGroup`.

### The printer or scanner shows "away"

The device can't be reached and nothing waits (switched off, or on another network). For the printer, jobs waiting
make it an alert instead (`not reachable, 2 waiting`). Without `avahi-browse`, presence is checked by a TCP probe every
5 minutes, so it can lag.

### "An agent may not operate the printer or scanner"

`devices` was run with `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR` set, as a bar started from an agent's session
is. Restart the bar from a clean session.

### Clicking the capsule's icon doesn't open the transport row

The row needs three entries on the capsule: `expand_for` above 0, `icon_clicks.left = ["barctl", "expand",
"player-capsule"]` and `segment_clicks.left = ["barctl", "transport", "player-capsule", "{segment}"]` (In-Depth
Configuration). `barctl expand player-capsule` says `expand_for is 0` (exit 3) when the first is missing. It never
opens on a faded capsule or with no player: a click on a faded icon plays, as before. Without the controller the row
still opens and a detached `barctl reload` folds it; `barctl status` says whether the controller runs.

### The transport row's loop or shuffle button shows the old mode

The loop and shuffle buttons draw the `loop` and `shuffle` the player source last read from `playerctl --follow`; a
press runs `playerctl -p <player> loop <next>` or `shuffle toggle`, and the button follows when playerctl prints the
change. If a player changes mode without telling playerctl, the button catches up on its next event (a new track, a
pause). `barctl watch player-capsule --json` prints the state barctl holds, `loop` and `shuffle` with it.

### The visualiser strip turned itself off

`barctl visualiser status` (or `barctl doctor`) says why. **Over its CPU budget**: cava and the controller together
used more than `visualiser_budget` percent of one core (default 6) for three 10-second samples in a row; lower
`visualiser_fps` (or raise the budget), then `barctl visualiser on`. **cava is not installed**: install `cava`, then
`barctl visualiser on`. **cava exited 3 times in 5 minutes**: run `cava` in a terminal to see why it ends (no PipeWire,
no default sink), then `barctl visualiser on`. Turned off with `barctl visualiser off` stays off across restarts until
`barctl visualiser on`. The strip also stands aside, by design, while the player is paused, the transport row is open
or the capsule has faded; and it needs `visualiser = true` on the capsule.

### `modules.toml` fails, and every barctl module is blank, after a downgrade

An older barctl rejects `display = "capsule"`, `"output"` or `"chips"` as an unknown display, and a per-segment click
table (`segment_clicks.<id>`) as an unknown button, which fails the whole file (one from before the transport row
ignores `expand_for` and `icon_clicks`: the icon just plays and pauses; one from before the strip rejects nothing but
ignores `visualiser`). Take `[modules.player-capsule]`,
`[modules.output-capsule]` and `[modules.player-chips]` out of the dotfiles' `modules.toml` (or revert the dotfiles
change that added them) before
downgrading desktop-tools; `barctl doctor` names the key it can't read.

### `barctl doctor` says "the bar runs in an agent's environment"

The controller or a bar was started from a shell with `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR` set (an agent's
or coordinator's session). Menus such as tessera's then refuse to act. Restart it from a terminal outside any agent
session: `barctl restart`, and `systemctl --user restart barctl.service` for the controller.

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

### A menu says "couldn't ask: …"

crew's Yes/No (rofi's `confirm` theme, else `prompt`) closed before it could be answered, twice, so nothing was done and crew
exited 1. The reason is rofi's own line (another rofi running, a keyboard it couldn't grab, no display) or "closed after
… ms": a rofi that opens while the menu's click is still landing takes that click as one outside it. crew waits
0.3 s for it first; each try is a warning in `journalctl --user -t crew`. Try the item again; if it keeps happening,
close any other rofi.

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

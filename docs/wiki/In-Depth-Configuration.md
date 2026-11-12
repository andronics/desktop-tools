# In-Depth Configuration

## Where configuration comes from

Every setting can be given in four places, and the first one that has it wins:

1. `DESKTOP_TOOLS_<KEY>_FILE`: the path of a file holding the value (Docker and Kubernetes secrets)
2. `DESKTOP_TOOLS_<KEY>`: an environment variable
3. the YAML config file: `DESKTOP_TOOLS_CONFIG` or `--config`, default `/etc/desktop-tools/config.yaml`. A missing file is fine.
4. the built-in default

`<KEY>` is the setting's key in upper case, with the dots as underscores: `listen.port` is `DESKTOP_TOOLS_LISTEN_PORT`.
A value of the wrong type, such as `0.5` or `true` for an integer or a list for a string, is an error that names the setting.
`desktop-tools config` prints the effective value of every setting and where it came from, with secrets masked.
The engine is [interpose](https://github.com/metalayerlab/interpose)'s settings loader; `src/desktop_tools/config.py` declares the settings.

## Settings

Generated from the code: don't edit the table, run `uv run scripts/gen-wiki.py`.

<!-- generated:start settings -->
| Key | Environment variable | Default | Description |
|---|---|---|---|
| `log_level` | `DESKTOP_TOOLS_LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `scanner` | `DESKTOP_TOOLS_SCANNER` | *(none)* | The scanner `devices` and barctl's scanner module use: a SANE device name, as `scanimage -L` lists it (`airscan:e0:<name>`). Empty: the one picked in the scanner menu, else the first found (record 0004 §2). |
| `scan_dir` | `DESKTOP_TOOLS_SCAN_DIR` | *(none)* | The default folder scans are saved in. Empty: `Scans` in the Documents folder (`xdg-user-dir DOCUMENTS`), made on the first scan (record 0004 §3). |
<!-- generated:end settings -->

The settings above are the template's, for `desktop-tools` itself. The tools read their own files, below, with the
standard library's `tomllib` (record 0003 §A5), so the bar's hook never loads the settings engine.

### barctl: `modules.toml`

The package ships a default for the live modules (`src/desktop_tools/barctl/modules.toml`);
`$XDG_CONFIG_HOME/barctl/modules.toml` (the dotfiles' `desktop/.config/barctl/modules.toml`), or the file
`$BARCTL_CONFIG` names, replaces it whole: it lists every IPC module.

| Key | Meaning |
|---|---|
| `source` | One of barctl's own sources (`volume`, `player`; `printer`, `scanner`, `vpn`, `bluetooth`, `counter` are reserved) |
| `pusher` | Or: the one outside program allowed to `barctl push` the module (`crew`). Exactly one of the two |
| `display` | `icon` (the glyph, then the count), `text` (the label, cut to 40 characters), `both`, `capsule` (the player's "now playing" module, below), `output` (the output segment beside it, below) or `chips` (one chip per player, below) |
| `glyph` | Shown before anything has written the module |
| `glyph_override` | A glyph that wins over the pusher's or source's: a string (every tier) or a table of tiers (`unavailable`, `idle`, `active`, `alert`; a tier left out shows the pusher's glyph). Precedence for the tier shown (a stale module is `unavailable`): the table's entry, the string, the state's glyph, `glyph`. An empty string hides the glyph. `barctl status --json` gives `glyph_source` (`override-tier`, `override`, `pushed`, `default`) and `glyph_pushed`; `barctl doctor` lists each override (design record 0002 §7) |
| `separator` | Between segments, for a module of several cells |
| `[modules.<m>.clicks]` | `left`, `middle`, `right`, `scroll-up`, `scroll-down` = a command as a list; `{target}` is filled from the state, as a whole argument |
| `[modules.<m>.segment_clicks]` | The same per segment, with `{segment}`; a table under it, `[modules.<m>.segment_clicks.<id>]`, is one segment's own clicks, which win button by button for that cell and fall back to the module's (a list is a command, a table a cell's clicks; the id must be a segment id, `[A-Za-z0-9_.-]`, 64 at most, or the file fails to load naming it) |
| `[[modules.<m>.menu]]` | Right-click rows: `glyph`, `label`, `command`. `right` with no command of its own opens the menu |

`display = "capsule"` (design record 0003 §1-3) draws the `player` source as one module: the play-state glyph (set
per tier with `glyph_override`), then `Artist – Title` padded to a fixed width, scrolling while it plays when it is
longer (one pass round to the start, then a rest), and the track's progress as an underline under the first cells.
These keys are read only for a capsule; a value out of range or of the wrong type is a load error naming the key:

| Key | Default | Meaning |
|---|---|---|
| `width` | 32 | Cells of text after the icon, a whole number 8-80 |
| `scroll` | 2 | Steps a second, 0-4; 0 never scrolls (the title is cut with "…") |
| `scroll_rest` | 10 | Seconds the start of the title rests between passes, 0-120 |
| `accent` | `"role"` | The line's and icon's colour: the theme's `accent`, or `"art"`, the cover's average colour (needs `curl` and ImageMagick's `magick`; one fetch per new cover; a colour under 3:1 against the theme's `bg` falls back to the role). The text keeps the tier's role colour either way |
| `fade_after` | 0 | Minutes the shown player may be paused or stopped before the capsule draws its icon alone, in the `idle` colour, giving its width back to the bar; a whole number 0-240, 0 never (design record 0005 phase B). Playing again (from any player, a key, a chip or a left-click on the icon) brings it back |
| `spoken` | `false` | Podcasts and audiobooks (design record 0005 phase B): `true` lets the source mark spoken word (below), which gives `barmenu player` ±30 s skips and a speed row and moves the line at the player's rate |
| `spoken_players` | `[]` | Player names always taken as spoken word when `spoken = true`, any case, e.g. `["gpodder", "cozy", "kasts"]` |

```toml
[modules.player-capsule]
source = "player"
display = "capsule"
glyph = "\U000F038A"
glyph_override = { active = "\U000F040A", idle = "\U000F03E4", unavailable = "\U000F038A" }

[modules.player-capsule.clicks]
left = ["playerctl", "-p", "{target}", "play-pause"]
middle = ["playerctl", "-p", "{target}", "next"]
scroll-up = ["playerctl", "-p", "{target}", "volume", "0.05+"]
scroll-down = ["playerctl", "-p", "{target}", "volume", "0.05-"]
right = ["barmenu", "player"]
```

The packaged file keeps `player-play-pause` and `player-metadata` and has this capsule as a commented example; the
source writes every player module the same state, so a capsule can run beside the old buttons. `barctl pin
player-capsule <instance>` shows one player until it goes (`--auto` undoes it; `--toggle` unpins it when it is
already the pinned one; a controller restart forgets it).

**Quiet when idle** (design record 0005 phase B). With `fade_after = 10`, a capsule whose player has been paused ten
minutes shows only its `idle` icon; nothing is written then (render works it out from the state's `status_at`), and
the controller pokes it once at that minute. To hide the capsule when there is no player at all, give it
`glyph_override.unavailable = ""`: an empty `custom/ipc` module is not drawn, and the output segment beside it stays.
Both are off in the packaged file and in a capsule without the keys.

**Spoken word.** With `spoken = true`, the shown player plays spoken word (the state's `kind` is `spoken`) when the
first of these matches: the track id or URL names an episode (`spotify:episode:`, `/episode/`); the genre contains
`podcast`, `audiobook`, `audio book` or `spoken`, any case; the URL is a local `.m4b` or `.aax` file, or under a folder
named `Podcasts` or `Audiobooks`; the player's name is in `spoken_players`. Length is not used. Then `barmenu player`
shows `Back 30 s` and `Forward 30 s` in place of the 10-second rows, and `Speed: 1.25×` in place of shuffle, which steps
through 0.75, 1, 1.25, 1.5, 1.75 and 2 within the player's own MPRIS range and back round (hidden when the range is 1
to 1 or can't be read), so the menu stays at eight rows. A miss leaves the music controls; a false match only changes
the skip step and adds the speed row.

`display = "chips"` (design record 0005 phase A) draws the `player` source as one small chip per MPRIS player, just
before the capsule: each player's app icon (from the `player` tool's `instances.json`; `glyph` for a player with
none), in the `active` colour while it plays and `idle` otherwise, in the order each player was first seen (so chips
keep their places). The shown player's chip is underlined in the accent, and the pinned one also carries md-pin. Each
chip is a segment whose id is the player's instance name, so `segment_clicks` act on that player. An instance name
over 64 characters, or one named `more` (the `+N` cell's id), is left out of the chips (it is still in `barmenu players`). Two keys, read only for chips:

| Key | Default | Meaning |
|---|---|---|
| `chips_min` | 2 | Fewer players than this and the module draws nothing, a whole number 1-8 |
| `chips_max` | 4 | At most this many cells; past it the last cell is `+N` (md-dots_horizontal and the count, segment id `more`), a whole number 1-8 |

```toml
[modules.player-chips]
source = "player"
display = "chips"
glyph = "\U000F075A"
chips_min = 2
chips_max = 4

[modules.player-chips.segment_clicks]
left = ["barctl", "pin", "player-capsule", "{segment}", "--toggle"]
middle = ["playerctl", "-p", "{segment}", "play-pause"]
right = ["barmenu", "players"]

[modules.player-chips.segment_clicks.more]
left = ["barmenu", "players"]
```

Left pins that player (a second left-click unpins it), middle plays or pauses that player (not the shown one), right
opens `Players ›`, scroll does nothing. The polybar module is a `custom/ipc` with `hook-0 = barctl render
player-chips` and no `click-*` lines: each chip carries its own action tags. The packaged file has it as a commented
example, so a release changes nothing on the bar until the dotfiles turn it on.

`display = "output"` (design record 0003 §10) draws the `volume` source as the output segment, the second half of the
capsule: the default sink's kind glyph (Bluetooth headphones, other Bluetooth, wired headphones or headset, HDMI, USB,
speakers, from the sink's `pactl -f json list sinks` properties; a `glyph_override` entry for a tier wins over it),
its short name (the dotfiles' `audio/devices.json` name whose `pattern` matches the sink, else `device.nick`, else the
description, cut to 16 characters), a Bluetooth sink's battery (BlueZ's `Battery1.Percentage`, read when it becomes
the default and every 5 minutes), then the volume glyph and percentage; muted, md-volume_off in the idle colour. A
Bluetooth sink appearing shows `<glyph> <name> connected` in place of the name for 5 seconds, and one going `<name>
disconnected`. barctl never switches the default sink: WirePlumber decides, and the segment shows what it chose. No
extra keys.

```toml
[modules.output-capsule]
source = "volume"
display = "output"
glyph = "\U000F0581"

[modules.output-capsule.clicks]
left = ["audio", "mute-toggle"]
scroll-up = ["audio", "volume-increase"]
scroll-down = ["audio", "volume-decrease"]
right = ["barmenu", "outputs"]
```

The packaged file has it as a commented example. `audio-level` and an output segment can run side by side; the source
lists the sinks' properties only when an output segment is configured.

#### The printer and the scanner (design record 0004)

Two modules, `source = "printer"` and `source = "scanner"`, both `display = "icon"` (the glyph, then the count). The
packaged file has them as commented examples; the dotfiles turn them on with their own `glyph_override` for `idle`,
`active` and `unavailable`, leaving `alert` out so the source's reason glyph shows (paper, ink, not found):

```toml
[modules.printer]
source = "printer"
display = "icon"
glyph = "\U000F042A"
glyph_override = { idle = "\U000F042A", active = "\U000F042A", unavailable = "\U000F0E5D" }

[modules.printer.clicks]
left = ["barmenu", "printer-queue"]
middle = ["system-config-printer"]
right = ["barmenu", "printer"]

[modules.scanner]
source = "scanner"
display = "icon"

[modules.scanner.clicks]
left = ["devices", "scan"]        # the remembered preset: the feeder when loaded, else the flatbed
middle = ["simple-scan"]
right = ["barmenu", "scanner"]
```

| Module | Tier | When |
|---|---|---|
| printer | `idle` | The default queue accepting, not paused, no jobs, the printer reachable (`ready`) |
| printer | `active` | A job printing or waiting (`printing`, `2 waiting`); the count is the unfinished jobs |
| printer | `alert` | Paused, not accepting, out of paper, a jam, a cover open, ink empty, a held or stopped job, jobs waiting while the printer can't be reached; a low supply once a day. A new alert blinks once |
| printer | `unavailable` | The printer away with nothing waiting, no queue, or CUPS not running |
| scanner | `idle` | Found (`ready`, `feeder loaded`) |
| scanner | `active` | A scan running (`scanning page 3`); the count is the pages so far |
| scanner | `alert` | The last scan failed (for 10 minutes or until the next), a jam or open cover, or not found while its network is up |
| scanner | `unavailable` | SANE missing, no scanner found, or away |

Ink levels come from the queue's `marker-levels`, named by `marker-names` when the printer gives them, else by the
order it reports them: magenta, cyan, yellow, black (M, C, Y, BK). A driverless (IPP Everywhere) queue reports paper,
ink and jam states; a raw `socket://` queue mostly doesn't.

The scanner menus remember the preset, format, folder and scanner in `$XDG_STATE_HOME/desktop-tools/devices/scan.json`.
The presets: Document (300 dpi, grey, PDF; the default), Colour document (300 dpi, colour, PDF), Text, smallest
(300 dpi, black and white, PDF), Draft (150 dpi, grey, PDF), Photo (600 dpi, colour, PNG). A preset sets the format; a
format picked afterwards wins until another preset is picked. The settings `scanner` and `scan_dir` (above) choose the
scanner and the default folder.

### barmenu: `menus.toml`

The package ships the zsh barmenu's menus (layout, screenshot, settings, vpn, session) and the theme and lock
menus (design record 0001); `$XDG_CONFIG_HOME/barmenu/menus.toml` (or `$BARMENU_CONFIG`) adds menus and replaces
whole menus of the same name.
A menu has `glyph`, `title`, `side` (`left` or `right`, the corner used when the pointer can't be read), `settle`
(seconds to wait after rofi closes), `rows` (`glyph`, `label`, `command`: a shell command run with `zsh -fc`, or a
list of arguments; `current = true` marks a row), and one of `dynamic` or `provider`, never both:

| Key | What |
|---|---|
| `dynamic` | A barctl module whose source's rows are appended |
| `provider` | `theme`, `lock`, `tessera`, `player`, `players`, `outputs`, `printer`, `printer_queue`, `printer_default`, `scanner`, `scanner_presets`, `scanner_folders` or `scanner_devices`: a function in `barmenu/providers/` that gives the menu's rows when it opens, the static `rows` following them. It reads state only through read-only queries with a 2 s limit (`theme current --json`, `lockscreen status --json`, `tessera status --json`, `playerctl -p <shown> metadata --format …`, `playerctl -l`, `pactl -f json list sinks`, BlueZ's `GetManagedObjects`); when one fails, the rows still come, unmarked and with labels that name no state |
| `player`, `players` (menus) | Design record 0003 §4: next, previous, loop and shuffle (marked; hidden when the player gives none), `Player: <name> ›` (opens `players`), back and forward 10 s (when a length is known), all `playerctl -p <shown>` argument lists for the player `player-capsule` shows; with no player, `No player` (runs nothing) and `Player… ›`; the last row is always `Output ›` (below). `players` lists every player, the shown one marked, then `Automatic` (marked when nothing is pinned); a pick runs `barctl pin player-capsule …` |
| `outputs` (menu) | Design record 0003 §10, from the output segment's right-click and the player menu's `Output: <name> ›` row (which shows the segment's kind glyph and name, or `Output… ›`): one row per sink, the default marked (`pactl set-default-sink <sink>`); `Connect <alias>` per paired Bluetooth audio device not connected and `Disconnect <alias>` per connected one (`bluetoothctl connect`/`disconnect <address>`); `Mixer…` (`pwvucontrol`). With BlueZ unreadable the Bluetooth rows are left out. No row pairs, removes, trusts or powers a device |
| `printer`, `printer-queue`, `printer-default` (menus) | Design record 0004 §3: `Queue: 2 jobs…`, `Pause printing` or `Resume printing` (by state), `Default: <queue>…` (two or more queues), `Print a test page…` (asks first), the printer's state (`Network printer: reachable`, a notification with everything), `Printer settings`. The queue lists each unfinished job newest first by number, state and age, never its name; picking one of yours cancels it after a Yes/No; `Cancel all my jobs (n)…` with two or more. Every action row runs `devices printer …` |
| `scanner`, `scanner-presets`, `scanner-folders`, `scanner-devices` (menus) | Design record 0004 §3: `Scan from feeder` (`(loaded)`/`(empty)` when the scanner says), `Scan from feeder, both sides` (a duplex feeder only), `Scan from flatbed`, the preset, the folder (never a full path), `Preview in Simple Scan` (or `Scanner: <model>…` with two or more), the last scan's path and file. Not found, the scan rows become `Find scanners…`. Every scan row runs `devices scan …` |
| `current` (a row's) | Shown as one of rofi's active rows, which the dotfiles' `bar-menu.rasi` colours in the theme's accent; the cursor still starts on the first row. Providers set it from the state they read |

An override can add rows to a provider's menu, for example a 30-minute pause:

```toml
[menus.lock]
glyph = "\uF023"
title = "Lock"
side = "right"
provider = "lock"
rows = [{ label = "Idle lock off for 30 minutes", command = ["lockscreen", "hook-disable", "30m"] }]
```

### Environment

| Variable | What |
|---|---|
| `BARCTL_RUNTIME_DIR` | Module states, the lock, the control socket (default `$XDG_RUNTIME_DIR/barctl`) |
| `BARCTL_SETTINGS_DIR` | Disabled modules (default `$XDG_STATE_HOME/desktop-tools/barctl`) |
| `BARCTL_CONFIG`, `BARMENU_CONFIG`, `BARMENU_THEME` | Another `modules.toml`, `menus.toml`, rofi theme |
| `BARCTL_SOURCE` | Who is pushing, when `push` isn't given `--source` |
| `BARCTL_RETRY` | Seconds before a source whose stream ended is restarted (2) |
| `BARCTL_POLYBAR_WAIT` | Seconds a restarted bar has to answer before it counts as frozen (6) |
| `BARCTL_POLYBAR_CONFIG` | The polybar config `doctor` reads (default `$XDG_CONFIG_HOME/polybar`) |
| `THEME_STATE_DIR` | Where the current theme is (default `$XDG_STATE_HOME/theme`) |
| `CREW_CLASS`, `CREW_OLD_CLASS` | crew's window class (`crew`) and the second one it matches until coord's windows close (`coord`; empty for none) |
| `CREW_ACTORS_DIR` | Where the coordinators' homes are (`/pool/local/actors`) |
| `BRAIN_BIN` | Where crew finds `meta` (`/mnt/brain/bin`; PATH when it isn't there): systemd units, polybar and sxhkd may not have the brain's folder on PATH |
| `CREW_TMUX_SOCKET` | Another tmux server for crew: a path is `-S`, a name `-L` (tests); unset, the default server |
| `CREW_LAUNCH_TIMEOUT` | Seconds crew waits for a window or a lock (10) |
| `CREW_GUARD_SETTLE` | Seconds of quiet after a crew window's last event before the guard re-docks (0.2) |
| `CREW_REGISTRY_MAX_AGE` | Seconds the registry's kept copy is used before `meta` is asked again (300; 0 asks every time) |
| `CREW_BAR_TTL` | Seconds a pushed strip holds before barctl shows it stale (86400: a coordinator may wait hours for an answer, and must still show it) |
| `CREW_MENU_THEME` | The full menu's rofi theme, a name in `rofi/themes` or a path (unset: `crew`, else coord's `coord`) |
| `CREW_CONFIRM_THEME` | The rofi theme of the full menu's second level (`prompt`; the Yes/No questions use `confirm`, else `prompt`) |
| `CREW_DEBUG` | `1`: crew's debug lines on stderr |
| `TOOL_STATS=skip`, `TOOL_JOURNAL=off` | No run record; nothing to the journal (brain record 0017) |

## Secrets

A secret setting is read from all four places, like any other, so nothing stops it being set in the config file or a plain environment variable. Don't: `docker inspect` and `ps` show the variable. Use the `_FILE` variant and mount the value as a file:

- Docker: `DESKTOP_TOOLS_<KEY>_FILE=/run/secrets/<name>` with a secrets file or bind mount
- Kubernetes: a Secret mounted as a volume (SOPS-encrypted in the GitOps repo)
- systemd: `LoadCredential=` and `%d/<name>`

This project has no secrets.

## Examples

A complete config file with every default is in [contrib/desktop-tools.example.yaml](https://github.com/andronics/desktop-tools/blob/main/contrib/desktop-tools.example.yaml).

A pushed module, for crew's coordinator strip (a segment per coordinator, each with its own clicks):

```toml
[modules.crew]
pusher = "crew"
display = "icon"

[modules.crew.segment_clicks]
left = ["crew", "toggle", "--launch", "{segment}"]
scroll-up = ["crew", "cycle", "prev"]
scroll-down = ["crew", "cycle", "next"]
```

A segment may carry `"underline": true` (crew marks the shown coordinator with it), drawn in the theme's `accent`.
The menus (`right = ["crew", "quick", "{segment}"]`, `middle = ["crew", "menu"]`) come with crew's menu.

```sh
barctl push crew --json - --ttl 10m <<<'{"source": "crew", "segments": [{"id": "brain", "tier": "alert", "glyph": "…"}]}'
barctl alert crew --segment brain --for 10s
```

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
| `display` | `icon` (the glyph, then the count), `text` (the label, cut to 40 characters), `both`, or `capsule` (the player's "now playing" module, below) |
| `glyph` | Shown before anything has written the module |
| `glyph_override` | A glyph that wins over the pusher's or source's: a string (every tier) or a table of tiers (`unavailable`, `idle`, `active`, `alert`; a tier left out shows the pusher's glyph). Precedence for the tier shown (a stale module is `unavailable`): the table's entry, the string, the state's glyph, `glyph`. An empty string hides the glyph. `barctl status --json` gives `glyph_source` (`override-tier`, `override`, `pushed`, `default`) and `glyph_pushed`; `barctl doctor` lists each override (design record 0002 §7) |
| `separator` | Between segments, for a module of several cells |
| `[modules.<m>.clicks]` | `left`, `middle`, `right`, `scroll-up`, `scroll-down` = a command as a list; `{target}` is filled from the state, as a whole argument |
| `[modules.<m>.segment_clicks]` | The same per segment, with `{segment}` |
| `[[modules.<m>.menu]]` | Right-click rows: `glyph`, `label`, `command`. `right` with no command of its own opens the menu |

`display = "capsule"` (design record 0003 §1-3) draws the `player` source as one module: the play-state glyph (set
per tier with `glyph_override`), then `Artist – Title` padded to a fixed width, scrolling while it plays when it is
longer (one pass round to the start, then a rest), and the track's progress as an underline under the first cells.
Four keys, read only for a capsule; a value out of range or of the wrong type is a load error naming the key:

| Key | Default | Meaning |
|---|---|---|
| `width` | 32 | Cells of text after the icon, a whole number 8-80 |
| `scroll` | 2 | Steps a second, 0-4; 0 never scrolls (the title is cut with "…") |
| `scroll_rest` | 10 | Seconds the start of the title rests between passes, 0-120 |
| `accent` | `"role"` | The line's and icon's colour: the theme's `accent`, or `"art"`, the cover's average colour (needs `curl` and ImageMagick's `magick`; one fetch per new cover; a colour under 3:1 against the theme's `bg` falls back to the role). The text keeps the tier's role colour either way |

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
player-capsule <instance>` shows one player until it goes (`--auto` undoes it; a controller restart forgets it).

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
| `provider` | `theme`, `lock`, `tessera`, `player` or `players`: a function in `barmenu/providers/` that gives the menu's rows when it opens, the static `rows` following them. It reads state only through read-only queries with a 2 s limit (`theme current --json`, `lockscreen status --json`, `tessera status --json`, `playerctl -p <shown> metadata --format …`, `playerctl -l`); when one fails, the rows still come, unmarked and with labels that name no state |
| `player`, `players` (menus) | Design record 0003 §4: next, previous, loop and shuffle (marked; hidden when the player gives none), `Player: <name> ›` (opens `players`), back and forward 10 s (when a length is known), all `playerctl -p <shown>` argument lists for the player `player-capsule` shows; with no player, `No player` (runs nothing) and `Player… ›`. `players` lists every player, the shown one marked, then `Automatic` (marked when nothing is pinned); a pick runs `barctl pin player-capsule …` |
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

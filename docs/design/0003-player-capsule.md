# 0003: The player capsule: one "now playing" module on the bar, drawn by barctl

<!-- Add a line for this record to the index in docs/design/README.md (CI checks). -->

Status: Proposed
Date: 2026-11-12
Authors: Stephen Cox (direction, 2026-11-12: replace the bar's player group with one large barctl-drawn
module, idea 1 first and ideas 2-5 to follow); written up by the desktop coordinator

## Context

**Today's bar.** The dotfiles' main bar (`desktop/.config/polybar/bars/main`, `modules-right`) has seven
player modules in a row, between `crew` and the audio group:

| Module | Kind | What it does |
|---|---|---|
| `player-previous` | `custom/text` | left `player previous`, right `player seek 10-` |
| `player-stop` | `custom/text` | left `player stop` |
| `player-play-pause` | `custom/ipc`, barctl | the shown player's icon and state; left `barctl click player-play-pause left` |
| `player-next` | `custom/text` | left `player next`, right `player seek 10+` |
| `player-loop` | `custom/text` | left `player loop` |
| `player-shuffle` | `custom/text` | left `player shuffle` |
| `audio-spectrum` | `custom/script` | nothing: its `exec = audio spectrum` and `tail = true` are commented out (in `modules/audio.ini`) |

`desktop/.config/polybar/modules/player.ini` also defines four modules no bar uses: `player-metadata`
(`custom/ipc`, barctl, the "artist: title" label), `player-instance`, `player-seek-backward` and
`player-seek-forward` (whose labels are swapped: "forward" runs `seek 10-`). The dotfiles'
`barctl/modules.toml` has two player entries, `[modules.player-play-pause]` (with `clicks.left = ["player",
"play-pause", "{target}"]`) and `[modules.player-metadata]`. So of the eight things Stephen named
(previous, stop, play-pause, next, loop, shuffle, spectrum, metadata), seven are on the bar, the spectrum
draws nothing, and the metadata is defined but not placed.

Faults in today's group: loop and shuffle act on playerctl's default player, not the one the bar shows
(they pass no target); seek is on a hidden right-click; there is no track title on the bar; six of the
seven are fixed text buttons that never show state.

**The `player` source today** (`barctl/sources/player.py`; the dotfiles' record 0001, question 3): one stream, `playerctl -a --follow metadata --format` with five fields (instance, player name,
status, artist, title). It keeps every player it has seen, shows one (Playing over Paused over Stopped,
then the most recent to change), and writes every module of the source the same state: tier
(`unavailable` with no player, `idle` paused or stopped, `active` playing), glyph (the player's icon then
its state's icon, from the `player` tool's `instances.json` and `states.json`), label (`artist: title`, cut
to 40 characters in the source) and target (the instance, so `{target}` in a click is the shown player).
After every line it runs `playerctl -l` once to forget players that went. It has no position, length,
art, loop, shuffle or rate. Its right-click rows (`menu_rows`) are one per player, each running
`player play-pause <instance>`.

**What a render costs.** Each poke is one polybar IPC message per running bar, and each bar then runs
`barctl render <module>` (the standard-library fast path). Six runs of `barctl render player-metadata`
on this machine, against a test runtime folder: 38, 31, 31, 30, 30, 30 ms. So every redraw is about
30 ms of CPU per bar. Today the player modules redraw only on a player event.

**What barmenu and barctl give** (records 0001 and 0002): menu providers (Python rows when the menu opens,
2 s query limit, state-free rows on failure), the `current` mark, argument-list rows, picks started
detached on `/dev/null`, rofi placed just above the clicked button (the main bar is at the bottom), an
8-line window, and a journal line that names the menu, never a row's arguments. barctl gives
`[modules.<m>.clicks]` for every button (`left`, `middle`, `right`, `scroll-up`, `scroll-down`),
`segments` with per-segment clicks and an underline mark, a controller tick that already pokes blinking
modules twice a second, and `glyph_override` (record 0002 §7), which picks a module's glyph per tier.

`playerctl` is v2.4.1 here. No player was started, stopped or queried for this record.

## Decision

### Phase 1, for approval now: one "now playing" capsule

#### 1. What it looks like and does

One `custom/ipc` module, `player-capsule`, in place of the group:

```text
 ▶  Massive Attack – Teardrop                 (scrolls when longer than the capsule)
 ━━━━━━━━━━━━━━━━━━━━━━──────────────────
```

- **Play-state icon** first: md-play U+F040A playing, md-pause U+F03E4 paused or stopped, md-music_note_off
  U+F038A with no player. Set with record 0002's `glyph_override` per tier (`active`, `idle`,
  `unavailable`), so the source's pushed glyph (app icon and state) still shows on other player modules.
- **`Artist – Title`** (an en dash), in the tier's role colour as every barctl module (`dim`, `fg_dim`,
  `accent`). Longer than the capsule's width, it scrolls (§3); with no player the capsule shows only its
  icon, dim.
- **A thin progress line**: polybar's underline (`%{u<colour>}%{+u}…%{-u}`, height `line-size` from the
  theme) under the first `round(progress × width)` cells of the capsule. Resolution is one cell: a
  4-minute track on a 32-cell capsule moves every 7.5 s. No line when the length is unknown (a stream,
  a player that gives none) or with no player.
- **Accent**: the progress line and the icon take the theme's `accent` role (`accent = "role"`, the
  default), or the art's colour (`accent = "art"`, §5), never the text, which keeps the role colours and
  so the theme's contrast rules (dotfiles record 0004).
- **A fixed width**, padded with spaces to `width` cells, so the bar does not shift as titles change.
  The text font may be proportional; the padding is in characters, so the width is close, not exact
  (open question 9).

Clicks, all on the player the capsule shows (`{target}`), each an argument list run detached by `barctl
click`:

| Button | Runs |
|---|---|
| left | `playerctl -p {target} play-pause` |
| middle | `playerctl -p {target} next` |
| scroll-up / scroll-down | `playerctl -p {target} volume 0.05+` / `0.05-` (open question 3) |
| right | `barmenu player` (§4) |

`playerctl` directly, not the dotfiles' `player` tool: every `player` verb builds a string and `eval`s it,
and each click would pay a zsh start-up. With no player, `{target}` is empty and barctl runs nothing
(as today: `ops` refuses a `{target}` click with no target).

#### 2. The dotfiles entries

```toml
[modules.player-capsule]
source = "player"
display = "capsule"
glyph = "\U000F038A"   # md-music_note_off: before the source has written it
glyph_override = { active = "\U000F040A", idle = "\U000F03E4", unavailable = "\U000F038A" }
width = 32             # cells of text after the icon
scroll = 2.0           # steps per second; 0 cuts with "…" instead
scroll_rest = 10       # seconds the start of the title rests between passes
accent = "role"        # or "art"

[modules.player-capsule.clicks]
left = ["playerctl", "-p", "{target}", "play-pause"]
middle = ["playerctl", "-p", "{target}", "next"]
scroll-up = ["playerctl", "-p", "{target}", "volume", "0.05+"]
scroll-down = ["playerctl", "-p", "{target}", "volume", "0.05-"]
right = ["barmenu", "player"]
```

```ini
[module/player-capsule]
inherit = module/base-ipc-inverse
type = custom/ipc
hook-0 = barctl render player-capsule
click-left = barctl click player-capsule left
click-middle = barctl click player-capsule middle
click-right = barctl click player-capsule right
scroll-up = barctl click player-capsule scroll-up
scroll-down = barctl click player-capsule scroll-down
```

New `modules.toml` keys, all optional and read only for `display = "capsule"`: `width` (integer 8-80,
default 32), `scroll` (number 0-4, default 2), `scroll_rest` (seconds 0-120, default 10), `accent`
(`"role"` or `"art"`, default `"role"`). A value out of range or of the wrong type is a load error naming
the key, as every `modules.toml` mistake. None is secret.

**What goes, once the capsule is on (§7 step 3):**

- From `bars/main`'s `modules-right`: `player-previous`, `player-stop`, `player-play-pause`,
  `player-next`, `player-loop`, `player-shuffle`. `audio-spectrum` stays where it is (open question 2).
- From `modules/player.ini`: every module but `player-capsule` (`player-instance`, `player-loop`,
  `player-metadata`, `player-next`, `player-play-pause`, `player-previous`, `player-seek-backward`,
  `player-seek-forward`, `player-shuffle`, `player-stop`); the file then holds the capsule only.
- From `barctl/modules.toml`: `[modules.player-play-pause]` with its `clicks`, and
  `[modules.player-metadata]`.
- The sxhkd keys that run `player next`, `player play-pause` and `player previous` stay: they act on
  playerctl's default player, which is a separate question (open question 10).

The packaged `modules.toml` in this repository keeps its two player entries (it is the default for a
machine without the dotfiles) and gains a commented `player-capsule` example.

#### 3. Scrolling and the progress line, without extra writes

Render stays a pure function of the state and the time, as the blink already is:

- The **scroll offset** is worked out in `render` from `now` and the time the label last changed:
  one pass at `scroll` cells a second from the start to the end (with a three-space gap before the text
  repeats), then `scroll_rest` seconds resting at the start, then again. It scrolls only while playing;
  paused, stopped, or with `scroll = 0`, the title is cut at `width` with "…".
- The **progress** is worked out from the state's `progress` field (§5): `position + (now - at) × rate`
  while playing, `position` otherwise, over `length`, clamped to 0-1.
- The **controller's tick** pokes a capsule when what it shows would change: the next scroll step while
  scrolling, or the next cell boundary of the progress line, never more than `scroll` times a second and
  never more than once a second for progress alone. It sleeps until the nearer of the two, as it does
  for the blink and for expiries.
- `store.shown` does not count `progress.position` and `progress.at` as "what is shown" (only `length`
  and whether it plays), so the source re-reading the position does not poke the bar by itself.

#### 4. The right-click menu: `barmenu player`

From a new provider, `barmenu/providers/player.py`. It reads the shown player from barctl's state for
`player-capsule` (its `target`), then one query, `playerctl -p <target> metadata --format
'{{status}}<US>{{loop}}<US>{{shuffle}}'` (2 s limit). Rows, in the order Stephen gave:

| # | Glyph | Label | Runs | Shown / marked |
|---|---|---|---|---|
| 1 | md-skip_next U+F04AD | `Next` | `playerctl -p <t> next` | Always |
| 2 | md-skip_previous U+F04AE | `Previous` | `playerctl -p <t> previous` | Always |
| 3 | md-repeat_off U+F0457 / md-repeat_once U+F0458 / md-repeat U+F0456 | `Loop: off` / `Loop: track` / `Loop: playlist` | `playerctl -p <t> loop <next>` (None → Track → Playlist → None) | Marked unless off; hidden when the player gives no loop |
| 4 | md-shuffle_variant U+F049F / md-shuffle_disabled U+F049E | `Shuffle: on` / `Shuffle: off` | `playerctl -p <t> shuffle Off` when on, `On` when off | Marked when on; hidden when the player gives none |
| 5 | md-playlist_play U+F0411 | `Player: <name> ›` | `barmenu players` | Always |
| 6 | md-rewind_10 U+F0D2A | `Back 10 s` | `playerctl -p <t> position 10-` | When the player can seek (a length is known) |
| 7 | md-fast_forward_10 U+F0D71 | `Forward 10 s` | `playerctl -p <t> position 10+` | Same |

- Seven rows fit the 8-line window. Every row is an argument list; the instance comes from barctl's state
  and playerctl's own list, never from a shell string.
- **With no player** (no target, or the query fails or takes over 2 s): one row, `No player`, which does
  nothing, and row 5 (`Player… ›`) so another can be chosen.
- **`barmenu players`**, a second menu (provider `players`, `[menus.players]`), lists `playerctl -l`'s
  instances, each with its icon from `instances.json` (as `menu_rows` does today), the shown one marked,
  then `Automatic` (marked when nothing is pinned). Picking an instance runs `barctl pin player-capsule
  <instance>`; `Automatic` runs `barctl pin player-capsule --auto`. A separate menu keeps the first one
  inside eight rows however many players there are.
- `menus.toml` gets `[menus.player]` (glyph md-music_note U+F0387, title `Player`, side `right`,
  `provider = "player"`) and `[menus.players]` (same glyph, title `Players`, side `right`, `provider =
  "players"`).

#### 5. The `player` source: what it adds

| Today | Added in phase 1 | Why |
|---|---|---|
| instance, name, status, artist, title in the stream | `{{mpris:length}}` and `{{mpris:artUrl}}` in the same stream | the progress line's length; the art accent |
| label `artist: title`, cut to 40 in the source | label `Artist – Title`, whole (up to 200 characters); `display = "text"` and `"both"` cut it to 40 in `render` | the capsule scrolls the whole title; `player-metadata` still shows 40 |
| no position | `playerctl -p <shown> position` once on each event of the shown player, and every 30 s while it plays | the progress line; catches seeks made elsewhere |
| tier, glyph, label, target | a new state field `progress`: `{position, length, rate, at, playing}` (seconds, epoch seconds, a boolean) | the capsule draws position without a write per second |
| | a new state field `accent`: `#rrggbb`, only with `accent = "art"` | the art colour |
| one player shown by rank | `barctl pin <module> <instance>` / `--auto`: the shown player is the pinned one while it is listed | the menu's player choice |

- **Position is not in the follow format.** playerctl may re-print a followed format that contains
  `{{position}}` on a timer (to be measured in the build, with Stephen's player, not by an agent); with
  the source's `playerctl -l` after every line, that would be a process a second. The 30-second
  re-query and interpolation (§3) cost one short `playerctl` run per 30 s while playing.
- **Rate** is taken as 1.0 in phase 1 (MPRIS `Rate`, read by `playerctl -p <t> metadata --format
  '{{rate}}'` if this playerctl has it, is idea 5's); the field is in `progress` already so idea 5 adds no
  new state.
- **Loop and shuffle** are read by the menu when it opens (§4), not followed: nothing on the capsule
  shows them in phase 1. Idea 2 adds them to the stream.
- **The pin** is held by the controller in memory: `barctl pin` sends a `pin` request on the control
  socket, which the source applies at once. It ends when that player leaves `playerctl -l`, on `--auto`,
  or when the controller restarts (open question 8). `barctl pin` on a module whose source is not
  `player` exits 2 with one line. `barctl status --json` gives the player modules `pinned` (the instance
  or null).
- **`state.validate`** takes `progress` (numbers in range, `playing` a boolean) and `accent` (only
  `#` and six hex digits, so no colour can carry a polybar tag) from a pusher as from the source; any
  other shape is a `StateError` naming the field.

**The art accent** (`accent = "art"` only; off by default, open question 5): on a new `mpris:artUrl`,
the source reads it (`file://` read directly; `https://` fetched with `curl --max-time 2 --max-filesize
1048576 --proto =https`, no cookies), into `$XDG_RUNTIME_DIR/barctl/art/<sha256 of the URL>`, at most 20
files, oldest removed first; then `magick <file> -resize 1x1 txt:-` (2 s limit) gives the average colour.
A colour under 3:1 contrast with the theme's `bg` (the non-text contrast rule) or any failure gives no
`accent`, and the role colour shows. One fetch per new art URL, never per redraw.

#### 6. The environment rule

- barmenu and barctl never set, clear or change `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR`, for
  this menu or any click: commands get the bar's environment untouched, as record 0002 §6 says for
  tessera. No player command reads them, so the player menu needs no "Not available" row.
- **The bar is never started from an agent's environment.** No agent runs `barctl restart`,
  `polybar-reload` or `polybar` for this work: the rollout's restarts (§7) are Stephen's. `barctl doctor`
  gains one warning line when the running controller's or a bar's environment (its `/proc/<pid>/environ`,
  same user) has any of the three set: "the bar runs in an agent's environment: restart it from a clean
  session". It names the variable, never its value.

#### 7. Rollout and rollback

1. **desktop-tools** (this repository): §3-6, tests (§8), the wiki; a release. Nothing on the bar changes:
   no packaged module uses `capsule`.
2. **dotfiles, PR A: alongside.** Pin that release; add `[modules.player-capsule]` and its clicks to
   `barctl/modules.toml` and `[module/player-capsule]` to `player.ini`; put `player-capsule` in
   `bars/main`'s `modules-right` just before `player-previous`, with the old six still there. Stephen
   restarts the bar (`barctl restart`) and uses both for as long as he likes.
3. **dotfiles, PR B: replace.** On Stephen's word, remove the old six from `bars/main`, the unused
   modules from `player.ini` and the two old entries from `modules.toml` (§2).

Rollback:

- **During step 2**: remove `player-capsule` from `modules-right` (one word), `barctl restart`. The old
  group never left.
- **After step 3**: revert PR B: the old modules and entries come back unchanged and work with the new
  barctl (the source still writes `player-play-pause`, with its pushed glyph, and `player-metadata`, cut
  to 40 by `render`).
- **Downgrading desktop-tools**: first remove `[modules.player-capsule]` from the dotfiles'
  `modules.toml` (or revert PR A), then downgrade. An older barctl ignores the new keys but rejects
  `display = "capsule"` as an unknown display, which fails the whole file and blanks every barctl module.
  The release notes say so.
- Nothing is stored but the runtime state, the in-memory pin and the art cache in `$XDG_RUNTIME_DIR`,
  all gone at logout.

#### 8. Tests

Unit, no player, no bar (the existing fake-command and fake-poke fixtures):

- **Source**: the new format's fields parsed; `progress` written on an event and refreshed by the
  30-second query (a fake clock), with no poke when only `position`/`at` change; the label whole, en
  dash, and the 200-character cap; a fake `playerctl` that fails the test if called with `play`,
  `pause`, `play-pause`, `stop`, `next`, `previous`, `position <n>`, `loop <mode>`, `shuffle <mode>` or
  `volume`, so no source or provider code can control a player.
- **Pin**: a pinned player shown over a Playing one; the pin dropped when the player leaves the list and
  on `--auto`; `barctl pin` on a non-player module exits 2; the `pinned` status field.
- **Render**: `display = "capsule"`: padding to `width`; the scroll offset at chosen times (start, mid
  pass, end, rest) for a long label, none paused or with `scroll = 0` (cut with "…"); the underline
  covering `round(progress × width)` cells, none without a length; the accent hex on the underline and
  icon, never on the text; `%{` in a title escaped; `text` and `both` still cut to 40.
- **Controller tick**: the next wake time while scrolling, at a progress cell boundary, and both at once;
  never above `scroll` a second; no wake for a paused capsule.
- **modules.toml**: each new key's range and type errors; `capsule` with none of them gets the defaults.
- **State**: `progress` and `accent` validated; a bad `accent` (`#fff`, `red`, `#12345g`, with `%{`) is a
  `StateError`.
- **Art**: `file://` and `https://` (a fake `curl` and `magick`), the cache cap, a low-contrast colour
  dropped, a failure giving no `accent`, one fetch per URL.
- **barmenu providers**: `player` rows for loop None/Track/Playlist and shuffle on/off, the hidden rows
  when a field is empty, the no-player and timeout rows, each row's exact argv (an argument list with
  `-p <target>`); `players` rows, the marks and the `barctl pin` argv; `barmenu --help` names both
  without calling them.
- **Environment**: no row or click argv sets or unsets the three variables (the provider's rows and the
  `ops` click path, with each set and unset); `doctor`'s warning with a fake `/proc` whose environ has one
  set, and that it prints the name only.
- Every existing source, render, ops and status test passes unchanged.

Live, after dotfiles PR A, by Stephen (no agent touches a player or the bar): the capsule shows the
track and its progress; each click and scroll does what §1 says; the menu's loop and shuffle rows change
state and show it on the next open; `Back 10 s` moves the line back; choosing a second player in
`Players ›` switches the capsule; `journalctl --user -t barmenu -t barctl --since -10m` names menus,
modules and buttons and no track; `top` shows `barctl render` at about the expected rate (§9) while a
long title scrolls.

#### 9. Data, rates and privacy

- **Rates**: scrolling at most 4 steps a second (2 by default) and only while playing; progress at most
  once a second (in practice once per cell, every few seconds); position re-read every 30 s while
  playing; art once per new URL. At about 30 ms per render (Context), a long title at the default 2 steps
  a second costs about 60 ms of CPU a second per bar while it scrolls; with the 10-second rest, a
  60-character title in 32 cells scrolls 14 s of every 24, about 35 ms a second on average. A title that
  fits costs one render every few seconds. Every poke is one IPC message per bar.
- **Privacy**: the track (artist, title) lives only in the module's state file in `$XDG_RUNTIME_DIR`
  (0700, a tmpfs, emptied at logout), as `player-metadata`'s does today. barctl's journal lines name the
  module and button, never the label; render's error lines name the module; the provider logs nothing of
  the player's state, and barmenu's line names the menu. Art files sit in the same runtime folder. The
  art fetch, when on, goes only to the URL the player itself gives, which it has already fetched.
  `barctl status` shows the label to the user's own processes, as it does today.

### Roadmap, not for approval now

Each idea gets its own record when it comes up. What each needs from phase 1, so phase 1 does not block
it:

#### Idea 2: an expanding transport row

A click (left-click held, or a new `expand` row in the menu) widens the capsule for a few seconds into a
row of buttons (previous, play-pause, next, loop, shuffle, seek), then it folds back. Needs: the capsule
able to draw `segments` (barctl already draws segments with `segment_clicks`, so the expanded row is the
capsule's state with segments, and the capsule's own keys stay the folded look); a timed state (the
existing `expires`/ttl, so the controller folds it back); loop and shuffle in the source's stream, so
their buttons show state. Phase 1 keeps the capsule one module with its clicks in `modules.toml`, which
is what `segment_clicks` builds on.

#### Idea 3: a visualiser-led strip

A spectrum strip beside or behind the title. **Measure first**: barctl's sustained push and render rate
(pokes a second per bar, CPU per render, polybar's own redraw cost) against cava's 20-60 frames a
second. At 30 ms a render, barctl through IPC tops out near 10 frames a second on one core, so the
likely shape is a `custom/script` with `tail = true` fed straight from cava's FIFO (what
`audio-spectrum` was meant to be), drawn only while playing, with barctl only deciding when it shows.
Needs from phase 1: a fixed-width capsule (so a strip can sit next to it without moving it) and the
`active` tier as the "playing" signal; `audio-spectrum` left alone until then (open question 2).

#### Idea 4: multi-player switcher chips

One small chip per player (its app icon), the shown one underlined, click to show it. Needs: the pin
(phase 1 adds it), the source's map of every player (it keeps one already), and `segments` with
`underline` (barctl has them, crew uses them). Phase 1's `Players ›` menu becomes the fallback when
there are more chips than fit.

#### Idea 5: context-aware visibility

After 10 minutes paused, the capsule fades to its icon alone; it comes back on play. For podcasts and
audiobooks, the seek rows become ±30 s (md-rewind_30 U+F0D96, md-fast_forward_30 U+F0D06) and a speed row
appears (md-speedometer U+F04C5, MPRIS `Rate`). Needs: when the status last changed (phase 1's
`progress.at` and the label-change time render already uses), a controller wake at the 10-minute mark
(the tick already sleeps to the next change), `rate` in `progress` (phase 1 has the field), and a way to
tell a podcast (the track id or URL in the stream, for example Spotify's `spotify:episode:`), which the
source can add to its format without a state change.

## Alternatives considered

- **Keep the buttons and add the title.** Least work, but the bar keeps six stateless buttons, and loop
  and shuffle still act on the wrong player. Lost to one module with the rare actions in a menu.
- **The capsule as a `custom/script` with `tail = true`** (a script printing frames). Scrolling is easy,
  but it leaves barctl's state, theme colours, escaping and clicks, and a long-running script holding
  polybar's pipe is what froze bar restarts before (barmenu's close-inherited fix). Lost.
- **The source writes a new label for every scroll step.** Works with today's render, but a state write
  and a `store` diff per step, and a stale frame survives a controller crash. Lost to render working the
  offset out from the time (§3), as the blink does.
- **Progress as block characters** (`▁▂▃` or `━━──` as text). Takes a second line's worth of width or
  shares the title's. Lost to the underline, which costs no width.
- **`{{position}}` in the follow format.** See §5: a likely per-second line. Lost to a 30-second re-query
  plus interpolation.
- **barctl's own right-click menu** (`[[modules.player-capsule.menu]]` rows plus the source's
  `menu_rows`). No marks for loop and shuffle and no state in labels. Lost to a barmenu provider, as for
  record 0002.
- **One menu with every player in it.** Overflows eight rows with two players. Lost to `Players ›`.
- **The `player` tool for clicks** (`player next {target}`). It works, but each verb `eval`s a string and
  starts zsh. Lost to `playerctl` argument lists.
- **A new bar variant (`bars/main-capsule`) for the trial.** Clean A/B, but switching needs the bar
  stopped and started under another name. Lost to both side by side on the main bar (open question 4).
- **Art colour as the text colour.** Breaks the theme's contrast rules on dark art. Lost to the art
  colouring only the line and icon.

## Consequences

- The bar's player group becomes one module; the rare actions (loop, shuffle, seek, player choice) move
  to a right-click menu, one click further away. Stop leaves the bar (pause does the same for every
  player that matters; open question 7).
- barctl gains a display (`capsule`), four module keys, two state fields, a control request and a CLI
  verb (`barctl pin`), and a timer in its tick. barmenu gains two providers and two menus.
- The source's label changes from `artist: title` to `Artist – Title`, whole; `player-metadata` users
  see the dash, still cut to 40.
- While a long title scrolls the bar redraws twice a second (§9).
- `accent = "art"` needs `curl` and ImageMagick's `magick` on `PATH`; `barctl doctor` says when either is
  missing while a module asks for art. The role accent needs neither.
- A stopped player shows the pause icon: the tiers do not tell paused from stopped.
- Rollback is a dotfiles change (§7); downgrading desktop-tools needs the capsule out of `modules.toml`
  first.
- Wiki: CLI-Reference (regenerated: `barctl pin`, `barmenu player`, `barmenu players`),
  In-Depth-Configuration (the `capsule` display and its keys; the two providers), Architecture-Internals
  (the source's new fields, the tick's capsule timer, the pin), Security (the art fetch's limits, the
  environment rule, nothing of the track logged), Troubleshooting ("my modules.toml fails after a
  downgrade"; "the capsule shows no line": no length; the doctor's environment warning), Testing-Guide
  (the player-control guard in the fake playerctl; the fake clock for scroll and progress).

## Open questions

1. **Phase 1's shape.** (a) One capsule as §1-5, the rare actions in `barmenu player`; (b) the capsule
   plus previous and next buttons kept beside it. Recommendation: **(a)**: middle-click is next, and
   the menu has previous; two buttons more brings back the row this replaces.
2. **The spectrum.** (a) Keep `audio-spectrum` as its own module, unchanged, for now; (b) remove it now
   (it draws nothing); (c) fold it into the capsule now. Recommendation: **(a)**: it is
   inert, and idea 3 decides its future after the rate is measured; removing it is a one-word
   change then.
3. **What scrolling changes.** (a) The player's own volume (`playerctl volume 0.05±`); (b) the default
   sink's (`audio volume-increase`/`-decrease`, as `audio-level`). Recommendation: **(a)**: the sink is
   already one module over, and the capsule is the player's. Some players ignore MPRIS volume; if
   Stephen's does, switch to (b) in `modules.toml` alone, no code.
4. **The trial.** (a) Capsule and old group side by side on the main bar (PR A), then PR B; (b) a bar
   variant `main-capsule`, started instead of `main`. Recommendation: **(a)**: one restart, both in
   front of him, and rollback is one word.
5. **The art accent.** (a) Build `accent = "art"` in phase 1, off by default, with `file://` and
   `https://` (§5); (b) `file://` only; (c) role accent only, art later. Recommendation: **(a)**: it is
   self-contained and off until he turns it on; (b) would rarely help, since Spotify's art is
   `https://`.
6. **How titles scroll.** (a) One pass, then 10 s resting at the start, while playing; (b) scroll all the
   time while playing; (c) never: cut with "…". Recommendation: **(a)**: readable, and about half the
   redraws of (b).
7. **Stop.** (a) No stop anywhere on the capsule or its menu; (b) a `Stop` row in the menu (eight rows).
   Recommendation: **(a)**: pause covers it, and the menu stays at seven.
8. **The pin's life.** (a) In memory, ends with the player or a controller restart; (b) saved in
   barctl's settings across restarts. Recommendation: **(a)**: a saved pin to a player that comes back
   days later would surprise.
9. **Width.** (a) 32 cells; (b) 40, as the metadata cut; (c) Stephen picks after the trial.
   Recommendation: **(a)** to start, then (c): the right side is already full, and the key changes it
   without code.
10. **The sxhkd media keys.** (a) Leave them on playerctl's default player; (b) point them at the
    capsule's player (`barctl click player-capsule left` and `middle`). Recommendation: **(b)**, in
    PR B: keys and bar then act on the same player. Its own small change, not needed for phase 1.

## Change log

| Date | Change |
|---|---|
| 2026-11-12 | Proposed by the desktop coordinator |

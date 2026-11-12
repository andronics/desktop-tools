# 0005: The player capsule's roadmap: player chips, quiet when idle, a transport row and a visualiser strip

<!-- Add a line for this record to the index in docs/design/README.md (CI checks). -->

Status: Proposed (phases A-C: Approved and built; phase D: Proposed)
Date: 2026-11-12
Authors: Stephen Cox (direction, 2026-11-12: ideas 2-5 of record 0003 approved, all four; the old
`audio-spectrum` module dropped; the old player buttons already retired on his bar); written up by the
desktop coordinator

**Stephen approved the four ideas on 2026-11-12** ("3 all 4 approved"). This record is the design each
one needs before code: one record, four phases, in the build order it recommends. It changes nothing in
records 0001-0004; phase 1 of record 0003 (the capsule) and its §10 (the output segment) are built and
live, and every phase here builds on them.

## Context

**The bar today.** Stephen's working copy of the dotfiles' main bar (`desktop/.config/polybar/bars/main`,
read only for this record) has `modules-right = crew spacer-corner-rt player-capsule output-capsule
spacer-corner-lb bluetooth-status sys-time sys-date`: the old six player buttons and `audio-spectrum` are
gone from it, and the printer and scanner modules sit on the left. `[module/audio-spectrum]` is still
defined in `modules/audio.ini` (its `exec = audio spectrum` commented out), drawn by no bar.

**What barctl gives** (this repository, `origin/main` at release 0.1.12):

- `display = "capsule"` (`render.capsule`): the play-state icon (per tier with `glyph_override`), the
  label padded to `width` cells, scrolling while it plays, the progress as an underline under the first
  cells. Render is a pure function of the state and the time; `render.next_change` tells the
  controller's tick when the frame next changes, and the tick pokes it then (`controller.capsules`).
- **Segments**: a state may hold `segments`, a list of cells `{id, tier, glyph, label, alert_until,
  underline}`. Render draws each in its tier's role colour, joined by the module's `separator`, each
  wrapped in its own action tags (`barctl click <module> <button> --segment <id>`); `barctl click` runs
  `segment_clicks[<button>]` with `{segment}` filled with the cell's id and `{target}` with the state's
  target. Today one command per button serves every cell (crew's strip uses it). When a state has
  segments, render draws them in place of the module's display, the capsule's too.
- **`glyph_override`** (record 0002 §7): a glyph per tier that wins over the source's; an empty string
  hides the glyph. A capsule with no player draws its icon only, so `unavailable = ""` already draws
  nothing.
- **The `player` source**: one `playerctl -a --follow metadata --format` stream (instance, name,
  status, artist, title, `mpris:length`, `mpris:artUrl`), a map of every player it has seen, one shown
  (the pin from `barctl pin`, else Playing over Paused over Stopped, then the most recent to change),
  the position re-read every 30 s while playing, `rate` fixed at 1.0. Every module of the source gets
  the same state.
- **The controller** runs as the user service `barctl.service`; its tick blinks, expires, and pokes
  capsules and output segments when their frame changes, sleeping to the next change.
- **The cost of a frame**: one IPC message per bar, then `barctl render <module>` in a new process,
  about 30 ms of CPU per bar per redraw (record 0003, Context).

**What polybar gives** (3.7.2 here, its installed CHANGELOG): action tags for buttons 1-5 (left,
middle, right, scroll up, scroll down) and 6-8 (double-clicks). **There is no hover**: no enter, leave
or motion action for a module. A module with a double-click action makes every single click on it wait
the `double-click-interval` (400 ms by default) to tell the two apart. `custom/ipc` has, besides
`hook.<n>`, a **`send.<data>`** action (since 3.6.0) that shows the given text, format tags and all,
with no hook process. A `custom/ipc` module whose output is empty is not drawn. A module's width is its
text's: when it changes, polybar lays its block out again; a right-aligned block grows or shrinks to the
left, so modules to the left of the one that changed move.

**Tools here**: `cava` 0.10.7 (PipeWire input, raw ASCII output), `playerctl` 2.4.1, `pw-record`,
`parec`. Codepoints in this record were checked in the installed Symbols Nerd Font by glyph name.

No player, audio stream, Bluetooth device or bar was started, stopped, queried or changed for this
record. The reads were: the bar file above, `git diff --stat` of the dotfiles' polybar folder,
polybar's CHANGELOG and the man pages.

## Decision

### Build order

| Order | Idea | Phase | Why here |
|---|---|---|---|
| A | 4 | Player chips | Smallest: segments, `segment_clicks` and the pin all exist; it adds per-segment click tables, which C reuses, and a per-display state from the player source |
| B | 5 | Quiet when idle, spoken-word controls | Small and useful every day; adds `status_at` and `kind`, which C uses for its skip step; the "hide" half needs no code |
| C | 2 | Transport row | Needs A's per-segment clicks and B's `kind`; a new capsule mode with a timed state; most taste in it |
| D | 3 | Visualiser strip | Gated by its own experiment, which may say no; off by default; must stand aside for C's row and B's fade |

D's experiment (§D1) builds nothing in barctl and touches no live bar or audio, so it may run at any
time, beside A; only D's build waits for its numbers. Each phase is its own PR (or two) with its own
release, and each can stop after it ships without leaving the next half-built.

### Phase A (idea 4): player chips

Status: Approved (Stephen 2026-11-12, arbiter standing rule), built; open questions 11-13 and the chips' share of
6 and 19 answered as recommended.

**What it looks like.** A new module, `player-chips`, just before `player-capsule` in the same unit: one
small chip per MPRIS player, its app icon (from the `player` tool's `instances.json`, as today's glyph),
in the `active` role colour while it plays and `idle` otherwise. The chip of the player the capsule
shows is underlined in the accent (as crew marks the shown coordinator); when that player is pinned, its
chip also carries md-pin U+F0403 as its label.

```text
 [spotify] [firefox]  ▶  Massive Attack – Teardrop          [headphones] Headphones 45%
 ━━━━━━━━━                                                  (the underline marks the shown player)
```

**The entries.**

```toml
[modules.player-chips]
source = "player"
display = "chips"
chips_min = 2          # fewer players than this: the module draws nothing
chips_max = 4          # more: the last cell is "+N", which opens barmenu players

[modules.player-chips.segment_clicks]
left = ["barctl", "pin", "player-capsule", "{segment}", "--toggle"]
middle = ["playerctl", "-p", "{segment}", "play-pause"]
right = ["barmenu", "players"]

[modules.player-chips.segment_clicks.more]   # one cell's own clicks (new, below)
left = ["barmenu", "players"]
```

```ini
[module/player-chips]
inherit = module/base-ipc-inverse
type = custom/ipc
hook-0 = barctl render player-chips
```

(Segments carry their own action tags, so the polybar module needs no `click-*` lines.)

**Clicks.** Left pins that player (`barctl pin`, record 0003 §5); `--toggle`, new, unpins (back to
automatic) when that player is already the pinned one, so a second click undoes the first. Middle plays
or pauses that player, not the shown one. Right opens `Players ›`. Scroll does nothing.

**Per-segment click tables (new in `modules.toml`).** Today `segment_clicks` is one table of
button = command. It gains, optionally, tables keyed by a segment id (`segment_clicks.<id>.<button>`)
that win for that cell, falling back to the button-level command. A list is a command and a table is a
cell's own clicks, so the two cannot be confused; the id must pass `valid_segment` (a load error names
it otherwise). crew's strip is unchanged. Phase C reuses it.

**How the source grows.** It already follows every player in one stream and keeps the map; what changes:

- `Player` gains `first`, the order it was first seen in, so chips keep their places (rank would make
  them jump on every play and pause).
- `update` writes, for each module with `display = "chips"`, `segments` (one per player, by `first`,
  the shown one `underline: true`) and no label; every other module gets what it gets today.
  `store.shown` already compares segments, so a chip change pokes the chips only, and a new title
  pokes the capsule only.
- No new process, query or timer: positions are still read for the shown player only.

**Limits.** At most `chips_max` (1-8, default 4) chips; past that the last cell is `+N`
(md-dots_horizontal U+F01D8 and the count, id `more`). A segment id is the instance name; MPRIS names
are `[A-Za-z0-9_-]` parts joined by dots, which `valid_segment` takes, but one over 64 characters is left
out of the chips (still in `Players ›`). Browsers can expose one player per tab or process, which is
what the cap is for. The chips' width changes when a player comes or goes, so the unit moves then (rare,
and once). `playerctl -a --follow` sees players that start later; one that never sends MPRIS events
shows from its first one.

### Phase B (idea 5): quiet when idle, spoken-word controls

Status: Approved (Stephen 2026-11-12, arbiter standing rule), built; open questions 14-18 and phase B's share
of 19 answered as recommended. Spoken word is behind its own capsule switch, `spoken` (default false), so that
a release changes nothing for a capsule without the keys (question 19).

**Fade after N minutes paused.** With `fade_after = 10` (minutes, 0-240; 0 never, the packaged default),
a capsule whose shown player has been paused or stopped that long draws its icon alone, in the `idle`
role colour (`fg_dim`), and gives its width back to the bar. It comes back on play (from any player, the
keys, a chip, or a left-click on the faded icon, which is play-pause as before). Render works it out from
a new state field, `status_at` (epoch seconds: when the shown player's status last changed, or another
player became the shown one), so nothing is written at the 10-minute mark; `next_change` returns
`status_at + fade_after` for an idle capsule, so the tick pokes once then. The source keeps a
`changed_at` per player. The bar lays out again twice: at the fade and at play.

**Hide when nothing plays.** With no player at all, the capsule draws only its icon; giving it
`glyph_override.unavailable = ""` (record 0002 §7) makes that nothing, and polybar does not draw an
empty `custom/ipc` module. **No code**: a dotfiles line. The output segment stays, so the unit keeps its
background and corners.

**Podcasts and audiobooks.** The stream gains three fields, `{{mpris:trackid}}`, `{{xesam:url}}` and
`{{xesam:genre}}`, and the source works out a new state field `kind`, `"spoken"` or `""`, from the first
rule that matches:

1. the track id or URL names an episode (`spotify:episode:`, `/episode/`);
2. the genre (a list, joined by playerctl) contains `podcast`, `audiobook`, `audio book` or `spoken`,
   ignoring case;
3. the URL is a local file ending `.m4b` or `.aax`, or under a folder named `Podcasts` or
   `Audiobooks`;
4. the player's name is in `spoken_players` (a list on the capsule, default empty; for example
   `["gpodder", "cozy", "kasts"]`).

Limits: players fill these fields unevenly (a browser playing a web podcast usually gives neither genre
nor URL; Spotify's episode ids are the most reliable signal), so a miss leaves music controls and a
false match only changes the skip step and adds a speed row. Length is not used: long mixes would match.
Only `kind` is kept; the track id, URL and genre are read and dropped (Privacy).

**What changes when `kind` is spoken.**

- `barmenu player`: rows 6-7 become `Back 30 s` (md-rewind_30 U+F0D96, `playerctl -p <t> position
  30-`) and `Forward 30 s` (md-fast_forward_30 U+F0D06, `position 30+`); the shuffle row (meaningless
  for an episode) becomes `Speed: 1.25×` (md-speedometer U+F04C5), which steps through 0.75, 1.0, 1.25,
  1.5, 1.75 and 2.0 within the player's own range and back round. The window stays at eight rows.
- **Rate**: MPRIS `Rate`, `MinimumRate` and `MaximumRate`, read when the menu opens with `busctl --user
  get-property org.mpris.MediaPlayer2.<instance> /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player
  <name>` (2 s limit for the three); the row is hidden when the range is 1.0 to 1.0 or unreadable.
  Picking it runs `busctl --user set-property … Rate d <value>`, an argument list. The source reads
  `Rate` once per track change of the shown player when `kind` is spoken and puts it in
  `progress.rate` (the field record 0003 left for this), so the line moves at 1.5× when the player does;
  a rate changed elsewhere is caught by the 30-second position re-read.
- Phase C's transport row uses ±30 s for its skip buttons (§C).

### Phase C (idea 2): the transport row

Status: Approved (Stephen 2026-11-12, arbiter standing rule), built; open questions 2-6 and phase C's share of 19
answered as recommended: a left-click on the icon opens the row, in place at the capsule's width, an instant swap (the
wipe waits for phase D and his word after the preview), open 5 s after the last press in the dotfiles (`expand_for`,
packaged 0: off), per-segment tables and `barctl transport`. Plain `barctl expand` folds a row already open (the
icon's second click); on a capsule the segment id `icon` is the icon, whose clicks are `icon_clicks`; the row never
opens on a faded capsule.

**At rest** the capsule is as today: icon and title. **Expanded**, for `expand_for` seconds (default 5,
0-30; 0 never expands, the packaged default), the same cells (no change of width, so nothing on the bar
moves) show a row of buttons and a seek bar:

```text
 ▶  [prev] [play-pause] [next] [loop] [shuffle] ━━━━━━━━━───────
                                                  seek bar: 16 cells, each a seek to its place
```

- previous md-skip_previous U+F04AE, play-pause md-play_pause U+F040E, next md-skip_next U+F04AD, loop
  (md-repeat_off U+F0457 / md-repeat_once U+F0458 / md-repeat U+F0456, by the player's mode), shuffle
  (md-shuffle_variant U+F049F / md-shuffle_disabled U+F049E): five cells of three columns, 15 of the 32;
- a seek bar in the other 16-17: `━` (accent) up to the position, `─` (`fg_dim`) after it, each cell its
  own segment `seek-<i>` that seeks to `i/16` of the length. With no length (a stream), the seek bar
  gives way to `Back 10 s` / `Forward 10 s` buttons (30 s when `kind` is spoken), and loop or shuffle
  is left out when the player gives none.

**Opening it.** There is no hover in polybar (Context), so a click does it:

- **left-click on the icon** expands (the icon gets its own action tag inside the capsule's; the inner
  tag wins), left-click on the title stays play-pause, as record 0003 decided;
- in the expanded row, left on the icon folds it at once;
- every button press in the row starts the `expand_for` count again, so working the row keeps it open;
- not a double-click: it would delay every single click on the capsule by 400 ms.

A hover could only be faked from outside polybar, by a client watching the pointer over the bar window
(polling `xdotool getmouselocation`, or an X input listener): one more process, fragile across bar
restarts and screens. Lost (Alternatives); the click is the design.

**State and clicks.**

- `barctl expand <module> [--for <seconds>]` (new; also `--off`) writes a new state field,
  `expanded_until` (epoch seconds), as `barctl alert` writes `alert_until`; the store keeps it across
  the source's writes as it keeps `alert_until`; the controller's tick pokes the capsule when it ends
  (as for expiries), and with no controller a detached `barctl reload` after the time does (as alerts
  do). The capsule's icon click is `["barctl", "expand", "player-capsule"]` on a new icon-only button
  table, `icon_clicks.left`.
- Render, for a capsule with `expanded_until` in the future, builds the row's cells itself (they are
  not in the state, which stays the source's), each wrapped in `barctl click player-capsule left
  --segment <id>`.
- `segment_clicks.left = ["barctl", "transport", "player-capsule", "{segment}"]`: a new verb that maps
  the cell to one `playerctl -p <target>` argument list, run detached: `previous`, `play-pause`,
  `next`; `loop` steps None → Track → Playlist → None from the state's `loop`; `shuffle` toggles;
  `seek-<i>` runs `position <i/16 × length>`; `back`/`forward` `position 10-`/`10+` (or 30). It then
  starts the `expand_for` count again. With no target it runs nothing (as `{target}` clicks today).
- The source adds `{{loop}}` and `{{shuffle}}` to the stream and two state fields, `loop` and
  `shuffle`. Whether `playerctl --follow` prints a line when only loop or shuffle changes is to be seen
  with Stephen's player in the trial; if it does not, `barctl transport` re-reads them (one `playerctl
  metadata` query, 2 s limit) after a loop or shuffle press, and the menu reads them when it opens, as
  today.

**Animation, without jerkiness.** The swap is **one poke**: the next render draws the row. No frames,
nothing to stutter. A wipe (the buttons replacing the title cells left to right over three frames,
about 250 ms) is possible the way the scroll is done, worked out in render from `expanded_at` and the
time, so a late frame skips ahead rather than slowing the wipe; but each frame is a poke and a 30 ms
render per bar, and render times vary (30-38 ms measured), which is where the jerk would come from. So
the wipe waits for phase D's `send` path, which draws frames with no process, and for Stephen's word
after the preview (open question 4).

**Width.** In place, by design: the row fits the capsule's own `width`, so the bar never moves when it
opens or folds. A capsule set narrower than 24 cells drops the seek bar to the ±10 s buttons.

### Phase D (idea 3): the visualiser strip

**The old module goes.** `[module/audio-spectrum]` (and its commented `exec = audio spectrum`) leaves
the dotfiles' `modules/audio.ini` in the desktop coordinator's next dotfiles PR; it is already out of
`bars/main`. The record 0003 roadmap's idea of feeding it from cava's FIFO is dropped with it. The zsh
`audio spectrum` verb, a terminal visualiser that bar module would have run, is a separate tool: open
question 10.

**What it looks like.** While the shown player plays and the capsule is at rest (not expanded, not
faded), the capsule's text cells show a spectrum of block glyphs (`▁▂▃▄▅▆▇█`, U+2581-U+2588), one per
cell, low bars in `fg_dim` and the rest in the accent (the role's, or the art's with `accent = "art"`;
never the alert colour, which means urgent). **The title overlays it in time**: the title shows for
`visualiser_title` seconds (default 5) on each track change, after a seek and whenever the capsule is
paused; the progress underline stays under the strip. The alternative overlay, the title always shown
with the spectrum as an overline whose colour steps with each cell's level, keeps the title readable but
is subtler: both go in the preview (open question 7).

**Where the levels come from.** cava, which barctl starts with its own config (written to
`$XDG_RUNTIME_DIR/barctl/cava.conf`): `[input] method = pipewire`, `source = auto` (the default sink's
monitor); `[general] framerate = <visualiser_fps>`, `bars = <width>`; `[output] method = raw`,
`raw_target = /dev/stdout`, `data_format = ascii`, `ascii_max_range = 7`, `channels = mono`. One line a
frame, one digit a bar. barctl starts it when the strip should show and stops it, by its own PID, when it
should not (paused, expanded, faded, no player, off): no cava runs while nothing plays.

**How frames reach the bar.** Not through `barctl render`: at 30 ms per render per bar, 15 frames a
second would be about 45% of a core per bar. The controller builds each frame in its own process (the
same render code, with the same escaping and the capsule's action tags, so clicks work during the strip)
and sends it with polybar's `#player-capsule.send.<frame>` action, one IPC message per bar and no
process. A source write or tick poke for the capsule while the strip runs becomes the next send, so a
hook render never draws over a frame; when the strip stops, one ordinary poke draws the capsule again.
A bar restart draws the capsule from its hook, and the next frame follows.

**D1: the gating experiment, first.** Before any strip code goes into barctl, a bench script under the
build's task folder (not in the package) measures, on a **test polybar** on a virtual X display (Xvfb)
with a copy of the bar's config, sending only to that bar's PID (polybar's IPC goes to every bar of the
user unless a PID is given: the live bar must never receive a frame), and with cava reading a FIFO of
generated noise (`method = fifo`: no live audio), at 10, 15, 20 and 30 frames a second, 60 seconds each,
three runs, median, from `/proc/<pid>/stat` CPU times:

| # | Measure | To meet, at the chosen rate (15 frames a second, or the highest of 10/15/20/30 that meets all) |
|---|---|---|
| G1 | cava's CPU, 32 bars | at most 2% of one core |
| G2 | the sender's CPU (frame build and `send`) | at most 2% |
| G3 | polybar's added CPU, per bar | at most 3% |
| G4 | the three together | at most 6% |
| G5 | frame interval | 95th percentile at most twice the period; no gap over 250 ms |
| G6 | idle | zero added CPU and no cava process while "paused", checked over 60 s |
| G7 | clicks during the strip | a left-click (`xdotool` on the test display) still runs its command |

If 10 frames a second does not meet G1-G7, phase D stops there: this record's change log says so, with
the numbers, and the strip is not built. If they are met, the build adds the strip, and Stephen's own
check (5 minutes of `top` on his bar while music plays) confirms them on real hardware.

**Off by default, and a kill switch.**

- `visualiser = false` (the packaged and default value) on the capsule; nothing starts unless it is
  true.
- `barctl visualiser off|on|status` (new): a runtime switch kept in barctl's settings beside disabled
  modules (it survives restarts), which wins over the key; `off` stops cava and draws the capsule at
  once.
- A budget guard: every 10 s the controller adds up cava's and its own CPU; over `visualiser_budget`
  (percent of a core, default 6) for three samples in a row, it turns the strip off (as `barctl
  visualiser off`), writes one journal line ("visualiser off: over its CPU budget") and shows nothing
  else; `barctl doctor` says why it is off.
- cava missing, or exiting three times in five minutes: off, and `doctor` says so.
- `visualiser_fps` (5-30, default the rate D1 chose).

### Cross-cutting

**New `modules.toml` keys** (all optional; a value out of range or of the wrong type is a load error
naming the key; none is secret):

| Key | On | Type, range | Default | Phase |
|---|---|---|---|---|
| `display = "chips"` | a `player` module | | | A |
| `chips_min`, `chips_max` | chips | whole, 1-8 | 2, 4 | A |
| `segment_clicks.<id>.<button>` | any module with segments | command | none | A |
| `fade_after` | capsule | minutes, 0-240 | 0 (never) | B |
| `spoken` | capsule | boolean | false | B |
| `spoken_players` | capsule | list of player names | `[]` | B |
| `expand_for` | capsule | seconds, 0-30 | 0 (never) | C |
| `icon_clicks.<button>` | capsule | command | none | C |
| `visualiser` | capsule | boolean | false | D |
| `visualiser_fps` | capsule | whole, 5-30 | D1's rate | D |
| `visualiser_title` | capsule | seconds, 0-30 | 5 | D |
| `visualiser_budget` | capsule | percent, 1-25 | 6 | D |

Reused, not added: `glyph_override` (the faded icon is the `idle` entry; `unavailable = ""` hides the
capsule), `segment_clicks` (the chips' and the row's clicks), `accent` (the strip's colour), `width`
(the row and the strip fill it).

**New state fields**, each validated by `state.validate` like the existing ones: `status_at` (a time;
B), `kind` (`"spoken"` or `""`; B), `loop` (`None`, `Track`, `Playlist` or empty), `shuffle` (a
boolean or null; C), `expanded_until` (a time; C). New CLI verbs: `barctl expand`, `barctl transport`,
`barctl visualiser`, and `barctl pin --toggle`.

**What each phase needs from the earlier ones.** A needs only record 0003. B needs nothing of A. C
needs A's per-segment tables (its row could use one command table and the transport verb alone, but the
icon's and the `more` cell's clicks are cleaner with them) and B's `kind` for the skip step (without B,
the step is 10 s). D needs C and B only to know when to stand aside (expanded, faded), and offers C its
`send` path for a wipe.

**Failure modes.**

| What fails | What shows |
|---|---|
| `playerctl` stream ends | As today: every player module unavailable, the chips empty, restart after `BARCTL_RETRY` |
| A player gives no loop, shuffle, length or rate | That button, row or seek bar is left out; nothing guessed |
| `busctl` (Rate) fails or takes over 2 s | No speed row; `rate` stays 1.0 |
| `barctl transport` with no target | Runs nothing, as a `{target}` click today |
| Controller down while expanded | A detached `barctl reload` folds it after the time, as for alerts |
| Controller down while the strip runs | No sender: cava is the controller's child and goes with it; the next hook render draws the capsule |
| cava fails or exits repeatedly | Strip off, `doctor` says why; the capsule as without it |
| Over the CPU budget | Strip off (kill switch), one journal line |
| A frame lost on the IPC socket | The next frame replaces it; no retry |
| `kind` wrong | Music controls on a podcast, or ±30 s and a speed row on music: both harmless |
| A downgrade of desktop-tools | An older barctl rejects `display = "chips"` and per-segment tables (unknown display, unknown button), which fails the whole file; the release notes say to take the keys out first, as record 0003 §7 does |

**Rollout, beside the live capsule, by settings.** Every new behaviour is off in the packaged
`modules.toml` and in a capsule without the keys, so a release changes nothing on the bar. Each phase
then has a dotfiles PR that turns it on: A adds `[modules.player-chips]` and `player-chips` before
`player-capsule` in `modules-right`; B sets `fade_after = 10` and `glyph_override.unavailable = ""`;
C sets `expand_for = 5` and the clicks; D sets `visualiser = true` after D1 passes. Stephen restarts the
bar (`barctl restart`) himself; no agent does (record 0003 §6).

**Rollback.** Take the key out of the dotfiles (or `barctl disable player-chips`; `barctl visualiser
off` for the strip, at once), `barctl restart`. Nothing is stored but runtime state, the cava config in
`$XDG_RUNTIME_DIR`, and the visualiser switch in barctl's settings.

**Tests** (unit, stubs only; no player, audio server, Bluetooth or bar; the existing fake commands,
fake poke and fake clock):

- The fake `playerctl` fails the test on any controlling verb (as record 0003 §8) outside one test per
  row or button that checks the exact argv and never runs it; the same guard on a fake `busctl` for
  `set-property`.
- A: chips' segments by `first`, the underline on the shown one, the pin label, `chips_min` and
  `chips_max` with `+N`, an over-long instance left out; per-segment tables parsed, their fallback, a
  bad id; `pin --toggle`.
- B: the fade at `fade_after` with a fake clock and the one tick wake; play bringing it back; the empty
  output with `unavailable = ""`; each `kind` rule and its misses; the menu's spoken rows and speed
  steps within a fake range; no speed row on 1.0-1.0; the source's `rate` read once per track.
- C: the row's cells at widths 32 and 20, each cell's action tag, the seek fractions, the stream case;
  `transport`'s argv per cell, the loop cycle, the re-arm; `expand` writing, keeping and ending
  `expanded_until` with and without a controller.
- D: a fake cava printing scripted frames; frames built and sent to a fake socket for one PID; the
  stand-asides (paused, expanded, faded); title overlay timing; the budget guard with fake CPU
  readings; the switch over the key; cava's restart limit. D1's bench is evidence in the task folder,
  not a test.
- Every existing source, render, ops and status test passes unchanged.

**Privacy.** The chips hold player names, already in `barctl status`. The track id, URL and genre are
read to work out `kind` and kept nowhere: not in state, not in the journal. The visualiser reads the
default sink's monitor, which is everything that plays, calls included, while the shown player plays;
cava turns it into 32 levels a frame in memory, and nothing records, stores or logs audio or levels.
Journal lines name the module, button or switch, never a title, player state or level.

**What needs Stephen's eyes, and the preview.** Taste: the chips' look; the faded icon; the expanded
row's layout and glyphs, and whether to wipe; the strip's look and which overlay; every colour choice.
Each phase's PR carries a preview: screenshots (and for C's wipe and D's strip a short screen recording)
of a test polybar on a virtual display, drawn from canned state files in a test runtime folder, never
from his bar or a live player. Then the trial on his bar, turned on by the dotfiles PR above.

## Alternatives considered

- **Hover to expand.** Polybar has no hover; faking it needs a pointer watcher outside polybar. Lost to a
  click on the icon.
- **Double-click to expand.** Every single click on the capsule would wait 400 ms. Lost.
- **Growing the capsule when it expands.** More room for buttons, but the bar moves twice every time.
  Lost to the row in place.
- **The transport row as a separate module** beside the capsule. Simple, but always present or always
  reflowing. Lost.
- **Only per-segment click tables, no `barctl transport`.** Loop's next mode and a seek's seconds depend
  on the state, which a fixed command can't hold. Lost; and only the verb, without tables, can't give
  the icon or the `+N` cell their own commands.
- **The strip through `barctl render`** at frame rate. About 45% of a core per bar at 15 frames. Lost
  to `send`.
- **A `custom/script` with `tail = true` fed by cava** (record 0003's roadmap guess, and what
  `audio-spectrum` was meant to be). Cheap, but a second module beside the capsule that the capsule
  can't make stand aside, outside barctl's theme colours and clicks, and a long-running script holding
  polybar's pipe (what froze bar restarts before). Lost; dropped with the module.
- **Levels from `pw-record`/`parec` and an FFT in Python.** A numerical dependency and more CPU than
  cava for the same picture. Lost to cava.
- **Spoken-word by length** (over 45 minutes). Long mixes and DJ sets would match. Lost.
- **A hide-when-idle key.** `glyph_override.unavailable = ""` already does it. Lost.
- **A ninth menu row for speed.** One past the eight-line window. Lost to the speed row in shuffle's
  place, for spoken word only.

## Consequences

- barctl gains a display (`chips`), per-segment click tables, an icon click table, nine keys, five state
  fields, three verbs and a flag, the `send` path, and (with D) a child process while music plays.
- The `player` source's stream gains five fields (loop, shuffle, track id, URL, genre) and a Rate read
  for spoken word; still one stream.
- barmenu's `player` provider gains the spoken-word rows.
- The bar moves when the chips' count changes and when the capsule fades or comes back; never when the
  row opens.
- With D on, the bar redraws at the strip's rate while music plays, within D1's numbers.
- Dotfiles: `[module/audio-spectrum]` goes; each phase's keys arrive in its own PR.
- Wiki: In-Depth-Configuration (the new display, keys and tables), CLI-Reference (regenerated: `expand`,
  `transport`, `visualiser`, `pin --toggle`), Architecture-Internals (chips' segments, `status_at`,
  `kind`, `expanded_until`, the `send` path and the budget guard), Security (nothing of the track id or
  URL kept; the monitor stream), Troubleshooting ("the strip turned itself off"; "my modules.toml fails
  after a downgrade"), Testing-Guide (the fake cava and fake `busctl` guard).

## Open questions

| # | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Build order | (a) A chips, B quiet, C row, D strip (D1 any time); (b) the ideas' own order 2-5 | **(a)**: smallest first, each gives the next what it needs, and the gated one last |
| 2 | What opens the row | (a) left-click on the icon; (b) double-click; (c) a menu row; (d) a pointer watcher for hover | **(a)**: one click, no delay to other clicks, no extra process |
| 3 | The row's width | (a) in place, the capsule's width; (b) grow | **(a)**: the bar never moves |
| 4 | Animate the row | (a) instant; (b) a three-frame wipe now; (c) a wipe after D's `send` path, if he likes the preview | **(a)**, then (c) |
| 5 | How long the row stays | (a) 5 s after the last press; (b) 3 s; (c) 8 s | **(a)** |
| 6 | Clicks for the row and chips | (a) per-segment tables and `barctl transport`; (b) the verb only; (c) tables only | **(a)** (Alternatives) |
| 7 | The strip's look | (a) block strip, the title over it in time; (b) title always, the spectrum as an overline tint; (c) a separate module beside the capsule | **(a)**, with (b) in the same preview for him to choose |
| 8 | The strip's gate | (a) G1-G7 as written, at 15 frames or the best that meets them, 10 the floor; (b) looser | **(a)**: about 6% of a core is the most a decoration should cost |
| 9 | Where levels come from | (a) cava from PipeWire; (b) `pw-record` and a Python FFT | **(a)** |
| 10 | The zsh `audio spectrum` verb | (a) keep it, a terminal tool; (b) remove it with the module | **(a)**: only the bar module was dropped; it's the dotfiles' to remove if he wants |
| 11 | When chips show | (a) two or more players; (b) always | **(a)**: one chip says nothing the capsule doesn't |
| 12 | Clicking the pinned chip | (a) unpins (`--toggle`); (b) pins again (nothing) | **(a)**: the click undoes itself |
| 13 | How many chips | (a) 4, then `+N`; (b) 6 | **(a)**: the right side is full |
| 14 | Fade: shrink or keep the width | (a) shrink to the icon; (b) keep the width, blank | **(a)**: it gives the room back; two moves a pause |
| 15 | Minutes before the fade | (a) 10; (b) 5; (c) 30 | **(a)**, as he suggested |
| 16 | No player | (a) hidden (`unavailable = ""`); (b) the dim icon, as today | **(a)**: nothing to show, nothing drawn |
| 17 | Spotting spoken word | (a) rules 1-4; (b) and a length rule; (c) only the `spoken_players` list | **(a)** |
| 18 | The speed row | (a) in shuffle's place for spoken word; (b) a ninth row; (c) a submenu | **(a)**: eight rows, and shuffle means nothing for an episode |
| 19 | The packaged defaults | (a) every new behaviour off, on in the dotfiles; (b) on in the package | **(a)**: a release never changes the bar by itself |

## Change log

| Date | Change |
|---|---|
| 2026-11-12 | Proposed by the desktop coordinator, after Stephen approved ideas 2-5 of record 0003 (2026-11-12) |
| 2026-11-12 | Phase A (player chips) Approved and built in desktop-tools: Stephen 2026-11-12, arbiter standing rule (❓ 2026-11-12 Desktop Tools Design Records Are Approved Until Notified); its open questions (11 two or more players, 12 a second click unpins, 13 four then `+N`, and 6 and 19 for the chips) answered as recommended. Phases B-D stay Proposed |
| 2026-11-12 | Phase B (quiet when idle, spoken-word controls) Approved and built in desktop-tools: Stephen 2026-11-12, arbiter standing rule (❓ 2026-11-12 Desktop Tools Design Records Are Approved Until Notified); its open questions (14 shrink to the icon, 15 ten minutes, 16 hidden with `unavailable = ""`, 17 rules 1-4, 18 the speed row in shuffle's place, and 19 for phase B) answered as recommended. Spoken word gets its own switch, `spoken` (default false), so every phase B behaviour is off until a setting turns it on. Phases C-D stay Proposed |
| 2026-11-12 | Phase C (the transport row) Approved and built in desktop-tools: Stephen 2026-11-12, arbiter standing rule (❓ 2026-11-12 Desktop Tools Design Records Are Approved Until Notified); its open questions (2 a left-click on the icon, 3 in place, 4 instant now and a wipe after phase D, 5 five seconds, 6 tables and `barctl transport`, and 19 for phase C) answered as recommended. `expand_for` defaults to 0, so the row is off until a setting turns it on. Phase D stays Proposed |

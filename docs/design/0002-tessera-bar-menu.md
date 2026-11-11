# 0002: A right-click menu on the tessera bar module, and glyph overrides in barctl

<!-- Add a line for this record to the index in docs/design/README.md (CI checks). -->

Status: Approved
Date: 2026-11-11
Authors: Stephen Cox (direction, 2026-11-11: the menu; and that tessera's glyph "is set for its own use but
should allow others to overwrite"); written up by the desktop coordinator

## Context

tessera, the password-store tool (its own repository, andronics/tessera; its design record 0001, Approved),
lights a module on the bar: it runs `barctl push tessera --source tessera` itself (its §4), with tiers
`idle` (locked, level), `active` (unlocked), `alert` (reads waiting, diverged, sync failing, first sync
pending, a denial) and `unavailable` (no push for 20 minutes). The module is drawn by barctl like every
`custom/ipc` module (`hook-0 = barctl render tessera` in the dotfiles'
`desktop/.config/polybar/modules/tessera.ini`; `[modules.tessera]` with `pusher = "tessera"` in the
dotfiles' `barctl/modules.toml`). Both files say "No clicks: each alert is fixed at a terminal".

Stephen wants a right-click menu on it for the common actions: lock and unlock, show, two-factor code,
pick, and a read-only sync status row. `tessera sync` stays out: it is his, at a terminal.

What tessera gives (read-only evidence: `tessera --help` and `tessera status --json`, tessera 0.1.3, on
2026-11-11; its record 0001 §5, §6, §10, §11, §14):

- `tessera status --json` is for anyone, never decrypts and took about 0.1 s (three runs, 74-103 ms). It
  gives `lock` (`locked` / `unlocked`), `waiting` (reads queued for an unlock), `sync` (`state`, `ahead`,
  `behind`, `dirty`, `first_sync`, `last_fetch`, `failing_since`), `checks` (name, state, detail),
  `summary` and `version`. Its details hold counts and states, never an entry name.
- **Who is calling** (its §5.2) decides everything. `TESSERA_ACTOR` set names an actor (or `unknown`);
  `CLAUDECODE` set is `claude`; otherwise the caller is `stephen` only when it is the foreground process
  group of its controlling terminal. A command barmenu starts is detached in its own session with no
  terminal (`procs.detach`), so tessera calls it `system`: unnamed, never queued, refused while locked,
  logged `would-deny` while enforcement is off and denied once it is on.
- **`tessera pick`** (its §10) is the exception: it is named `stephen` by how it is called (refused under
  `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR`, or with no display), because "rofi's menu is the
  evidence a person is there". It runs `rofi -dmenu` over `tessera names` (names only, never decrypting),
  then a second menu (`password`, `otp`, a named field), and copies the choice with pass's own `-c`,
  which uses `xclip` and clears the clipboard after 45 seconds, restoring what was there. Nothing is
  printed, notified or logged but the access line. It takes no arguments today.
- **`tessera lock`** (clear gpg-agent's cache) and **`tessera unlock`** (show the waiting reads, then
  unlock with gpg's pinentry) are "Stephen, at a terminal": exit 3 without one, or under `COORDINATOR`,
  `CLAUDECODE` or `TESSERA_ACTOR`.
- `tessera show -c[<line>] <path>` clips with the same 45-second clear; `tessera otp <path>` prints the
  code and has no `-c`.

What barmenu gives (record 0001): menu providers (`provider = "<name>"`, a Python function in
`barmenu/providers/` whose read-only queries have a 2 s limit and which still returns state-free rows when
they fail), the `current` mark (rofi's active rows, in the accent), shell or argument-list row commands,
picks launched detached on `/dev/null` (so a child's output reaches neither the bar nor the journal), and
an 8-line window. barmenu's journal line (record 0017 through `journal.run`) names the menu
(`barmenu tessera`), never a row's arguments. barctl gives `barctl click <module> <button>`, which runs the
module's `clicks` from `modules.toml`, detached.

**Whose glyph shows.** A pusher's `--glyph` always wins today: barctl shows the state's `glyph` and falls
back to `modules.toml`'s `glyph` only when the state has none (`render.text_of`, `store.shown`,
`ops.module_info`, `ops.menu`'s prompt). So `glyph` in `modules.toml` means only "shown before anything
has written the module" (its own comment says so). tessera pushes md-lock or md-lock_open on every push,
so the dotfiles can't choose its icon. barctl's own sources set glyphs too (the volume source picks one by
level and one for muted), so `glyph` can't simply start winning.

## Decision

### 1. Right-click opens `barmenu tessera`

- The dotfiles' `barctl/modules.toml` gets `[modules.tessera.clicks]` with `right = ["barmenu",
  "tessera"]`, and `tessera.ini` gets `click-right = barctl click tessera right`, as `audio-level` does.
  Clicks stay in `modules.toml`, one place per module (dotfiles record 0003 §B4). Left, middle and scroll
  do nothing (open question 5).
- `menus.toml` gets `[menus.tessera]`: glyph md-lock U+F033E, title `Passwords`, side `right`,
  `provider = "tessera"`. `barmenu tessera` also works from a keybinding or a terminal.

### 2. The rows

From the new `barmenu/providers/tessera.py`, which runs one query, `tessera status --json` (2 s limit):

| # | Glyph | Label | Runs | Shown / marked |
|---|---|---|---|---|
| 1 | md-lock U+F033E | `Locked` | `tessera lock` (§3) | Marked when `lock` is `locked` |
| 2 | md-lock_open U+F033F | `Unlocked`; `Unlock…` when locked; `Unlock: <n> waiting…` when reads wait | `tessera unlock` in a terminal window (§3) | Marked when `lock` is `unlocked` |
| 3 | md-key U+F0306 | `Copy password…` | `tessera pick --password` (asked of tessera, §8) | When tessera's `version` has it (§8) |
| 4 | md-two_factor_authentication U+F09AF | `Copy two-factor code…` | `tessera pick --otp` (asked of tessera, §8) | When tessera's `version` has it |
| 5 | md-form_textbox_password U+F07F5 | `Pick…` | `tessera pick` | Always |
| 6 | md-sync U+F04E6, md-sync_alert U+F04E7 when `sync`'s check is not `ok` | `Sync: <state>, <age> ago` (e.g. `Sync: level, 20h ago`; `Sync: ahead 2`; `Sync: diverged`; `Sync: first sync pending`) | a notification with `tessera status`'s checks (§5) | Always; `Sync status…` when unreadable |

- The lock state is shown the way record 0001's idle-lock rows show theirs: the row in effect is marked.
  Picking the marked row repeats what is already true: `tessera lock` on a locked key clears an empty
  cache; `tessera unlock` with the key unlocked answers in its window, whatever tessera says.
- With the status unreadable (tessera missing, a failure, over 2 s): rows 1 and 2 unmarked, labelled
  `Lock` and `Unlock…`; rows 3 and 4 hidden (their version can't be told); row 6 `Sync status…`, which
  then runs `tessera status` in a terminal window so the reason can be read.
- No row runs `tessera sync`, `sync --watch`, `show`, `otp`, `names`, `log`, `health` or `pass`. Six rows
  fit the 8-line window.

### 3. Lock and unlock: the verbs that need Stephen at a terminal

- **Unlock** runs in a terminal window: `alacritty --class tessera-prompt -e zsh -fc 'tessera unlock ||
  read -sk1 "?Press any key to close"'` (the dotfiles set `TERMINAL=alacritty`; the class lets bspwm
  float it). tessera is the foreground of the window's terminal, so §5.2's terminal test passes, and
  pinentry asks for the passphrase there. That is what unlocking needs anyway: Stephen typing it. The
  window closes on success; on a failure or refusal it stays until a key is pressed, so the reason is
  read. The click is Stephen's, so the prompt is not a surprise (tessera §6).
- **Lock** asks tessera to accept `tessera lock` at the desktop the way it accepts `pick`: with a display,
  refused under `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR` (open question 1). Locking only takes access
  away, so it needs no proof of a person. Until tessera ships that, row 1 runs `tessera lock` in the same
  terminal window as unlock (it closes at once on success). Not `lockscreen forget-passphrase`: that would
  clear the cache behind tessera's back, unlogged, and the bar would show `active` until the next watcher
  run.
- Both go through tessera, which pushes its bar state itself after a lock or unlock, so the module's tier
  changes at once.

### 4. Entry names and secrets

- **Names are chosen inside `tessera pick`**, by its rofi over `tessera names`, which never decrypts.
  barmenu never lists, holds or passes an entry name: none reaches its arguments, its journal line or
  `ps`. Nothing is decrypted until Stephen picks an entry in tessera's own menu.
- **The clipboard** is pass's `-c`, through `tessera pick`: `xclip`, cleared after 45 seconds
  (`PASSWORD_STORE_CLIP_TIME`), restoring what was there, and only if the clipboard still holds the value.
  pass-otp's `-c` uses the same clip function, so a two-factor code clears after 45 seconds too.
- **Nothing is printed.** barmenu starts every row detached with stdout and stderr on `/dev/null`; the
  provider reads only `tessera status --json` and logs nothing of it; the sync notification (§5) carries
  only status's states and counts. No row is a shell string that could echo a value, except the unlock
  window's, which prints only what tessera prints to its own terminal. tessera's access log (its §3) is the
  one record of each read.

### 5. The sync status row

Read-only. Its label comes from the status already read: `sync.state` (with `ahead`/`behind` when not
level) and the age of `last_fetch`. Picking it runs `dunstify -a tessera "Password store" "<lines>"`, one
line per check (`ok  lock  the key is locked`), as `tessera status` prints them at a terminal; a check
that is not `ok` ends with "fix at a terminal: `tessera status`". It never syncs: a level, behind, ahead or
diverged store is Stephen's to sync at a terminal (`tessera sync`), and the watcher (`sync --watch`) is the
systemd unit's.

### 6. The environment rule

- barmenu never sets, clears or changes `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR` for a tessera row:
  they pass to tessera untouched, as crew passes them to meta. Clearing them would turn an agent's call
  into Stephen's; setting `TESSERA_ACTOR` would make `pick` refuse and turn Stephen's call into an
  actor's.
- **A tainted bar.** If any of the three is set in barmenu's own environment (the bar or sxhkd was started
  from a coordinator's or agent's session, or an agent ran `barmenu tessera`), the provider gives rows 1-5
  as one row, `Not available: the bar runs in an agent's environment`, which runs a notification saying to
  restart the bar from a clean session; row 6 stays (status is anyone's). tessera would refuse those verbs
  anyway (exit 3); the row says why before a click fails silently.
- No row needs an actor name. `tessera status` is for anyone; nothing else the menu runs is a read by an
  actor. If a later row reads for an actor, it sets `TESSERA_ACTOR` to that actor's slug in that row's
  command only, and the actor's note carries the `pass_access` it needs.

### 7. Glyph overrides in barctl

The pushed (or source's) glyph stays the default; an override in `modules.toml` wins when it is there.

- **A new key, `glyph_override`**, beside `glyph` (snake case, as `segment_clicks`). It takes one of two
  shapes:

  ```toml
  [modules.tessera]
  pusher = "tessera"
  glyph = "\U000F099D"           # unchanged: shown before the first push
  glyph_override = "\U000F099D"  # every tier: this glyph, whatever the pusher sends
  # or, per tier; a tier left out shows the pusher's glyph:
  # glyph_override = { idle = "\U000F099D", active = "\U000F199A", alert = "\U000F0ECC", unavailable = "\U000F099C" }
  ```

  A string is every tier. A table's keys are tiers (`unavailable`, `idle`, `active`, `alert`) and its
  values text; any other key, or a value that isn't text, is a load error naming the key, like every
  `modules.toml` mistake.
- **`glyph` keeps its meaning**: the glyph before anything has written the module. No module changes
  unless it adds the new key, so there is nothing to migrate.
- **Precedence**, for the tier barctl shows (after the ttl: a stale module is `unavailable`):
  1. `glyph_override`'s entry for that tier, when it is a table with that tier;
  2. `glyph_override`, when it is a string;
  3. the state's `glyph` (the pusher's or source's);
  4. `glyph`.

  With no state at all the tier is `unavailable`, so steps 1, 2 and 4 apply. An override that is the empty
  string hides the glyph (the module shows its count or label only), as an empty pushed glyph does today.
- **One function decides**, `modules.Module.glyph_for(tier, state) -> (glyph, source)`, and every place
  that reads a glyph uses it: `render.text_of`, `store.shown` (so a pusher changing only a glyph the
  override hides does not poke the bar), `ops.module_info` and `ops.menu`'s prompt. Segments (cells of a
  module made of several) keep their own glyphs: overrides are per module, not per segment, in this
  record.
- **Seeing which won.** `barctl status --json` gives each module `glyph` (what the bar shows, as before
  when there is no override), `glyph_source` (`override-tier`, `override`, `pushed`, `default`) and
  `glyph_pushed` (the state's, or null). Plain `barctl status` shows `(override)` after an overridden
  glyph. `barctl doctor` adds one `ok` line per module with an override (`glyph tessera: override for
  idle, active, alert, unavailable`), so a forgotten override is visible; it is never a warning.
- **A config change** takes effect on `barctl reload`, like every `modules.toml` change.

For tessera this needs nothing from tessera: the dotfiles set the icons (§8), and tessera keeps pushing
md-lock and md-lock_open, which show wherever no override is set.

### 8. What changes where

**desktop-tools (this repository):**

- `barmenu/providers/tessera.py`, `"tessera"` in `providers.NAMES`, `[menus.tessera]` in `menus.toml`.
- Rows 3 and 4 appear when the status's `version` is at least the tessera release that ships
  `pick --password` and `--otp` (the number goes in when it exists); the provider runs no extra query to
  find out.
- barctl: `glyph_override` in `modules.py` (parse, `Module.glyph_for`), its use in `render.py`,
  `store.py` and `ops.py`, the `status` fields and the `doctor` line (§7); the packaged `modules.toml`'s
  header comment documents the key. No packaged module sets it.
- Wiki: CLI-Reference (regenerated: `barmenu tessera`), In-Depth-Configuration (`tessera` among the
  providers; `glyph_override` and its precedence), Architecture-Internals (the provider; `glyph_for`),
  Security (names only in tessera, the clipboard, the environment rule), Troubleshooting (`Not
  available…`, unmarked rows; "my modules.toml glyph doesn't show": `glyph` is only the pre-push glyph),
  Testing-Guide (the fake tessera; the precedence matrix).

**dotfiles (their own PR):**

- `barctl/modules.toml`: `[modules.tessera.clicks]` `right = ["barmenu", "tessera"]`; the comment's "No
  clicks" goes. And tessera's icons, one family, locked and unlocked told apart (open question 9):
  `glyph = "\U000F099D"` and `glyph_override = { idle = "\U000F099D", active = "\U000F199A", alert =
  "\U000F0ECC", unavailable = "\U000F099C" }`: md-shield_lock (locked, level), md-shield_lock_open
  (unlocked), md-shield_alert (Stephen needed), md-shield_off_outline (no push for 20 minutes).
- `polybar/modules/tessera.ini`: `click-right = barctl click tessera right`; the comment's "No clicks"
  goes. Stephen has an uncommitted change in his checkout of that file (`inherit =
  module/base-ipc-inverse`): the PR is made from `origin/main` in a worktree, never his checkout, and its
  description says the two must be reconciled (he commits his line first, or the PR carries it too, as he
  says).
- `bspwm`: a rule that floats `tessera-prompt` windows, centred.
- Pin the desktop-tools release that has the menu and `glyph_override`.

**tessera (the security coordinator's repository; asks only, nothing is edited from here):**

1. `tessera pick --password` and `tessera pick --otp`: skip the second menu and copy line 1 or the
   current code (`pass otp -c`), still over its own rofi of names, still named `stephen` by how it is
   called. Without an `otpauth://` line the entry is not offered, or the pick says so in a notification
   that names no entry.
2. `tessera lock` at the desktop, accepted as `pick` is (a display; refused under the three variables),
   and pushing its bar state after it.
3. A stated contract for `tessera status --json`: the fields this provider reads (`lock`, `waiting`,
   `sync.state`, `sync.ahead`, `sync.behind`, `sync.last_fetch`, `checks`, `version`) stay, and nothing in
   it is ever an entry name or a value.

Each goes to tessera's owner as an issue, through the desktop coordinator. None is needed for rows 1, 2,
5 and 6, nor for the icons: the menu works on tessera 0.1.3, with lock in a terminal window and no rows 3
and 4, and the icons are the dotfiles' own (§7).

### 9. Tests

Unit, in `tests/unit/test_barmenu_providers.py`, with a fake `tessera` on `PATH` (the existing
`commands` fixture) that records its calls:

- One query, `["tessera", "status", "--json"]`, per open; the fake fails the test if called with `show`,
  `otp`, `names`, `sync`, `log`, `health` or as `pass`, and no row's command contains `sync`.
- Locked, unlocked, locked with 2 waiting: labels and marks of rows 1 and 2.
- Each sync state (level, behind, ahead, diverged, first sync pending, failing): row 6's label, glyph and
  notification lines.
- An old `version`: rows 3 and 4 absent; a new one: present with their exact argv.
- Unreadable status (missing, exit 4, bad JSON, over the 2 s limit): the state-free rows.
- `CLAUDECODE`, `COORDINATOR` or `TESSERA_ACTOR` set: the one `Not available…` row plus row 6, and no row
  command sets or unsets any of them.
- Unlock's argv (`alacritty --class tessera-prompt -e …`), and that every row is an argument list but the
  unlock and lock windows' inner command.
- `menus.toml`: `tessera` loads, and `barmenu --help` names the provider without calling it.

Unit, for the glyph overrides (`tests/unit/test_barctl_render.py`, `test_barctl_ops.py`,
`test_barctl_cli.py`):

- Parsing: a string; a table of some tiers; an unknown tier key, a non-text value and a non-string,
  non-table value each a load error naming the key; no key at all is today's module.
- The precedence matrix: each tier × {no override, string, table with that tier, table without it} ×
  {pushed glyph, none}; a stale state uses `unavailable`'s entry; no state uses steps 1, 2 and 4; an empty
  override hides the glyph.
- `store.shown`: with an override for the tier, a push that changes only the glyph is not a change (no
  poke); without one it still is.
- `barctl status --json`'s `glyph`, `glyph_source` and `glyph_pushed`; the plain `(override)` mark; the
  `doctor` line; `barctl menu`'s prompt glyph.
- Every existing render, ops and status test passes unchanged (no packaged module sets the key).

Live, after the dotfiles PR, by Stephen (no agent runs a tessera read): right-click with the key locked
and unlocked; `Unlock…` asks for the passphrase in its window and the module turns `active`; `Locked`
turns it `idle`; `Pick…` copies and the clipboard clears after 45 seconds; `tessera log --since 10m`
shows the picks as `stephen` and nothing else; `journalctl --user -t barmenu --since -10m` names only the
menu. The icons: after `barctl reload`, `barctl status tessera --json` says `glyph_source: override-tier`,
and locking and unlocking switch md-shield_lock and md-shield_lock_open on the bar.

## Alternatives considered

- **barmenu's own rofi over `tessera names`, then `tessera show -c <path>` or `tessera otp <path>`,
  detached.** The obvious build, but tessera calls a detached process `system`: refused while locked,
  logged `would-deny` now and denied once enforcement is on. It would also put entry names through
  barmenu's process and arguments. Lost.
- **barmenu's names menu, then `tessera pick <path>`.** Works with tessera's identity rule only by
  weakening it: anything could then call `tessera pick <path>` with no menu shown and be treated as
  Stephen. The rofi must be tessera's own. Lost.
- **`show` and `otp` in a terminal window** (`alacritty -e tessera show -c <path>`): passes the terminal
  test, but flashes a window per copy and still needs barmenu to choose the name. Lost to `pick`'s flags.
- **Static `[[modules.tessera.menu]]` rows in `modules.toml`**, opened by barctl's own right-click: no
  state, so no marked lock row and no sync row. Lost.
- **Lock through `lockscreen forget-passphrase`**: it works at the desktop today, but bypasses tessera's
  log and leaves the bar on `active` until the next watcher run. Lost (§3).
- **Refusing lock and unlock in the menu** (rows that only say "at a terminal: `tessera unlock`"): honest,
  but leaves the two most common actions out. Lost; open question 1 keeps it as an option.
- **`glyph` itself starts winning over the pushed glyph.** One key, but it changes what every existing
  `glyph` means: the volume source's level and mute glyphs and the player's would be frozen to their
  pre-push glyph. Lost to a new key.
- **A pusher-side flag** (`barctl push --glyph-weak`, the config winning only over weak glyphs): it puts
  the choice in each pusher's code, so tessera would need a release, which is what Stephen's "allow others
  to overwrite" avoids. Lost.
- **Two keys, `glyph_override` (string) and `[modules.<m>.glyphs]` (per tier)**: works, but two names for
  one idea, and `glyphs` reads as "the module's glyphs", easily mistaken for `glyph`'s plural. Lost to one
  key with two shapes; open question 7 asks.
- **Tessera choosing new glyphs in its own release**: the icon would still be the pusher's alone. Not
  needed once overrides exist.
- **A sync row that runs `tessera sync`** in a terminal window: Stephen's at a terminal, and excluded by
  him. Not offered.

## Consequences

- barmenu gains a third provider; no change to its interfaces. The tessera module gains its first click.
- barctl gains `glyph_override`: any module's icon can be chosen in the dotfiles without its pusher's or
  source's release. `glyph`'s meaning is unchanged, so no existing `modules.toml` changes. barctl status
  gains two fields; none goes.
- Each open costs one `tessera status --json`, about 0.1 s.
- The menu depends on tessera's `status --json` fields (ask 3) and, for rows 3 and 4, on asks 1 and 2.
  A tessera without them still gets rows 1, 2, 5 and 6.
- Build order: (1) this repository: the provider, menu, tests and wiki, then a release; nothing changes on
  the bar until (2) the dotfiles PR adds the click. (3) The tessera asks land in their own time; rows 3
  and 4 and the windowless lock appear with the tessera release that has them, with no change here beyond
  the version number.
- The glyph overrides go in the same desktop-tools release as the menu (one record, one PR, one release),
  and the dotfiles set tessera's icons in the same PR that adds the click.
- Rollback: revert the dotfiles click lines (the module goes back to no clicks); the barmenu menu can stay,
  unused. For the icons, remove `glyph_override` from the dotfiles' `modules.toml` and `barctl reload`:
  the pushed glyphs show again. An older barctl ignores keys it doesn't know (its `modules.toml` parser
  reads only the keys it names), so downgrading desktop-tools before or after removing the key is safe.
  Nothing is stored, so there is nothing else to undo.

## Open questions

1. **Lock and unlock.** (a) Unlock in a terminal window; lock asked of tessera to work at the desktop
   (in the window until then); (b) both always in a terminal window; (c) neither: the rows only say what
   to type at a terminal. Recommendation: **(a)**: unlocking needs the passphrase typed, which the window
   gives, while locking only takes access away and should be one click.
2. **Show and two-factor rows.** (a) Ask tessera for `pick --password` and `pick --otp`, the rows shown
   once its release has them; (b) only `Pick…` (its second menu already offers both); (c) barmenu's own
   names menu and `show -c` in a terminal window. Recommendation: **(a)**, with (b) as the state until
   then: one click less for the commonest copy, and tessera keeps the names and the identity rule.
3. **How the lock state shows.** (a) Two rows, the one in effect marked (as record 0001's idle-lock rows);
   (b) one state row (`Key: locked`) and one action row (`Unlock…`). Recommendation: **(a)**: the same
   pattern as the lock menu next to it, and each row is both the state and the way to it.
4. **The sync row's click.** (a) A notification with the checks; (b) nothing (a label only); (c)
   `tessera status` in a terminal window. Recommendation: **(a)**: it says why the module is lit without a
   window; (c) stays the fallback when the status can't be read.
5. **Which buttons.** (a) Right-click only, as asked; (b) left-click too. Recommendation: **(a)**: left is
   free for a later one-click action (for example lock), and a stray left-click on a status light should
   not open a menu.
6. **A tainted bar.** (a) The `Not available…` row; (b) hide the menu (no rows, nothing opens).
   Recommendation: **(a)**: a menu that does not open looks broken; the row says what to fix.
7. **The override key's name and shape.** (a) One key, `glyph_override`, a string or a table of tiers;
   (b) two keys, `glyph_override` (string) and `[modules.<m>.glyphs]` (per tier); (c) `glyph-override`,
   kebab case. Recommendation: **(a)**: one name for one idea, and snake case as `segment_clicks` already
   is in the same file.
8. **What the override keys on.** (a) The tier barctl shows (four keys); (b) any label the pusher sends
   (for example `unlocked`, `diverged`), a finer map. Recommendation: **(a)**: tiers are barctl's own,
   fixed vocabulary; labels are each pusher's and change between its releases, so a map on them breaks
   silently.
9. **tessera's icons.** (a) The md-shield_lock family: shield_lock (locked), shield_lock_open (unlocked),
   shield_alert, shield_off_outline; (b) md-shield_key and md-shield_key_outline, as first suggested, with
   shield_alert and shield_off_outline; (c) keep md-lock and md-lock_open (no override). Recommendation:
   **(a)**: shield_key has no open form, so locked and unlocked would differ only by outline, hard to tell
   at bar size; shield_lock and shield_lock_open say the state, and the shield sets them apart from the
   screen-lock button's md-lock on the same bar.

## Change log

| Date | Change |
|---|---|
| 2026-11-11 | Proposed by the desktop coordinator |
| 2026-11-11 | Approved: Stephen via the arbiter, 2026-11-11, ❓ 2026-11-11 Approve Desktop Tools Record 0002 Tessera Bar Menu (option a, the recommendations on the open questions) |

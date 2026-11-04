# 0001: Theme and lock bar menus on barmenu

Status: Approved
Date: 2026-11-04
Authors: Stephen Cox (direction, through the brain coordinator); written up by the desktop coordinator

## Context

Two bar buttons are still polybar's own expanding menus (`custom/menu` in the dotfiles'
`desktop/.config/polybar/modules/menu.ini`); every other bar menu is `barmenu <menu>`, a rofi menu whose
rows live in `src/desktop_tools/barmenu/menus.toml`. The dotfiles' design record 0001 (Polybar IPC module
taxonomy) lists the two as the last `custom/menu` modules; the dotfiles' record 0003 (desktop tools move to
Python) moved barmenu here. This record moves both onto barmenu and rethinks what they offer.

Today:

| Button | Rows (label: command) |
|---|---|
| Theme (left of the bar) | REFRESH: `theme reload`; UNDO: `theme undo`; DEFAULT: `theme apply default` |
| Lock (right of the bar) | DISABLE: `lockscreen hook-disable`; ENABLE: `lockscreen hook-enable`; TRIGGER: `lockscreen hook-trigger` |

The lock menu shows no state: nothing says whether idle locking is on. The theme menu can't change the
theme, only reload, undo or reset it.

What barmenu can do today: a menu is static TOML rows (glyph, label, command). One kind of dynamic row
exists: `dynamic = "<module>"` appends the rows a **barctl module's source** gives (the volume source's
sinks, the player source's players). Neither theme nor lock is a barctl module, and there is no way to
**mark a row as current**: the volume source only swaps a row's glyph. So both are new here.

What the dotfiles give (read-only evidence: `theme help`, `dotlib/_theme`, `dotlib/_theme_ui`,
`dotlib/_lockscreen`, `dotlib/_xidlehook`, `dotlib/_power`, all on 2026-11-04):

- `theme pick` already is a rofi picker over every scheme, with colour previews, the applied one marked
  and selected, plus a Wallpapers view (`theme pick wallpapers`) and a dark/light row.
- `theme current --json` prints the applied theme (`name`, `title`, `mode`, `source`); `theme mode toggle`,
  `theme random`, `theme undo`, `theme reload`, `theme apply default` exist.
- `lockscreen status` prints one word: `armed`, `paused` or `not running`. `lockscreen activate` locks now
  (betterlockscreen); `hook-enable`/`hook-disable` resume and pause xidlehook's timer; `hook-trigger` locks
  through the idle daemon, so only while it runs. There is **no timed pause**.
- Every lock already forgets the GPG passphrase (`betterlockscreen/custom-pre.sh` runs
  `gpg-connect-agent reloadagent /bye`). `power suspend` asks Yes/No, locks, then suspends; xss-lock is being
  added so that suspends outside the menu lock too.
- xidlehook already skips locking while a window is fullscreen (`XIDLEHOOK_NOT_WHEN_FULLSCREEN=true`), so a
  fullscreen presentation is covered; a windowed one (a shared screen, a call) is not.
- rofi's bar-menu window shows 8 lines; more rows scroll.

## Decision

### 1. barmenu: menu providers and a current mark (new)

- **`provider = "<name>"`** in a menu's TOML table names a Python function in a new
  `desktop_tools/barmenu/providers/` package (`theme`, `lock`). barmenu calls it when the menu opens; it
  returns the menu's rows, and any static `rows` in the TOML follow them (so an override can add rows).
  `dynamic` (barctl module sources) stays as it is; a menu takes one of the two, never both (a load error).
- A provider reads state only through read-only queries (`procs.query`, 2 s timeout). If a query fails or
  times out it still returns its rows, unmarked and with the state-free labels, so the menu always opens.
- **`Row.current`** (bool, default false; also a `current = true` key on static rows). barmenu passes the
  current rows to rofi as active (`-a <indices>`); the cursor still starts on the first row. The dotfiles'
  `rofi/themes/bar-menu.rasi` styles `element normal.active` and `element selected.active` with the theme's
  `accent` role.
- The menu's `description()` (the CLI help) names the provider ("rows from the lock provider") instead of
  calling it, so `barmenu --help` never runs a query.

### 2. The theme menu (`barmenu theme`, glyph md-palette U+F03D8, side left)

| # | Glyph | Label | Runs | Shown / marked |
|---|---|---|---|---|
| 1 | md-palette_swatch U+F08B5 | `Scheme: <title>…` (e.g. `Scheme: Catppuccin Mocha…`) | `theme pick` | Always; the title is `theme current --json`'s `title`, or `Scheme…` when that fails |
| 2 | md-image_multiple U+F02F9 | `Wallpaper…` | `theme pick wallpapers` | Always |
| 3 | md-dice_multiple U+F076E | `Random wallpaper` | `theme random` | Always |
| 4 | md-theme_light_dark U+F050E | `Light mode` or `Dark mode` (the one not in use) | `theme mode toggle` | Always; `Toggle dark/light` when the mode can't be read |
| 5 | md-undo U+F054C | `Undo` | `theme undo` | Always |
| 6 | md-refresh U+F0450 | `Reload` | `theme reload` | Always |
| 7 | md-home U+F02DC | `Default` | `theme apply default` | Always |

No row is marked: the current scheme is marked inside `theme pick`, which already does it with previews.
Seven rows fit the 8-line window.

### 3. The lock menu (`barmenu lock`, glyph fa-lock U+F023, side right)

| # | Glyph | Label | Runs | Shown / marked |
|---|---|---|---|---|
| 1 | md-lock U+F033E | `Lock now` | `lockscreen activate` | Always |
| 2 | md-lock_clock U+F097F | `Idle lock on` | `lockscreen hook-enable`; `lockscreen hook-init` when the daemon is not running (label then `Idle lock on (start it)`) | Marked when status is `armed` |
| 3 | md-lock_off U+F1671 | `Idle lock off` | `lockscreen hook-disable` | Marked when `paused` with no end time |
| 4 | md-timer_sand U+F051F | `Idle lock off for 1 hour`; `Idle lock off until HH:MM` when a timed pause runs | `lockscreen hook-disable 1h` (new, below) | Marked when `paused` with an end time |
| 5 | md-power_sleep U+F0904 | `Suspend` | `power suspend` (asks Yes/No, locks first) | Always |
| 6 | md-key_remove U+F030A | `Forget GPG passphrase` | `lockscreen forget-passphrase` (new, below) | Always |

State comes from `lockscreen status --json` (new); with the status unreadable, no row is marked and row 2
runs `lockscreen hook-enable`.

### 4. What the dotfiles add (their own PR)

- `lockscreen hook-disable [duration]`: with a duration (`30m`, `1h`, systemd time syntax), pauses the timer
  and starts a transient user timer, `systemd-run --user --unit=lockscreen-resume --on-active=<duration>
  lockscreen hook-enable` (with `PATH` set so `lockscreen` is found). `hook-enable` and a plain
  `hook-disable` stop that timer first, so the last choice wins.
- `lockscreen status --json`: `{"state": "armed" | "paused" | "not running", "until": "<ISO time>" | null}`;
  `until` is the resume timer's next run. The plain `status` output stays as it is.
- `lockscreen forget-passphrase`: what `custom-pre.sh` does (`gpg-connect-agent reloadagent /bye`, 2 s
  timeout), plus a short notification so the click has feedback.
- `rofi/themes/bar-menu.rasi`: the `active` element styles above.
- `polybar/modules/menu.ini`: `menu-theme` and `menu-lock` become `base-text-inverse` buttons with
  `click-left = barmenu theme` and `click-left = barmenu lock`; the "still polybar custom/menu" comment goes.

Nothing is needed from `theme`: every verb the theme menu uses exists. Nothing from barctl in this
record (see open question 3).

### 5. Dropped

- `TRIGGER` (`lockscreen hook-trigger`): `Lock now` (`lockscreen activate`) runs the same lock without
  needing the idle daemon to be running.
- `ENABLE`/`DISABLE` as stateless rows: replaced by rows 2-4, which show which one is in effect.
- `REFRESH`, `UNDO`, `DEFAULT` keep their commands; the labels become `Reload`, `Undo`, `Default`, in the
  same case as the new rows.

### 6. Build order

1. desktop-tools PR: providers, `Row.current`, the `theme` and `lock` menus in `menus.toml`, tests (stubbed
   queries), wiki (CLI reference, In-Depth Configuration for `provider` and `current`); then the release
   (release-please).
2. dotfiles PR: pin that desktop-tools release, add the three `lockscreen` verbs (with tests), the rasi
   styles and the `menu.ini` switch, in one PR. Until it merges the bar keeps its `custom/menu` buttons, so
   step 1 changes nothing live. Opened by hand before step 2, the lock menu's row 4 would pause with no end
   (today's `hook-disable` ignores the duration) and row 6 would fail as an unknown verb: one more reason the
   bar switches in the same PR that adds the verbs.

## Alternatives considered

- **`rows_from = ["<command>", …]`**: barmenu runs a command that prints rows as JSON. Generic and
  overridable without Python, but the menu's labels and glyphs would move into zsh, against record 0003's
  direction (desktop tools in Python), and every menu open pays a zsh start-up. Lost.
- **Theme and lock as barctl modules with sources**, opened through the existing `dynamic`: it reuses code,
  but makes two static buttons into bar modules with a state store just to fill a menu, and `dynamic` only
  appends after static rows. Lost; open question 3 covers the lock button later becoming a module.
- **Every scheme as a row in the theme menu** (the brain coordinator's starting idea): 13 schemes plus the
  actions overflow the 8-line window, and it would duplicate `theme pick`'s marked, previewed list without
  the previews. Lost, but open question 1 asks.
- **A timed pause run by a background `sleep` process**: nothing could show the end time or cancel it
  cleanly, and it dies with the menu's session. Lost to the transient systemd timer.

## Consequences

- barmenu gains a small provider interface and the current mark; every other menu is unchanged.
- The bar loses its last `custom/menu` modules, so polybar's menu module settings
  (`base-menu-inverse`) can go in the dotfiles PR if nothing else uses them.
- A provider runs queries on every open: `theme current --json` and `lockscreen status --json` (with a
  `systemctl --user show` inside it), both well under the 2 s limit; a failing one only costs the state.
- Rollback: revert the dotfiles `menu.ini` change; the barmenu menus can stay.
- Wiki pages that change in step 1: CLI-Reference (regenerated: `barmenu theme`, `barmenu lock`),
  In-Depth-Configuration (`provider`, `current`), Architecture-Internals (providers).

## Open questions

Answered: the brain coordinator approved this record on 2026-11-04 with all five recommendations, (a) each.

1. **Schemes in the theme menu.** (a) One row, `Scheme: <current>…`, opening `theme pick`; (b) every
   scheme as its own row, the current one marked; (c) only the current mode's schemes inline (about 9 dark
   or 4 light), then `theme pick` for the rest. Recommendation: **(a)**: `theme pick` already marks the
   current scheme and shows previews, and the menu stays within its 8 lines.
2. **Timed pause length.** (a) One row, 1 hour; (b) three rows, 30 minutes, 1 hour, 2 hours; (c) a
   follow-up rofi prompt for any duration. Recommendation: **(a)**: it is the presentation case; the verb
   takes any duration, so a row can be added in an override.
3. **Lock button showing idle lock off.** (a) Not now: the button stays a static lock glyph; (b) make it a
   barctl module (new `idlelock` source over `lockscreen status --json`, glyph md-lock_off when paused, the
   `warn` tier), refreshed by the `lockscreen` verbs. Recommendation: **(a) now, (b) as its own record
   later**: it is useful (a forgotten pause is a security gap) but it is a new barctl source and a bar
   change, larger than this menu move.
4. **Suspend in the lock menu.** (a) Keep it (row 5, `power suspend`); (b) drop it, since the power button
   already offers it. Recommendation: **(a)**: it sits next to the lock it implies, and it runs the same
   `power suspend`, so there is one confirm-and-lock path.
5. **Forget GPG passphrase.** (a) A `lockscreen forget-passphrase` verb, with a notification;
   (b) the row runs `gpg-connect-agent reloadagent /bye` directly, silently. Recommendation: **(a)**: one
   place for the timeout, and the click gets feedback.

## Change log

| Date | Change |
|---|---|
| 2026-11-04 | Proposed by the desktop coordinator |
| 2026-11-04 | Approved by the brain coordinator, about 04:20 UTC on 2026-11-04, by SendMessage to the desktop coordinator, before the arbiter's cut-over (06:59), with all five recommendations: one `Scheme: <current>…` row opening `theme pick`; a 1-hour timed pause only; no bar indicator for idle lock off, for now; Suspend stays in the lock menu; a `lockscreen forget-passphrase` verb with a notification |
| 2026-11-04 | Step 1 of §6 built: providers, `Row.current`, the `theme` and `lock` menus |

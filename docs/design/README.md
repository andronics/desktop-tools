# Design records

Why the code is the way it is. Copy [0000-template.md](0000-template.md) to `NNNN-short-title.md` before a
new feature, a new dependency, or a public-interface change, and add a line below. Status moves Proposed →
Approved (by a human) → Implemented; supersede an implemented record with a new one, never rewrite it.

**Index:** read this first, then open only the records relevant to your task. CI checks that every record is listed.

| # | Title | Status | Decision in one line |
|---|---|---|---|
| 0001 | [Theme and lock bar menus on barmenu](0001-theme-and-lock-bar-menus.md) | Implemented | The last two `custom/menu` buttons become `barmenu theme` and `barmenu lock`, with menu providers and a current-row mark new in barmenu |
| 0002 | [A right-click menu on the tessera bar module, and glyph overrides in barctl](0002-tessera-bar-menu.md) | Approved | Right-click on the tessera module opens `barmenu tessera` (lock and unlock, copy through `tessera pick`, a read-only sync row, never `tessera sync`); a new `glyph_override` in modules.toml wins over a pusher's glyph |
| 0003 | [The player capsule: one "now playing" module on the bar](0003-player-capsule.md) | Approved | The bar's player buttons become one barctl-drawn capsule (play-state icon, scrolling `Artist – Title`, an underline progress line; right-click `barmenu player`) beside an output segment (volume, output kind and name, Bluetooth battery; `barmenu outputs`), tried beside the old group first; ideas 2-6 are a roadmap only |
| 0004 | [Printer and scanner modules on the bar, drawn by barctl](0004-printer-scanner-modules.md) | Approved | The plain printer and scanner launchers become barctl `printer` and `scanner` sources (IPP pull notifications and DNS-SD events, eSCL status) with tiers, connectivity and `barmenu` menus (queue with confirmed cancels, pause, default, test page; feeder, duplex and flatbed scans to a multi-page PDF), actions through a new `devices` command, tried beside the old buttons first |
| 0005 | [The player capsule's roadmap: chips, quiet when idle, a transport row, a visualiser strip](0005-player-capsule-roadmap.md) | Proposed (phase A Approved, built) | Ideas 2-5 of record 0003 (approved by Stephen 2026-11-12) as four phases: player chips with per-segment clicks, fade and hide when idle with spoken-word skip and speed, an in-place transport row opened by an icon click (polybar has no hover), and a cava visualiser sent over polybar's `send` action, gated by a measured CPU budget and off by default |
| 0006 | [The crew strip shows favourites and live coordinators only](0006-crew-favourites.md) | Approved | `favourite` from the registry; the strip, `crew cycle` and the scroll show favourites plus running coordinators (all of them when no entry carries the key); the full menu and the verbs still reach every one |

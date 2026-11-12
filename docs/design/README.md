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
| 0004 | [Printer and scanner modules on the bar, drawn by barctl](0004-printer-scanner-modules.md) | Proposed | The plain printer and scanner launchers become barctl `printer` and `scanner` sources (IPP pull notifications and DNS-SD events, eSCL status) with tiers, connectivity and `barmenu` menus (queue with confirmed cancels, pause, default, test page; feeder, duplex and flatbed scans to a multi-page PDF), actions through a new `devices` command, tried beside the old buttons first |

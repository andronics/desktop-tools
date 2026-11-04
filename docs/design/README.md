# Design records

Why the code is the way it is. Copy [0000-template.md](0000-template.md) to `NNNN-short-title.md` before a
new feature, a new dependency, or a public-interface change, and add a line below. Status moves Proposed →
Approved (by a human) → Implemented; supersede an implemented record with a new one, never rewrite it.

**Index:** read this first, then open only the records relevant to your task. CI checks that every record is listed.

| # | Title | Status | Decision in one line |
|---|---|---|---|
| 0001 | [Theme and lock bar menus on barmenu](0001-theme-and-lock-bar-menus.md) | Implemented | The last two `custom/menu` buttons become `barmenu theme` and `barmenu lock`, with menu providers and a current-row mark new in barmenu |

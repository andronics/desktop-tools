# desktop-tools

Stephen's desktop tools in Python: barctl (the Polybar controller), barmenu and the rest of the dotfiles' tools

Stephen's desktop tools, moved from the dotfiles' zsh library to one Python package ([dotfiles record 0003](https://github.com/andronics/dotfiles/blob/main/docs/design/0003-desktop-tools-in-python.md)).
Each tool is its own command with the name and flags it had in zsh, and is also mounted under `desktop-tools`. Today:

- **`barctl`**, the Polybar controller: it follows volume and the media players, holds the state of every
  `custom/ipc` module, colours it from the theme, and is the only program that talks to polybar.
- **`barmenu`**, the bar's rofi menus, opened just above the clicked button.

```console
$ barctl status
controller: running (pid 2248259, since 2026-11-04T09:12:03+00:00)
bar 1254861: answering
audio-level        volume   active           2s  󰖁 35%
player-play-pause  player   active           9s
player-metadata    player   active           9s  Wolf Alice: Silk
```

## Table of Contents

**Getting started**: [Introduction](Introduction) · [Quick Start](Quick-Start)

**Using it**: [In-Depth Configuration](In-Depth-Configuration) · [CLI Reference](CLI-Reference)

**Help**: [Troubleshooting](Troubleshooting) · [FAQ](Frequently-Asked-Questions) · [Security](Security)

**Developers**: [Contributing](Contributing) · [Architecture Internals](Architecture-Internals) · [Testing Guide](Testing-Guide) · [Release Process](Release-Process)

# Introduction

## What it is

Stephen's desktop tools in Python: one package, `desktop_tools`, one console command per tool, installed with `uv tool`
from a release tag pinned in the dotfiles. The dotfiles keep only config (the polybar ini files, `modules.toml`, sxhkd)
and, while a zsh module still calls a moved function, one-line shims. The design is the dotfiles'
[record 0003](https://github.com/andronics/dotfiles/blob/main/docs/design/0003-desktop-tools-in-python.md), which amends [record 0001](https://github.com/andronics/dotfiles/blob/main/docs/design/0001-polybar-ipc-module-taxonomy.md) (the Polybar IPC module taxonomy).

The first tools are **barctl**, the bar controller, and **barmenu**, the rofi menus it draws. It is not a general
status-bar framework: it serves this desktop's polybar 3.7, bspwm and theme.

## How it works

polybar draws nothing on its own: each IPC module has one hook, `hook-0 = barctl render <module>`, whose output is the
module's text. barctl keeps every module's state as a small JSON file and redraws a module (a poke over polybar's IPC
socket) only when what it shows changes.

- **The controller** (`barctl run`, from `barctl.service`) follows the event streams: `pactl subscribe` for volume,
  `playerctl -a --follow` for the players. It writes each module's state and pokes the module.
- **Other tools** change the bar only through `barctl push` (crew's coordinator strip, next), never polybar directly.
- **`render`** reads the state and the theme's roles at draw time: unavailable `dim`, idle `fg_dim`, active `accent`,
  alert `urgent`. It wraps the text in action tags that run `barctl click <module> <button>`, so every click goes
  through barctl, runs detached, and acts on what the bar shows (the shown player, not playerctl's default).
- **Right-click menus** are rows in `modules.toml` plus rows the module's source gives, drawn by barmenu (rofi).

`render` and `push` run with the standard library only, before Typer is imported, so a redraw costs about as much as
the zsh version did (about 30 ms).

## When not to use it

- On another desktop: it assumes polybar 3.7's IPC protocol, PipeWire's `pactl`, MPRIS players through `playerctl`,
  rofi, and the dotfiles' generated theme (`~/.local/state/theme/current/theme.zsh`).
- For a module that is a clock: polybar's own `custom/script` with an `interval` is simpler.
- For the printer, scanner, VPN, Bluetooth and counter modules: not built yet; their source names are reserved and come
  in later PRs (see [Adding a Module](Adding-A-Module)).

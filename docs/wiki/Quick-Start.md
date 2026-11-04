# Quick Start

From nothing to a working desktop-tools in a few minutes. Everything else is in [In-Depth Configuration](In-Depth-Configuration).

## Prerequisites

- For running from source: Python >= 3.13 and [uv](https://docs.astral.sh/uv/)
- On the desktop: polybar 3.7 with `enable-ipc = true`, `pactl` (pipewire-pulse), `playerctl`, rofi, xdotool and
  xrandr, and the dotfiles' theme. No accounts or keys.

## Install

From a release tag, with a uv-managed Python so a system Python upgrade can't break the bar's hook
([record 0003 §A2](https://github.com/andronics/dotfiles/blob/main/docs/design/0003-desktop-tools-in-python.md#a2-installing-uv-tool-from-a-release-tag)):

```sh
uv tool install --python 3.13 --managed-python "git+https://github.com/andronics/desktop-tools@v<version>"
desktop-tools completions zsh --out ~/.config/zsh/completions
```

The dotfiles do this in `desktop/.postinstall`, from the version pinned in `desktop/.config/desktop-tools/version`.
Commands land in `~/.local/bin`. `uv tool` refuses to overwrite a file it didn't install, so the zsh `barctl` and
`barmenu` wrappers must be unlinked first (the dotfiles' cut-over PR does it).

## First run

```sh
systemctl --user start barctl.service   # the controller: ExecStart=%h/.local/bin/barctl run
barctl doctor                           # every check ok, or a fix to try for each problem
barctl status                           # the controller, the bars and every module
barctl watch                            # each change as it happens; Ctrl-C to stop
```

A polybar module drawn by barctl:

```ini
[module/audio-level]
type = custom/ipc
initial = 1
hook-0 = barctl render audio-level
```

## Next steps

- [Adding a Module](Adding-A-Module): a new bar module, pushed or with a source of its own
- [In-Depth Configuration](In-Depth-Configuration): `modules.toml`, `menus.toml` and the environment
- [Troubleshooting](Troubleshooting) if something doesn't work

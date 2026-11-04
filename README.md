# desktop-tools

[![CI](https://github.com/andronics/desktop-tools/actions/workflows/base-ci.yml/badge.svg)](https://github.com/andronics/desktop-tools/actions/workflows/base-ci.yml)
[![Release](https://img.shields.io/github/v/release/andronics/desktop-tools?sort=semver)](https://github.com/andronics/desktop-tools/releases)

Stephen's desktop tools in Python: barctl (the Polybar controller), barmenu and the rest of the dotfiles' tools

Stephen's desktop tools, moved from the dotfiles' zsh library to one Python package, one command per tool, each with
the name and flags it had before. The design is the dotfiles' [record 0003](https://github.com/andronics/dotfiles/blob/main/docs/design/0003-desktop-tools-in-python.md).

- **`barctl`**, the Polybar controller and the only program that talks to polybar. The controller (`barctl run`, from
  `barctl.service`) follows volume (`pactl subscribe`) and the media players (`playerctl -a --follow`), holds every
  `custom/ipc` module's state, and redraws a module only when what it shows changes. Each module's hook,
  `barctl render <module>`, colours its state from the theme's roles. Other tools change the bar with `barctl push`;
  every click goes through `barctl click`, runs detached, and acts on what the bar shows. Verbs: `status`, `list`,
  `show`, `push`, `alert`, `menu`, `click`, `reload`, `restart`, `theme`, `enable`, `disable`, `watch`, `doctor`,
  `run`, `render`, `hide`, `unhide`.
- **`barmenu`**, the bar's rofi menus, opened just above the clicked button: `barmenu <menu>`, `barmenu run <command>`.
- **`crew`**, the coordinator switchboard (brain record 0019 §7, replacing the dotfiles' `coord`): one hidden
  terminal per Claude Code coordinator, docked left or right when shown, with its strip in the bar (pushed to barctl)
  and the Claude hooks' `crew status`. Showing never starts a stopped coordinator; only `crew toggle --launch` (the
  glyph's left click) does, through `meta <name> launch`. Verbs: `toggle`, `show`, `hide`, `cycle`, `width`, `side`,
  `guard`, `status`, `bar`, `list`, `names`, `stopped`. The wiki's
  [Crew](https://github.com/andronics/desktop-tools/wiki/Crew) page has the rest.

## Quick Start

From a release tag, with a uv-managed Python (the dotfiles' `desktop/.postinstall` does this from the version they pin):

```sh
uv tool install --python 3.13 --managed-python "git+https://github.com/andronics/desktop-tools@v<version>"
desktop-tools completions zsh --out ~/.config/zsh/completions
systemctl --user start barctl.service
barctl doctor
```

A polybar module barctl draws is `type = custom/ipc`, `initial = 1`, `hook-0 = barctl render <module>`, listed in
`$XDG_CONFIG_HOME/barctl/modules.toml`. Adding one: the wiki's
[Adding a Module](https://github.com/andronics/desktop-tools/wiki/Adding-A-Module).

## Module notes

- **Live today:** `audio-level` (volume), `player-play-pause` and `player-metadata` (players).
- **Printer and scanner** (next PRs; one Brother device): availability is a 1 to 2 s TCP connect to port 631, at a low
  rate. Never port 9100 (it can start an empty print job), and never port 54921 or eSCL on a timer (it wakes the
  scanner). This overrides record 0003 §B8's timed `GET /eSCL/ScannerStatus`, after the homelab coordinator found the
  printer off the network; the scanner's eSCL query runs only when its menu opens.
- **VPN, Bluetooth and the counter:** as record 0003 §B8 says, each in its own PR.

The full walk-through is in the wiki's [Quick Start](https://github.com/andronics/desktop-tools/wiki/Quick-Start).

## Documentation

Everything is in the **[wiki](https://github.com/andronics/desktop-tools/wiki)**. Its source is [`docs/wiki/`](docs/wiki/), in this
repository, reviewed with the code.

- [Introduction](https://github.com/andronics/desktop-tools/wiki/Introduction): what it is and how it works
- [In-Depth Configuration](https://github.com/andronics/desktop-tools/wiki/In-Depth-Configuration): every setting
- [Troubleshooting](https://github.com/andronics/desktop-tools/wiki/Troubleshooting) and [FAQ](https://github.com/andronics/desktop-tools/wiki/Frequently-Asked-Questions)
- [Contributing](https://github.com/andronics/desktop-tools/wiki/Contributing) and [Release Process](https://github.com/andronics/desktop-tools/wiki/Release-Process)

## For AI assistants

Built with AI assistants; every change gets human review. **[AGENTS.md](AGENTS.md) and
[.agents/stack.md](.agents/stack.md) are the only instruction files** (stack, commands, rules, definition of
done, docs map). Read them instead of this README.

| Assistant | Entry point |
|---|---|
| Claude Code | [CLAUDE.md](CLAUDE.md) (imports both) + [.claude/settings.json](.claude/settings.json) |
| Codex, Cursor, Copilot coding agent | AGENTS.md, natively ([Copilot](.github/copilot-instructions.md), [Cursor](.cursor/rules/project.mdc) pointers) |
| Gemini CLI | [GEMINI.md](GEMINI.md) (imports both) |
| Chat without repo access | [docs/ai/prompts.md](docs/ai/prompts.md), "Context for a chat assistant" |

Humans: kick-off prompts are in [docs/ai/prompts.md](docs/ai/prompts.md), and the review checklist in
[docs/ai/review-checklist.md](docs/ai/review-checklist.md).

## Development

```sh
uv sync                           # Python >= 3.13, dev tools included
uv run pytest                     # tests (80% coverage floor)
uv run ruff check && uv run mypy  # lint and type check
```

New project? Fill in `.github/repository.toml` (the description, `homepage` = the wiki, `topics`), then run
`python3 scripts/repo-metadata.py` to set GitHub's About box from it; CI warns when the two drift.

The workflow is: a branch, Conventional Commit PR titles, squash merge. Releases are automated by
release-please. See [Contributing](https://github.com/andronics/desktop-tools/wiki/Contributing).

This project was generated from [template-base](https://github.com/andronics/template-base) and
[template-python](https://github.com/andronics/template-python). Template
fixes arrive as a weekly *Template update* PR per template.

## License

Released into the public domain under the [Unlicense](LICENSE).

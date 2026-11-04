# Contributing

<!-- AI assistants: AGENTS.md holds these rules in short form. Read further only for the reasons behind a rule. -->

## Development setup

```sh
git clone https://github.com/andronics/desktop-tools && cd desktop-tools
uv sync                                  # Python >= 3.13: uv fetches it if needed
uv tool install pre-commit && pre-commit install -t pre-commit -t commit-msg
uv run pytest                            # all green before you start
```

## Workflow

1. Branch from `main`: `feat/<topic>` or `dev/<topic>`. Pushes build `:<branch>` images (when there is an image).
2. Non-trivial change (a new feature or dependency, or a change to a public interface): write a [design record](https://github.com/andronics/desktop-tools/tree/main/docs/design) first, and get it approved.
3. Open a PR against `main` with a **Conventional Commit title** (`feat: add retry to uploads`; `feat!:` for a breaking change). It becomes the squash commit and the CHANGELOG line, so CI wants a lower-case subject with no full stop: see [Release Process](Release-Process).
4. CI must be green: tests, lint, types, secret scan, manifests, and the wiki checks.
5. A code owner reviews ([review checklist](https://github.com/andronics/desktop-tools/blob/main/docs/ai/review-checklist.md)), then squash-merge.
   The only code owner and also the author? GitHub won't let you approve your own PR. Review it against the checklist yourself, then, if `main`'s ruleset lets admins bypass it, merge with `gh pr merge --squash --admin` once CI is green. Never push to `main` instead.

Never edit `CHANGELOG.md` or the version, and never push tags: release-please does that. AI assistants push their own feature branches and open the PR; `main`'s ruleset, not `.claude/settings.json`, is what keeps them off `main`.

## Code style

- ruff (lint + format, line length 100) and mypy `--strict` decide formatting and typing. Don't argue with them in review.
- Comments explain *why*. Logging goes through `logging`; only the CLI prints.
- Settings go through `config.SETTINGS`. Secrets come from `_FILE`, and are never logged.
- Prefer the standard library and existing dependencies. Justify every new one in the PR.

- Each tool keeps the name, flags, exit codes and output of its zsh version; a change says so in its cut-over PR.
- `barctl render` and `push` import nothing beyond the standard library (`tests/unit/test_barctl_cli.py` checks).
- Only `common/polybar.py` talks to polybar (`tests/unit/test_one_owner.py` checks).
- Child processes start through `common/procs.py`; anything started from a click is detached.
- Glyphs are current Nerd Font codepoints written as `\U000Fxxxx` escapes.
- Every tool logs through `common/journal.py` (brain record 0017); `render` and `push` write no run records.
- After changing a command: `uv run scripts/gen-completions.py` and `uv run scripts/gen-wiki.py`.

## Working with AI assistants

AI assistants are welcome and expected, under the same rules as anyone else:

- They follow [AGENTS.md](https://github.com/andronics/desktop-tools/blob/main/AGENTS.md). Each tool's own file (`CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.cursor/rules/`) points there.
- Kick-off prompts: [docs/ai/prompts.md](https://github.com/andronics/desktop-tools/blob/main/docs/ai/prompts.md).
- The PR template asks how much was generated. Say so honestly: it tells the reviewer how closely to read.
- An assistant that asks you something gives its own recommendation and why, so you can say "yes" or argue with a stated reason instead of having to ask. It still waits for your answer.
- A human who understands the change approves every PR. "The AI wrote it" is never a reason to merge.
- An assistant ending a session lists what it left behind (worktrees, local and remote branches, temp files, processes, containers), says whether each is safe to remove and why (merged as #N, already in `main`, unpushed work), and removes only what you approve. Left alone, these pile up: a branch with an unpushed commit can look like a merged one, and deleting a worktree while another agent still works in it breaks that agent's run. The assistant's own scratch directory is out of scope: the tool manages it.
- Assistants change only this repository. A change another codebase needs (another repository, a submodule, an installed dependency) is asked for in an issue there, through that repository's own issue form so its maintainers get the fields they ask for (a hand-written issue only when it has none, with your yes); a bug in a template-owned file goes to the template that owns it (`_src_path` in its `.copier-answers.*.yml`), because every other project has it too.

## Documentation

This wiki's source is [`docs/wiki/`](https://github.com/andronics/desktop-tools/tree/main/docs/wiki), in the repository. It's published to the GitHub wiki from `main`, so **never edit the GitHub wiki directly**: the next publish overwrites it.

- Code and docs change in the same PR. .agents/stack.md's "Docs map" says which page goes with which code, and CI fails a PR that changes watched paths without touching `docs/wiki/`. A reviewer, never the author, can add the `no-docs-needed` label when nothing user-visible changed.
- The required pages and headings are in `docs/wiki/.standard.toml` (template-owned). Add pages freely, and link each one from `_Sidebar.md`.
- Tables between `<!-- generated:start/end -->` markers come from the code: run `uv run scripts/gen-wiki.py`.
- Link pages by name (`[Quick Start](Quick-Start)`), and repo files by full URL.
- Check locally: `python3 scripts/check-wiki.py`.

### Keeping AI context small

Assistants pay for what they read in every session, so the instruction files are written for that:

- `AGENTS.md` and `.agents/stack.md` hold the *rules*, tersely. The *reasons* live on these wiki pages. `sh scripts/checks.sh` fails if they or a tool pointer file (`CLAUDE.md`, `GEMINI.md`, Copilot, Cursor) exceed their context budget. That budget is template-base's: if it's genuinely too small, change it there.
- AGENTS.md's and .agents/stack.md's "Don't read" lists (and the `Read` denies in `.claude/settings.json`) keep lock files, caches and generated output out of context. Add any large or generated path the project introduces.
- `docs/design/README.md` indexes every design record, so an assistant reads one line per record instead of every record. CI checks the index is complete.
- Pointer files only point: don't copy AGENTS.md content into them.
- The checks print one line when they pass, and their detail only when they fail (`check-wiki.py --verbose` lists the warnings it counts). Keep new scripts that way: an assistant reads their output on every run.
- Every turn sends the whole conversation again. Start each task in a new session (the assistant suggests it when one ends), and point to a file or a failing check by name instead of pasting it.
- Assistants reply tersely: the result, then what they need from you. Terse means no preamble or recaps, not fewer reasons: recommendations and what was skipped still belong in the reply.

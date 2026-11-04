# Security

## Threat model

The tools run as Stephen on his desktop and open no network port. What they trust and guard:

- **Pushed text is text.** Anything a program pushes to the bar has polybar's `%{` escaped, and the colour and action
  tags are barctl's own, so a pusher can't put a command into a click. A click runs only the command in
  `modules.toml`, with `{target}` filled in as one whole argument, never through a shell.
- **One writer per module.** `push` is refused for a module drawn by barctl's own source or owned by another pusher.
- **Local sockets only.** The control socket and the state files are in `$XDG_RUNTIME_DIR/barctl` (mode 700, the socket
  600); polybar's sockets are its own. Anyone running as Stephen can already change his bar.
- **Menu items are data.** crew's quick menu runs what `meta <name> menu --json` offers, but only as argument
  lists, never through a shell: a `meta` verb with its arguments, `xdg-open` for `https://` and `obsidian://` links
  only, `code` for an absolute path only, and `xclip` with the text on stdin.
- **Out of scope:** a hostile process running as Stephen.

## Secrets

- Give each secret through `DESKTOP_TOOLS_<KEY>_FILE`, a mounted file. A secret setting is also read from its plain variable and the config file, like any setting, so keep it out of both: `docker inspect` and `ps` show variables. See [In-Depth Configuration](In-Depth-Configuration#secrets).
- Values are never logged. Logs and `desktop-tools config` show where a value came from, never the value itself.
- CI scans every commit with gitleaks, and secrets in history fail the build.

This project has no secrets; the journal helper redacts anything that looks like one before logging (brain record 0017).
A tool's arguments never reach the journal: the helper drops them from what it logs, and before its first entry it
rewrites its own process's command line to the program alone, since journald copies that into `_CMDLINE`. Where it
can't, it writes no journal entry (brain PR 170). From then on `ps` shows the tool without its arguments.

## Hardening

- **Supply chain:** dependencies are pinned in the lock file and updated weekly by Dependabot. GitHub Actions are pinned to commit SHAs.
- **Dependency auto-merge:** Dependabot patch updates get auto-merge queued by `dependabot-automerge.yml`: they still need a code owner's approval, then merge once CI passes.

- **Input validation:** a pushed state is checked field by field (tiers, counts, segment ids) and anything unknown is
  dropped; module and segment names are restricted to the characters a file name and an action tag can carry.
- **No root:** nothing here needs it (brain record 0016).

## Reporting a vulnerability

Report privately through [GitHub security advisories](https://github.com/andronics/desktop-tools/security/advisories/new), never in a public issue.

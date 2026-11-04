# CLI Reference

`desktop-tools --help` lists the commands. `desktop-tools <command> --help` shows a command's options.

## Commands

Generated from the code: don't edit, run `uv run scripts/gen-wiki.py`.

<!-- generated:start cli -->
### `desktop-tools config`

Print the effective configuration and where each value came from. Secrets: set or unset.

| Option | Environment variable | Description |
|---|---|---|
| `--config`, `-c` | `DESKTOP_TOOLS_CONFIG` | Config file (default /etc/desktop-tools/config.yaml; missing is fine). |

### `desktop-tools version`

Print the version.
<!-- generated:end cli -->

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Failure while running |
| 2 | Bad usage or invalid configuration |

<!-- guidance: add project-specific exit codes, and worked examples of common invocations. -->

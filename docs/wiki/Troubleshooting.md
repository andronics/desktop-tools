# Troubleshooting

## Diagnostics

- **Effective configuration:** `desktop-tools config` prints every setting and where it came from (default, file, env var). A secret shows only whether it is set (`******** (set)` or `(unset)`), never its value.
- **More logging:** `DESKTOP_TOOLS_LOG_LEVEL=DEBUG`.

## Common problems

<!-- guidance: one ### heading per symptom, in the user's words ("Exits with 'cannot read ..._FILE'"), then the cause and the fix. Add one whenever a bug report or a support question shows a new failure mode. -->

### `error: cannot read DESKTOP_TOOLS_..._FILE`

The file named by a `_FILE` variable doesn't exist, or the process can't read it. Check the path inside the container or unit, and the file's owner and mode: the process runs as uid 1000 / the `desktop-tools` user.

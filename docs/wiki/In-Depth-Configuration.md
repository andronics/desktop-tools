# In-Depth Configuration

## Where configuration comes from

Every setting can be given in four places, and the first one that has it wins:

1. `DESKTOP_TOOLS_<KEY>_FILE`: the path of a file holding the value (Docker and Kubernetes secrets)
2. `DESKTOP_TOOLS_<KEY>`: an environment variable
3. the YAML config file: `DESKTOP_TOOLS_CONFIG` or `--config`, default `/etc/desktop-tools/config.yaml`. A missing file is fine.
4. the built-in default

`<KEY>` is the setting's key in upper case, with the dots as underscores: `listen.port` is `DESKTOP_TOOLS_LISTEN_PORT`.
A value of the wrong type, such as `0.5` or `true` for an integer or a list for a string, is an error that names the setting.
`desktop-tools config` prints the effective value of every setting and where it came from, with secrets masked.
The engine is [interpose](https://github.com/metalayerlab/interpose)'s settings loader; `src/desktop_tools/config.py` declares the settings.

## Settings

Generated from the code: don't edit the table, run `uv run scripts/gen-wiki.py`.

<!-- generated:start settings -->
| Key | Environment variable | Default | Description |
|---|---|---|---|
| `log_level` | `DESKTOP_TOOLS_LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
<!-- generated:end settings -->

<!-- guidance: below the table, explain anything a one-line description can't: how settings interact, valid ranges, performance trade-offs. -->

## Secrets

A secret setting is read from all four places, like any other, so nothing stops it being set in the config file or a plain environment variable. Don't: `docker inspect` and `ps` show the variable. Use the `_FILE` variant and mount the value as a file:

- Docker: `DESKTOP_TOOLS_<KEY>_FILE=/run/secrets/<name>` with a secrets file or bind mount
- Kubernetes: a Secret mounted as a volume (SOPS-encrypted in the GitOps repo)
- systemd: `LoadCredential=` and `%d/<name>`

<!-- guidance: list this project's secrets, or say there are none. -->

## Examples

A complete config file with every default is in [contrib/desktop-tools.example.yaml](https://github.com/andronics/desktop-tools/blob/main/contrib/desktop-tools.example.yaml).

<!-- guidance: two or three real-world configurations, each with a sentence on when you'd use it. -->

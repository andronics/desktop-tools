# Testing Guide

## Running the tests

```sh
uv run pytest                                            # unit tests, with an 80% coverage floor
uv run pytest tests/unit/test_config.py -k env --no-cov  # a subset, no coverage floor
RUN_INTEGRATION=1 uv run pytest -m integration --no-cov  # integration tests (real external systems), no coverage floor
```

CI runs the unit tests on every supported Python version, together with ruff, mypy (strict), the wiki checks and the manifest checks. All of them block a merge.

## Test layout

| Path | What goes there |
|---|---|
| `tests/unit/` | Fast and offline: no network, no real external systems. Most tests. |
| `tests/integration/` | Real dependencies, marked `@pytest.mark.integration`; skipped unless `RUN_INTEGRATION=1` |
| `tests/conftest.py` | Shared fixtures: `clean_env`, `isolate` (every folder in `tmp_path`, for every test), `theme`, `bar`, `journal_sock`, `commands`, `launched`, `write_config` |
| `tests/fakes.py` | A fake polybar answering on its IPC socket, the journal's datagram socket, the theme, and fake commands on PATH that log every call |
| `tests/crew_fakes.py` | crew's fake desktop (the `desk` fixture): a bspwm keeping its windows in a file, a tmux, `meta`, alacritty, rofi and notify-send |

Nothing a test runs reaches the live desktop: `isolate` points every XDG folder, barctl's state, the journal socket,
the run store, `/proc` as barctl reads it and polybar's socket folder into `tmp_path`.

## Writing tests

- Every behaviour change needs a test that fails without it. A bug fix starts with the failing test.
- Assert outcomes (outputs, side effects, errors), not internal calls.
- Use placeholders for anything that looks real: `example.org`, `192.0.2.0/24`, fake tokens.
- Don't lower the coverage floor or skip a test to make CI pass.

- **Commands** (`pactl`, `playerctl`, `rofi`, ...): `commands(name="python body")` writes a script first on PATH that
  logs its arguments; `calls(log)` reads them back. A followed stream is a FIFO the test writes (`Feed`).
- **polybar**: the `bar` fixture listens on `ipc.4242.sock`; `bar.pokes()` and `bar.wait(n)` give the modules poked.
- **Detached launches**: the `launched` fixture records `procs.detach` instead of running it.
- **`--help` runs nothing**: `test_help_runs_nothing` runs every command's help in a real process with every command
  faked to fail, and checks nothing was called, written or sent.
- The zsh controller's tests (`tests/barctl.zsh` in the dotfiles) are ported case by case; their names appear in the
  docstrings ("Ported: ...").
- **crew** (`desk` fixture): `desk.coordinators(...)` is `meta`'s answer, `desk.window(...)` and `desk.session(...)`
  add windows and sessions, `desk.shown()`, `desk.padding()`, `desk.launched()`, `desk.lifecycle()` (every
  `meta <name> launch|stop|restart` call), `desk.sessions()` and `desk.notified()` say what happened. The fake
  `meta` stops and restarts too, and exits as files say (`stop-rc-<name>`, `check-rc`, with a `*-why`); the fake
  rofi answers with `rofi-answer`. The fake tmux refuses any call that doesn't name its own server (`-L` or `-S`) and the fixture fails
  the test, so nothing can reach the live server. crew's own detached children (the guard, the strip's refresh,
  notifications) are recorded, not run; alacritty runs (it is the fake) so a window appears.
  `tests/coordinators.zsh`'s cases (in the dotfiles) appear in the docstrings by name.

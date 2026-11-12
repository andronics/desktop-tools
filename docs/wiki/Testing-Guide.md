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
| `tests/crew_fakes.py` | crew's fake desktop (the `desk` fixture): a bspwm keeping its windows in a file, a tmux, `meta` (lifecycle, `menu` and read-only verbs), alacritty, rofi and notify-send; `ROFI_SEQ` and `XCLIP` for the menus |

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
- **journald's own fields**: `tests/unit/test_journal.py`'s `journald` fixture asks the fake journal socket for the
  sender's credentials (`SO_PASSCRED`) and reads its `/proc/<pid>/cmdline` while it is alive, as journald fills
  `_CMDLINE`; the sender waits on stdin after each entry. Linux only: skipped elsewhere.
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
- **barmenu's providers** (`tests/unit/test_barmenu_providers.py`): the fake `theme` and `lockscreen` print the
  JSON their `--json` verbs give, or fail, or sleep past the 2 s limit; each row's label, command and mark are checked
  for every state, and the state-free rows for every failure. Patch barmenu's own `time` (`bm.time`), never
  `time.sleep`: subprocess's wait loop sleeps too.
- **The player capsule** (`tests/unit/test_player_capsule.py`, design record 0003 §8): its fake `playerctl` starts with
  a guard that logs and fails any call that would control a player (`play`, `pause`, `play-pause`, `stop`, `next`,
  `previous`, `volume`, or `position`, `loop` or `shuffle` with a value), and the `config` fixture fails the test if
  it was reached, so no source or provider code can control a player. Scroll and progress are pure functions of the
  state and a time the test passes (`now=`); the source's clock is `source.clock`, so the 30-second position re-read
  runs on a fake clock. The art accent runs on fake `curl` and `magick`.
- **crew's menus** (`tests/unit/test_crew_menu.py`): the quick menu runs on meta's real JSON
  (`tests/fixtures/meta-menu-*.json`, from the live `meta <name> menu --json` with its paths made generic). The fake
  rofi answers from `rofi-answers`, one line per call ("" is Escape), and keeps each call's rows. `rofi-race`
  (seconds) makes a rofi started that soon after the last one closed close at once, as the menu's own click makes the
  real one do; `rofi-fails` (a count) fails that many Yes/No questions as a grab failure does. `make_desk` turns
  crew's Yes/No waits off (`life.SETTLE`, `life.UNSHOWN`); the tests of them set them back.

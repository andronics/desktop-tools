# Adding a Module

Every bar module that shows live state is a polybar `custom/ipc` module drawn by barctl
([dotfiles record 0003](https://github.com/andronics/dotfiles/blob/main/docs/design/0003-desktop-tools-in-python.md)). There are two kinds.

## A pushed module

Another program owns the state and tells barctl (crew's strip, next).

1. Add it to `modules.toml` with `pusher = "<program>"`, its `display`, `glyph`, clicks and menu rows
   ([In-Depth Configuration](In-Depth-Configuration#barctl-modulestoml)).
2. Add the polybar module, `type = custom/ipc`, `initial = 1`, `hook-0 = barctl render <module>`, and put it on a bar.
3. The program runs `barctl push <module> --source <program> --tier active --label …` (or `--json -` with a whole
   state, segments included). A program that can die without saying so passes `--ttl`, so its state goes
   `unavailable` instead of staying stale. A push to a module drawn by a source, or by another pusher, is refused
   (exit 3): one writer per module.
4. `barctl doctor` checks that the polybar config and `modules.toml` agree.

## A module with a source of its own

barctl follows the event stream itself.

1. Write a `Source` subclass in `src/desktop_tools/barctl/sources/` (`volume.py` is the model): `follow()` reads the
   stream and calls `self.set_all(tier, glyph=…, label=…, target=…)` for each event, `gone()` marks its modules
   unavailable when the stream ends, `commands` lists what `doctor` checks, and `menu_rows()` gives dynamic
   right-click rows. Run commands through `desktop_tools.common.procs` (`Stream`, `query`), never a shell.
2. List it in `SOURCES` (`sources/__init__.py`) and in `BUILT` (`barctl/modules.py`).
3. Name it as the module's `source` in `modules.toml`, add the polybar module as above, and write tests against fake
   commands (`tests/unit/test_barctl_sources.py` shows how: a FIFO stands in for the stream).

A source writes only through `self.set_all` (the same call `push` uses), and the module is poked only when what it
shows changes. Colours come from the theme's roles at render time; glyphs are current Nerd Font codepoints written as
`\U000Fxxxx` escapes, never the legacy U+F900 to U+FAFF range.

## Notes for the modules still to build

- **Printer and scanner** (one Brother device): the availability probe is a TCP connect to port 631 with a 1 to 2 s
  timeout, at a low rate. Never port 9100 (a connection there can start an empty print job), and never port 54921 or
  eSCL on a timer (`GET /eSCL/ScannerStatus` wakes the scanner). This overrides the timed eSCL status check in record
  0003 §B8: the homelab coordinator found the printer off the network, and a probe must not wake or print. The
  scanner's eSCL query runs only when its menu opens.
- **VPN, Bluetooth, the counter**: as record 0003 §B8 says.

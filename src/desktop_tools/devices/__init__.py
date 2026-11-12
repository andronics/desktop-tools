"""The printer and the scanner (record 0004): readers shared by barctl's `printer` and `scanner`
sources, barmenu's providers and the `devices` command.

- `ipp`: a minimal IPP/1.1 client for the local cupsd; `cups`: the printer's reading and tier.
- `sane`: scanners and their options; `escl`: an eSCL scanner's status; `mdns`: DNS-SD presence.
- `scan`: the scan runner (feeder, duplex, flatbed; pages to a PDF, PNG or JPEG).
- `prefs`: the chosen preset, format, folder and scanner; `store`: where files live.
- `cli`: the `devices` command, whose acting verbs refuse to run for an agent (§7).

Privacy (§7): no document name, job title, file name, path, device URI, host name or address
reaches a log, the journal, barctl's state fields or `doctor`.
"""

from __future__ import annotations

import os

AGENT_VARIABLES = ("COORDINATOR", "CLAUDECODE", "TESSERA_ACTOR")
REFUSED = "An agent may not operate the printer or scanner"


def agent() -> str | None:
    """The agent variable set in this environment (read, never set or cleared), else None."""
    return next((v for v in AGENT_VARIABLES if os.environ.get(v)), None)

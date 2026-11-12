"""The controller's control socket, `$XDG_RUNTIME_DIR/barctl/control.sock` (record 0003 §B4).

One JSON object per line each way: a request `{"op": ...}` and its answer `{"ok": ...}`.
Requests: `ping`, `pushed <module>` (a push changed what it shows: poke it, follow its ttl),
`alert <module>` (follow its blink), `expand <module>` (a capsule's transport row opened or
folded: draw it, record 0005 phase C), `pin`, `reload` (re-read modules.toml), `settings` (a
module was enabled or disabled) and `visualiser` (its switch changed, record 0005 phase D). A
client waits at most a second: no answer means no controller.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from desktop_tools.barctl import state as st

TIMEOUT = 1.0


def path() -> Path:
    return st.runtime() / "control.sock"


def request(op: str, timeout: float = TIMEOUT, **fields: Any) -> dict[str, Any] | None:
    """Ask the controller; its answer, or None when no controller answered."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path()))
            sock.sendall((json.dumps({"op": op, **fields}) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
    except OSError:
        return None
    try:
        answer = json.loads(data)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None

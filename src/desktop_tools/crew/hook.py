"""`crew status`: what nine Claude Code hooks in ~/.claude/settings.json run, with the hook's JSON
on stdin, in every Claude session under the actors folder.

It never prints to stdout and always returns 0. A session whose cwd is
`<actors>/<name>(/...)` for a coordinator crew knows moves `<name>` between idle, busy and
waiting in `$XDG_RUNTIME_DIR/crew/state/<name>`; any other session is a silent no-op, rejected on
a plain substring test before the JSON is parsed. Only a change of state is written (by rename),
and only a change starts the strip's refresh and, entering waiting, the notification, both
detached, so the hook returns at once. Event to state, as coord's:

    UserPromptSubmit, PostToolUse, PostToolUseFailure   busy (an answered question or a
                                                        granted permission clears waiting)
    PreToolUse for AskUserQuestion                      waiting (the question is the notice)
    Notification (permission and elicitation types)     waiting
    Stop, StopFailure, SessionStart                     idle
    SessionEnd                                          state removed

`idle_prompt` is not waiting: coordinators run self-paced loops that end a turn every tick, so
it would fire about 60 s after each one and keep the strip red.

Standard library only, with the registry's kept copy (never `meta`): this is a hot path.
"""

from __future__ import annotations

import sys

from desktop_tools.crew import conf

# The hook runs on every Claude event: json, the registry and the state files are imported only
# once a session is known to be under the actors folder, and typing never.
TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import IO, Any

BUSY = ("UserPromptSubmit", "PostToolUse", "PostToolUseFailure")
IDLE = ("Stop", "StopFailure", "SessionStart")
WAITING_TYPES = (
    "permission_prompt",
    "elicitation_dialog",
    "elicitation_url_dialog",
    "agent_needs_input",
)


def state_for(event: str, data: dict[str, Any]) -> str | None:
    """The state an event moves to: busy, waiting, idle, "" (removed), or None (no change)."""
    if event in BUSY:
        return "busy"
    if event == "PreToolUse":
        return "waiting" if data.get("tool_name") == "AskUserQuestion" else None
    if event == "Notification":
        return "waiting" if data.get("notification_type") in WAITING_TYPES else None
    if event in IDLE:
        return "idle"
    if event == "SessionEnd":
        return ""
    return None


def message_of(data: dict[str, Any]) -> str:
    text: Any = data.get("message")
    if not text:
        try:
            text = data["tool_input"]["questions"][0]["question"]
        except (KeyError, IndexError, TypeError):
            text = ""
    return " ".join(str(text).split())


def coordinator_of(cwd: str) -> str | None:
    """The coordinator a session's cwd belongs to, by its home's folder name."""
    prefix = str(conf.actors_dir()).rstrip("/") + "/"
    if not cwd.startswith(prefix):
        return None
    name = cwd[len(prefix) :].split("/", 1)[0]
    if not name:
        return None
    from desktop_tools.crew import registry

    reg = registry.load(refresh=False)
    resolved = reg.resolve(name)
    return resolved if resolved in reg.names else None


def run(args: list[str], stdin: IO[str] | None = None) -> int:
    stdin = sys.stdin if stdin is None else stdin
    try:
        if stdin.isatty():
            return 0
        raw = stdin.read()
    except (OSError, ValueError):
        return 0
    prefix = '"' + str(conf.actors_dir()).rstrip("/") + "/"
    if '"cwd"' not in raw or prefix not in raw:
        return 0
    import json

    from desktop_tools.crew import store

    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(data, dict) or not isinstance(data.get("cwd"), str):
        return 0
    name = coordinator_of(data["cwd"])
    if name is None:
        return 0
    event = args[0] if args else str(data.get("hook_event_name") or "")
    state = state_for(event, data)
    if state is None or state == store.activity(name):
        return 0
    if not store.set_activity(name, state):
        return 0
    from desktop_tools.crew import switch

    if state == "waiting":
        switch.detach(switch.crew_argv("notify", name, message_of(data) or "Waiting for input"))
    switch.detach(switch.crew_argv("bar", "--quiet"))
    return 0

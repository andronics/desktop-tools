"""Record 0004 §9: the one opt-in test against the real cupsd (RUN_INTEGRATION=1). It only reads,
CUPS-Get-Printers, CUPS-Get-Default and Get-Jobs: never a subscription, a job or a scan."""

from __future__ import annotations

import os
import socket

import pytest

from desktop_tools.devices import cups, ipp


@pytest.mark.integration
def test_the_real_cupsd_answers_the_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    # The unit tests' guard keeps every test off the real cupsd; this one is the exception, and
    # it sends only the three reads.
    monkeypatch.setattr(socket.socket, "connect", socket.socket.connect.__wrapped__)  # type: ignore[attr-defined]  # set by the guard below
    server = os.environ.get("REAL_CUPS_SERVER", "")
    if server:
        monkeypatch.setenv("CUPS_SERVER", server)
    else:
        monkeypatch.delenv("CUPS_SERVER", raising=False)
    sent: list[int] = []
    real_call = ipp.Client.call

    def call(self: ipp.Client, operation: int, *a: object, **kw: object) -> ipp.Response:
        sent.append(operation)
        return real_call(self, operation, *a, **kw)  # type: ignore[arg-type]  # passed through

    monkeypatch.setattr(ipp.Client, "call", call)
    found = cups.read()
    assert set(sent) <= {ipp.CUPS_GET_PRINTERS, ipp.CUPS_GET_DEFAULT, ipp.GET_JOBS}
    assert all(q.name for q in found.queues)
    shown = cups.view(found)
    assert shown.tier in ("unavailable", "idle", "active", "alert")

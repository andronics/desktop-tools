"""The printer queue's rows (record 0004 §3): one per unfinished job on the default queue, newest
first, up to SHOWN; a job is its number, state and age, never its name (open question 4).
Picking one of yours cancels it after a Yes/No (`devices printer cancel <id>`); other users'
jobs are listed without a cancel. With two or more of yours, `Cancel all my jobs (n)…`.
"""

from __future__ import annotations

from desktop_tools.barmenu.menus import Row
from desktop_tools.barmenu.providers.printer import read
from desktop_tools.devices import cups, ipp

SHOWN = 6
JOB = "\U000f0219"  # md-file_document
CANCEL = "\U000f0156"  # md-close
NONE = "\U000f0279"  # md-format_list_bulleted


def rows() -> list[Row]:
    r = read()
    if r is None:
        return [Row(NONE, "CUPS is not running", [])]
    if not r.jobs:
        return [Row(NONE, "No jobs", [])]
    me = ipp.username()
    newest = sorted(r.jobs, key=lambda j: (j.created, j.id), reverse=True)
    out = []
    for job in newest[:SHOWN]:
        age = cups.age(job.created)
        label = "  ".join(p for p in (f"#{job.id}", job.word, age) if p)
        mine = job.user in ("", me)
        out.append(Row(JOB, label, ["devices", "printer", "cancel", str(job.id)] if mine else []))
    if len(newest) > SHOWN:
        out.append(Row("", f"…and {len(newest) - SHOWN} more", []))
    mine_count = sum(1 for j in r.jobs if j.user in ("", me))
    if mine_count >= 2:
        out.append(
            Row(
                CANCEL,
                f"Cancel all my jobs ({mine_count})…",
                ["devices", "printer", "cancel", "--all"],
            )
        )
    return out

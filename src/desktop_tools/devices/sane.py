"""SANE: which scanners there are (`scanimage -L`) and what each offers (`scanimage -d <dev> -A`),
record 0004 §2 (scanner) and §5.

`scanimage -L` asks every backend and takes 8-10 s, so it runs at the source's start, from the
menu's `Find scanners` row and on a new DNS-SD scanner, never on a timer more than hourly. Its
result is kept in the runtime folder (`scanners.json`). `-A` opens the device and lists its
options without scanning; its sources and modes are cached per device (`options.json`) until
the scanner is found again. A scanner's description is kept without its `ip=` words: no address
reaches a label, a log or the bar's state.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from desktop_tools.common import procs
from desktop_tools.devices import store

FIND_TIMEOUT = 15.0
OPTIONS_TIMEOUT = 15.0
DEVICE = re.compile(r"^device `(.+)' is an? (.*)$")
OPTION = re.compile(r"^\s+--?(source|mode|resolution)\s+(.+?)(?:\s+\[(.*)\])?\s*$")


@dataclass(frozen=True)
class Scanner:
    device: str  # SANE's device name, e.g. airscan:e0:<name>
    model: str  # for people: the description without addresses

    @property
    def network(self) -> bool:
        return self.device.split(":", 1)[0] in ("airscan", "escl", "net")

    @property
    def instance(self) -> str:
        """The DNS-SD instance name sane-airscan found it by (its device name's last part)."""
        if self.device.startswith("airscan:"):
            parts = self.device.split(":", 2)
            return parts[2] if len(parts) == 3 else ""
        return ""


def model(description: str) -> str:
    words = [w for w in description.split() if not re.match(r"^(ip|addr|host)=", w)]
    if words and words[0] in ("eSCL", "WSD"):
        words = words[1:]
    return " ".join(words).strip()


def parse_list(text: str) -> list[Scanner]:
    out = []
    for line in text.splitlines():
        m = DEVICE.match(line.strip())
        if m:
            out.append(Scanner(m.group(1), model(m.group(2)) or m.group(1)))
    return out


def find(timeout: float = FIND_TIMEOUT) -> list[Scanner] | None:
    """`scanimage -L`: the scanners, kept for the session; None when SANE isn't there."""
    out = procs.query(["scanimage", "-L"], timeout=timeout)
    if out is None:
        return None
    found = parse_list(out)
    store.write(
        store.scanners_path(),
        {"at": time.time(), "scanners": [{"device": s.device, "model": s.model} for s in found]},
    )
    store.remove(store.options_path())  # found again: its sources are read again
    return found


def known() -> list[Scanner]:
    """The scanners found last, this session (none before a discovery)."""
    raw = store.read(store.scanners_path()).get("scanners")
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("device"), str):
            out.append(Scanner(item["device"], str(item.get("model") or item["device"])))
    return out


def found_at() -> float:
    try:
        return float(store.read(store.scanners_path()).get("at") or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Options:
    sources: tuple[str, ...]
    modes: tuple[str, ...]
    resolutions: tuple[int, ...]


def _choices(text: str) -> list[str]:
    text = re.sub(r"dpi$", "", text.strip())
    if ".." in text and "|" not in text:
        return [text]
    return [c.strip() for c in text.split("|") if c.strip()]


def parse_options(text: str) -> Options:
    found: dict[str, list[str]] = {"source": [], "mode": [], "resolution": []}
    for line in text.splitlines():
        m = OPTION.match(line)
        if m and not found[m.group(1)]:
            found[m.group(1)] = _choices(m.group(2))
    resolutions = []
    for r in found["resolution"]:
        if ".." in r:  # a range: the usual stops inside it
            low, _, high = r.partition("..")
            try:
                lo, hi = int(float(low)), int(float(high.split()[0]))
            except ValueError:
                continue
            resolutions += [d for d in (75, 100, 150, 200, 300, 600, 1200) if lo <= d <= hi]
        elif r.isdigit():
            resolutions.append(int(r))
    return Options(tuple(found["source"]), tuple(found["mode"]), tuple(resolutions))


def options(device: str, timeout: float = OPTIONS_TIMEOUT) -> Options | None:
    """The device's sources, modes and resolutions: cached, else `scanimage -d <dev> -A`."""
    cached = cached_options(device)
    if cached is not None:
        return cached
    out = procs.query(["scanimage", "-d", device, "-A"], timeout=timeout)
    if out is None:
        return None
    found = parse_options(out)
    cache = store.read(store.options_path())
    cache[device] = {
        "sources": list(found.sources),
        "modes": list(found.modes),
        "resolutions": list(found.resolutions),
    }
    store.write(store.options_path(), cache)
    return found


def cached_options(device: str) -> Options | None:
    """The cached options only (the menu never opens a device)."""
    entry = store.read(store.options_path()).get(device)
    if not isinstance(entry, dict):
        return None
    return Options(
        tuple(str(s) for s in entry.get("sources") or []),
        tuple(str(s) for s in entry.get("modes") or []),
        tuple(int(r) for r in entry.get("resolutions") or [] if isinstance(r, int)),
    )


def pick_source(sources: tuple[str, ...], kind: str) -> str | None:
    """The source name for `feeder`, `duplex` or `flatbed` (§5), or None if it lacks one."""
    for name in sources:
        low = name.lower()
        if (
            kind == "feeder"
            and re.search(r"adf|feeder", low)
            and not re.search(r"duplex|back", low)
        ):
            return name
        if kind == "duplex" and "duplex" in low:
            return name
        if kind == "flatbed" and re.search(r"flatbed|platen", low):
            return name
    return None


MODES = {
    "colour": ("Color", "Colour", "24bit Color", "Color24"),
    "grey": ("Gray", "Grey", "Grayscale", "True Gray", "8bit Gray"),
    "lineart": ("Lineart", "Black & White", "Binary", "Halftone"),
}


def pick_mode(modes: tuple[str, ...], kind: str) -> str:
    """SANE's name for colour, grey or lineart on this scanner (the standard name when the
    scanner's own list doesn't say)."""
    wanted = MODES[kind]
    for name in modes:
        if name in wanted or name.lower() in {w.lower() for w in wanted}:
            return name
    return wanted[0]

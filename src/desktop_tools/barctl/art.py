"""The art accent (record 0003 §5): the average colour of a track's cover, for the capsule's
progress line and icon when a module asks for `accent = "art"`.

A `file://` URL is read where it is; an `https://` one is fetched once with curl (2 s, 1 MiB,
HTTPS only, no config file, so no cookies) into `$XDG_RUNTIME_DIR/barctl/art/<sha256 of the
URL>`, at most CACHE_MAX files, the oldest removed first. `magick <file> -resize 1x1 txt:-`
gives the average colour. A colour under 3:1 contrast with the theme's `bg` (the non-text
contrast rule), or any failure, gives None, and the role colour shows. Nothing here logs the
URL or the track.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from desktop_tools.barctl import state as st
from desktop_tools.common import procs, theme

CACHE_MAX = 20
MAX_BYTES = 1048576
TIMEOUT = 2.0
CONTRAST_MIN = 3.0
COMMANDS = ("curl", "magick")
HEX = re.compile(r"#([0-9A-Fa-f]{6})")


def cache_dir() -> Path:
    return st.runtime() / "art"


def _prune(folder: Path, keep: int = CACHE_MAX) -> None:
    """Oldest first, down to `keep` files."""
    try:
        files = [f for f in folder.iterdir() if f.is_file() and not f.name.startswith(".")]
    except OSError:
        return
    files.sort(key=lambda f: f.stat().st_mtime)
    for old in files[: max(0, len(files) - keep)]:
        with contextlib.suppress(OSError):
            old.unlink()


def fetch(url: str) -> Path | None:
    """The art's file: a local one where it is, a remote one in the cache; None on failure."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        return path if path.is_file() else None
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    folder = cache_dir()
    dest = folder / hashlib.sha256(url.encode()).hexdigest()
    if dest.is_file():
        return dest
    with contextlib.suppress(OSError):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = folder / f".{dest.name}.{os.getpid()}.tmp"
    out = procs.query(
        [
            "curl",
            "-q",  # first: no .curlrc, so nothing but these options (no cookie jar)
            "--silent",
            "--fail",
            "--max-time",
            f"{TIMEOUT:g}",
            "--max-filesize",
            str(MAX_BYTES),
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--output",
            str(tmp),
            "--",
            url,
        ],
        timeout=TIMEOUT + 1,
    )
    if out is None or not tmp.is_file() or tmp.stat().st_size > MAX_BYTES:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return None
    os.replace(tmp, dest)
    _prune(folder)
    return dest


def average(path: Path) -> str | None:
    """The file's average colour as `#rrggbb`, from ImageMagick; None when it can't tell."""
    out = procs.query(["magick", str(path), "-resize", "1x1", "txt:-"], timeout=TIMEOUT)
    match = HEX.search(out or "")
    return f"#{match.group(1).lower()}" if match else None


def _luminance(hex_: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two `#rrggbb` colours, 1 to 21."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def background() -> str | None:
    found = theme.roles({"bg": "bg"}).get("bg")
    try:
        return st.accent(found) if found else None
    except st.StateError:
        return None


def colour(url: str) -> str | None:
    """The accent for this art, or None (the role colour shows)."""
    path = fetch(url)
    found = average(path) if path is not None else None
    if found is None:
        return None
    bg = background()
    if bg is not None and contrast(found, bg) < CONTRAST_MIN:
        return None
    return found

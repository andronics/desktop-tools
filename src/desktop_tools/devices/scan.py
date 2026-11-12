"""The scan runner (record 0004 §5): feeder, duplex or flatbed, pages joined into one PDF (or one
PNG or JPEG per page), saved in the chosen folder.

A scan runs `scanimage` into a 0700 folder under `$XDG_RUNTIME_DIR/desktop-tools/devices/`
(RAM, never the target folder, so a failed scan leaves no partial file there): `--batch` for a
feeder, `--output-file` for the flatbed, TIFF pages, with `LC_ALL=C` for that child only so its
SANE status line is SANE's English. A feeder scan ends with `Document feeder out of documents`,
which is success once a page was scanned. Then `tiffcp` joins the pages and `tiff2pdf` writes the
PDF (`-j -q 85` for colour and grey, lossless for black and white), or `magick` converts each
page. The result is copied into the folder under a hidden name and renamed into place as
`scan-YYYY-MM-DD-HHMMSS.<ext>` (`-2`, `-3` on a clash), and the temporary folder goes, in every
case.

One at a time: a lock file in the runtime folder. The progress (`scan.json` there: phase, pages,
result) is what barctl's scanner source reads, only while the lock is held, then once at the end.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from desktop_tools.devices import notify, prefs, sane, store

KINDS = ("feeder", "duplex", "flatbed")
SCANNING = re.compile(r"^Scanning page (\d+)")
SCANNED = re.compile(r"^Scanned page (\d+)")
NO_DOCS = "Document feeder out of documents"

# (what scanimage or the scanner says, the result word, alert afterwards)
FAILURES = (
    ("open of device", "unreachable", True),
    ("Document feeder jammed", "jam", True),
    ("Scanner cover is open", "cover", True),
    ("Device busy", "busy", True),
    ("Error during device I/O", "lost", True),
    ("Operation timed out", "lost", True),
    ("Invalid argument", "invalid", False),
)
WORDS = {
    "empty": "The feeder is empty: load the pages and scan again",
    "jam": "The feeder is jammed: clear it, then scan the rest",
    "cover": "The scanner's cover is open",
    "busy": "The scanner is busy (in use from its panel or another computer)",
    "lost": "Lost the scanner mid-scan",
    "invalid": "This scanner can't do {preset}: pick another preset",
    "unreachable": "The scanner can't be reached",
    "stopped": "Scan stopped",
    "failed": "The scan failed",
}


class ScanError(Exception):
    """A scan that couldn't start or didn't save anything: the words say why. `usage` marks a
    request the scanner can't take (a source it lacks): exit 2, not 1."""

    def __init__(self, words: str, result: str = "failed", *, usage: bool = False) -> None:
        super().__init__(words)
        self.result, self.usage = result, usage


class Busy(ScanError):
    def __init__(self) -> None:
        super().__init__("A scan is already running", "busy-here")


@dataclass
class Job:
    kind: str  # feeder, duplex, flatbed
    device: str
    source: str  # the scanner's own source name
    mode: str  # SANE's mode name
    preset: prefs.Preset
    fmt: str  # pdf, png, jpeg
    folder: Path


@dataclass
class Result:
    path: Path
    pages: int
    fmt: str
    folder: Path
    failure: str = ""  # the words of a failure after some pages were kept


# ---------------------------------------------------------------- the lock and progress


class Lock:
    """The one-scan-at-a-time lock: flock on scan.lock, released when the scan ends (or its
    process does)."""

    def __init__(self) -> None:
        self.fd: int | None = None

    def acquire(self) -> None:
        path = store.lock_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise Busy() from None
        self.fd = fd

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def running() -> bool:
    """Whether a scan holds the lock now (the source reads progress only then)."""
    path = store.lock_path()
    if not path.exists():
        return False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def report(**fields: object) -> None:
    store.write(store.progress_path(), {**fields, "at": time.time()})


# ---------------------------------------------------------------- planning


def plan(
    kind: str,
    *,
    preset_name: str | None = None,
    fmt: str | None = None,
    folder: Path | None = None,
    device: str | None = None,
) -> Job:
    """The scan to run, with the scanner's own source and mode names. Raises ScanError."""
    if kind not in KINDS:
        raise ScanError(f"Not a scan source: {kind} (feeder, duplex or flatbed)", usage=True)
    chosen = prefs.preset(preset_name) if preset_name else prefs.chosen_preset()
    if chosen is None:
        names = ", ".join(p.name for p in prefs.PRESETS)
        raise ScanError(f"No preset {preset_name!r} (one of {names})", usage=True)
    if fmt is not None and fmt not in prefs.FORMATS:
        raise ScanError(f"Not a format: {fmt} (pdf, png or jpeg)", usage=True)
    if fmt is None:
        fmt = chosen.format if preset_name else prefs.chosen_format()
    device = device or scanner()
    if not device:
        raise ScanError(WORDS["unreachable"], "unreachable")
    options = sane.options(device)
    if options is None:
        raise ScanError(WORDS["unreachable"], "unreachable")
    source = sane.pick_source(options.sources, kind) if options.sources else None
    if source is None and options.sources:
        lacks = {"feeder": "document feeder", "duplex": "duplex feeder", "flatbed": "flatbed"}
        raise ScanError(f"This scanner has no {lacks[kind]}", "invalid", usage=True)
    return Job(
        kind,
        device,
        source or "",
        sane.pick_mode(options.modes, chosen.mode),
        chosen,
        fmt,
        folder or prefs.chosen_folder(),
    )


def scanner() -> str:
    """The scanner to use: the setting or the menu's pick, else the first found."""
    chosen = prefs.chosen_scanner()
    if chosen:
        return chosen
    found = sane.known() or sane.find() or []
    return found[0].device if found else ""


def argv(job: Job, tmp: Path) -> list[str]:
    out = ["scanimage", "-d", job.device]
    if job.source:
        out += ["--source", job.source]
    out += ["--resolution", str(job.preset.resolution), "--mode", job.mode, "--format=tiff"]
    if job.kind == "flatbed":
        return [*out, "--output-file", str(tmp / "p001.tif")]
    return [*out, f"--batch={tmp}/p%03d.tif"]


def failure(said: list[str]) -> tuple[str, bool] | None:
    """(result word, alert) from scanimage's last lines; None when nothing failed."""
    for line in reversed(said):
        for text, word, alert in FAILURES:
            if text in line:
                return word, alert
    return None


def words(result: str, preset: str = "", pages: int = 0) -> str:
    text = WORDS.get(result, WORDS["failed"]).format(preset=preset)
    if pages and result in ("jam", "lost"):
        text += f"; {pages} page{'s' if pages != 1 else ''} saved"
    return text


# ---------------------------------------------------------------- assembling


def _tool(argv: list[str]) -> None:
    try:
        # S603: a fixed argument list (the pages' own paths in our temporary folder).
        done = subprocess.run(  # noqa: S603
            argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=300, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ScanError(f"Couldn't make the file: {argv[0]} {type(e).__name__}") from None
    if done.returncode != 0:
        raise ScanError(f"Couldn't make the file: {argv[0]} exited {done.returncode}")


def assemble(pages: list[Path], job: Job, tmp: Path) -> Path:
    """The pages as one PDF, or one PNG/JPEG per page (a folder for more than one)."""
    if job.fmt == "pdf":
        joined = tmp / "all.tif"
        _tool(["tiffcp", *(str(p) for p in pages), str(joined)])
        out = tmp / "scan.pdf"
        quality = [] if job.preset.mode == "lineart" else ["-j", "-q", "85"]
        _tool(["tiff2pdf", *quality, "-o", str(out), str(joined)])
        return out
    ext = "jpg" if job.fmt == "jpeg" else "png"
    converted = []
    for page in pages:
        target = page.with_suffix(f".{ext}")
        _tool(["magick", str(page), str(target)])
        converted.append(target)
    if len(converted) == 1:
        return converted[0]
    folder = tmp / "pages"
    folder.mkdir()
    for page in converted:
        page.rename(folder / page.name)
    return folder


def free_name(folder: Path, stem: str, ext: str) -> Path:
    """`stem.ext`, else `stem-2.ext`, `stem-3.ext`, …: never overwriting."""
    suffix = f".{ext}" if ext else ""
    candidate = folder / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def place(made: Path, job: Job, now: float | None = None) -> Path:
    """Copy the result into the folder under a hidden name, then rename it into place."""
    job.folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(now))
    ext = "" if made.is_dir() else made.suffix.lstrip(".")
    final = free_name(job.folder, f"scan-{stamp}", ext)
    partial = job.folder / f".{final.name}.partial"
    if made.is_dir():
        shutil.copytree(made, partial)
    else:
        shutil.copyfile(made, partial)
    os.replace(partial, final)
    return final


# ---------------------------------------------------------------- running


class Stopper:
    """The progress notification's Stop: SIGTERM to scanimage."""

    def __init__(self, proc: subprocess.Popen[str] | None) -> None:
        self.proc = proc
        self.notification = ""
        self.scan: subprocess.Popen[str] | None = None
        self.stopped = False
        self.thread: threading.Thread | None = None
        if proc is not None and proc.stdout is not None:
            self.thread = threading.Thread(target=self._read, name="scan-stop", daemon=True)
            self.thread.start()

    def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None  # noqa: S101 - see init
        for line in self.proc.stdout:
            word = line.strip()
            if word.isdigit() and not self.notification:
                self.notification = word
            elif word == "stop":
                self.stopped = True
                if self.scan is not None and self.scan.poll() is None:
                    self.scan.send_signal(signal.SIGTERM)

    def close(self) -> None:
        notify.close(self.notification)
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(2)
        if self.thread is not None:
            self.thread.join(1)
        if self.proc is not None and self.proc.stdout is not None:
            with contextlib.suppress(OSError):
                self.proc.stdout.close()


def run(
    job: Job,
    *,
    progress: Callable[[str, str], subprocess.Popen[str] | None] | None = None,
    now: Callable[[], float] = time.time,
) -> Result:
    """Run one scan. Raises Busy when one is running, ScanError when nothing was saved."""
    lock = Lock()
    lock.acquire()
    tmp: Path | None = None
    stopper = Stopper(None)
    pages = 0
    try:
        report(phase="scanning", pages=0, page=1, result="")
        base = store.runtime()
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = Path(tempfile.mkdtemp(prefix="scan-", dir=base))  # 0700
        start = progress or (lambda title, body: notify.progress("scanner", title, body))
        stopper = Stopper(start("Scanning", f"{job.preset.name}, from the {job.kind}"))
        env = {**os.environ, "LC_ALL": "C"}
        # S603: argv is a fixed list built here; the device name is SANE's, never a shell string.
        scan = subprocess.Popen(  # noqa: S603
            argv(job, tmp),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=env,
        )
        stopper.scan = scan
        said: list[str] = []
        counted = False  # scanimage said "Scanned page N" at least once
        assert scan.stderr is not None  # noqa: S101 - stderr=PIPE above
        for raw in scan.stderr:
            line = raw.strip()
            said = [*said[-20:], line]
            if m := SCANNING.match(line):
                report(phase="scanning", pages=pages, page=int(m.group(1)), result="")
            elif m := SCANNED.match(line):
                pages, counted = int(m.group(1)), True
                report(phase="scanning", pages=pages, page=pages, result="")
        scan.stderr.close()
        code = scan.wait()
        found = sorted(tmp.glob("p*.tif"))
        done_feeder = any(NO_DOCS in s for s in said)
        if job.kind == "flatbed":
            pages = 1 if code == 0 and found else 0
        elif not counted and (code == 0 or done_feeder):
            pages = len(found)  # a scanimage that doesn't say each page: every file is one
        pages = min(pages, len(found))
        if stopper.stopped:
            raise ScanError(WORDS["stopped"], "stopped")
        failed = failure(said)
        if code != 0 and done_feeder and pages:
            failed = None  # the feeder ran out after the last page: the scan is done
        elif code != 0 and done_feeder:
            failed = ("empty", True)
        elif code != 0 and failed is None:
            failed = ("failed", True)
        kept = found[:pages]
        if failed is not None and not (kept and failed[0] in ("jam", "lost")):
            raise ScanError(words(failed[0], job.preset.name), failed[0])
        report(phase="assembling", pages=pages, page=pages, result="")
        made = assemble(kept, job, tmp)
        final = place(made, job, now())
        store.write(store.last_path(), {"path": str(final)})
        result = Result(final, pages, job.fmt, job.folder)
        if failed is not None:
            result.failure = words(failed[0], job.preset.name, pages)
            report(phase="failed", pages=pages, result=failed[0], alert=True)
        else:
            report(phase="done", pages=pages, result="saved", alert=False)
        return result
    except ScanError as e:
        alert = e.result not in ("stopped", "invalid", "busy-here")
        report(phase="failed", pages=pages, result=e.result, alert=alert)
        raise
    except OSError as e:
        report(phase="failed", pages=pages, result="failed", alert=True)
        raise ScanError(f"{WORDS['failed']}: {e.strerror or type(e).__name__}") from None
    finally:
        stopper.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
        lock.release()


def last() -> Path | None:
    """The last scan saved this session, if it is still there."""
    raw = store.read(store.last_path()).get("path")
    path = Path(raw) if isinstance(raw, str) and raw.startswith("/") else None
    return path if path is not None and path.exists() else None


def describe(result: Result) -> str:
    """`3 pages, PDF, in Documents/Scans`."""
    n = result.pages
    kind = result.fmt.upper()
    return f"{n} page{'s' if n != 1 else ''}, {kind}, in {prefs.shown(result.folder)}"


def scanner_name_only() -> str:
    """The scanner to use, without running a discovery (status reads)."""
    chosen = prefs.chosen_scanner()
    if chosen:
        return chosen
    known = sane.known()
    return known[0].device if known else ""


def feeder_loaded(device: str) -> bool:
    """Whether the scanner says its feeder is loaded: its eSCL status when airscan.conf names
    it, else what barctl's scanner source last showed. Unknown (a non-eSCL scanner) is no."""
    from desktop_tools.devices import escl

    instance = sane.Scanner(device, "").instance
    base = escl.base_from_conf(instance) if instance else ""
    if base:
        status = escl.status(base)
        if status is not None:
            return status.feeder == "loaded"
    from desktop_tools.barctl import state as st

    for module in st.stored():
        data = st.read(module) or {}
        if data.get("source") == "scanner" and data.get("label") == "feeder loaded":
            return True
    return False


def auto_kind() -> str:
    """The left-click's source (§6): the feeder when it is loaded, else the flatbed."""
    device = scanner_name_only()
    if not device:
        return "flatbed"
    options = sane.cached_options(device)
    has_feeder = options is None or sane.pick_source(options.sources, "feeder") is not None
    return "feeder" if has_feeder and feeder_loaded(device) else "flatbed"

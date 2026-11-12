"""The scan runner (record 0004 §5) with a fake scanimage that writes N pages then ends with a
chosen SANE status: 0, 1 and 5 pages; a jam after 2 (2 kept); busy, cover open, invalid
argument; the PDF and per-page argv; name clashes; the lock; stop; and the temporary folder gone
afterwards in every case."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from desktop_tools.devices import prefs, scan, store
from tests.devices_fakes import FAKE_MAGICK, FAKE_TIFF2PDF, FAKE_TIFFCP, fake_scanimage
from tests.fakes import calls

DEVICE = "airscan:e0:Office Scanner"


@pytest.fixture
def scanner(isolate: Path, commands: Callable[..., Path]) -> Callable[..., Path]:
    prefs.remember(device=DEVICE)

    def make(pages: int, status: str = "", code: int | None = None) -> Path:
        return commands(
            scanimage=fake_scanimage(pages, status, code),
            tiffcp=FAKE_TIFFCP,
            tiff2pdf=FAKE_TIFF2PDF,
            magick=FAKE_MAGICK,
        )

    return make


def no_notice(title: str, body: str) -> subprocess.Popen[str] | None:
    return None


def go(kind: str, folder: Path, **kw: str) -> scan.Result:
    job = scan.plan(kind, folder=folder, **kw)
    return scan.run(job, progress=no_notice, now=lambda: 1_800_000_000.0)


def leftovers() -> list[str]:
    return sorted(p.name for p in store.runtime().glob("scan-*"))


def test_five_pages_from_the_feeder_to_one_pdf(
    scanner: Callable[..., Path], tmp_path: Path
) -> None:
    log = scanner(5, "Document feeder out of documents")
    out = tmp_path / "Scans"
    result = go("feeder", out)
    assert result.pages == 5 and result.path.parent == out and result.path.suffix == ".pdf"
    assert result.path.name.startswith("scan-") and not result.failure
    assert result.path.read_bytes() == b"%PDF " + b"".join(
        f"page{n};".encode() for n in range(1, 6)
    )
    ran = [c for c in calls(log) if c[0] == "scanimage" and "-A" not in c]
    (argv,) = ran
    assert argv[1:9] == ["-d", DEVICE, "--source", "ADF", "--resolution", "300", "--mode", "Gray"]
    assert argv[9] == "--format=tiff" and argv[10].endswith("/p%03d.tif")
    tiff2pdf = next(c for c in calls(log) if c[0] == "tiff2pdf")
    assert tiff2pdf[1:4] == ["-j", "-q", "85"]
    assert leftovers() == [] and not scan.running()
    assert json.loads(store.progress_path().read_text())["result"] == "saved"
    assert scan.last() == result.path
    env = json.loads((tmp_path / "scan.env").read_text())
    assert env["LC_ALL"] == "C"


def test_one_page_from_the_flatbed(scanner: Callable[..., Path], tmp_path: Path) -> None:
    log = scanner(1)
    result = go("flatbed", tmp_path / "out")
    assert result.pages == 1
    argv = next(c for c in calls(log) if c[0] == "scanimage" and "-A" not in c)
    assert "--source" in argv and argv[argv.index("--source") + 1] == "Flatbed"
    assert "--output-file" in argv
    assert scan.describe(result).startswith("1 page, PDF, in ")


def test_no_pages_is_an_empty_feeder(scanner: Callable[..., Path], tmp_path: Path) -> None:
    scanner(0, "Document feeder out of documents")
    with pytest.raises(scan.ScanError) as e:
        go("feeder", tmp_path / "out")
    assert e.value.result == "empty" and "load the pages" in str(e.value)
    assert not (tmp_path / "out").exists()  # nothing in the target folder
    assert leftovers() == []
    progress = json.loads(store.progress_path().read_text())
    assert progress["alert"] is True and progress["result"] == "empty"


def test_a_jam_after_two_keeps_two(scanner: Callable[..., Path], tmp_path: Path) -> None:
    scanner(2, "Document feeder jammed")
    result = go("feeder", tmp_path / "out")
    assert result.pages == 2 and "jammed" in result.failure and "2 pages saved" in result.failure
    assert leftovers() == []


@pytest.mark.parametrize(
    ("status", "result", "words"),
    [
        ("Device busy", "busy", "busy"),
        ("Scanner cover is open", "cover", "cover is open"),
        ("Invalid argument", "invalid", "can't do Document"),
        ("Error during device I/O", "lost", "Lost the scanner"),
        ("Something else", "failed", "The scan failed"),
    ],
)
def test_failures_in_words(
    scanner: Callable[..., Path], tmp_path: Path, status: str, result: str, words: str
) -> None:
    scanner(0, status)
    with pytest.raises(scan.ScanError) as e:
        go("feeder", tmp_path / "out")
    assert e.value.result == result and words in str(e.value)
    assert leftovers() == []


def test_png_per_page_in_a_folder(scanner: Callable[..., Path], tmp_path: Path) -> None:
    scanner(2, "Document feeder out of documents")
    result = go("feeder", tmp_path / "out", fmt="png")
    assert result.path.is_dir()
    assert sorted(p.name for p in result.path.iterdir()) == ["p001.png", "p002.png"]
    scanner(1)
    one = go("flatbed", tmp_path / "out", preset_name="Photo")
    assert one.path.suffix == ".png" and one.path.is_file()  # one page: one file, no folder


def test_lineart_is_lossless(scanner: Callable[..., Path], tmp_path: Path) -> None:
    log = scanner(1)
    go("flatbed", tmp_path / "out", preset_name="Text, smallest")
    tiff2pdf = next(c for c in calls(log) if c[0] == "tiff2pdf")
    assert "-j" not in tiff2pdf
    argv = next(c for c in calls(log) if c[0] == "scanimage" and "-A" not in c)
    assert argv[argv.index("--mode") + 1] == "Lineart"


def test_names_never_clash(tmp_path: Path) -> None:
    (tmp_path / "scan-x.pdf").write_text("")
    (tmp_path / "scan-x-2.pdf").write_text("")
    assert scan.free_name(tmp_path, "scan-x", "pdf").name == "scan-x-3.pdf"
    assert scan.free_name(tmp_path, "scan-y", "").name == "scan-y"


def test_two_scans_in_one_second(scanner: Callable[..., Path], tmp_path: Path) -> None:
    scanner(1)
    first = go("flatbed", tmp_path / "out")
    second = go("flatbed", tmp_path / "out")
    assert first.path != second.path and second.path.name.endswith("-2.pdf")


def test_one_scan_at_a_time(scanner: Callable[..., Path], tmp_path: Path) -> None:
    scanner(1)
    lock = scan.Lock()
    lock.acquire()
    try:
        with pytest.raises(scan.Busy, match="already running"):
            go("flatbed", tmp_path / "out")
    finally:
        lock.release()
    assert not scan.running()


def test_a_missing_source_is_a_usage_error(
    scanner: Callable[..., Path], tmp_path: Path, commands: Callable[..., Path]
) -> None:
    scanner(1)
    store.write(store.options_path(), {DEVICE: {"sources": ["Flatbed"], "modes": ["Color"]}})
    with pytest.raises(scan.ScanError, match="no duplex feeder") as e:
        go("duplex", tmp_path / "out")
    assert e.value.usage
    with pytest.raises(scan.ScanError, match="no document feeder"):
        go("feeder", tmp_path / "out")
    with pytest.raises(scan.ScanError, match="Not a scan source"):
        scan.plan("sideways")
    with pytest.raises(scan.ScanError, match="No preset"):
        scan.plan("flatbed", preset_name="Nope")
    with pytest.raises(scan.ScanError, match="Not a format"):
        scan.plan("flatbed", fmt="tiff")


def test_stop_from_the_notification(
    scanner: Callable[..., Path], tmp_path: Path, commands: Callable[..., Path]
) -> None:
    """The progress notification prints its id, then `stop`: scanimage gets SIGTERM and the
    temporary folder goes; nothing is saved."""
    import sys

    log = scanner(0)
    commands(dunstify="pass")
    # A scanimage that waits to be stopped.
    slow = tmp_path / "bin" / "scanimage"
    body = slow.read_text().replace("for n in range(1, 0 + 1):", "time.sleep(20)\nfor n in []:")
    slow.write_text(body)

    def notice(title: str, body: str) -> subprocess.Popen[str]:
        code = "import sys, time; print(7, flush=True); time.sleep(0.5); print('stop', flush=True)"
        # S603: the test's own fixed command line.
        return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)  # noqa: S603

    job = scan.plan("flatbed", folder=tmp_path / "out")
    with pytest.raises(scan.ScanError) as e:
        scan.run(job, progress=notice)
    assert e.value.result == "stopped"
    assert leftovers() == [] and not (tmp_path / "out").exists()
    assert ["dunstify", "-C", "7"] in calls(log)  # the progress notification closed


def test_the_scanner_from_discovery(commands: Callable[..., Path], isolate: Path) -> None:
    commands(scanimage=fake_scanimage(0))
    assert scan.scanner() == DEVICE
    assert scan.scanner_name_only() == DEVICE
    assert scan.auto_kind() == "flatbed"  # nothing says the feeder is loaded


def test_auto_scans_the_feeder_when_loaded(isolate: Path) -> None:
    from desktop_tools.barctl import state as st

    prefs.remember(device=DEVICE)
    store.write(store.options_path(), {DEVICE: {"sources": ["Flatbed", "ADF"], "modes": []}})
    st.write("scanner", {"tier": "idle", "label": "feeder loaded", "source": "scanner"})
    assert scan.auto_kind() == "feeder"
    store.write(store.options_path(), {DEVICE: {"sources": ["Flatbed"], "modes": []}})
    assert scan.auto_kind() == "flatbed"


def test_last_needs_the_file(tmp_path: Path) -> None:
    assert scan.last() is None
    store.write(store.last_path(), {"path": str(tmp_path / "gone.pdf")})
    assert scan.last() is None
    os.close(os.open(tmp_path / "here.pdf", os.O_CREAT))
    store.write(store.last_path(), {"path": str(tmp_path / "here.pdf")})
    assert scan.last() == tmp_path / "here.pdf"

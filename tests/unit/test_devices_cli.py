"""The `devices` command (record 0004 §4, §7): every verb's argv, the confirm asked for cancel and
the test page and not for the others, --yes, exit 3 for an agent on every acting verb and not
on status, no variable set or cleared in a child's environment, the words for CUPS's refusals,
and no title, host or path in the journal or in `status --json`."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from desktop_tools.common import confirm
from desktop_tools.devices import cli, cups, prefs, scan, store
from tests.devices_fakes import (
    FAKE_TIFF2PDF,
    FAKE_TIFFCP,
    FakeCups,
    fake_scanimage,
    job_attrs,
    printer_attrs,
)
from tests.fakes import FakeJournal, calls

runner = CliRunner()
DEVICE = "airscan:e0:Office Scanner"
# Each fake CUPS tool logs its argv and environment.
ENV_LOG = (
    "open(here + '/env-' + os.path.basename(sys.argv[0]), 'w').write(json.dumps(dict(os.environ)))"
)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confirm, "SETTLE", 0.0)
    monkeypatch.setattr(confirm, "UNSHOWN", 0.0)


@pytest.fixture
def tools(commands: Callable[..., Path], cupsd: FakeCups) -> Path:
    return commands(
        cupsdisable=ENV_LOG,
        cupsenable=ENV_LOG,
        lpoptions=ENV_LOG,
        cancel=ENV_LOG,
        lp=ENV_LOG,
        dunstify="pass",
        rofi="print('Yes')",
        xclip="sys.stdin.read()",
    )


def run(*args: str) -> tuple[int, str]:
    r = runner.invoke(cli.app, list(args))
    return r.exit_code, r.output


def ran(log: Path, name: str) -> list[list[str]]:
    return [c for c in calls(log) if c[0] == name]


@pytest.mark.parametrize(
    ("args", "argv", "said"),
    [
        (["printer", "pause"], ["cupsdisable", "Office"], "Printing paused"),
        (["printer", "resume"], ["cupsenable", "Office"], "Printing resumed"),
        (["printer", "pause", "Other"], ["cupsdisable", "Other"], "Printing paused"),
        (["printer", "default", "Other"], ["lpoptions", "-d", "Other"], "Default printer: Other"),
    ],
)
def test_one_click_verbs(tools: Path, args: list[str], argv: list[str], said: str) -> None:
    code, out = run(*args)
    assert code == 0 and said in out
    assert ran(tools, argv[0]) == [argv]
    assert ran(tools, "rofi") == []  # no confirm
    assert ["dunstify", "-a", "printer", said] in calls(tools)


def test_cancel_asks_first(tools: Path, commands: Callable[..., Path]) -> None:
    code, out = run("printer", "cancel", "123")
    assert code == 0 and "Job 123 cancelled" in out
    (rofi,) = ran(tools, "rofi")
    assert rofi[-2:] == ["-mesg", "Cancel job 123?"] and "-selected-row" in rofi
    assert ran(tools, "cancel") == [["cancel", "123"]]
    commands(rofi="print('No')")
    code, out = run("printer", "cancel", "124")
    assert code == 0 and "not done" in out
    assert ran(tools, "cancel") == [["cancel", "123"]]
    code, _ = run("printer", "cancel", "125", "--yes")
    assert code == 0 and ran(tools, "cancel")[-1] == ["cancel", "125"]
    assert len(ran(tools, "rofi")) == 2


def test_cancel_all_mine(tools: Path, cupsd: FakeCups) -> None:
    import getpass

    me = getpass.getuser()
    cupsd.jobs["Office"] = [job_attrs(1, user=me), job_attrs(2, user=me), job_attrs(3, user="x")]
    code, out = run("printer", "cancel", "--all")
    assert code == 0, out
    assert ran(tools, "rofi")[0][-1] == "Cancel 2 jobs?"
    assert ran(tools, "cancel") == [["cancel", "-u", me, "Office"]]
    assert run("printer", "cancel")[0] == 2
    assert run("printer", "cancel", "1", "--all")[0] == 2


def test_cancel_all_with_none(tools: Path) -> None:
    code, out = run("printer", "cancel", "--all")
    assert code == 0 and "No jobs of yours" in out and ran(tools, "cancel") == []


def test_test_page_asks_first(tools: Path) -> None:
    code, out = run("printer", "test-page")
    assert code == 0 and "Test page sent" in out
    assert ran(tools, "rofi")[0][-1] == "Print a test page on Office?"
    assert ran(tools, "lp") == [["lp", "-d", "Office", str(cli.TEST_PAGE)]]


def test_unasked_does_nothing(tools: Path, commands: Callable[..., Path]) -> None:
    commands(rofi="sys.stderr.write('Failed to grab keyboard\\n'); sys.exit(1)")  # unshown, twice
    code, _ = run("printer", "test-page")
    assert code == 1 and ran(tools, "lp") == []


@pytest.mark.parametrize("variable", ["COORDINATOR", "CLAUDECODE", "TESSERA_ACTOR"])
@pytest.mark.parametrize(
    "args",
    [
        ["printer", "pause"],
        ["printer", "resume"],
        ["printer", "default", "Office"],
        ["printer", "cancel", "1", "--yes"],
        ["printer", "test-page", "--yes"],
        ["scan", "feeder"],
        ["scan", "duplex"],
        ["scan", "flatbed"],
        ["scan"],
    ],
)
def test_an_agent_is_refused(
    tools: Path, monkeypatch: pytest.MonkeyPatch, variable: str, args: list[str]
) -> None:
    monkeypatch.setenv(variable, "1")
    code, out = run(*args)
    assert code == 3 and "An agent may not operate the printer or scanner" in out
    for name in ("cupsdisable", "cupsenable", "lpoptions", "cancel", "lp", "rofi"):
        assert ran(tools, name) == []


def test_status_is_anyones(tools: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out = run("printer", "status", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["tier"] in ("idle", "unavailable") and data["queue"] == "Office"
    assert data["supplies"][0] == {"name": "magenta", "level": 44}
    assert run("scanner", "status")[0] == 0


def test_children_get_the_environment_untouched(
    tools: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: devices never sets or clears COORDINATOR, CLAUDECODE or TESSERA_ACTOR. With them
    unset the verbs run; the child's environment is the caller's, less nothing, plus nothing."""
    import os

    monkeypatch.setenv("SOMETHING_ELSE", "kept")
    assert run("printer", "pause")[0] == 0
    env = json.loads((tools.parent / "env-cupsdisable").read_text())
    for name in ("COORDINATOR", "CLAUDECODE", "TESSERA_ACTOR"):
        assert name not in env
    assert env["SOMETHING_ELSE"] == "kept"
    assert set(os.environ) - set(env) <= {"COLUMNS", "LINES"}


def test_cups_refusals_in_words(tools: Path, commands: Callable[..., Path]) -> None:
    commands(cupsdisable="sys.stderr.write('cupsdisable: Forbidden\\n'); sys.exit(1)")
    code, out = run("printer", "pause")
    assert code == 1 and cli.NOT_ALLOWED in out
    commands(
        cupsdisable="sys.stderr.write('cupsdisable: Unable to connect to server\\n'); sys.exit(1)"
    )
    assert cli.NOT_RUNNING in run("printer", "pause")[1]
    assert cli.cups_words("") == "CUPS refused"
    assert cli.run(["no-such-tool-here"])[0] == 127


def test_without_cupsd(commands: Callable[..., Path]) -> None:
    commands(dunstify="pass")
    code, out = run("printer", "pause")
    assert code == 1 and "CUPS is not running" in out
    code, out = run("printer", "status")
    assert code == 1 and "CUPS is not running" in out


def test_no_default(tools: Path, cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("A"), printer_attrs("B")]
    cupsd.default = ""
    assert run("printer", "pause")[0] == 1


def test_status_notify_and_lines(tools: Path, cupsd: FakeCups) -> None:
    cupsd.printers = [printer_attrs("Office", uri="usb://Brand/Model", state=cups.STOPPED)]
    code, out = run("printer", "status", "--notify")
    assert code == 0 and "Paused: yes" in out and "Kind: local" in out
    notes = [c for c in calls(tools) if c[:3] == ["dunstify", "-a", "printer"]]
    assert notes and notes[-1][3] == "Printer" and "Paused: yes" in notes[-1][4]


# ---------------------------------------------------------------- scanning


@pytest.fixture
def scanning(commands: Callable[..., Path], launched: list[list[str]]) -> Path:
    prefs.remember(device=DEVICE)
    return commands(
        scanimage=fake_scanimage(3, "Document feeder out of documents"),
        tiffcp=FAKE_TIFFCP,
        tiff2pdf=FAKE_TIFF2PDF,
        dunstify="print('open') if '-A' in args and 'open,Open' in args else None",
        xclip="open(here + '/clip', 'w').write(sys.stdin.read())",
    )


def test_a_scan_saves_copies_and_offers_open(
    scanning: Path, launched: list[list[str]], tmp_path: Path
) -> None:
    code, out = run("scan", "feeder", "--to", str(tmp_path / "Scans"))
    assert code == 0 and "Scan saved: 3 pages, PDF" in out and "Path copied" in out
    saved = Path((tmp_path / "clip").read_text())
    assert saved.parent == tmp_path / "Scans" and saved.suffix == ".pdf"
    note = next(c for c in calls(scanning) if c[0] == "dunstify" and "open,Open" in c)
    assert note[1:3] == ["-a", "scanner"] and "folder,Show folder" in note
    assert launched == [["xdg-open", str(saved)]]
    assert run("scan", "copy-last")[0] == 0
    assert run("scan", "open-last")[0] == 0
    assert launched[-1] == ["xdg-open", str(saved)]


def test_a_failed_scan_says_why(
    scanning: Path, commands: Callable[..., Path], tmp_path: Path
) -> None:
    commands(scanimage=fake_scanimage(0, "Device busy"))
    code, out = run("scan", "flatbed", "--to", str(tmp_path / "Scans"))
    assert code == 1 and "busy" in out
    store.write(store.options_path(), {DEVICE: {"sources": ["Flatbed"], "modes": []}})
    code, out = run("scan", "duplex")
    assert code == 2 and "no duplex feeder" in out


def test_no_last_scan(commands: Callable[..., Path]) -> None:
    commands(dunstify="pass")
    assert run("scan", "copy-last")[0] == 1
    assert run("scan", "open-last")[0] == 1


def test_the_auto_scan_uses_the_flatbed_without_a_loaded_feeder(
    scanning: Path, tmp_path: Path, commands: Callable[..., Path]
) -> None:
    commands(scanimage=fake_scanimage(1))
    prefs.remember(folder=str(tmp_path / "auto"))
    code, out = run("scan")
    assert code == 0 and "1 page, PDF" in out
    argv = next(c for c in calls(scanning) if c[0] == "scanimage" and "-A" not in c)
    assert argv[argv.index("--source") + 1] == "Flatbed"


def test_set_remembers(commands: Callable[..., Path], tmp_path: Path) -> None:
    assert run("scan", "set", "--preset", "photo")[0] == 0
    assert prefs.chosen_preset().name == "Photo" and prefs.chosen_format() == "png"
    assert run("scan", "set", "--format", "jpeg")[0] == 0
    assert prefs.chosen_format() == "jpeg"
    assert run("scan", "set", "--preset", "Draft")[0] == 0
    assert prefs.chosen_format() == "pdf"  # a preset sets its format again
    assert run("scan", "set", "--to", str(tmp_path))[0] == 0
    assert prefs.chosen_folder() == tmp_path
    assert run("scan", "set", "--preset", "nope")[0] == 2
    assert run("scan", "set", "--format", "tiff")[0] == 2
    commands(zenity=f"print({str(tmp_path / 'picked')!r})")
    assert run("scan", "set", "--choose")[0] == 0
    assert prefs.chosen_folder() == tmp_path / "picked"
    commands(zenity="sys.exit(1)")
    assert run("scan", "set", "--choose")[0] == 0
    assert prefs.chosen_folder() == tmp_path / "picked"


def test_scanner_find_and_pick(commands: Callable[..., Path]) -> None:
    log = commands(scanimage=fake_scanimage(0), dunstify="pass")
    code, out = run("scanner", "find")
    assert code == 0 and "Found 1 scanner" in out and "192.0.2" not in out
    assert run("scanner", "pick", "airscan:e1:Other")[0] == 0
    assert scan.scanner_name_only() == "airscan:e1:Other"
    code, out = run("scanner", "status", "--json")
    assert code == 0 and json.loads(out)["configured"] is True
    commands(scanimage="print('nothing')")
    assert "No scanner found" in run("scanner", "find")[1]
    assert [c for c in calls(log) if c[0] == "scanimage"]


# ---------------------------------------------------------------- privacy (§7)


def test_no_title_host_or_path_in_the_journal(
    tools: Path,
    cupsd: FakeCups,
    journal_sock: FakeJournal,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A job title, owner, host and folder carrying a marker: none reaches the journal's fields
    or `printer status --json`."""
    marker = "MARK3R-a91c"
    cupsd.printers = [printer_attrs("Office", uri=f"ipp://{marker.lower()}.example/ipp")]
    cupsd.jobs["Office"] = [job_attrs(1, title=marker, user=marker)]
    monkeypatch.setattr("sys.argv", ["devices", "printer", "status", "--json"])
    code = cli.run_app(["printer", "status", "--json"])
    assert code in (0, 1)
    code = cli.run_app(["scan", "set", "--to", str(tmp_path / marker)])
    assert code == 0
    fields = json.dumps(journal_sock.received())
    assert marker not in fields and marker.lower() not in fields
    _, out = run("printer", "status", "--json")
    assert marker not in out and marker.lower() not in out

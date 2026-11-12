"""The output segment (record 0003 §10, tests §8): the sinks' kind glyphs and short names, the
volume source's properties, notices, coalescing and battery read, the `output` render, the
controller's notice tick, the `outputs` menu and the player menu's `Output` row.

No audio server, no Bluetooth: pactl, busctl and bluetoothctl are fakes. Each fails the test if
it is asked to change anything (a default sink, a volume, a mute; a connect, disconnect,
power, pair, remove or trust; a BlueZ method other than GetManagedObjects), so no source or
provider code can. A picked row's argv is checked, never run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from desktop_tools.barctl import doctor, outputs, render
from desktop_tools.barctl import modules as mods
from desktop_tools.barctl import state as st
from desktop_tools.barctl.controller import Controller
from desktop_tools.barctl.sources import VolumeSource
from desktop_tools.barctl.sources import volume as volume_source
from desktop_tools.barctl.store import Writer, shown
from desktop_tools.barmenu import menus as bm
from desktop_tools.barmenu import providers
from desktop_tools.barmenu.providers import outputs as outputs_menu
from desktop_tools.barmenu.providers import player as player_menu
from desktop_tools.common import procs
from tests.fakes import calls

CONFIG = """
[modules.output-capsule]
source = "volume"
display = "output"
glyph = "V"

[modules.output-capsule.clicks]
left = ["audio", "mute-toggle"]
scroll-up = ["audio", "volume-increase"]
scroll-down = ["audio", "volume-decrease"]
right = ["barmenu", "outputs"]

[modules.audio-level]
source = "volume"
display = "both"
"""
COLOURS = {
    "unavailable": "#111111",
    "idle": "#222222",
    "active": "#333333",
    "alert": "#444444",
    "underline": "#333333",
}

WIRED = "alsa_output.pci-0000_0d_00.4.analog-stereo"
HDMI = "alsa_output.pci-0000_0b_00.1.hdmi-stereo"
BT = "bluez_output.AA_BB_CC_DD_EE_FF.1"
BT_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
BT_ADDRESS = "AA:BB:CC:DD:EE:FF"
SPEAKER_ADDRESS = "11:22:33:44:55:66"


def sink(index: int, name: str, props: dict[str, str], **extra: Any) -> dict[str, Any]:
    return {"index": index, "name": name, "description": extra.pop("description", name), **extra,
            "properties": {"node.name": name, **props}}  # fmt: skip


SINKS = {
    WIRED: sink(
        57,
        WIRED,
        {"device.bus": "pci", "device.nick": "HD-Audio Generic", "device.profile.name": "analog"},
        active_port="analog-output-headphones",
        ports=[
            {"name": "analog-output-speaker", "type": "Speaker"},
            {"name": "analog-output-headphones", "type": "Headphones"},
        ],
    ),
    HDMI: sink(
        58,
        HDMI,
        {"device.bus": "pci", "device.nick": "HDA NVidia", "device.profile.name": "hdmi-stereo"},
        active_port="hdmi-output-0",
        ports=[{"name": "hdmi-output-0", "type": "HDMI"}],
    ),
    BT: sink(
        59,
        BT,
        {
            "device.bus": "bluetooth",
            "device.form_factor": "headphone",
            "device.description": "WH-1000XM4 Wireless Headphones",
            "api.bluez5.path": BT_PATH,
            "api.bluez5.address": BT_ADDRESS,
        },
    ),
}

# The fakes' first lines: anything that would change the audio or Bluetooth is logged, fails.
PACTL_GUARD = """
if args and (args[0].startswith('set-') or args[0] in ('load-module', 'unload-module',
        'move-sink-input', 'suspend-sink', 'send-message')):
    open(here + '/controlled', 'a').write('pactl ' + ' '.join(args) + '\\n'); sys.exit(1)
"""
BUSCTL_GUARD = """
read_only = ('get-property' in args) or ('GetManagedObjects' in args)
if not read_only or 'set-property' in args:
    open(here + '/controlled', 'a').write('busctl ' + ' '.join(args) + '\\n'); sys.exit(1)
"""
BLUETOOTHCTL = """
open(here + '/controlled', 'a').write('bluetoothctl ' + ' '.join(args) + '\\n'); sys.exit(1)
"""


class Pokes:
    def __init__(self) -> None:
        self.names: list[str] = []

    def __call__(self, name: str) -> None:
        self.names.append(name)

    def wait(self, count: int, timeout: float = 3.0) -> list[str]:
        end = time.monotonic() + timeout
        while len(self.names) < count and time.monotonic() < end:
            time.sleep(0.02)
        time.sleep(0.3)
        return list(self.names)


@pytest.fixture
def config(isolate: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, mods.Module]]:
    path = isolate / "modules.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("BARCTL_CONFIG", str(path))
    yield mods.load()
    assert not (isolate / "controlled").exists(), (isolate / "controlled").read_text()


@pytest.fixture
def names(isolate: Path) -> None:
    """The dotfiles' audio/devices.json: a name for the HDMI sink, a broken pattern skipped."""
    folder = isolate / "xdg" / "data" / "audio"
    folder.mkdir(parents=True)
    (folder / "devices.json").write_text(
        json.dumps(
            [
                {"pattern": "[broken", "name": "Never"},
                {"pattern": ".hdmi-stereo$", "name": "HDMI Speakers", "icon": "x"},
            ]
        )
    )


class Audio:
    """A fake pulse server and BlueZ: what each command answers is in files the test changes."""

    def __init__(self, base: Path, commands: Callable[..., Path]) -> None:
        self.dir = base / "audio"
        self.dir.mkdir()
        self.stream = base / "pa.fifo"
        os.mkfifo(self.stream)
        self.set(default=WIRED, volume=45, mute=False, sinks=[WIRED, HDMI], battery={})
        self.objects([])
        d = str(self.dir)
        self.log = commands(
            pactl=PACTL_GUARD
            + f"""
D = {d!r}
read = lambda n: open(D + '/' + n).read()
if args[0] == 'subscribe':
    os.execvp('cat', ['cat', {str(self.stream)!r}])
elif args == ['get-default-sink']:
    print(read('default'))
elif args[0] == 'get-sink-volume':
    v = read('volume')
    print(f'Volume: front-left: 29491 /  {{v}}% / -20.92 dB,   front-right: 29491 /  {{v}}%')
elif args[0] == 'get-sink-mute':
    print('Mute: ' + read('mute'))
elif args == ['-f', 'json', 'list', 'sinks']:
    print(read('sinks.json'))
else:
    open(here + '/unexpected', 'a').write(' '.join(args) + '\\n'); sys.exit(1)
""",
            busctl=BUSCTL_GUARD
            + f"""
D = {d!r}
if 'GetManagedObjects' in args:
    if os.path.exists(D + '/no-bluez'):
        sys.exit(1)
    print(open(D + '/objects.json').read())
else:
    battery = json.load(open(D + '/battery.json'))
    path = args[args.index('get-property') + 2]
    if path not in battery:
        sys.stderr.write('No such interface'); sys.exit(1)
    print(f'y {{battery[path]}}')
""",
            bluetoothctl=BLUETOOTHCTL,
        )

    def set(self, **values: Any) -> None:
        if "default" in values:
            (self.dir / "default").write_text(values["default"])
        if "volume" in values:
            (self.dir / "volume").write_text(str(values["volume"]))
        if "mute" in values:
            (self.dir / "mute").write_text("yes" if values["mute"] else "no")
        if "sinks" in values:
            (self.dir / "sinks.json").write_text(json.dumps([SINKS[n] for n in values["sinks"]]))
        if "battery" in values:
            (self.dir / "battery.json").write_text(json.dumps(values["battery"]))

    def objects(self, devices: list[tuple[str, str, str, bool, bool]]) -> None:
        """BlueZ's managed objects as busctl --json=short gives them: (address, alias, icon,
        paired, connected) per device, and an adapter that isn't one."""
        tree: dict[str, Any] = {"/org/bluez/hci0": {"org.bluez.Adapter1": {}}}
        for address, alias, icon, paired, connected in devices:
            path = "/org/bluez/hci0/dev_" + address.replace(":", "_")
            tree[path] = {
                "org.bluez.Device1": {
                    "Address": {"type": "s", "data": address},
                    "Alias": {"type": "s", "data": alias},
                    "Icon": {"type": "s", "data": icon},
                    "Paired": {"type": "b", "data": paired},
                    "Connected": {"type": "b", "data": connected},
                }
            }
        (self.dir / "objects.json").write_text(
            json.dumps({"type": "a{oa{sa{sv}}}", "data": [tree]})
        )

    def calls(self, *prefix: str) -> list[list[str]]:
        return [c for c in calls(self.log) if c[: len(prefix)] == list(prefix)]


@pytest.fixture
def audio(isolate: Path, commands: Callable[..., Path], config: dict[str, mods.Module]) -> Audio:
    return Audio(isolate, commands)


def make_source(config: dict[str, mods.Module]) -> tuple[VolumeSource, Pokes, list[float]]:
    pokes = Pokes()
    clock = [1000.0]
    found = VolumeSource(["output-capsule", "audio-level"], Writer(config, pokes))
    found.clock = lambda: clock[0]
    return found, pokes, clock


def visible(line: str) -> str:
    return re.sub(r"(?<!%)%\{[^}]*\}", "", line).replace("%%{", "%{").replace(render.BREAK, "")


def out_state() -> st.State:
    return st.read("output-capsule") or {}


# ---------------------------------------------------------------- kinds and names


def test_each_kind_glyph() -> None:
    assert outputs.kind({"device.bus": "bluetooth", "device.form_factor": "headset"}) == (
        outputs.BT_HEADPHONES
    )
    assert outputs.kind({"device.bus": "bluetooth", "device.form_factor": "speaker"}) == (
        outputs.BT_SPEAKER
    )
    assert outputs.kind({"device.form_factor": "headphone"}) == outputs.HEADPHONES
    assert outputs.kind({"device.form_factor": "headset", "device.bus": "usb"}) == outputs.HEADSET
    assert outputs.kind({}, {"name": "analog-output-headphones"}) == outputs.HEADPHONES
    assert outputs.kind({"node.name": "alsa_output.x.hdmi-stereo"}) == outputs.TELEVISION
    assert outputs.kind({"device.profile.name": "HDMI-surround"}) == outputs.TELEVISION
    assert outputs.kind({"device.bus": "usb"}) == outputs.USB
    assert outputs.kind({"device.bus": "pci"}) == outputs.SPEAKER


def test_the_sinks_kind_and_short_name(names: None) -> None:
    found = outputs.parse_sinks(json.dumps(list(SINKS.values())))
    assert [(s.index, s.glyph, s.short, s.bluetooth, s.path) for s in found] == [
        (57, outputs.HEADPHONES, "HD-Audio Generic", False, ""),
        (58, outputs.TELEVISION, "HDMI Speakers", False, ""),  # devices.json's name
        (59, outputs.BT_HEADPHONES, "WH-1000XM4 Wire…", True, BT_PATH),  # cut to 16
    ]


def test_a_sink_that_cant_be_used_is_skipped() -> None:
    bad = [
        sink(1, "-x", {}),  # would read as an option
        sink(2, "a b", {}),
        {"index": True, "name": "ok"},
        "not a sink",
        sink(3, "bluez_output.y", {"device.bus": "bluetooth", "api.bluez5.path": "/etc/x"}),
        sink(4, "plain", {"device.description": "Line\nTwo %{F#f00}"}),
    ]
    found = outputs.parse_sinks(json.dumps(bad), [])
    assert [(s.name, s.path, s.short) for s in found] == [
        ("bluez_output.y", "", "bluez_output.y"),  # not a BlueZ path: no battery read
        ("plain", "", "Line Two %{F#f0…"),  # one line; render escapes the rest
    ]


def test_battery_glyph_by_level() -> None:
    assert outputs.battery_glyph(None) == ""
    assert outputs.battery_glyph(0) == "\U000f007a"  # md-battery_10 is the lowest
    assert outputs.battery_glyph(14) == "\U000f007a"
    assert outputs.battery_glyph(50) == "\U000f007e"  # md-battery_50
    assert outputs.battery_glyph(90) == "\U000f0082"  # md-battery_90
    assert outputs.battery_glyph(95) == outputs.BATTERY_FULL
    assert outputs.volume_glyph(20, False) == outputs.VOL_LOW
    assert outputs.volume_glyph(50, False) == outputs.VOL_MEDIUM
    assert outputs.volume_glyph(80, False) == outputs.VOL_HIGH
    assert outputs.volume_glyph(80, True) == outputs.VOL_OFF


def test_battery_from_bluez_and_none_without_battery1(audio: Audio) -> None:
    audio.set(battery={BT_PATH: 80})
    assert outputs.battery(BT_PATH) == 80
    assert outputs.battery("/org/bluez/hci0/dev_00_00_00_00_00_00") is None  # no Battery1
    assert outputs.battery("--help") is None  # not a path: never asked
    assert audio.calls("busctl") == [
        ["busctl", "--system", "get-property", "org.bluez", p, "org.bluez.Battery1", "Percentage"]
        for p in (BT_PATH, "/org/bluez/hci0/dev_00_00_00_00_00_00")
    ]


# ---------------------------------------------------------------- state, modules.toml


def test_output_and_notice_validated() -> None:
    good = st.validate(
        {"output": {"volume": 45, "battery": None}, "notice": "a\nb", "notice_until": 5}
    )
    assert good == {
        "output": {"volume": 45, "battery": None},
        "notice": "a b",
        "notice_until": 5.0,
    }
    bads: list[dict[str, object]] = [
        {"output": []},
        {"output": {"volume": -1}},
        {"output": {"volume": True}},
        {"output": {"volume": 10, "battery": 101}},
        {"notice": 3},
        {"notice_until": "soon"},
    ]
    for bad in bads:
        with pytest.raises(st.StateError):
            st.validate(bad)
    assert st.notice_on({"notice": "x", "notice_until": 10}, 9.0) == "x"
    assert st.notice_on({"notice": "x", "notice_until": 10}, 10.0) is None
    assert st.notice_on({"notice": "", "notice_until": 10}, 9.0) is None


def test_output_is_a_display_and_the_packaged_example_is_commented() -> None:
    assert mods.parse({"modules": {"o": {"source": "volume", "display": "output"}}})["o"]
    packaged = mods.load(mods.PACKAGED)
    assert "output-capsule" not in packaged
    text = mods.PACKAGED.read_text()
    assert '# [modules.output-capsule]\n# source = "volume"\n# display = "output"' in text


# ---------------------------------------------------------------- render


def output_state(**extra: Any) -> st.State:
    return {
        "tier": "active",
        "glyph": outputs.BT_HEADPHONES,
        "label": "Headphones",
        "target": BT,
        "output": {"volume": 45, "battery": 80},
        **extra,
    }


def test_the_segment_shows_kind_name_battery_and_volume(config: dict[str, mods.Module]) -> None:
    module = config["output-capsule"]
    line = render.render(module, output_state(), now=1.0, colours=COLOURS, controller=True)
    battery, vol = "\U000f0081", outputs.VOL_MEDIUM
    assert visible(line) == f"{outputs.BT_HEADPHONES} Headphones {battery} {vol} 45% "
    assert line.count("%{F#333333}") == 1  # the active role colour, all of it
    assert "%{A1:barctl click output-capsule left:}" in line
    assert "%{A3:barctl click output-capsule right:}" in line
    no_battery = output_state(output={"volume": 100, "battery": None})
    line = render.render(module, no_battery, now=1.0, colours=COLOURS, controller=True)
    assert visible(line) == f"{outputs.BT_HEADPHONES} Headphones {outputs.VOL_HIGH} 100%"


def test_muted_is_volume_off_in_the_idle_colour(config: dict[str, mods.Module]) -> None:
    line = render.render(
        config["output-capsule"],
        output_state(tier="idle"),
        now=1.0,
        colours=COLOURS,
        controller=True,
    )
    assert f"{outputs.VOL_OFF} 45%" in visible(line)
    assert "%{F#222222}" in line and "%{F#333333}" not in line


def test_unavailable_shows_only_the_glyph(config: dict[str, mods.Module]) -> None:
    module = config["output-capsule"]
    line = render.render(module, None, now=1.0, colours=COLOURS, controller=True)
    assert visible(line) == "V"
    gone = {"tier": "unavailable", "glyph": outputs.VOL_OFF}
    line = render.render(module, gone, now=1.0, colours=COLOURS, controller=True)
    assert visible(line) == outputs.VOL_OFF


def test_the_notice_shows_in_place_of_the_name_until_it_ends(
    config: dict[str, mods.Module],
) -> None:
    module = config["output-capsule"]
    state = output_state(
        tier="idle", notice=f"{outputs.BT_SPEAKER} Speaker connected", notice_until=10.0
    )
    line = render.render(module, state, now=9.0, colours=COLOURS, controller=True)
    assert "Speaker connected" in visible(line) and "Headphones" not in visible(line)
    assert "%{F#333333}" + f"{outputs.BT_SPEAKER} Speaker connected" in line  # active accent
    line = render.render(module, state, now=10.0, colours=COLOURS, controller=True)
    assert "Headphones" in visible(line) and "connected" not in visible(line)


def test_a_name_is_escaped(config: dict[str, mods.Module]) -> None:
    line = render.render(
        config["output-capsule"],
        output_state(label="%{A1:rm:}x"),
        now=1.0,
        colours=COLOURS,
        controller=True,
    )
    assert "%%{A1:rm:}x" in line


def test_a_glyph_override_wins_over_the_kind_glyph() -> None:
    module = mods.parse(
        {
            "modules": {
                "o": {
                    "source": "volume",
                    "display": "output",
                    "glyph_override": {"unavailable": "U", "alert": "A"},
                }
            }
        }
    )["o"]
    state = output_state()

    def drawn(data: st.State) -> str:
        return visible(render.render(module, data, now=1.0, colours=COLOURS, controller=False))

    assert drawn(state).startswith(outputs.BT_HEADPHONES)  # no entry for active: the kind's
    assert drawn({"tier": "unavailable"}) == "U"
    assert drawn({**state, "tier": "alert"}).startswith("A Headphones")


def test_shown_counts_the_notice_only_while_it_shows(config: dict[str, mods.Module]) -> None:
    module = config["output-capsule"]
    base = output_state()
    noticed = {**base, "notice": "x connected", "notice_until": 10.0}
    assert shown(module, base, 9.0) != shown(module, noticed, 9.0)
    assert shown(module, base, 11.0) == shown(module, noticed, 11.0)
    louder = {**base, "output": {"volume": 50, "battery": 80}}
    assert shown(module, base, 1.0) != shown(module, louder, 1.0)


# ---------------------------------------------------------------- the controller's tick


def test_the_tick_pokes_once_when_a_notice_ends(config: dict[str, mods.Module]) -> None:
    pokes: list[str] = []
    controller = Controller(config, poke=pokes.append, sources={})
    st.write("output-capsule", output_state())
    assert controller.tick(now=100.0) == 1.0
    st.write("output-capsule", output_state(notice="x connected", notice_until=103.0))
    assert controller.tick(now=101.0) == 1.0  # the notice is 2 s off; a second at most
    assert controller.tick(now=102.5) == pytest.approx(0.52)  # wakes just past its end
    assert pokes == []  # the source's own write drew it
    controller.tick(now=103.02)
    assert pokes == ["output-capsule"]
    controller.tick(now=104.0)
    assert pokes == ["output-capsule"]
    # A notice the source replaced before it ended: its write poked; the tick doesn't.
    st.write("output-capsule", output_state(notice="y connected", notice_until=110.0))
    controller.tick(now=105.0)
    st.write("output-capsule", output_state())
    controller.tick(now=106.0)
    assert pokes == ["output-capsule"]


# ---------------------------------------------------------------- the source


def test_the_source_writes_kind_name_volume_and_battery(
    audio: Audio, config: dict[str, mods.Module]
) -> None:
    source, pokes, _ = make_source(config)
    source.update()
    state = out_state()
    assert (state["tier"], state["glyph"], state["label"], state["target"]) == (
        "active",
        outputs.HEADPHONES,
        "HD-Audio Generic",
        WIRED,
    )
    assert state["output"] == {"volume": 45, "battery": None}
    level = st.read("audio-level") or {}
    assert (level["glyph"], level["label"]) == (volume_source.VOL_LOW, "45% ")  # unchanged
    assert sorted(pokes.names) == ["audio-level", "output-capsule"]
    assert audio.calls("busctl") == []  # not a Bluetooth sink: no battery read

    audio.set(mute=True)
    source.update()
    assert out_state()["tier"] == "idle"
    assert len(audio.calls("pactl", "-f", "json")) == 1  # a mute is no new listing


def test_a_volume_change_lists_no_sinks_a_new_default_does(
    audio: Audio, config: dict[str, mods.Module]
) -> None:
    source, _, _ = make_source(config)
    source.update()
    for volume in (50, 55, 60):
        audio.set(volume=volume)
        source.events([("change", "sink", 57)])
    assert out_state()["output"]["volume"] == 60
    assert len(audio.calls("pactl", "-f", "json")) == 1
    audio.set(default=HDMI)
    source.events([("change", "server", 0)])
    assert len(audio.calls("pactl", "-f", "json")) == 2
    assert (out_state()["glyph"], out_state()["label"]) == (outputs.TELEVISION, "HDA NVidia")


def test_only_audio_level_lists_nothing(audio: Audio, config: dict[str, mods.Module]) -> None:
    source = VolumeSource(["audio-level"], Writer(config, Pokes()))
    source.update()
    source.events([("new", "sink", 59)])
    assert audio.calls("pactl", "-f", "json") == [] and audio.calls("busctl") == []


def test_headphones_connecting_and_going_give_a_5_second_notice(
    audio: Audio, config: dict[str, mods.Module]
) -> None:
    source, pokes, clock = make_source(config)
    audio.set(battery={BT_PATH: 62})
    source.update()
    pokes.names.clear()

    audio.set(sinks=[WIRED, HDMI, BT])  # WirePlumber leaves the default where it was
    source.events([("new", "sink", 59)])
    state = out_state()
    assert state["notice"] == f"{outputs.BT_HEADPHONES} WH-1000XM4 Wire… connected"
    assert state["notice_until"] == 1005.0
    assert state["label"] == "HD-Audio Generic"  # the default is still the wired one
    assert pokes.names == ["output-capsule"]  # audio-level shows nothing new
    assert audio.calls("busctl") == []  # not the default: no battery read

    clock[0] = 1003.0
    audio.set(default=BT)  # now it is the default
    source.events([("change", "server", 0)])
    state = out_state()
    assert (state["glyph"], state["output"]["battery"]) == (outputs.BT_HEADPHONES, 62)
    assert state["notice_until"] == 1005.0  # the notice runs its five seconds
    assert len(audio.calls("busctl")) == 1

    clock[0] = 1010.0
    audio.set(default=WIRED, sinks=[WIRED, HDMI])
    source.events([("remove", "sink", 59)])
    state = out_state()
    assert state["notice"] == "WH-1000XM4 Wire… disconnected"
    assert state["notice_until"] == 1015.0
    assert (state["label"], state["output"]["battery"]) == ("HD-Audio Generic", None)

    clock[0] = 1020.0
    audio.set(volume=46)
    source.events([("change", "sink", 57)])
    assert "notice" not in out_state()  # an ended notice is not written again


def test_a_new_wired_sink_gives_no_notice(audio: Audio, config: dict[str, mods.Module]) -> None:
    source, _, _ = make_source(config)
    audio.set(sinks=[WIRED])
    source.update()
    audio.set(sinks=[WIRED, HDMI])
    source.events([("new", "sink", 58)])
    assert "notice" not in out_state()


def test_the_battery_is_reread_every_5_minutes_only_while_bluetooth_is_the_default(
    audio: Audio, config: dict[str, mods.Module]
) -> None:
    source, _, clock = make_source(config)
    audio.set(default=BT, sinks=[WIRED, BT], battery={BT_PATH: 70})
    source.update()
    assert out_state()["output"]["battery"] == 70
    assert source.battery_due(1000.0) == 300.0
    assert source.refresh(1299.0) is False
    audio.set(battery={BT_PATH: 40})
    clock[0] = 1300.0
    assert source.refresh() is True
    assert out_state()["output"]["battery"] == 40
    assert len(audio.calls("busctl")) == 2

    audio.set(default=WIRED)
    source.events([("change", "server", 0)])
    assert source.battery_due(2000.0) is None
    assert source.refresh(9999.0) is False
    assert len(audio.calls("busctl")) == 2
    assert out_state()["output"]["battery"] is None


def test_a_failed_listing_keeps_the_last(audio: Audio, config: dict[str, mods.Module]) -> None:
    source, _, _ = make_source(config)
    source.update()
    (audio.dir / "sinks.json").write_text("not json")
    source.events([("new", "sink", 60)])
    assert out_state()["label"] == "HD-Audio Generic" and source.relist is True


# ---------------------------------------------------------------- following the stream


def follow(source: VolumeSource) -> threading.Thread:
    def run() -> None:
        source.follow()
        if not source.stopping:
            source.gone()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_the_stream_coalesces_changes_and_gives_the_notice(
    audio: Audio, config: dict[str, mods.Module]
) -> None:
    source, pokes, _ = make_source(config)
    source.clock = time.time
    fd = os.open(audio.stream, os.O_RDWR)
    thread = follow(source)
    pokes.wait(2)
    first = len(audio.calls("pactl", "get-sink-volume"))
    # Ten notches of a fast scroll in one burst: one read at once, then one for the rest.
    burst = "".join("Event 'change' on sink #57\n" for _ in range(10))
    audio.set(volume=70)
    os.write(fd, burst.encode())
    pokes.wait(4)
    reads = len(audio.calls("pactl", "get-sink-volume")) - first
    assert 1 <= reads <= 2
    assert out_state()["output"]["volume"] == 70

    audio.set(sinks=[WIRED, HDMI, BT])
    os.write(fd, b"Event 'new' on sink #59\nEvent 'change' on client #3\n")
    end = time.monotonic() + 3
    while "notice" not in out_state() and time.monotonic() < end:
        time.sleep(0.02)
    assert out_state()["notice"].endswith("connected")
    os.close(fd)
    thread.join(3)
    assert out_state()["tier"] == "unavailable"
    assert not (audio.dir.parent / "unexpected").exists()


def test_the_source_logs_no_sink_or_device(
    audio: Audio, config: dict[str, mods.Module], journal_sock: Any
) -> None:
    source, _, _ = make_source(config)
    audio.set(default=BT, sinks=[WIRED, BT], battery={BT_PATH: 70})
    source.update()
    source.events([("remove", "sink", 59)])
    text = repr(journal_sock.received())
    for word in ("WH-1000", "bluez", "AA_BB", BT_ADDRESS, "HD-Audio"):
        assert word not in text


# ---------------------------------------------------------------- barmenu outputs


def table(rows: list[bm.Row]) -> list[tuple[str, str, str | list[str], bool]]:
    return [(r.glyph, r.label, r.command, r.current) for r in rows]


MIXER = ("\U000f057e", "Mixer…", ["pwvucontrol"], False)


def test_outputs_rows_marks_and_argv(audio: Audio, names: None) -> None:
    audio.set(sinks=[WIRED, HDMI, BT])
    audio.objects(
        [
            ("AA:BB:CC:DD:EE:FF", "WH-1000XM4", "audio-headphones", True, True),
            (SPEAKER_ADDRESS, "Kitchen", "audio-speakers", True, False),
            ("22:22:22:22:22:22", "Mouse", "input-mouse", True, False),  # not audio
            ("33:33:33:33:33:33", "Unpaired", "audio-headset", False, False),
        ]
    )
    st.write("output-capsule", {"tier": "active", "target": HDMI})
    assert table(outputs_menu.rows()) == [
        (outputs.HEADPHONES, "HD-Audio Generic", ["pactl", "set-default-sink", WIRED], False),
        (outputs.TELEVISION, "HDMI Speakers", ["pactl", "set-default-sink", HDMI], True),
        (
            outputs.BT_HEADPHONES,
            "WH-1000XM4 Wire…",
            ["pactl", "set-default-sink", BT],
            False,
        ),
        ("\U000f00b1", "Connect Kitchen", ["bluetoothctl", "connect", SPEAKER_ADDRESS], False),
        (
            "\U000f00b2",
            "Disconnect WH-1000XM4",
            ["bluetoothctl", "disconnect", BT_ADDRESS],
            False,
        ),
        MIXER,
    ]
    assert audio.calls("pactl", "get-default-sink") == []  # barctl's state named it


def test_outputs_without_barctl_or_bluez(audio: Audio) -> None:
    (audio.dir / "no-bluez").touch()
    audio.set(default=WIRED)
    rows = outputs_menu.rows()
    assert [r.label for r in rows] == ["HD-Audio Generic", "HDA NVidia", "Mixer…"]
    assert rows[0].current and not rows[1].current  # pactl's default, barctl had none
    (audio.dir / "sinks.json").write_text("{")
    assert table(outputs_menu.rows()) == [MIXER]  # nothing readable: the mixer still opens


def test_outputs_queries_take_the_providers_limit(
    audio: Audio, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(providers, "TIMEOUT", 0.2)
    limits: list[tuple[str, float]] = []
    original = procs.query

    def query(argv: list[str], timeout: float = 3.0, **kw: Any) -> str | None:
        limits.append((argv[0], timeout))
        return original(argv, timeout=timeout, **kw)

    monkeypatch.setattr(procs, "query", query)
    outputs_menu.rows()
    assert limits == [("pactl", 0.2), ("pactl", 0.2), ("busctl", 0.2)]


def test_a_picked_row_runs_only_its_argv(
    audio: Audio, launched: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    audio.objects([(SPEAKER_ADDRESS, "Kitchen", "audio-speakers", True, False)])
    rows = outputs_menu.rows()
    pick = next(i for i, r in enumerate(rows) if r.label == "Connect Kitchen")
    monkeypatch.setattr(bm, "choose", lambda menu, extra=None: pick)
    picked = bm.open_menu(bm.Menu("outputs", provider="outputs"))
    assert picked is not None
    assert launched == [["bluetoothctl", "connect", SPEAKER_ADDRESS]]  # recorded, never run


def test_the_outputs_menu_is_listed(isolate: Path) -> None:
    menu = bm.load()["outputs"]
    assert (menu.provider, menu.title, menu.side, menu.glyph) == (
        "outputs",
        "Output",
        "right",
        "\U000f04c3",
    )


# ---------------------------------------------------------------- the player menu's row


def test_the_player_menus_output_row(config: dict[str, mods.Module]) -> None:
    assert table([player_menu.output_row()]) == [
        ("\U000f04c3", "Output… \u203a", ["barmenu", "outputs"], False)
    ]
    st.write("output-capsule", output_state())
    assert table([player_menu.output_row()]) == [
        (outputs.BT_HEADPHONES, "Output: Headphones \u203a", ["barmenu", "outputs"], False)
    ]
    st.write("output-capsule", {"tier": "unavailable", "label": "x"})
    assert player_menu.output_row().label == "Output… \u203a"


# ---------------------------------------------------------------- the environment rule, doctor

AGENT = ("COORDINATOR", "CLAUDECODE", "TESSERA_ACTOR")


@pytest.mark.parametrize("tainted", [False, True])
def test_no_output_row_or_click_touches_the_agent_variables(
    audio: Audio, monkeypatch: pytest.MonkeyPatch, tainted: bool
) -> None:
    from desktop_tools.barctl import ops

    for name in AGENT:
        if tainted:
            monkeypatch.setenv(name, "x")
        else:
            monkeypatch.delenv(name, raising=False)
    audio.objects([(SPEAKER_ADDRESS, "Kitchen", "audio-speakers", True, False)])
    st.write("output-capsule", output_state())
    started: list[tuple[list[str], object]] = []

    def detach(argv: list[str], env: object = None, cwd: object = None) -> int:
        started.append((list(argv), env))
        return 1

    monkeypatch.setattr(procs, "detach", detach)
    argvs = [r.argv() for r in outputs_menu.rows()]
    for button in ("left", "scroll-up", "scroll-down", "right"):
        ops.click("output-capsule", button)
    assert [argv for argv, _ in started] == [
        ["audio", "mute-toggle"],
        ["audio", "volume-increase"],
        ["audio", "volume-decrease"],
        ["barmenu", "outputs"],
    ]
    assert all(env is None for _, env in started)
    for argv in argvs + [a for a, _ in started]:
        assert not any(name in " ".join(argv) for name in AGENT), argv
        assert argv[0] not in ("env", "unset", "zsh", "sh"), argv


def test_doctor_names_the_output_commands(
    config: dict[str, mods.Module], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda c: None if c in ("busctl", "bluetoothctl") else real(c)
    )
    check = {c["name"]: c for c in doctor.checks()}["output segment"]
    assert check["state"] == "warn" and "output-capsule" in check["detail"]
    assert "busctl" in check["fix"] and "bluetoothctl" in check["fix"]

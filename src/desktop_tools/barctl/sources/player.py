"""player: every MPRIS player, from `playerctl -a --follow metadata`, shown as one (record 0001,
question 3): the pinned player while it is listed (record 0003 §5, `barctl pin`), else Playing
beats Paused beats Stopped, then the player whose status changed most recently.

Every module this source draws gets the same state: the glyph is the player's icon then its
state's (from the `player` tool's instances.json and states.json), the label "Artist DASH
Title" (an en dash), whole up to LABEL_MAX characters (`text` and `both` show 40 of it,
`capsule` scrolls it), the target the player's instance name, so a click acts on the player
the bar shows, and `progress` (position, length, rate, when it was read, whether it plays),
for the capsule's line. Each module's display picks what it shows, except `display = "chips"`
(record 0005 phase A), which gets one segment per player instead, in the order each was first
seen (so chips keep their places), the shown one underlined and the pinned one labelled with a
pin; at most `chips_max` cells, the last `+N` past that, and none below `chips_min` players.
Unavailable with no player, idle paused or stopped, active playing. A module with
`accent = "art"` also gets the cover's colour (barctl/art.py).

A capsule also gets `status_at` (record 0005 phase B): when the shown player's status last
changed, or another player became the shown one, from which render works out its fade. With
`spoken = true` it gets `kind = "spoken"` for a podcast or audiobook, from the first rule that
matches: the track id or URL names an episode; the genre says podcast, audiobook or spoken; the
URL is a local `.m4b` or `.aax` file or under a `Podcasts` or `Audiobooks` folder; the player's
name is in `spoken_players`. The track id, URL and genre are read for that and kept nowhere.
For spoken word the shown player's MPRIS `Rate` is read once per track and with each 30-second
position re-read (`busctl --user get-property`, read only) into `progress.rate`, so the line
moves at the player's speed. A capsule also gets the shown player's `loop` mode and `shuffle`
(record 0005 phase C), for its transport row's buttons; absent when the player gives none.

The position is not in the followed format (playerctl may re-print one with `{{position}}`
every second): it is read with `playerctl -p <shown> position` on each event of the shown player
and every POSITION_EVERY seconds while it plays, and render moves it on from the time. Nothing
here controls a player: the only playerctl calls are the stream, `-l`, `position` (no value)
and `metadata`, and the only busctl call is `get-property`.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from desktop_tools.barctl import art
from desktop_tools.barctl import state as st
from desktop_tools.barctl.modules import Module, Row, valid_segment
from desktop_tools.barctl.sources.base import Source
from desktop_tools.barctl.store import Writer
from desktop_tools.common import paths, procs

US = "\x1f"
FIELDS = (
    "{{playerInstance}}",
    "{{playerName}}",
    "{{status}}",
    "{{artist}}",
    "{{title}}",
    "{{mpris:length}}",
    "{{mpris:artUrl}}",
    "{{mpris:trackid}}",  # these three only say whether it is spoken word (record 0005 B)
    "{{xesam:url}}",
    "{{xesam:genre}}",
    "{{loop}}",  # the transport row's loop and shuffle buttons (record 0005 C)
    "{{shuffle}}",
)
FORMAT = US.join(FIELDS)
RANK = {"Playing": 3, "Paused": 2, "Stopped": 1}
LABEL_MAX = 200
DASH = "\u2013"  # an en dash between artist and title
POSITION_EVERY = 30.0  # seconds between position re-reads while the shown player plays
RATE = 1.0  # the rate when it isn't read: music, or a player that gives none
RATE_TIMEOUT = 2.0  # seconds the Rate read (busctl) may take
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"
SPOKEN = "spoken"
EPISODE = re.compile(r"spotify:episode:|/episode/", re.IGNORECASE)
SPOKEN_GENRES = ("podcast", "audiobook", "audio book", "spoken")
SPOKEN_FILES = (".m4b", ".aax")
SPOKEN_FOLDERS = ("podcasts", "audiobooks")
PIN = "\U000f0403"  # md-pin: the pinned player's chip
MORE = "\U000f01d8"  # md-dots_horizontal: the `+N` cell past chips_max
MORE_ID = "more"  # the `+N` cell's segment id, for its own clicks (segment_clicks.more)


def _icons(file: str, field: str, fallback: str) -> dict[str, str]:
    """name (or state) -> icon from the player tool's JSON, with `*` for its fallback entry."""
    try:
        data = json.loads((paths.data_home() / "player" / file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for entry in data if isinstance(data, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get(field), str):
            key = entry[field]
            out.setdefault("*" if key == fallback else key, str(entry.get("icon", "")))
    return out


def player_icon(icons: dict[str, str], name: str) -> str:
    return icons.get(name, icons.get("*", ""))


def track(artist: str, title: str) -> str:
    """`Artist DASH Title` (an en dash), whole up to LABEL_MAX characters."""
    text = f"{artist} {DASH} {title}" if artist and title else artist + title
    return text if len(text) <= LABEL_MAX else text[: LABEL_MAX - 1] + "…"


def spoken_hint(trackid: str, url: str, genre: str) -> bool:
    """Rules 1-3 of record 0005 phase B: the track id or URL names an episode; the genre (a
    list, joined by playerctl) says podcast, audiobook or spoken; the URL is a local `.m4b` or
    `.aax` file, or under a folder named `Podcasts` or `Audiobooks`. Only the answer is kept."""
    if EPISODE.search(trackid) or EPISODE.search(url):
        return True
    lowered = genre.lower()
    if any(word in lowered for word in SPOKEN_GENRES):
        return True
    if url.lower().startswith("file://"):
        local = url[len("file://") :]
        if local.lower().endswith(SPOKEN_FILES):
            return True
        folders = [part.lower() for part in local.split("/")[:-1]]
        if any(folder in SPOKEN_FOLDERS for folder in folders):
            return True
    return False


def rate_of(out: str | None) -> float | None:
    """A `busctl get-property` answer (`d 1.5`) as a number; None when it isn't one."""
    parts = (out or "").split()
    if len(parts) != 2 or parts[0] != "d":
        return None
    try:
        value = float(parts[1])
    except ValueError:
        return None
    return value if 0 < value <= st.RATE_MAX else None


def read_rate(instance: str) -> float | None:
    """The player's MPRIS Rate, read only, or None when it can't be read in RATE_TIMEOUT."""
    out = procs.query(
        [
            "busctl",
            "--user",
            "get-property",
            f"org.mpris.MediaPlayer2.{instance}",
            MPRIS_PATH,
            MPRIS_PLAYER,
            "Rate",
        ],
        timeout=RATE_TIMEOUT,
    )
    return rate_of(out)


def shuffle_of(text: str) -> bool | None:
    """playerctl's `{{shuffle}}` (`true`, `false`, empty when the player gives none)."""
    lowered = text.strip().lower()
    return True if lowered == "true" else False if lowered == "false" else None


def seconds(micro: str) -> float | None:
    """mpris:length (microseconds) in seconds; None when unknown (a stream gives none)."""
    try:
        value = int(micro.strip())
    except ValueError:
        return None
    return value / 1_000_000 if value > 0 else None


@dataclass
class Player:
    status: str
    name: str
    track: str
    seq: int
    length: float | None = None
    art: str = ""
    first: int = 0  # the order it was first seen in: the chips' order
    changed_at: float = 0.0  # when its status last changed (record 0005 phase B)
    spoken: bool = False  # rules 1-3 of spoken word matched its track; its fields aren't kept
    loop: str = ""  # None, Track or Playlist; empty when the player gives none (record 0005 C)
    shuffle: bool | None = None


class PlayerSource(Source):
    name = "player"
    commands = ("playerctl",)

    def __init__(self, modules: Sequence[str], writer: Writer) -> None:
        super().__init__(modules, writer)
        self.players: dict[str, Player] = {}
        self.tick = 0
        self.names = _icons("instances.json", "name", "default")
        self.states = _icons("states.json", "state", "stopped")
        self.pinned: str | None = None
        self.seen = 0  # players first seen so far, for Player.first
        # instance -> (position in seconds, None when it couldn't be read; when it was read):
        # the shown player's, mostly. A failed read waits POSITION_EVERY like a good one.
        self.positions: dict[str, tuple[float | None, float]] = {}
        self.colours: dict[str, str | None] = {}  # art URL -> its accent (None: none)
        # The shown player and since when (record 0005 phase B: a new one restarts the fade).
        self.shown: tuple[str | None, float] = (None, 0.0)
        # instance -> (the track it was read for, its Rate or None): one read per track.
        self.rates: dict[str, tuple[str, float | None]] = {}
        self.fetching: set[str] = set()
        self.lock = threading.RLock()
        self.clock: Callable[[], float] = time.time

    # ------------------------------------------------------------ the shown player

    def pick(self) -> str | None:
        """The shown player's instance, or None with no player."""
        if self.pinned is not None and self.pinned in self.players:
            return self.pinned
        best: tuple[int, int] | None = None
        chosen = None
        for instance, p in self.players.items():
            key = (RANK.get(p.status, 0), p.seq)
            if best is None or key > best:
                best, chosen = key, instance
        return chosen

    def listed(self) -> set[str]:
        return set((procs.query(["playerctl", "-l"]) or "").split())

    def prune(self) -> None:
        """Forget players playerctl no longer lists: `--follow` prints an empty line when one
        goes, but not always before the next event. A pin ends with its player."""
        live = self.listed()
        for instance in list(self.players):
            if instance not in live:
                del self.players[instance]
                self.positions.pop(instance, None)
                self.rates.pop(instance, None)
        if self.pinned is not None and self.pinned not in live:
            self.pinned = None

    def parse(self, line: str) -> str | None:
        """One line of the stream into the players: its instance, or None for an empty one."""
        fields = line.split(US)
        if len(fields) < 5 or not fields[0]:
            return None
        instance, name, status, artist, title = fields[:5]
        length = seconds(fields[5]) if len(fields) > 5 else None
        art_url = fields[6].strip() if len(fields) > 6 else ""
        trackid, url, genre, loop, shuffle = (
            fields[i].strip() if len(fields) > i else "" for i in (7, 8, 9, 10, 11)
        )
        old = self.players.get(instance)
        if old is None or old.status != status:
            self.tick += 1
            seq, changed_at = self.tick, self.clock()
        else:
            seq, changed_at = old.seq, old.changed_at
        first = old.first if old is not None else self.first_seen()
        self.players[instance] = Player(
            status,
            name,
            track(artist, title),
            seq,
            length,
            art_url,
            first,
            changed_at,
            spoken_hint(trackid, url, genre),
            loop if loop in st.LOOPS else "",
            shuffle_of(shuffle),
        )
        return instance

    def first_seen(self) -> int:
        self.seen += 1
        return self.seen

    def event(self, line: str) -> None:
        """One line of the stream: instance, name, status, artist, title, length, art."""
        with self.lock:
            instance = self.parse(line)
            self.prune()
            shown = self.pick()
            if shown is not None and (instance == shown or shown not in self.positions):
                self.read_position(shown)
            self.update()

    def read_position(self, instance: str) -> None:
        """`playerctl -p <instance> position`: the one query that reads where a track is. It
        is given no value, so it never seeks."""
        out = procs.query(["playerctl", "-p", instance, "position"])
        try:
            position: float | None = max(0.0, float((out or "").strip()))
        except ValueError:
            position = None
        self.positions[instance] = (position, self.clock())

    def refresh(self, now: float | None = None) -> bool:
        """Re-read the shown player's position if it plays and the last read is
        POSITION_EVERY seconds old (it catches seeks made elsewhere). Returns whether it read."""
        now = self.clock() if now is None else now
        with self.lock:
            shown = self.pick()
            if shown is None or self.players[shown].status != "Playing":
                return False
            last = self.positions.get(shown)
            if last is not None and now - last[1] < POSITION_EVERY:
                return False
            self.read_position(shown)
            # The Rate too, for spoken word (record 0005 phase B): a speed set mid-track (the
            # menu's speed row, the player's own) or a failed read is caught here.
            self.rates.pop(shown, None)
            self.update()
            return True

    def pin(self, instance: str | None, toggle: bool = False) -> str | None:
        """Show this player while it is listed (None: back to the rank; with `toggle`, back to
        the rank when it is already the pin). Returns the pin. Raises LookupError when
        playerctl doesn't list it."""
        with self.lock:
            if instance is None or (toggle and instance == self.pinned):
                self.pinned = None
            else:
                if instance not in self.listed():
                    raise LookupError(f"no player {instance!r} (playerctl -l lists them)")
                if instance not in self.players:
                    out = procs.query(["playerctl", "-p", instance, "metadata", "--format", FORMAT])
                    if not out or self.parse(out.splitlines()[0]) is None:
                        self.players[instance] = Player(
                            "Stopped",
                            instance.split(".")[0],
                            "",
                            0,
                            first=self.first_seen(),
                            changed_at=self.clock(),
                        )
                self.pinned = instance
                self.read_position(instance)
            self.update()
            return self.pinned

    # ------------------------------------------------------------ writing

    def wants_art(self) -> bool:
        return any(
            (m := self.writer.modules.get(name)) is not None and m.accent == "art"
            for name in self.modules
        )

    def accent_for(self, url: str) -> str | None:
        """The art's colour if it is known; a fetch started for a new URL, once."""
        if not url or not self.wants_art():
            return None
        if url in self.colours:
            return self.colours[url]
        if url not in self.fetching:
            self.fetching.add(url)
            threading.Thread(target=self._fetch, args=(url,), name="art", daemon=True).start()
        return None

    def _fetch(self, url: str) -> None:
        try:
            found = art.colour(url)
        except OSError:
            found = None
        with self.lock:
            self.colours[url] = found
            self.fetching.discard(url)
            if len(self.colours) > art.CACHE_MAX:
                self.colours.pop(next(iter(self.colours)))
            if not self.stopping:
                self.update()

    def kind(self, module: Module | None, p: Player) -> str:
        """`spoken` for a capsule with `spoken = true` whose player plays spoken word (rules
        1-4, record 0005 phase B), else empty: every other module, and the switch off."""
        if module is None or module.display != "capsule" or not module.spoken:
            return ""
        names = {n.lower() for n in module.spoken_players}
        return SPOKEN if p.spoken or p.name.lower() in names else ""

    def rate(self, instance: str, p: Player, spoken: bool) -> float:
        """The shown player's Rate for spoken word, read once per track (`refresh` drops it, so
        the 30-second re-read reads it again); RATE otherwise or when it can't be read."""
        if not spoken:
            return RATE
        known = self.rates.get(instance)
        if known is None or known[0] != p.track:
            known = (p.track, read_rate(instance))
            self.rates[instance] = known
        return known[1] if known[1] is not None else RATE

    def status_at(self, instance: str, p: Player, now: float) -> float:
        """When the shown player's status changed, or it became the shown one: the later."""
        if self.shown[0] != instance:
            self.shown = (instance, now)
        return max(p.changed_at, self.shown[1])

    def progress(self, instance: str, p: Player, rate: float = RATE) -> st.State | None:
        read = self.positions.get(instance)
        if read is None or read[0] is None:
            return None
        return {
            "position": read[0],
            "length": p.length,
            "rate": rate,
            "at": read[1],
            "playing": p.status == "Playing",
        }

    def chips(self, module: Module, shown: str) -> list[st.State]:
        """The chips' cells: one per player by `first`, the shown one underlined, the pinned
        one carrying md-pin; past `chips_max`, the last cell is `+N` (id `more`); none with
        fewer than `chips_min`. An instance that can't be a segment id (over 64 characters),
        or is named `more` (the `+N` cell's id and click table), is left out (it is still in
        `barmenu players`)."""
        listed = sorted(
            (p.first, instance)
            for instance, p in self.players.items()
            if valid_segment(instance) and instance != MORE_ID
        )
        if len(listed) < module.chips_min:
            return []
        keep = listed
        if len(listed) > module.chips_max:
            keep = listed[: module.chips_max - 1]
        cells: list[st.State] = []
        for _, instance in keep:
            p = self.players[instance]
            cell: st.State = {
                "id": instance,
                "tier": "active" if p.status == "Playing" else "idle",
                # A player with no icon in instances.json (and no fallback entry) shows the
                # module's own glyph, so its chip is still drawn and clickable.
                "glyph": player_icon(self.names, p.name) or module.glyph,
            }
            if instance == self.pinned:
                cell["label"] = PIN
            if instance == shown:
                cell["underline"] = True
            cells.append(cell)
        if len(keep) < len(listed):
            more = {
                "id": MORE_ID,
                "tier": "idle",
                "glyph": MORE,
                "label": str(len(listed) - len(keep)),
            }
            cells.append(more)
        return cells

    def update(self) -> None:
        with self.lock:
            instance = self.pick()
            now = self.clock()
            if instance is None:
                self.shown = (None, now)
                self.set_all("unavailable")
                return
            p = self.players[instance]
            tier = "active" if p.status == "Playing" else "idle"
            icon = player_icon(self.names, p.name)
            state_icon = player_icon(self.states, p.status.lower())
            glyph = " ".join(g for g in (icon, state_icon) if g)
            kinds = {name: self.kind(self.writer.modules.get(name), p) for name in self.modules}
            rate = self.rate(instance, p, SPOKEN in kinds.values())
            progress = self.progress(instance, p, rate)
            accent = self.accent_for(p.art)
            status_at = self.status_at(instance, p, now)
            for name in self.modules:
                module = self.writer.modules.get(name)
                if module is not None and module.display == "chips":
                    self.writer.set(
                        name, self.name, tier, segments=self.chips(module, instance), now=now
                    )
                    continue
                capsule = module is not None and module.display == "capsule"
                self.writer.set(
                    name,
                    self.name,
                    tier,
                    glyph=glyph,
                    label=p.track,
                    target=instance,
                    progress=progress,
                    accent=accent if module is not None and module.accent == "art" else None,
                    status_at=status_at if capsule else None,
                    kind=kinds[name],
                    loop=p.loop if capsule else "",
                    shuffle=p.shuffle if capsule else None,
                    now=now,
                )

    # ------------------------------------------------------------ following

    def _refresher(self, done: threading.Event) -> None:
        while not done.wait(1.0):
            if self.stopping:
                return
            self.refresh()

    def follow(self) -> None:
        with self.lock:
            self.players.clear()
            self.positions.clear()
            self.update()
        # An event of its own per stream: a restarted stream never shares the old timer's.
        done = threading.Event()
        timer = threading.Thread(
            target=self._refresher, args=(done,), name="player-position", daemon=True
        )
        timer.start()
        try:
            stream = self.stream(["playerctl", "-a", "--follow", "metadata", "--format", FORMAT])
            for line in stream.lines():
                if self.stopping:
                    return
                self.event(line)
        finally:
            done.set()

    def gone(self) -> None:
        with self.lock:
            self.players.clear()
            self.positions.clear()
            self.rates.clear()
            self.update()  # a pin outlives a restarted stream; prune ends it with its player

    @classmethod
    def menu_rows(cls, module: str, state: st.State | None) -> list[Row]:
        """One row per player: picking it plays or pauses that player."""
        names = _icons("instances.json", "name", "default")
        out = procs.query(["playerctl", "-l"]) or ""
        rows = []
        for instance in out.split():
            icon = player_icon(names, instance.split(".", 1)[0])
            rows.append(Row(icon, instance, ["player", "play-pause", instance]))
        return rows

# Security

## Threat model

The tools run as Stephen on his desktop and open no network port. What they trust and guard:

- **Pushed text is text.** Anything a program pushes to the bar has polybar's `%{` escaped, and the colour and action
  tags are barctl's own, so a pusher can't put a command into a click. A click runs only the command in
  `modules.toml`, with `{target}` filled in as one whole argument, never through a shell.
- **One writer per module.** `push` is refused for a module drawn by barctl's own source or owned by another pusher.
- **Local sockets only.** The control socket and the state files are in `$XDG_RUNTIME_DIR/barctl` (mode 700, the socket
  600); polybar's sockets are its own. Anyone running as Stephen can already change his bar.
- **Menu items are data.** crew's quick menu runs what `meta <name> menu --json` offers, but only as argument
  lists, never through a shell: a `meta` verb with its arguments, `xdg-open` for `https://` and `obsidian://` links
  only, `code` for an absolute path only, and `xclip` with the text on stdin.
- **Out of scope:** a hostile process running as Stephen.

## Secrets

- Give each secret through `DESKTOP_TOOLS_<KEY>_FILE`, a mounted file. A secret setting is also read from its plain variable and the config file, like any setting, so keep it out of both: `docker inspect` and `ps` show variables. See [In-Depth Configuration](In-Depth-Configuration#secrets).
- Values are never logged. Logs and `desktop-tools config` show where a value came from, never the value itself.
- CI scans every commit with gitleaks, and secrets in history fail the build.

This project has no secrets; the journal helper redacts anything that looks like one before logging (brain record 0017).
A tool's arguments never reach the journal: the helper drops them from what it logs, and before its first entry it
rewrites its own process's command line to the program alone, since journald copies that into `_CMDLINE`. Where it
can't, it writes no journal entry (brain PR 170). From then on `ps` shows the tool without its arguments.

### The tessera menu

`barmenu tessera` (design record 0002) reads only `tessera status --json`, which never decrypts and holds counts and
states, never an entry name. Entry names are chosen inside `tessera pick`'s own rofi, so no name reaches barmenu's
arguments, its journal line or `ps`. The clipboard is pass's own `-c` through tessera: cleared after 45 seconds.
barmenu never sets or clears `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR`: tessera reads them to tell who is
calling. When one is set in barmenu's own environment, the menu shows one `Not available` row instead of the
actions, since tessera would refuse them.

### The player capsule

The capsule and its menus (design record 0003) never control a player on their own: the player source's only
`playerctl` calls are its stream, `-l`, `position` with no value and `metadata`, and a click or menu row runs a
`playerctl -p <instance>` argument list, the instance from barctl's state and `playerctl -l`, never a shell string.
The track (artist, title) lives only in the module's state file in `$XDG_RUNTIME_DIR/barctl` (700, emptied at
logout); barctl's journal lines name the module and button, never the label, and the menus' providers log nothing of
the player's state. `barctl status` shows the label to the user's own processes, as before. The player chips
(design record 0005 phase A) hold only player instance names and icons, already in `barctl status`; a chip's click
fills `{segment}` with that name as one whole argument, and the name must pass the segment-id check (no space, colon
or `%`) before it goes into an action tag. The transport row (design record 0005 phase C) adds only barctl's own
cells: its segment ids are fixed words (`previous` … `seek-15`), never a writer's text, and `barctl transport` maps
each to one `playerctl -p <instance>` argument list (a seek's seconds worked out from the state's length, never
passed in); an unknown cell is refused. While the row shows, the title is not drawn at all. Spoken-word detection (design record 0005 phase B, `spoken = true`) reads
the track id, URL and genre to work out `kind` and keeps them nowhere: not in the state file, not in the journal;
only `kind` is kept. Its only `busctl` call in the source is a read (`get-property Rate`); the speed row in `barmenu
player` runs `busctl --user set-property … Rate d <value>` only when picked, as an argument list, the bus name built
from the instance in barctl's state.

- **The art fetch** (`accent = "art"`, off by default) goes only to the cover URL the player itself gives, once per
  new URL: `curl -q` (no `.curlrc`, so no cookie jar), HTTPS only (redirects too), 2 seconds, 1 MiB at most, into a
  20-file cache in the runtime folder; `file://` covers are read where they are. The colour it gives is checked to
  `#` and six hex digits, so no cover can put a polybar tag on the bar.
- **The environment rule:** barctl and barmenu never set, clear or change `COORDINATOR`, `CLAUDECODE` or
  `TESSERA_ACTOR` for a click or a row: commands get the bar's environment untouched. `barctl doctor` warns when the
  running controller or a bar was started with any of them set ("the bar runs in an agent's environment"), naming
  the variable, never its value; restart the bar from a clean session.

### The output segment

The output segment and `barmenu outputs` (design record 0003 §10) never change the audio or Bluetooth on their own:
the volume source's only `pactl` calls read (`subscribe`, `get-default-sink`, `get-sink-volume`, `get-sink-mute`,
`-f json list sinks`, `list short sinks`) and its only `busctl` call reads `Battery1.Percentage`; barctl never switches
the default sink. A menu row (`pactl set-default-sink`, `bluetoothctl connect`/`disconnect`) runs only when picked, as
an argument list whose sink name, BlueZ path and address come from the queries' JSON and are checked first (no leading
`-`, BlueZ's path and address shapes). No row pairs, removes, trusts or powers a device. Sink and device names are shown
on the bar and in the menu, and held in the module's runtime state file, as the track is; nothing barctl or barmenu
writes to the journal names a sink, a device, an alias or an address.

### The printer and the scanner

Design record 0004 §7. `devices`'s acting verbs (pause, resume, default, cancel, test page, every scan) refuse with
exit 3 when `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR` is set: `An agent may not operate the printer or scanner`. A
scan or a cancelled job is a physical-world act that stays Stephen's click; the variables are read, never set or
cleared, and pass to every child untouched. `status` and `find` and the sources' and menus' reads stay anyone's.

Nothing reaches a log, the journal, barctl's state fields or `doctor` that names a document, a job title, a file name, a
path, a device URI, a host name or an address: they carry counts, states, tiers, reason words, local or network, and a
job number. The job title is never asked of CUPS. A scan's file name is shown only in its own notification and copied
on purpose. Scans are made in a `0700` folder in `$XDG_RUNTIME_DIR` (RAM) and only the finished file reaches the
chosen folder.

The reachability probe connects to port 631, then 80, never 9100: a connection to a raw print port can feed a blank
page. The eSCL status is one read-only `GET`; a scanner's XML is parsed by expat, with no external entities.

## Hardening

- **Supply chain:** dependencies are pinned in the lock file and updated weekly by Dependabot. GitHub Actions are pinned to commit SHAs.
- **Dependency auto-merge:** Dependabot patch updates get auto-merge queued by `dependabot-automerge.yml`: they still need a code owner's approval, then merge once CI passes.

- **Input validation:** a pushed state is checked field by field (tiers, counts, segment ids, the capsule's `progress`
  numbers and its `accent`, which must be `#` and six hex digits, the output segment's `output` numbers and `notice`) and anything unknown is dropped; module and segment names are restricted to the characters a file name and an action tag can carry.
- **No root:** nothing here needs it (brain record 0016).

## Reporting a vulnerability

Report privately through [GitHub security advisories](https://github.com/andronics/desktop-tools/security/advisories/new), never in a public issue.

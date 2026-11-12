# 0004: Printer and scanner modules on the bar, drawn by barctl

<!-- Add a line for this record to the index in docs/design/README.md (CI checks). -->

Status: Proposed
Date: 2026-11-12
Authors: Stephen Cox (direction, 2026-11-12: the printer and scanner buttons get "the barctl IPC treatment
like the tessera module": status, connectivity and quick actions such as scanning from the document feeder
or the flatbed and viewing the print queue); written up by the desktop coordinator

## Context

The bar's printer and scanner buttons are plain launchers. In the dotfiles' `desktop/.config/polybar/modules/device.ini`,
`device-printer` runs `system-config-printer` and `device-scanner` runs `simple-scan`, both
`module/base-text-inverse` text modules with fixed legacy glyphs (U+F929, U+F92A), between
`device-bluetooth` and the next group in `bars/main`'s `modules-left`. They say nothing: not whether the
printer is on, printing, out of paper or paused, nor whether the scanner can be reached.

Stephen wants them drawn by barctl like the tessera module (record 0002): a state with tiers, the device's
connectivity, and a right-click menu of the common actions. barctl already reserves the source names
`printer` and `scanner` (`modules.SOURCES`, "their sources come in later PRs").

What the desktop has (read-only evidence, 2026-11-12; only `lpstat -r`, `lpstat -p -d -o`, `lpstat -l -p`,
`lpstat -v`, `lpstat -l` and `scanimage -L` were run; nothing was printed, scanned, cancelled or changed):

- **CUPS 2.4** (`cups.service`, `cups.socket` active) with one queue, a networked inkjet multifunction
  printer, set as the default destination. Its device URI is a raw `socket://<host>:9100` queue with a
  vendor PPD, so CUPS learns little from the printer itself: an idle queue says `idle` whether the printer
  is on or not, and supply levels arrive only if the backend's SNMP query gets them (`lpstat -l -p`:
  `Alerts: none`). `lpstat -p` took about 1.0 s on each of three runs; `lpstat -r` 0.01 s.
- cupsd's notifiers include `dbus`, and IPP's pull notifications (`ippget`) are built in. `ipptool`,
  `lpoptions`, `cupsenable`/`cupsdisable`, `cancel` and `lp` are installed; `cups-browsed` is not.
  `/usr/share/cups/data/default-testpage.pdf` is CUPS's test page.
- **SANE 1.4.0 with sane-airscan 0.99.38.** The same multifunction device is the only scanner, as an eSCL
  (AirScan) device named in `airscan.conf`: `scanimage -L` lists it as `airscan:e0:<model>`. `scanimage -L`
  took 8.2 s and 9.6 s (it asks every SANE backend), so it can't be a status query.
- `scanimage` writes PNM, TIFF, PNG or JPEG (no PDF); `--batch` writes one file per page until the feeder
  reports no more documents. `tiffcp`, `tiff2pdf` (libtiff), `pdfunite` (poppler), `zenity`, `xclip`,
  `xdg-user-dir`, `dunstify` and `avahi-browse` (avahi-daemon active) are installed. `img2pdf` and
  `ocrmypdf` are not.
- The user is in `wheel`, which CUPS's default `SystemGroup` on this distribution includes, so pausing and
  resuming a queue over the local socket should not ask for a password. Not tested: it would change the
  queue.
- The screenshot tool copies a saved file's **path** to the clipboard (`xclip -selection clipboard`) and
  says so in its notification. That is "the clipboard path" this record follows.

What barctl and barmenu give: sources (`barctl/sources/`: `follow` a stream, `gone`, `menu_rows`; the
controller restarts a source whose stream ends after `BARCTL_RETRY` seconds), tiers (`unavailable`,
`idle`, `active`, `alert`), `count`, `label`, `detail`, `target`, `barctl alert --for` (blinking),
`glyph_override` and its precedence (record 0002 §7), `barctl click`, and barmenu's providers with their
2 s query limit, `current` marks and the 8-line window (record 0001). crew has a rofi Yes/No
(`crew.life.confirm`); barmenu has none.

## Decision

Two barctl sources, `printer` and `scanner`; three barmenu providers, `printer`, `printer-queue` and
`scanner` (with two small picker menus); and one new command, `devices`, that every action row runs, so the
confirm, the words for each failure, the notifications and the privacy rule live in one place and are
tested there.

### 1. The modules and their tiers

Each is a polybar `custom/ipc` module (`hook-0 = barctl render printer`), `display = "icon"` (glyph, then
the count when above 0), `source = "printer"` or `"scanner"` in `modules.toml`.

**printer** (the default queue; the label and detail name the reason):

| Tier | When | Glyph the source sets | Count | Label (detail adds more) |
|---|---|---|---|---|
| `idle` | Default queue accepting, not stopped, no jobs, printer reachable | md-printer U+F042A | none | `ready` |
| `active` | A job is printing, or jobs are waiting on a reachable, running queue | md-printer U+F042A | jobs not finished | `printing`, `2 waiting` |
| `alert` | Queue paused (stopped) or not accepting; a held job; a job stopped by the backend; a state reason of `media-empty`, `media-jam`, `media-needed`, `cover-open`, `door-open`, `marker-supply-empty`/`-low`, `toner-empty`/`-low`, `marker-waste-full`, `offline-report`; or jobs waiting while the printer can't be reached | md-tray_alert U+F1295 for paper, md-water_alert U+F1502 for ink or toner, md-printer_alert U+F042C for the rest | jobs not finished | `paused`, `out of paper`, `ink low: cyan`, `1 held`, `not reachable, 2 waiting` |
| `unavailable` | The printer can't be reached and nothing waits (off, or on another network); no queue; cupsd not answering | md-printer_off U+F0E5D (away), md-printer_off_outline U+F1785 (no CUPS, no queue) | none | `away`, `no printer`, `CUPS not running` |

- An alert that appears (it wasn't there on the last read) also runs `barctl alert printer --for 10s`, so
  the module blinks once; a standing alert does not keep blinking.
- `low` supply reasons alert only once per supply per day (a low cartridge lasts weeks), then show in the
  detail with the tier back to `idle`. Empty, jam, paper and paused always alert.
- `target` is the default queue's name, for `{target}` in clicks.

**scanner** (the configured scanner, §4):

| Tier | When | Glyph | Count | Label |
|---|---|---|---|---|
| `idle` | Found and idle | md-scanner U+F06AB | none | `ready`; `feeder loaded` when the scanner says so |
| `active` | A scan is running | md-scanner U+F06AB | pages so far | `scanning`, `scanning page 3` |
| `alert` | The last scan failed (jam, cover open, feeder empty when asked for the feeder, busy, I/O error), until the next scan or 10 minutes; the configured scanner not found while the network it lives on is up; the scanner reports a jam or open door | md-tray_alert U+F1295 (feeder, paper, jam), md-scanner_off U+F090A (not found) | none | `feeder jammed`, `not found`, `scan failed: busy` |
| `unavailable` | SANE missing, no scanner configured or ever found, or the device is away (its network isn't this one) | md-scanner_off U+F090A | none | `away`, `no scanner` |

**Glyphs.** Each source sets a glyph by reason, as the volume source does by level, and the module's
`glyph` is md-printer / md-scanner (shown before the first write). Through `glyph_override` (record 0002
§7), the dotfiles choose the icons for `idle`, `active` and `unavailable` in their own `modules.toml` and
leave `alert` out, so the reason's glyph (paper, ink, not found) shows; a string override would hide it
(open question 6). All codepoints above and in §5-§6 are Material Design Icons names from Nerd Fonts'
`glyphnames.json`, each checked present in the installed Symbols Nerd Font and Symbols Nerd Font Mono
(fontTools, 2026-11-12).

### 2. How state is learned: events first

A shared, stdlib-only package `desktop_tools/devices/` holds the readers both the sources and the
`devices` command use: `ipp.py` (a minimal IPP client), `cups.py`, `sane.py`, `escl.py`, `mdns.py`.

**Printer.**

1. **IPP to the local cupsd**, never `lpstat` text: a small IPP/1.1 encoder and decoder over HTTP to the
   CUPS socket (`CUPS_SERVER` when set, else `/run/cups/cups.sock`, else `localhost:631`), about 200 lines
   of stdlib. `CUPS-Get-Printers` and `CUPS-Get-Default` give each queue's `printer-state`,
   `printer-state-reasons`, `printer-is-accepting-jobs`, `device-uri`, `marker-names`, `marker-levels`,
   `marker-low-levels`; `Get-Jobs` (`which-jobs=not-completed`, attributes `job-id`, `job-state`,
   `job-state-reasons`, `job-originating-user-name`, `time-at-creation`; no `job-name` here) gives the
   count. lpstat's text is localised and slow (1 s here); IPP gives the same in structured fields.
2. **Events: an IPP pull subscription.** On start the source makes one `Create-Printer-Subscriptions` on
   `ipp://localhost/` with `notify-pull-method = ippget`, events `printer-state-changed`, `printer-added`,
   `printer-deleted`, `printer-modified`, `job-created`, `job-state-changed`, `job-completed`, and a
   one-hour lease. It then loops on `Get-Notifications` with `notify-wait = yes`: cupsd holds each request
   until an event arrives or for up to the interval it states (`notify-get-interval`), so the source wakes
   on events, not on a timer. Any event re-reads the state (debounced 0.5 s, so a burst is one read). The
   lease is renewed (`Renew-Subscription`) every 30 minutes and cancelled (`Cancel-Subscription`) when the
   source stops; a crashed source's subscription lapses within the hour. A subscription is cupsd's own
   bookkeeping, not a printer or queue setting.
3. **Fallback: poll.** If the subscription can't be made (cupsd refuses, or the subscription limit is
   reached), the source polls the same IPP reads: every 30 s with no jobs, every 5 s while jobs are
   unfinished. The detail says `polling: CUPS refused a subscription` and `barctl doctor` shows it.
4. **Reachability (network queues only).** CUPS can't tell an idle raw-socket printer from a switched-off
   one, so the source watches DNS-SD: `avahi-browse -p -r -k _ipp._tcp _printer._tcp _pdl-datastream._tcp`
   as a stream (`+` and `=` lines add, `-` lines remove); a queue whose device URI host matches a resolved
   service is reachable. When avahi says nothing about the host (DNS-SD off on the printer, or a
   different subnet), a TCP connect to port 631, then 80, with a 1 s timeout, at most every 5 minutes idle
   and every 60 s while jobs wait. **Never port 9100**: a connection to a raw print port can feed a blank
   page. Two failures in a row are needed to call it unreachable (no flapping on a printer waking up).
5. **Asleep, or another network.** A sleeping printer still answers DNS-SD (or a sleep proxy does) and
   wakes on a connection, so asleep is `idle`. A host that doesn't resolve, or a network with none of the
   printer's services, is `away` (`unavailable`, grey), not an alert, unless jobs are waiting: those make
   it `alert`, `not reachable, 2 waiting`, because they will print later, perhaps somewhere unexpected.
6. **Local or network:** from the device URI's scheme: `usb`, `parallel`, `serial`, `hp` (USB), `file`
   are local; `socket`, `ipp`, `ipps`, `http(s)`, `lpd`, `smb`, `dnssd`, `implicitclass` are network. A
   local printer's reachability is CUPS's own (`offline-report`, a USB device gone is a backend error).

**Scanner.** SANE has no events and `scanimage -L` takes 8-10 s, so discovery and status are separate.

1. **Which scanner.** A setting, `DESKTOP_TOOLS_SCANNER` (a SANE device name such as `airscan:e0:<name>`),
   else the last one the user picked from the menu (§6), else the first from discovery. Discovery
   (`scanimage -L`, 15 s limit) runs at source start, from the menu's `Find scanners` row, and when DNS-SD
   reports a new scanner, never on a timer more than hourly.
2. **Presence, by events.** For network scanners, `avahi-browse -p -r -k _uscan._tcp _uscans._tcp` as a
   stream (eSCL's DNS-SD types; sane-airscan finds scanners the same way): the configured scanner's
   service appearing or going changes `found`/`away` at once. For a USB scanner, `udevadm monitor --udev
   --subsystem-match=usb` lines trigger a re-check with `scanimage -L` (debounced 2 s). A scanner named in
   `airscan.conf` by address (as here) and not advertised is checked with one HTTP `GET` of its eSCL
   `ScannerStatus` (below) at start and at most every 10 minutes.
3. **Status, for eSCL scanners: `GET <base>/eSCL/ScannerStatus`**, read-only HTTP (base from the DNS-SD
   record or `airscan.conf`), 3 s timeout with one retry (a sleeping scanner wakes slowly). It gives
   `pwg:State` (`Idle`, `Processing`, `Testing`, `Stopped`, `Down`) and `scan:AdfState`
   (`ScannerAdfLoaded`, `ScannerAdfEmpty`, `ScannerAdfJam`, `ScannerAdfDoorOpen`, …). It is asked when the
   menu opens, every 2 s while a scan of ours runs, and on DNS-SD changes; never on a plain timer when
   idle. Non-eSCL backends have no status: their tier comes from presence and our own scans' results.
4. **Our own scans** (§5) write their progress to `$XDG_RUNTIME_DIR/desktop-tools/devices/scan.json`
   (pages so far, phase, result word). The source reads that file every 1 s only while the scan's lock
   (§5) is held, then once at the end: the one writer of the module stays the source (one owner per
   module).
5. The source's `commands` (for `barctl doctor`) are `avahi-browse` and `scanimage`; without avahi it
   falls back to the 10-minute status check and discovery on demand, and says so in `doctor`.

**Load limits.** Printer: one held IPP request to the local cupsd at a time; reads at most two a second;
TCP probes at most every 60 s, only for network queues avahi says nothing about. Scanner: no network
traffic while idle except DNS-SD (multicast the daemon already does) and at most one status `GET` per 10
minutes for an unadvertised scanner; `scanimage -L` never more than hourly unless asked. Neither source
holds a device open or prevents sleep.

### 3. The menus: rows

Right-click on either module runs `barctl click <module> right`, which runs `barmenu printer` or
`barmenu scanner` (clicks in `modules.toml`, record 0002 §1's pattern). Each provider makes one read
(2 s limit), and with it unreadable still gives its rows, unmarked, with labels that name no state.

**`barmenu printer`** (`[menus.printer]`, glyph md-printer, title `Printer`, side `left`):

| # | Glyph | Label | Runs | Confirm |
|---|---|---|---|---|
| 1 | md-format_list_bulleted U+F0279 | `Queue: 2 jobs…`, `Queue: empty…` | `barmenu printer-queue` | none |
| 2 | md-pause U+F03E4 / md-play U+F040A | `Pause printing` / `Resume printing` (by state; `Pause or resume…` unreadable) | `devices printer pause` / `resume` | none: both undo each other |
| 3 | md-star U+F04CE | `Default: <queue>…` (shown when there are two or more queues) | `barmenu printer-default` (one row per queue, the default marked; picking runs `devices printer default <queue>`) | none |
| 4 | md-file_document U+F0219 | `Print a test page…` | `devices printer test-page` | **yes**: it uses paper and ink |
| 5 | md-lan U+F0317 or md-printer_wireless U+F0A0B (network), md-printer U+F042A (local) | `Network printer: reachable` / `Network printer: away` / `USB printer` (with `ink low: cyan` when set) | a notification with the full state: queue, default or not, local or network, reachable, accepting, paused, reasons in words, supply levels in percent, job count | none (read-only) |
| 6 | md-printer_settings U+F0707 | `Printer settings` | `system-config-printer` (the old launcher) | none |

With one queue, row 3 is left out (five rows). `printer-queue`:

| Row | Label | Runs | Confirm |
|---|---|---|---|
| one per unfinished job, newest first, up to 6 | `#123  printing  3 min ago` / `#124  waiting` / `#125  held` | `devices printer cancel 123` | **yes**: `Cancel job 123?` |
| when there are 2 or more | `Cancel all my jobs (4)…` | `devices printer cancel --all` | **yes**: `Cancel 4 jobs?` |
| when there are none | `No jobs` | nothing | none |

A job row shows its number, state and age, not the document's name (open question 4); more than six jobs
show as six and `…and 3 more` (a no-op row). Jobs of other users are listed without a cancel (cupsd would
refuse them; this is a one-user desktop).

**`barmenu scanner`** (`[menus.scanner]`, glyph md-scanner, title `Scanner`, side `left`), eight rows at
most:

| # | Glyph | Label | Runs | Confirm |
|---|---|---|---|---|
| 1 | md-tray_arrow_up U+F011D | `Scan from feeder` (`(loaded)` / `(empty)` when the scanner says) | `devices scan feeder` | none |
| 2 | md-file_document_multiple U+F1517 | `Scan from feeder, both sides` (only when the scanner offers a duplex source) | `devices scan duplex` | none |
| 3 | md-image_area U+F02EB | `Scan from flatbed` | `devices scan flatbed` | none |
| 4 | md-tune U+F062E | `Preset: Document (300 dpi, grey, PDF)…` | `barmenu scanner-presets` | none |
| 5 | md-folder_open U+F0770 | `Save to: Documents/Scans…` (home shown as nothing; never a full path in the label) | `barmenu scanner-folders` | none |
| 6 | md-eye U+F0208 | `Preview in Simple Scan` | `simple-scan` (the old launcher) | none |
| 7 | md-content_copy U+F018F | `Copy last scan's path` (only when there is one this session) | `devices scan copy-last` | none |
| 8 | md-file_pdf_box U+F0226 | `Open last scan` (same) | `devices scan open-last` | none |

Not found: rows 1-3 become one `Find scanners…` row (md-scanner_off), which runs discovery and a
notification with what it found; the other rows stay. With two or more scanners found, row 6 becomes
`Scanner: <model>…` (`barmenu scanner-devices`, the chosen one marked) and Simple Scan moves to the
scanner-devices menu's last row.

`scanner-presets`: one row per preset, the chosen marked, then `Format: PDF` / `PNG` / `JPEG` rows (the
chosen marked). The presets (built in; the dotfiles may add more in a `[devices.scan.presets]` table of
the desktop-tools config later, not in this record):

| Preset | Resolution | Mode | Format |
|---|---|---|---|
| Document (default) | 300 dpi | grey | PDF |
| Colour document | 300 dpi | colour | PDF |
| Text, smallest | 300 dpi | black and white (lineart) | PDF |
| Draft | 150 dpi | grey | PDF |
| Photo | 600 dpi | colour | PNG, flatbed suggested |

A preset sets the format too; picking a format afterwards overrides it until another preset is picked.
`scanner-folders`: `Documents/Scans` (default: `$(xdg-user-dir DOCUMENTS)/Scans`, made on first scan),
`Desktop`, `Downloads`, `Choose a folder…` (zenity's folder picker); the chosen one marked. The choice, the
preset and the format are remembered in `$XDG_STATE_HOME/desktop-tools/devices/scan.json`.

A confirm is crew's rofi Yes/No, moved to `common/confirm.py` (crew then imports it from there; no change
to how crew looks). Every confirm defaults to No. **Confirmed:** cancel a job, cancel all, test page.
**One click:** pause, resume, default printer, every scan (a scan uses no paper; a stray one leaves a file
and a notification), preset, folder, copy, open, settings, Simple Scan.

### 4. The `devices` command

A new console script in this package (no name clashes on `PATH` or in the dotfiles, checked 2026-11-12):

```text
devices printer status [--json]                  read-only; anyone
devices printer pause|resume [<queue>]           cupsdisable / cupsenable (default queue)
devices printer default <queue>                  lpoptions -d <queue> (the user's default, no admin)
devices printer cancel <job-id> | --all [--yes]  cancel <id> / cancel -u <me> <queue>; asks unless --yes
devices printer test-page [<queue>] [--yes]      lp -d <queue> …/default-testpage.pdf; asks unless --yes
devices scanner status [--json]                  read-only; anyone
devices scanner find                             scanimage -L (15 s), notification with the result
devices scan feeder|duplex|flatbed [--preset P] [--format F] [--to DIR]
devices scan copy-last | open-last
```

- Each action notifies its result in words (`Printing paused`, `Job 123 cancelled`, `Saved 3 pages`,
  `Not allowed: CUPS wants an administrator`) with `dunstify -a printer|scanner`, and exits 0, 1 (the
  device or CUPS refused; the words say why) or 2 (usage), as the other tools do.
- `--yes` exists for tests and keybindings; menu rows never pass it, so the confirm is in the command,
  wherever it is run from.
- The default printer is the user's (`lpoptions -d`, written to `~/.cups/lpoptions`), not the system's
  (`lpadmin -d`, which needs an administrator). `CUPS-Get-Default` answers the system default, so the
  reads honour `~/.cups/lpoptions` first, as `lp` does.

### 5. Scanning: feeder, flatbed, pages and the PDF

- **Source.** sane-airscan names its sources `Flatbed`, `ADF` and `ADF Duplex` (other backends differ:
  `Automatic Document Feeder`, `ADF Front`, `ADF Duplex`, …). The source list is read once per scanner
  with `scanimage -d <device> -A` (it opens the device and lists its options; nothing is scanned) and
  cached in the runtime folder until the scanner is rediscovered. `feeder` picks the first source matching
  `ADF|Feeder` and not `Duplex|Back`; `duplex` the first matching `Duplex`; `flatbed` the first matching
  `Flatbed|Platen`. The scan passes `--source "<that name>"`. A source the scanner lacks is a usage error
  in words (`This scanner has no duplex feeder`); the menu row is not offered.
- **A scan** runs `scanimage -d <device> --source <src> --resolution <dpi> --mode <Color|Gray|Lineart>
  --format=tiff --batch=<tmp>/p%03d.tif` for a feeder, or `--output-file <tmp>/p001.tif` for the flatbed,
  where `<tmp>` is a `0700` folder under `$XDG_RUNTIME_DIR/desktop-tools/devices/` (RAM, never the target
  folder, so a failed scan leaves no partial file there). Mode names come from the same `-A` cache.
- **Multi-page assembly.** A feeder scan ends when the scanner reports `Document feeder out of documents`
  (SANE's `NO_DOCS`), which is success when at least one page was scanned. Then for PDF: `tiffcp` joins
  the pages into one multi-page TIFF and `tiff2pdf` writes the PDF (`-j -q 85` for colour and grey,
  lossless for black and white). For PNG and JPEG each page is converted to its own file (`magick`;
  `p001.png`, … in a folder named after the scan). The result is moved into the target folder as
  `scan-YYYY-MM-DD-HHMMSS.pdf` (never overwriting: `-2`, `-3` appended), then the temporary folder goes.
  No new Python dependency: libtiff's tools and ImageMagick are already installed (`contrib/system-packages.txt`
  gains `libtiff` and `imagemagick` as runtime packages).
- **One at a time.** A lock file in the runtime folder: a second scan while one runs notifies `A scan is
  already running` and does nothing. A scan can be stopped from its progress notification's `Stop`
  action (SIGTERM to `scanimage`, then the temporary folder goes).
- **When done:** `dunstify -a scanner -A open,Open -A folder,"Show folder" "Scan saved" "3 pages, PDF, in
  Documents/Scans"`; `Open` runs `xdg-open <file>`, `Show folder` `xdg-open <folder>`. The file's **path is
  copied to the clipboard** (`xclip -selection clipboard`, as the screenshot tool does) and the
  notification says so (open question 8).
- **Preview** stays Simple Scan's job (row 6): it previews and crops, which a bar menu can't.
- **Failures, as words** (from `scanimage`'s SANE status line, read with `LC_ALL=C` set for that child so
  the text is SANE's English, and from eSCL's state when known):

| What scanimage or the scanner says | Shown as | Tier afterwards |
|---|---|---|
| `Document feeder out of documents` with 0 pages | `The feeder is empty: load the pages and scan again` | `alert` 10 min (or until the next scan) |
| `Document feeder jammed`, `ScannerAdfJam` | `The feeder is jammed: clear it, then scan the rest` (and how many pages were saved, if any; those are kept) | `alert` |
| `Scanner cover is open`, `ScannerAdfDoorOpen` | `The scanner's cover is open` | `alert` |
| `Device busy` | `The scanner is busy (in use from its panel or another computer)` | `alert` 10 min |
| `Error during device I/O`, a timeout, the device gone mid-scan | `Lost the scanner mid-scan; N pages saved` | `alert` |
| `Invalid argument` (a mode or resolution the scanner lacks) | `This scanner can't do <preset>: pick another preset` | `idle` |
| No device answering at the start | `The scanner can't be reached` | `alert` or `unavailable` per §2 |

- **Printer failures** in words: queue paused, `media-empty` (`out of paper`), `media-jam` (`paper jam`),
  `cover-open`/`door-open`, supply empty/low per marker name, `offline-report` (`printer offline`), a job
  `stopped` by the backend (`the printer refused the job; the queue may be paused`), `client-error-not-authorized`
  on pause/resume/test page (`Not allowed: CUPS wants an administrator; use Printer settings`), and cupsd
  not answering (`CUPS is not running`).

### 6. Clicks

| Module | Left | Middle | Right | Scroll |
|---|---|---|---|---|
| printer | `barmenu printer-queue` | `system-config-printer` (the old launcher) | `barmenu printer` | nothing |
| scanner | `devices scan` with the remembered preset, from the feeder when the scanner says it is loaded, else the flatbed | `simple-scan` (the old launcher) | `barmenu scanner` | nothing |

- Scroll does nothing on either: a stray scroll should not change a default or page through a queue.
- A scanner that can't say whether its feeder is loaded (non-eSCL) scans from the flatbed on left-click.
- The old launchers become the middle-click and the menus' `Printer settings` and `Preview in Simple Scan`
  rows, so nothing they did is lost.

### 7. The environment rule and privacy

- barctl, barmenu and `devices` never set, clear or change `COORDINATOR`, `CLAUDECODE` or `TESSERA_ACTOR`;
  they pass to every child untouched (record 0002 §6).
- `devices`'s acting verbs (pause, resume, default, cancel, test-page, every scan) **refuse with exit 3
  when `COORDINATOR` or `CLAUDECODE` is set**: `An agent may not operate the printer or scanner`. Reading
  a variable is not setting it. `status`, `find`, the sources and the menus' reads stay anyone's. A bar
  started from an agent's session (tainted, record 0002 §6) therefore shows its menus but each action
  says why it won't run.
- **Privacy:** no document name, job title, file name, path, device URI, hostname or address reaches a
  log, the journal (record 0017 lines), `barctl status`'s fields or `doctor`. They carry counts, states,
  tiers, reason words, local/network and a job number. The job title is never read from CUPS (§2.1 asks
  without `job-name`). The scan's file name is shown only in its own notification and copied on purpose.
  No scanned page is kept outside the chosen folder.

### 8. What changes where

**desktop-tools (this repository):**

- `devices/` (readers, the IPP client, scan runner), `barctl/sources/printer.py` and `scanner.py`,
  `"printer"` and `"scanner"` added to `modules.BUILT` and `sources.SOURCES`;
  `barmenu/providers/printer.py`, `printer_queue.py`, `scanner.py` (and the picker menus);
  `[menus.printer]`, `[menus.printer-queue]`, `[menus.printer-default]`, `[menus.scanner]`,
  `[menus.scanner-presets]`, `[menus.scanner-folders]`, `[menus.scanner-devices]` in `menus.toml`;
  `common/confirm.py` (moved from crew); the `devices` console script; settings `DESKTOP_TOOLS_SCANNER`,
  `DESKTOP_TOOLS_SCAN_DIR` through `config.SETTINGS`.
- The packaged `modules.toml` gains `printer` and `scanner` modules with their clicks.
- Wiki: CLI-Reference (`devices`, regenerated), In-Depth-Configuration (the two sources, settings,
  presets), Architecture-Internals (the IPP client, subscriptions, DNS-SD, the scan runner), Security (the
  agent refusal, privacy, port 9100), Troubleshooting (`polling: CUPS refused a subscription`, `Not
  allowed`, a scanner `away`), Testing-Guide (the stubs and fakes).

**dotfiles (their own PR):** new `polybar/modules/printer.ini` and `scanner.ini` (`custom/ipc`, `hook-0 =
barctl render …`, the four clicks through `barctl click`); `[modules.printer]` and `[modules.scanner]` in
`barctl/modules.toml` with `glyph_override` for `idle`, `active` and `unavailable`; the new modules in
`bars/main` beside the old ones (§10); and a pinned desktop-tools release. `device.ini` keeps
`device-bluetooth`.

### 9. Tests

Every test uses stubs; **none touches a real printer, queue or scanner**. A `devices_guard` fixture,
autouse in the devices, source and provider tests: `PATH` holds only the stub folder for `lpstat`, `lp`,
`cancel`, `cupsenable`, `cupsdisable`, `lpoptions`, `lpadmin`, `scanimage`, `simple-scan`,
`system-config-printer`, `tiffcp`, `tiff2pdf`, `magick`, `avahi-browse`, `udevadm`, `xclip`, `xdg-open`,
`dunstify`, `zenity`; `CUPS_SERVER` points at a fake IPP server on a Unix socket in `tmp_path`; and
`socket.connect` is patched to fail the test on `/run/cups/cups.sock`, port 631, 80 or 9100 of anything
but the fake. Each stub records its argv; `lp`, `cancel`, `cupsenable`/`cupsdisable` and `scanimage` stubs
fail the test if reached without the test asking for them.

Unit:

- IPP codec: encode/decode round trips; each operation's request bytes against fixtures; the fake
  server's answers for states, reasons, markers, jobs, `Get-Notifications` with and without events, a
  refused subscription (poll fallback).
- printer source: the tier table row by row (§1); the once-a-day low-supply alert; reachable/away/away
  with jobs; DNS-SD add and remove lines; the TCP probe only on 631/80, two failures before unreachable;
  debounce; lease renewal and cancel on stop; no `job-name` in any request.
- scanner source: found/away by DNS-SD lines; eSCL `ScannerStatus` XML fixtures (idle, processing, ADF
  loaded, empty, jam, door open, down); the 10-minute cap; progress from `scan.json` only while the lock is
  held.
- scan runner, with a fake `scanimage` that writes N TIFF pages then prints a chosen SANE status: 0, 1 and
  5 pages; jam after 2 (2 kept); busy; cover open; invalid argument; source selection from `-A` fixtures
  of sane-airscan and two other backends; PDF assembly argv; PNG/JPEG per page; name collisions; the lock;
  stop; the clipboard and notification argv; the temporary folder gone afterwards in every case.
- providers: rows and marks for each state; unreadable state; one queue (no default row); 0, 1, 7 jobs;
  duplex row only with a duplex source; not found; two scanners.
- `devices`: every verb's argv; confirms asked for cancel and test page and not for the others; `--yes`;
  exit 3 under `COORDINATOR` or `CLAUDECODE` for acting verbs and not for `status`; no variable set or
  cleared in any child's environment.
- Privacy: run every path with a job title, file name and host containing a marker string, capture the
  journal fields (`journal.run`'s sender stubbed) and `barctl status --json`: the marker appears in none.
- `common/confirm.py`: crew's existing confirm tests pass unchanged against the moved function.

**Needs the real device; cannot be tested here without hardware.** These are attempted only by Stephen,
by hand, after the dotfiles PR, and the record's build PR lists them as a checklist:

- that sane-airscan offers this scanner `ADF` and whether it offers `ADF Duplex`;
- a real multi-page feeder scan ending in `NO_DOCS`, a real jam, an open cover, an empty feeder;
- the eSCL `ScannerStatus` fields this scanner actually sends (`AdfState` values vary by vendor);
- sleep and wake timing (does the first status `GET` after sleep need the retry);
- cupsd accepting the pull subscription and delivering events for this raw-socket queue; pause and
  resume without a password; supply levels (likely none on a `socket://` queue: open question 7);
- `devices printer test-page` printing one page.

An opt-in integration test (`RUN_INTEGRATION=1`, marked) does only reads against the real cupsd
(`CUPS-Get-Printers`, `Get-Jobs`) and never a subscription, a job or a scan.

## Alternatives considered

- **Parse `lpstat` on a timer.** Simple, but localised text, 1 s a call here, and a poll. Kept only as the
  shape of the fallback's cadence; the fallback itself reads IPP.
- **cupsd's D-Bus notifier** (`notify-recipient-uri = dbus://`, then follow the signals). Events, but
  listening to the system bus's broadcast signals needs `dbus-monitor` or a D-Bus library; the monitor
  interface needs privileges on the system bus, and a library is a new dependency. Lost to IPP pull
  notifications, which need only HTTP to the local socket.
- **pycups** (the `cups` Python binding). Full API, but a C extension built against libcups (a build
  dependency for the uv tool install), and unneeded for six IPP operations. Lost.
- **`scanimage -L` as the scanner's status.** 8-10 s and every backend probed. Lost to DNS-SD and eSCL
  status.
- **A `[[modules.<m>.menu]]` static menu in barctl** (barctl's own right-click). No state, no confirm, no
  submenus. Lost to barmenu providers, as in record 0002.
- **Rows that run `cancel`, `lp`, `scanimage` directly.** No confirm, no words for failures, no place for
  the agent refusal or the privacy rule. Lost to the `devices` command.
- **One combined `devices` module** (printer and scanner in one capsule, the same multifunction device).
  Fewer pixels, but they fail separately (the scanner can be found while the queue is paused, and a USB
  printer with a network scanner is common) and their actions differ. Lost; two modules, side by side.
- **Probe reachability on port 9100.** Most direct for a raw queue, but some printers feed a page per
  connection. Never.
- **Assemble PDFs with ImageMagick alone, or add `img2pdf`.** ImageMagick's PDF writer recompresses and
  its policy files on some systems block PDF; `img2pdf` is not installed and would be a new system
  package. Lost to `tiffcp` + `tiff2pdf`, already installed.
- **Scan into the target folder directly.** A failed or stopped scan would leave a partial file there.
  Lost to the RAM temporary folder.

## Consequences

- Two more barctl sources, each a long-lived thread: the printer's holds one HTTP request to cupsd, the
  scanner's one `avahi-browse` child. Each menu open costs one IPP read (a few ms) or one eSCL `GET`.
- One new command, `devices`, and a shared confirm in `common/`. crew's confirm moves; its behaviour does
  not.
- The desktop gains a dependency on avahi for live reachability; without it both modules still work,
  with slower presence checks, and `doctor` says so.
- **Rollout, alongside the old buttons first.** Build order: (1) this repository: devices, sources,
  providers, `devices`, tests, wiki, a release; nothing changes on the bar. (2) The dotfiles PR adds
  `printer` and `scanner` to `bars/main` **next to** `device-printer` and `device-scanner`, which stay as
  they are. (3) Stephen uses both for a while (open question 9) and runs the hardware checklist (§9).
  (4) A second dotfiles PR removes `device-printer` and `device-scanner` from `bars/main` and
  `device.ini`; `device-bluetooth` stays.
- **Rollback:** remove the two modules from `bars/main` and `barctl disable printer scanner` (their sources
  stop and cancel their CUPS subscription; any left lapses within an hour); the old buttons are still
  there until step 4, and after it are restored by reverting that PR. Settings in
  `$XDG_STATE_HOME/desktop-tools/devices/scan.json` and scans already saved stay; nothing else is stored.
  An older desktop-tools ignores the two modules' sources it doesn't know (`doctor` names them).
- **Bluetooth is out of scope.** The `device-bluetooth` button (`bt menu`) and the `bluetooth-status`
  module are unchanged here. The Bluetooth and audio integration belongs to the player-capsule record
  (0003, "The player capsule: one 'now playing' module on the bar", its §10 "Output and Bluetooth in the
  same unit"), which keeps `device-bluetooth` as the device launcher beside printer and scanner and plans
  a Bluetooth source later (its idea 6); this record touches nothing it owns. The overlap: both records add
  barctl sources and barmenu providers in the same release train and both change `bars/main`; the
  `device-*` group on the left ends as `device-bluetooth`, `printer`, `scanner`. A later Bluetooth source
  could reuse this record's DNS-SD-free pieces (the `devices` command's confirm and notification
  helpers). Whichever is built second rebases on the first's `modules.toml` and `bars/main` changes.

## Open questions

1. **How the printer's state is learned.** (a) IPP to the local cupsd with a pull subscription
   (`ippget`), polling IPP as the fallback; (b) cupsd's D-Bus notifier; (c) `lpstat` every 10-30 s.
   Recommendation: **(a)**: events with no new dependency and no system-bus privileges, structured fields,
   and the reads are fast where `lpstat -p` took 1 s.
2. **Reachability of a network printer.** (a) DNS-SD events, then a TCP probe of 631/80 at most every 5
   minutes, never 9100; (b) CUPS's view only (no reachability); (c) ICMP ping. Recommendation: **(a)**:
   CUPS can't tell an idle raw-socket printer from an off one, and ping needs a raw socket or a setuid
   tool and says nothing about the printing service.
3. **What happens to the old launchers.** (a) Middle-click and a menu row each, removed from the bar
   after the trial; (b) kept as separate buttons. Recommendation: **(a)**: one button per device, nothing
   lost.
4. **Job names in the queue menu.** (a) Job number, state and age only; (b) also the job's title,
   truncated, on screen only (read from CUPS when the menu opens, never logged). Recommendation: **(a)**:
   the brief's privacy rule is easiest kept by never reading the title; on a one-user desktop the newest
   job is almost always the one to cancel. (b) is a small change if it is missed.
5. **Left-click on the scanner.** (a) A one-click scan with the remembered preset (feeder when loaded,
   else flatbed); (b) open the menu (as right); (c) Simple Scan (the old behaviour). Recommendation:
   **(a)**: it is the action asked for most, and a stray click costs a file and a notification, no paper.
   Printer left-click: the queue menu (no alternative is safer and as useful).
6. **Glyph overrides for the two modules.** (a) The dotfiles override `idle`, `active` and `unavailable`
   and leave `alert` to the source's reason glyphs; (b) override all four tiers (one alert glyph for
   every reason); (c) no override, the sources' glyphs throughout. Recommendation: **(a)**: the dotfiles
   own the look, and the alert glyph says paper, ink or not found at a glance.
7. **The printer queue's driver.** The queue is a raw `socket://` queue with a vendor PPD, so CUPS sees
   no paper, ink or jam state from the printer; an IPP Everywhere (driverless, `ipp://` or `ipps://`)
   queue for the same printer would report them. (a) Leave the queue alone; this record works with what
   CUPS reports and the alerts for paper and ink appear only if they arrive; (b) Stephen re-adds the
   printer as a driverless queue (his change, a live printer setting this record does not make).
   Recommendation: **(b), as a separate step after this ships**: it is what makes the alerts real, but it
   changes print output (driver differences) and is his to try; the modules handle either queue.
8. **The scan and the clipboard.** (a) The file's path copied as text on every scan, as the screenshot
   tool does, plus the `Copy last scan's path` row; (b) copied only from the row; (c) copied as a file
   (`text/uri-list`), so it pastes into a browser upload or a file manager. Recommendation: **(a)**: the
   same habit as screenshots; (c) can be a second row later if pasting into upload dialogs is wanted.
9. **The trial.** (a) Both sets of buttons for about a week, then the old ones go in their own PR; (b)
   replace at once. Recommendation: **(a)**, as Stephen asked: the new buttons run next to the old, and the
   hardware checklist (§9) is done before the old ones go.
10. **Agents and the devices.** (a) `devices`'s acting verbs refuse under `COORDINATOR` or `CLAUDECODE`;
    (b) no refusal, agents could scan or cancel. Recommendation: **(a)**: a scan or a cancelled job is a
    physical-world act that should be Stephen's click, and the refusal reads the variables without setting
    them, as the environment rule requires.
11. **Duplex.** (a) A `both sides` row only when the scanner offers a duplex source; (b) also a manual
    duplex (scan fronts, flip the stack, scan backs, interleave: `--batch-double`). Recommendation:
    **(a)** now: (b) is a good later addition for single-sided feeders, but it needs a two-step prompt and
    can only be tried with the device.

## Change log

| Date | Change |
|---|---|
| 2026-11-12 | Proposed by the desktop coordinator |

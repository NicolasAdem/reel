# reel — overview

A single map of what reel is, what it does today, how it's built, and where it's
going. Read this first; details live in `README.md` (use) and `ROADMAP.md` (next).
(The brand is always lowercase: it's "reel", never "Reel".)

---

## The mission (one line)
Plug something in → reel copies the **whole drive** onto your PC, verbatim (every
folder, every file, every name), then tidies the file names. Automatically. Locally.
No questions. **Copy first, forget nothing; rename last.** reel is *not* a media
player, a cloud service, or a thing you babysit.

## Where we are
- **Version:** 3.2.0
- **Status:** working and tested (recorder + simulated USB drives). Fully local.
- **Platform:** Windows-first (also runs on macOS/Linux for the core).
- **Hands-off is the only mode:** `reel setup` installs the at-login watcher; on
  plug-in a window pops up, shows the copy with progress bars, minimises when done,
  and closes on unplug.
- **The library lives in `Documents/reel`** and reel *follows it if you move it*.

## What it does today
The flow: **detect → copy the whole drive verbatim → rename in place**, with instant
auto-copy. Two phases, in that order — the complete copy always lands before any rename.

- **Detects any removable drive** the moment it mounts — the Sony ICD-UX570 (by label
  or its `REC_FILE` folder) and any USB stick / camera card. System & optical drives
  are excluded.
- **Copies automatically, no prompts.** Plug in, it copies — recorder, stick, SD card,
  anything that mounts.
- **Copies every file and folder, verbatim**, into `Documents/reel/<drive name>/` — every
  folder (empty ones too), every file, every name, exactly as it was. The only things
  skipped are unreadable OS system folders (recycle bins, System Volume Information), and
  those are *reported*, never silently dropped. "Forget nothing" is the rule.
- **Finds its own library.** The location is tracked by a stable pointer
  (`~/.reel/location.json`) + a marker inside the library. Move the folder anywhere and
  reel searches the likely places, finds it by that marker, and updates itself. (`locate.py`)
- **Then renames — in place, last.** Once the copy is complete: recordings & photos get
  a date-first sortable name; documents, music and everything else (including dotfiles)
  keep their exact name. Folders are never moved.
- **Never copies twice:** each drive keeps its own record (`.reel/mirror/<id>.json`) of
  what it copied, by path + size + modified-time — safe, no false "duplicate" drops.
- **Auto-closes** when you unplug (in terminal mode). Mirrors to extra drives if listed.
- **Runs itself.** `reel setup` installs a hidden launcher so reel starts at login. On
  plug-in a window pops up (logo + progress bars), minimises to the taskbar when the
  copy is done, fires a toast ("copied 12 files from KINGSTON"), and closes when you
  unplug — then the watcher waits for the next drive.
- **One mode: always on.** `reel setup` installs the at-login watcher and starts it
  right away. There is no off switch and no manual mode — plugging a drive in *is*
  the interface. (The watcher's own entry points, `reel auto run` / `reel auto
  session`, exist internally but aren't user commands.)
- **Recognises moved files by content.** If a file was renamed or moved *on the
  device* (recorders renumber constantly), reel matches it to its existing copy by a
  full byte-for-byte hash and moves the copy into place — no re-copy, no duplicate,
  and never a guess.
- **Self-heals.** Delete a file from the library and reel notices its copy is gone —
  it copies it fresh on the next plug-in. The record never lies about what's on disk.
- **Puts a drive back.** The per-drive record also stores what each file was renamed
  to, so `reel transfer` rebuilds a blank stick under its *original* names and folders
  (pausing the watcher itself during the restore).
- **Commands:** `setup` (once) · `transfer [name]` · `rename on/off` (name-tidying
  toggle; on by default) · `upgrade` (self-update from PyPI; `reel --version`).

## How it's built (module map)
The engine is small and split by responsibility, so each piece stays simple:

| Module         | Job |
|----------------|-----|
| `__main__.py`  | the CLI — `setup` / `transfer` / `rename`, splash + help |
| `config.py`    | settings + sensible defaults (Documents/reel; reads optional `config.toml`) |
| `locate.py`    | finds the library — stable pointer + marker; follows the folder if you move it |
| `device.py`    | find removable drives (serial, kind hints); scan files |
| `mirror.py`    | **the engine** — verbatim copy, then rename; moved-file recognition (full hash); self-heal; per-drive record; `transfer` restore; rename toggle |
| `profiles.py`  | device kind hints + `file_kind()` (which bucket a file is, used for naming/summary) |
| `formats.py`   | filename intelligence — date templates, real-name vs serial |
| `naming.py`    | clean names: dates (EXIF/template/video-container/mtime), ID3-tag music names, fingerprint |
| `runner.py`    | orchestration — setup, loops devices, drives the progress bars + summary |
| `watch.py`     | the pop-up window's copy loop — detect plug/change/unplug, copy, close |
| `autostart.py` | the always-on machinery — resident watcher + install/run at login |
| `upgrade.py`   | `reel upgrade` — check PyPI, pip-install the latest, restart the watcher |
| `notify.py`    | zero-dep native toast after a background copy ("synced 12 files …") |
| `console.py`   | terminal voice — themed output, panels, progress |
| `branding.py`  | identity — device/file kinds, glyphs, colours |

**Key design choice:** copy first, rename last — never the reverse. The verbatim copy
is the safety net (`reel/<drive name>/` mirrors the stick exactly), so nothing is ever
at risk; renaming is a finishing pass *on that copy*, in place. Dedup is per-drive by
path + size + mtime — there's no content-hash guesswork that could drop a distinct file.
This replaced an earlier design that scattered files into `Category/Year/` buckets via a
`classify.py`/`sync.py` engine (both since removed) — simpler, and it never loses a file.

## What we're building next (priorities)
1. **Share each release** — `twine upload dist/*` to PyPI; later a standalone `.exe`
   (PyInstaller) for friends with no Python.
2. **Faster imports** — a unified parallel copy path (see ROADMAP for why *not* per-type).
3. **Instant event-driven wake** — `WM_DEVICECHANGE` listener instead of the 2–3s poll
   (latency polish; the poll is already reliable).

*Done recently:* two-way restore (2.7 — `reel transfer`); toast notifications (2.6);
the great simplification (one always-on mode, three commands); video container
dates (2.4); smart naming engine (2.3); hands-off auto-launch + pop-up window;
sync-everything; any-USB-device, one folder.

See `ROADMAP.md` for the full, ordered plan.

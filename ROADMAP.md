# Reel — roadmap

**What Reel is:** you plug something in, and it copies the whole drive onto your PC —
every folder, every file, exactly as it is — then tidies the names. Automatically,
locally, no questions. The recorder, a camera card, a USB stick, anything. A faithful
copy, never a duplicate, never a wipe.

**What Reel is not:** a media player, a cloud service, a thing you have to babysit.
Copy first, forget nothing; rename last. Everything below serves that — nothing else.

The core is deliberately small and bulletproof: **detect → copy the whole drive
verbatim → rename in place.** That order is the point — the complete copy lands before
any rename. Improvements land one at a time, core first, always.

---

## Done
- **Verbatim copy, then rename** (`mirror.py`). Plug in → the whole drive is copied into
  `Reel/<drive name>/`, every folder and file exactly as it was, *then* names are tidied
  in place. Per-drive record (`.reel/mirror/<id>.json`) dedups by path+size+mtime, so
  nothing copies twice and no distinct file is ever dropped. Replaced the old
  category-bucket engine.
- **Two-way restore** (`reel transfer`, v2.7). The per-drive record also stores what each
  file was renamed to. Lose a card → plug in a blank one → `reel transfer` rebuilds it
  under the *original* names/folders from the copy. Picks the right drive automatically
  (only one, or by label), pauses the watcher via a flag file (not a kill), never
  overwrites, then resumes.
- **Any USB device, fully automatic.** Detects any removable drive and copies it with no
  prompts. (`device.py`)
- **Copies everything, every volume.** No file-type filter anywhere — drop a `test.txt`
  on the recorder and it's copied; both recorder volumes (internal + SD) are swept; even
  empty folders and dotfiles are kept. (`mirror._walk`, `watch._device_state`)
- **Always-on by design** (`reel setup`). Installed to run hidden at login; on plug-in
  it pops open a window showing the copy (logo + progress bars), minimises it to the
  taskbar when done, and closes it on unplug — then waits for the next drive. There is
  no manual mode and no off switch — three commands total: `setup`, `transfer`,
  `rename on/off`. (`autostart.py`)
- **Smart "same file" recognition.** A file renamed/moved on the device is matched to
  its existing copy by full content hash and just moved into place — no re-copy, no
  duplicate, never a guess. Delete a file from the library and it self-heals (copies
  fresh next plug-in). (`mirror.py`)

## Now — make the renaming excellent
The copy is the core and it's solid; the renaming is the finishing touch. Giving each
copied file the *right* name — without moving it out of its folder — is the polish job.
No neural nets — we dig out the metadata that's already there.

**Shipped (v2.3):** a real naming engine (`formats.py` + `naming.py`).
- A **date format registry**: reads the timestamp baked into known filename templates
  (IC recorder `YYMMDD_HHMM`, phone `IMG_YYYYMMDD_HHMMSS`, Pixel, WhatsApp, Signal,
  screenshots, plain dates) → EXIF for photos → mtime. Most files land in the right year.
- **ID3-tag rescue for music**: a boilerplate `track03.mp3` becomes
  `Artist - Title.mp3` from its own tags; a real filename is kept.
- **Boilerplate vs real-name detection**: camera serials (`IMG520947`) get a clean
  date name; meaningful names (`Beach Sunset`, `Tax Return 2025.pdf`) are kept.
- **Video dates from container metadata** (v2.4): reads the `moov/mvhd` creation time
  from mp4/mov, so a camera clip with no name date and no EXIF still lands in the right
  year. Pure-Python box walker — seeks past `mdat`, no deps. Full date chain is now
  EXIF → filename template → video container → mtime.

**Still to do here:**
- **Optional name templates.** Let `config.toml` choose the rename pattern (e.g.
  `{date}_{original}` vs `{date}_{reel-id}`), or turn renaming off entirely for a
  pure 1:1 copy — some people want the original names untouched.
- **Better collision handling.** Today a clash appends `(2)`; offer an option to keep
  the original name when two files tidy to the same thing.

## Hands-off — refinements (core already shipped)
The watcher is live: it runs at login and copies on plug-in via a 2–3s poll that never
misses. Nice-to-haves on top:
- ✓ **Toast notifications** (v2.6) — a native "Reel — synced 12 files from KINGSTON"
  after each background sync, via the built-in WinRT notifier. **Zero dependencies**
  (`notify.py`); silent no-op if it ever fails — a toast must never break a sync.
- **Instant event-driven wake.** Replace the poll with a `WM_DEVICECHANGE` /
  `DBT_DEVICEARRIVAL` listener so it reacts the *instant* a drive mounts. Pure latency
  polish — the poll is already reliable.
- **System-tray icon** *(deliberately skipped for now)*. A persistent tray icon would
  add a dependency (or fiddly ctypes + ghost-icon management) and a message loop, for
  marginal gain over the pop-up window + toast. The art of simplicity says leave it.
- ✓ **The great simplification** — the manual tools (`sync`, `sort`, `undo`,
  `--dry-run`, `start`, `play`, `status`, `devices`, `open`) were all removed: the
  product *is* automatic, and a copy is never destructive, so there's nothing to
  undo or preview. Three commands remain: `setup`, `transfer`, `rename on/off`.

## Faster imports (later — measure first)
Speed matters, but only where the time actually goes. For a USB import the bottleneck
is almost always **how fast the *source* device gives up its bytes** (the recorder is
USB 2.0; SD cards are slow), not the destination or syscall overhead. So:
- **The one lever that matters: parallelism.** While one file is read off the drive,
  the CPU and destination sit idle. A small **multi-threaded copy pool** overlaps
  read + write + hash and is the single biggest real win — especially for *many small
  files* (photos). Build **one** good parallel copy path, not one per file type (see below).
- **Tuned buffer / large block size** on `shutil.copyfileobj` — a cheap, safe win on big
  files (video). Low risk, do early.
- **Skip compression.** lz4/zstd-in-flight only helps on *compressible* data going to a
  slow/remote target. Reel's content is mp3 / jpg / mp4 — already compressed — so
  compressing in flight is pure overhead, net *slower*. Wrong tool for this job.
- **Skip the Linux-only tricks.** `io_uring`, `O_DIRECT`, tmpfs are Linux/POSIX and
  Windows-first Reel can't use them portably. A RAM-disk destination also defeats the
  point (we want files *on disk*, durable).

**Per-type vs one algorithm?** One unified copy path. The *bytes* don't care whether
they're a photo or a doc — file type already drives **naming and sorting** (where it
belongs), not the copy itself. The only type-ish refinement worth considering later is
**size-aware**, not kind-aware: a thread pool for lots of tiny files, big sequential
buffers for a few huge ones. That's a v-next tuning, gated on actually measuring a slow
import first.

## Robustness (as it comes up)
- **USB hard drives** report as *fixed* on Windows, so they're skipped today (we only
  auto-grab removable drives, to never touch the system disk). Add an opt-in list of
  specific fixed drives to watch.
- **Big cameras:** watch re-walks each drive every tick — fine for sticks, heavier for
  a huge card. Cache by top-level mtime if it ever bites.

## Sharing it (distribution)
So a friend can actually use it. We already have `pyproject.toml`.
- **PyPI** — `pip install reel-sync`, the command stays `reel`. ~30 min of one-time
  setup (account + token, `python -m build`, `twine upload`). Updates = bump, build, upload.
- **Standalone `reel.exe`** (PyInstaller `--onefile`) for friends with no Python.
  Ideally code-signed so SmartScreen stays quiet.

---
*Add ideas here as they come. Copy the whole drive, forget nothing, keep it automatic.*

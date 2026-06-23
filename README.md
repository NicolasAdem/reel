# reel

**plug it in, copied.** reel is a fully-local tool that copies every USB drive, SD card or voice recorder you plug in — the whole thing, every folder, every file, exactly as it is — into a `reel` folder in your Documents. Then it tidies the file names. Automatically, every time, without you touching anything.

> Everything stays on your machine. Your devices are never wiped. The library is just folders — open it in Explorer any time.

---

## why this exists

Anyone can drag files off a USB stick in Explorer. Almost nobody actually does it — every time, completely, without duplicates. That's the problem reel solves:

- **It happens without you.** reel runs from login. Plug a drive in and it's copied — even when you're in a hurry, even when you forget. A backup habit you install once instead of remember forever.
- **Nothing copies twice.** Re-plug the same stick and only what's new comes over. If a file was *renamed or moved on the device* (recorders renumber files all the time), reel recognises it by its actual content — a full byte-for-byte hash, never a guess — and just moves its existing copy into place instead of copying it again.
- **Nothing gets forgotten.** Every folder (empty ones too), every file, hidden files included. The only things skipped are unreadable OS system folders (recycle bins, System Volume Information) — and those are *reported on screen*, never silently dropped. If you delete a file from your library, reel notices and copies it fresh next plug-in.
- **It follows its folder.** Move the `reel` folder anywhere — another folder, another drive — and reel finds it again and keeps going. The library's location is the most important thing reel owns, so it never loses track of it.
- **Names get tidied — structure never moves.** A recorder's cryptic `250608_1432.mp3` becomes `2025-06-08_1432_reel-7F3A.mp3`, photos get a sortable date prefix, documents keep their names — all *inside* their original folders. Don't want it? `reel rename off` gives you pure 1:1 copies.
- **It works both ways.** Lose the SD card? `reel transfer` writes the copy back onto a blank stick — original folders, original filenames, exactly as the drive was.

Explorer is a tool you have to operate. reel is a habit you install.

## what your library looks like

```
Documents/reel/
├── IC RECORDER/                  ← one folder per drive, copied verbatim
│   ├── REC_FILE/FOLDER01/2026-06-08_1432_reel-7F3A.mp3
│   └── MUSIC/…
├── KINGSTON/
│   ├── DCIM/2026-05-14_0941_IMG_0421.jpg
│   ├── Holiday/Tax Return 2025.pdf      ← documents keep their exact name
│   └── Empty Folder/                    ← even empty folders are kept
└── .reel/                               ← reel's memory (what's already copied)
```

---

## install

```
pip install reel-sync
```
(The package is `reel-sync`; the command is just `reel`.) Needs Python 3.11+.

### from this folder (development)
```
pip install -e .
```

## use it

One command, once:

```
reel setup
```

Name your reel, and it installs itself: it starts with Windows and watches quietly in the background, forever. From then on —

> **Plug a drive in →** a small window pops up and shows the copy with live progress bars. **Done →** it shows "all copied — safe to unplug", waits a moment, then tucks itself to the taskbar; a toast slides in (*"reel — copied 12 files from KINGSTON"*). **Unplug →** the window closes. The watcher keeps waiting for the next drive.

**Don't unplug while it's still copying** — wait for "all copied" first. That's the only rule.

The other commands, for when you want them:

```
reel transfer          # put a copied drive back onto a blank stick,
                       # original folders & original names (plug the stick in first)
reel rename off        # pure 1:1 copies from now on — names untouched
reel rename on         # tidy, sortable names (the default)
reel upgrade           # update reel to the latest version (also: reel --upgrade)
reel --version         # print the installed version
```

`reel upgrade` checks PyPI and updates only if there's something newer — safe to run any time. On Windows it does the install in a fresh window and restarts the background watcher on the new version automatically.

## config (optional)

reel works with no config at all — copies land in `Documents/reel`, and reel follows that folder if you move it. To pin a fixed location instead, drop a `config.toml` next to the package, in the folder you run from, or at `~/.reel/config.toml`:

```toml
[library]
sync_root = "D:/MyBackups/reel"    # pin a fixed path (turns off auto-follow)

[watch]
interval_sec = 4                   # how often it looks for a drive
close_on_unplug = true             # close the pop-up when you unplug

[ui]
theme = "dark"                     # colours for a dark terminal
```

## notes

- **Privacy:** nothing ever leaves your machine.
- **Safety:** reel only ever *reads* your devices — it never writes to or deletes from them (the one exception is `reel transfer`, which writes exactly what you asked onto the stick you plugged in, and never overwrites).
- **Honesty:** anything reel can't read, it tells you about on screen. No silent skips, ever.

---

*reel v3.2.0 — plug it in, copied.*

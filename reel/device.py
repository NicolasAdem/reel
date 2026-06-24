"""
device.py — find the Sony ICD-UX570 when it's plugged in, and read its recordings.

The UX570 mounts as a USB mass-storage drive (volume label "IC RECORDER", and
"MEMORY CARD" for the microSD). Its tree:

    REC_FILE/FOLDER01..FOLDER05   voice recordings  (.mp3 / .wav)
    MUSIC/                        music you put on the device
    PODCASTS/ (or PODCAST/)       podcast episodes

We detect a device two ways (either is enough): a matching volume label, OR a
drive that simply contains a REC_FILE folder. That second rule means it still
works even if Sony changes the label or you point it at a plain folder of notes.
"""
from __future__ import annotations

import hashlib
import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".wma", ".flac", ".ogg", ".oga", ".opus", ".aiff"}

# device subfolders -> the "source" tag the classifier uses
SOURCE_DIRS = {
    "REC_FILE": "voice",
    "MUSIC": "music",
    "PODCASTS": "podcast",
    "PODCAST": "podcast",
}

# Files and folders we never copy off any drive — OS bookkeeping, trash, and our
# own library metadata.
_JUNK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db",
               "iconcache.db", ".localized"}
_JUNK_DIRS = {"system volume information", "$recycle.bin", ".trashes",
              ".spotlight-v100", ".fseventsd", "found.000", ".reel", "lost.dir"}


@dataclass
class Device:
    root: Path
    label: str
    serial: str = ""        # volume serial (hex) — stable across re-plugs
    removable: bool = True   # came from a removable drive

    @property
    def id(self) -> str:
        """A stable id for this physical volume. Serial survives drive-letter
        changes (so re-plugging on a different letter reads as 'same drive');
        falls back to a hash of the label when no serial is available."""
        if self.serial:
            return self.serial
        base = self.label or str(self.root)
        return "x" + hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:8]

    @property
    def display(self) -> str:
        """A friendly name for messages: the label, or the drive letter."""
        if self.label:
            return self.label
        letter = str(self.root).rstrip(":/\\")
        return f"USB drive ({letter})"

    def __str__(self) -> str:
        return f"{self.label or '?'} ({self.root})"


@dataclass
class Recording:
    path: Path        # absolute path on the device
    source: str       # voice | music | podcast | unknown
    rel: str          # path relative to the device root


# ── drive enumeration (Windows uses the WinAPI; others scan mount points) ────
def _windows_drives() -> list[Path]:
    import ctypes
    roots = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            roots.append(Path(f"{letter}:\\"))
    return roots


_DRIVE_REMOVABLE = 2
_DRIVE_CDROM = 5


def _windows_volume_info(root: Path) -> tuple[str, str]:
    """(label, serial-hex) for a Windows volume. Empty strings if unreadable."""
    import ctypes
    from ctypes import wintypes
    buf = ctypes.create_unicode_buffer(1024)
    serial = wintypes.DWORD(0)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(str(root)), buf, ctypes.sizeof(buf),
            ctypes.byref(serial), None, None, None, 0)
        if not ok:
            return "", ""
        return buf.value or "", f"{serial.value:08X}" if serial.value else ""
    except Exception:
        return "", ""


def _windows_drive_type(root: Path) -> int:
    import ctypes
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(str(root))))
    except Exception:
        return 0


def _candidate_volumes() -> list[tuple[Path, str, str, bool]]:
    """[(root, label, serial, removable)] for every mounted volume we can see."""
    out: list[tuple[Path, str, str, bool]] = []
    if sys.platform == "win32":
        system = (os.environ.get("SystemDrive", "C:") + "\\").upper()
        for root in _windows_drives():
            if not root.exists() or str(root).upper() == system:
                continue
            dtype = _windows_drive_type(root)
            if dtype == _DRIVE_CDROM:
                continue  # never touch optical drives
            label, serial = _windows_volume_info(root)
            out.append((root, label, serial, dtype == _DRIVE_REMOVABLE))
    elif sys.platform == "darwin":
        base = Path("/Volumes")
        if base.exists():
            for child in base.iterdir():
                # skip the boot volume (a symlink to /)
                if child.is_dir() and not child.is_symlink():
                    out.append((child, child.name, "", True))
    else:
        # Linux & other unixes: removable drives auto-mount one level under the
        # desktop mount roots. Each *child* is a mounted volume (its folder name is
        # the label); manual mounts live under /mnt. We look exactly one level deep
        # (not recursively) and only count real mount points, so stray empty
        # placeholder folders are ignored.
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        bases = [Path("/media") / user, Path("/run/media") / user,
                 Path("/media"), Path("/mnt")]
        seen: set[str] = set()
        for base in bases:
            if not base.exists():
                continue
            try:
                children = list(base.iterdir())
            except OSError:
                continue
            for child in children:
                key = os.path.realpath(child)
                if key in seen:
                    continue
                try:
                    if child.is_dir() and os.path.ismount(child):
                        seen.add(key)
                        out.append((child, child.name, "", True))
                except OSError:
                    continue
    return out


def _looks_like_recorder(root: Path, label: str, labels: list[str]) -> bool:
    if label and any(label.upper().strip() == l.upper().strip() for l in labels):
        return True
    # structural fallback: any of the known recording folders present
    return any((root / d).is_dir() for d in SOURCE_DIRS)


def is_recorder(device: "Device", cfg) -> bool:
    return _looks_like_recorder(device.root, device.label, cfg.device_labels)


def find_devices(cfg) -> list[Device]:
    """Every drive reel could sync right now: removable volumes, plus anything
    that structurally looks like the recorder (so it still works even if the
    recorder reports as a fixed disk). The system drive is always excluded."""
    found: list[Device] = []
    for root, label, serial, removable in _candidate_volumes():
        try:
            if removable or _looks_like_recorder(root, label, cfg.device_labels):
                found.append(Device(root=root, label=label, serial=serial,
                                    removable=removable))
        except OSError:
            continue
    return found


# ── reading recordings off a device (or any folder, for drag-and-drop) ───────
def _source_for(rel_parts: tuple[str, ...]) -> str:
    for part in rel_parts:
        tag = SOURCE_DIRS.get(part.upper())
        if tag:
            return tag
    return "unknown"


def scan(root: Path) -> list[Recording]:
    """*Every* file under `root` worth keeping, tagged by which device folder it
    came from. No file-type filter — reel syncs everything it finds (audio gets
    smart-categorised later; the rest is filed by kind). Only OS junk and trash
    are skipped.

    Uses `os.walk` so we prune protected folders (`System Volume Information`,
    recycle bins, `.reel`) before descending — fast on full drives, and no
    permission errors.
    """
    root = Path(root)
    recs: list[Recording] = []
    if root.is_file():
        recs.append(Recording(path=root, source="unknown", rel=root.name))
        return recs
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in _JUNK_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith(".") or fn.lower() in _JUNK_NAMES:
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(root)
            recs.append(Recording(path=p, source=_source_for(rel.parts), rel=rel.as_posix()))
    recs.sort(key=lambda r: r.rel)
    return recs

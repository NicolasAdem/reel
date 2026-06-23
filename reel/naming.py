"""
naming.py — clean, sortable names + a content fingerprint for dedup.

The UX570 names files by the moment you hit record, e.g. `250608_1432.mp3`
(YYMMDD_HHMM) or sometimes `YYYYMMDD...`. We read that when present and fall
back to the file's modified-time otherwise. Output:

    2026-06-08_1432_reel-7F3A.mp3
    └── date ──┘ └tm┘ └── id ──┘

Date-first sorts chronologically forever; `reel-7F3A` is a short hash of the
content so the same recording never lands twice, even if the device renumbers.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import formats


def signature(path: Path) -> str:
    """Fast, stable fingerprint: size + first 256 KB, hashed. 4-hex short id."""
    h = hashlib.sha1()
    size = path.stat().st_size
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(256 * 1024))
    return h.hexdigest()


def short_id(sig: str) -> str:
    return sig[:4].upper()


def recorded_at(path: Path) -> datetime:
    """When a recording was made: the date baked into its filename (any known
    template — the recorder's YYMMDD_HHMM, phone stamps, …), else its mtime."""
    dt, _ = formats.find_date(path.stem)
    if dt:
        return dt
    return datetime.fromtimestamp(path.stat().st_mtime)


def clean_name(path: Path, when: datetime, sig: str) -> str:
    return f"{when:%Y-%m-%d_%H%M}_reel-{short_id(sig)}{path.suffix.lower()}"


def duration_sec(path: Path) -> float | None:
    """Best-effort length in seconds via mutagen; None if unreadable."""
    try:
        from mutagen import File as MutagenFile
    except Exception:
        return None
    try:
        m = MutagenFile(str(path))
        if m is not None and m.info is not None:
            return float(m.info.length)
    except Exception:
        pass
    return None


# ── generic-device naming ────────────────────────────────────────────────────
# Cameras/phones use EXIF; everything else falls back to the filename date or the
# file's modified-time (so a photo still files under the day it was taken).
_EXIF_EXTS = {".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".heif", ".webp",
              ".png", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _exif_datetime(path: Path) -> datetime | None:
    """The moment a photo was taken, from EXIF — only if Pillow is installed."""
    try:
        from PIL import Image, ExifTags
    except Exception:
        return None
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            raw = tags.get("DateTimeOriginal") or tags.get("DateTime")
            if raw:
                return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


# mp4/mov-family containers carry their own creation time in a 'moov/mvhd' box —
# the only date a camera video (no name date, no EXIF) actually has, short of mtime.
_MP4_EXTS = {".mp4", ".m4v", ".mov", ".3gp", ".3g2"}
_EPOCH_1904 = datetime(1904, 1, 1)   # the QuickTime/MP4 epoch


def _iter_atoms(f, start: int, end: int):
    """Yield (type, data_start, atom_end) for each ISO-BMFF box in [start, end).
    Only reads 8–16 byte headers and seeks past payloads, so it's fast even when a
    huge 'mdat' sits before 'moov' (common for cameras)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            return
        size = int.from_bytes(header[:4], "big")
        atype = header[4:8]
        if size == 1:                       # 64-bit extended size
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = int.from_bytes(ext, "big")
            data_start = pos + 16
        elif size == 0:                     # extends to the end
            size = end - pos
            data_start = pos + 8
        else:
            data_start = pos + 8
        if size < 8:
            return
        yield atype, data_start, pos + size
        pos += size


def _find_atom(f, target: bytes, start: int, end: int):
    for atype, ds, de in _iter_atoms(f, start, end):
        if atype == target:
            return ds, de
    return None


def _video_datetime(path: Path) -> datetime | None:
    """When a video was shot, from its 'moov/mvhd' creation time. None if the box
    is missing or the field is 0 (unset) — then the caller falls back to mtime."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            moov = _find_atom(f, b"moov", 0, size)
            if not moov:
                return None
            mvhd = _find_atom(f, b"mvhd", moov[0], moov[1])
            if not mvhd:
                return None
            f.seek(mvhd[0])
            version = f.read(1)
            if not version:
                return None
            f.read(3)  # flags
            created = int.from_bytes(f.read(8 if version[0] == 1 else 4), "big")
            if not created:
                return None
            dt = _EPOCH_1904 + timedelta(seconds=created)
            return dt if 1990 <= dt.year <= 2100 else None
    except Exception:
        return None


def captured_at(path: Path) -> datetime:
    """Best timestamp for any file, most-trustworthy source first: EXIF (photos) →
    a date baked into the filename → the video container's creation time → mtime.
    Always returns *something* sortable; never invents a date out of nothing."""
    ext = path.suffix.lower()
    if ext in _EXIF_EXTS:
        dt = _exif_datetime(path)
        if dt:
            return dt
    dt, _ = formats.find_date(path.stem)
    if dt:
        return dt
    if ext in _MP4_EXTS:
        dt = _video_datetime(path)
        if dt:
            return dt
    return datetime.fromtimestamp(path.stat().st_mtime)


def safe_filename(name: str) -> str:
    """Strip characters Windows won't allow in a filename; never return empty."""
    cleaned = _ILLEGAL.sub("", name).strip().strip(".")
    return cleaned or "file"


def audio_tags(path: Path) -> tuple[str | None, str | None]:
    """(title, artist) from a track's own tags (ID3 / MP4 / Vorbis), if present.
    This is how a meaningless 'track03.mp3' becomes 'Queen - Bohemian Rhapsody'."""
    try:
        from mutagen import File as MutagenFile
    except Exception:
        return None, None
    try:
        m = MutagenFile(str(path))
        if not m or not getattr(m, "tags", None):
            return None, None

        def first(*keys):
            for k in keys:
                if k in m.tags:
                    v = m.tags[k]
                    v = v[0] if isinstance(v, list) else v
                    s = str(v).strip()
                    if s:
                        return s
            return None

        title = first("TIT2", "title", "\xa9nam", "Title")
        artist = first("TPE1", "artist", "\xa9ART", "Artist")
        return title, artist
    except Exception:
        return None, None


def device_name(path: Path, when: datetime, sig: str, kind: str) -> str:
    """Name a file copied off any drive — digging out the meaning that's there.

    • Music: if the filename is boilerplate (track03) but the tags know the song,
      name it "Artist - Title". A real filename is kept as-is.
    • Photos/Videos: a sortable date prefix. If the name is just a camera serial or
      an embedded-date string (IMG_20240615_143022), we normalise it; a real name
      (Beach Sunset) is kept after the date.
    • Documents / archives / everything else: the original name, untouched.

    Dedup is by content hash, so identical files never land twice regardless.
    """
    ext = path.suffix.lower()

    if kind == "Audio":
        title, artist = audio_tags(path)
        if title and not formats.is_meaningful(path.stem):
            label = f"{artist} - {title}" if artist else title
            return safe_filename(label) + ext
        return safe_filename(path.name)

    if kind in ("Photos", "Videos"):
        stem = path.stem
        _, span = formats.find_date(stem)
        if span:
            # the name encoded a date — drop it, keep any real remainder
            label = formats.clean_label(stem.replace(span, " ", 1))
            if not label:
                label = f"reel-{short_id(sig)}"
        else:
            label = stem            # serial (IMG520947) or a real name — keep it
        return f"{when:%Y-%m-%d_%H%M}_{safe_filename(label)}{ext}"

    return safe_filename(path.name)

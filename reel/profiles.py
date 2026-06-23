"""
profiles.py — what *kind* of device is this, and which bucket is a file?

Two small jobs, both used by the copy engine for naming and for the summary:

  • detect_kind(device) → recorder / camera / music / generic, a friendly guess
    from the drive's contents (used only for the right glyph + label).

  • file_kind(path)     → Photos / Videos / Audio / Documents / Archives / Other,
    by file extension (used to decide how a file is renamed, and to tally the
    summary). It does *not* move anything — every file stays in its own folder.
"""
from __future__ import annotations

from . import device

# file extension → the bucket a generic device's file is filed under
_KIND_EXTS = {
    "Photos": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
               ".heic", ".heif", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng",
               ".raf", ".orf", ".rw2", ".svg"},
    "Videos": {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".m2ts", ".mpg",
               ".mpeg", ".mpe", ".wmv", ".flv", ".3gp", ".webm", ".ts"},
    "Audio": set(device.AUDIO_EXTS),
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".pages",
                  ".ppt", ".pptx", ".odp", ".key", ".xls", ".xlsx", ".csv", ".ods",
                  ".numbers", ".epub", ".mobi", ".tex"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".iso"},
}


def file_kind(path) -> str:
    """Which Photos/Videos/Audio/Documents/Archives/Other bucket a file is."""
    ext = path.suffix.lower()
    for kind, exts in _KIND_EXTS.items():
        if ext in exts:
            return kind
    return "Other"


def detect_kind(d: device.Device, cfg) -> str:
    """Guess a device's kind from its contents. Cheap and bounded — samples up
    to a few hundred files. Returns one of branding.DEVICE_GLYPH's keys."""
    if device.is_recorder(d, cfg):
        return "recorder"
    if (d.root / "DCIM").is_dir():
        return "camera"
    counts: dict[str, int] = {}
    n = 0
    for rec in device.scan(d.root):
        k = file_kind(rec.path)
        counts[k] = counts.get(k, 0) + 1
        n += 1
        if n >= 400:
            break
    if not n:
        return "generic"
    top = max(counts, key=counts.get)
    if counts[top] / n >= 0.6:
        if top == "Photos":
            return "camera"
        if top == "Audio":
            return "music"
    return "generic"

"""
organize.py — file every voice recording under <library>/<year>/<month>/.

Recordings carry their date in the name (the recorder's stamp, reel's own
2026-06-24_1125_reel-AB5D, …). After each copy + transcribe, reel reads that date
and moves the recording — and its '-transcript.txt' — into a tidy
<library>/<year>/<month>/ folder. Months are always lowercase (january…december).

It's a full scan every time and idempotent: anything already sitting in the right
month is left alone; stragglers are tucked in. So one quick pass keeps the whole
library stacked by date, no matter how it got there.

The one subtlety: a recording reel copied from a device is tracked in that drive's
manifest (<library>/.reel/mirror/<id>.json), which both the incremental
"already copied?" check and `reel transfer` rely on. So when we move a file, we
rewrite its manifest entry to the new home — otherwise reel would think the file
was deleted and copy it all over again next plug-in.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import formats, mirror
from .config import Config
from .transcribe import _SUFFIX, _in_recordings_folder

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff"}

# Lowercase by design — the user asked for it, and lowercase sorts and reads clean.
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
_MONTHSET = set(MONTHS)


def in_date_folder(path, sync_root) -> bool:
    """True if `path` already lives in a reel date folder: <root>/<YYYY>/<month>/."""
    try:
        rel = Path(path).parent.relative_to(sync_root)
    except (ValueError, OSError):
        return False
    parts = rel.parts
    return (len(parts) == 2 and len(parts[0]) == 4 and parts[0].isdigit()
            and parts[1] in _MONTHSET)


def is_recording(path: Path, cfg: Config) -> bool:
    """A voice recording reel manages: an audio file that's either inside a
    recordings folder (REC_FILE, …) or already filed under a date folder."""
    if path.suffix.lower() not in _AUDIO_EXTS:
        return False
    return _in_recordings_folder(path, cfg) or in_date_folder(path, cfg.sync_root)


def _dest_dir(sync_root: Path, when) -> Path:
    return sync_root / f"{when.year:04d}" / MONTHS[when.month - 1]


def _norm(p) -> str:
    """A canonical, case-folded absolute path string for reliable comparison on
    Windows (purely lexical — no filesystem access, so it works pre/post move)."""
    return os.path.normcase(os.path.abspath(str(p)))


def _update_manifests(cfg: Config, moves: list) -> None:
    """Rewrite each moved copied-file's `final` path in its drive manifest, so the
    incremental copy and `reel transfer` keep pointing at the file's new home."""
    mdir = mirror.manifest_dir(cfg)
    if not mdir.exists() or not moves:
        return
    move_map = {_norm(old): new for old, new in moves}
    for mpath in mdir.glob("*.json"):
        m = mirror._load_manifest(mpath)
        mroot = mirror.mirror_root_for(cfg, m.get("name", ""))
        changed = False
        for rel, info in m.get("files", {}).items():
            cur = _norm(mroot / info.get("final", rel))
            if cur in move_map:
                info["final"] = os.path.relpath(move_map[cur], mroot).replace("\\", "/")
                changed = True
        if changed:
            mirror._save_manifest(mpath, m)


def organize_library(cfg: Config, con) -> int:
    """Scan the whole library and file every dated recording (and its transcript)
    under <library>/<year>/<month>/. Returns how many recordings were moved."""
    if not getattr(cfg, "organize_by_date", True):
        return 0
    root = Path(cfg.sync_root)
    if not root.exists():
        return 0

    moves: list = []          # (old_audio, new_audio) — only for manifest fix-ups
    moved = 0
    for audio in sorted(root.rglob("*")):
        if audio.suffix.lower() not in _AUDIO_EXTS or not audio.is_file():
            continue
        if ".reel" in audio.parts or not is_recording(audio, cfg):
            continue
        when, _ = formats.find_date(audio.stem)
        if when is None:
            continue              # no date in the name — nothing to file it under
        dest_dir = _dest_dir(root, when)
        if audio.parent == dest_dir:
            continue              # already in the right month — leave it be
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = mirror._unique(dest_dir / audio.name)
            audio.rename(dest)
            moved += 1
            moves.append((audio, dest))
            note = audio.with_name(audio.stem + _SUFFIX + ".txt")   # keep the words with it
            if note.exists():
                note.rename(mirror._unique(dest_dir / note.name))
        except OSError as e:
            con.err(f"couldn't file {audio.name}: {e}")

    if moves:
        _update_manifests(cfg, moves)
    if moved:
        con.ok(f"filed {moved} recording(s) by date — under <year>/<month> (e.g. 2026/june).")
    return moved

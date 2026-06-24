"""
mirror.py — reel's core. It copies the drive. Then it renames. That's it.

Plug a drive in and reel copies the whole thing into Documents/reel/<drive name>/ —
every folder, every file, every name, exactly as it was — and only *then* tidies
the file names (a finishing touch you can turn off with `reel rename off`).
The order is the whole point: the complete copy always lands first.

  Phase 1 — COPY.   The entire drive, verbatim. Nothing is dropped for being a
            "duplicate"; the only things skipped are OS-protected folders that
            can't be read (recycle bins, System Volume Information, macOS
            trash/index) and reel's own metadata — and even those are *recorded*,
            never silently lost.

  Phase 2 — RENAME. Once the copy is complete, tidy names in place, inside their
            original folders. A recorder's 250608_1432.mp3 becomes
            2025-06-08_1432_reel-7F3A.mp3; a photo gets a sortable date prefix;
            documents and anything else keep their exact name. Folders never move.

Nothing copies twice, and the engine is built to be *smart* about what "the same
file" means:

  • Re-plug the same drive → a per-drive record (.reel/mirror/<id>.json) knows,
    by each file's original path + size + modified-time, what's already here.
  • A file was renamed or moved *on the device* (recorders renumber, cameras
    reshuffle) → reel notices the old path vanished, compares actual file
    content (full hash, never a guess), and just moves its existing copy into
    place instead of copying the bytes again.
  • You deleted a file from your reel folder → reel notices its copy is gone
    and copies it fresh next plug-in. The record never lies about what's on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import device, formats, locate, naming
from .config import Config
from .profiles import file_kind

# Folders we never descend into: OS-protected, unreadable, or reel's own metadata.
# Everything else — including ordinary hidden/dotfiles — is copied, because the
# promise is "forget nothing".
_SKIP_DIRS = set(device._JUNK_DIRS)


def _unique(target: Path) -> Path:
    """`target`, or `target (2)`, `target (3)`… — the first name not taken. Keeps
    two genuinely-different files that tidy to the same name from clobbering."""
    if not target.exists():
        return target
    stem, suffix, parent, n = target.stem, target.suffix, target.parent, 2
    while True:
        cand = parent / f"{stem} ({n}){suffix}"
        if not cand.exists():
            return cand
        n += 1


def _content_hash(path: Path) -> str | None:
    """The file's full-content SHA-256. Used only to recognise a file that moved
    or was renamed on the device — a *full* hash, so two different files can
    never be mistaken for each other. None if unreadable."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


@dataclass
class MirrorSummary:
    copied: int = 0          # files copied this run
    skipped: int = 0         # already copied (unchanged) on a prior run
    relocated: int = 0       # recognised as moved/renamed on the device (no re-copy)
    renamed: int = 0         # files whose name was tidied in the rename pass
    bytes: int = 0
    errors: list = field(default_factory=list)
    devices: list = field(default_factory=list)
    by_category: dict = field(default_factory=dict)  # by file-kind — for the summary
    mirror_root: str = ""
    device_id: str = ""
    aborted: bool = False     # refused before copying (e.g. not enough free space)
    need_bytes: int = 0       # bytes this copy would have needed
    free_bytes: int = 0       # bytes free where the library lives


# ── the rename toggle ────────────────────────────────────────────────────────
# Renaming is ON by default; `reel rename off` drops a flag file and the rename
# pass simply doesn't run. The copy itself is never affected either way.
def _rename_off_path(cfg: Config) -> Path:
    return cfg.sync_root / ".reel" / "rename_off"


def renaming_on(cfg: Config) -> bool:
    return not _rename_off_path(cfg).exists()


def set_renaming(cfg: Config, on: bool) -> None:
    p = _rename_off_path(cfg)
    if on:
        try:
            p.unlink()
        except OSError:
            pass
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("renaming disabled — delete this file (or run "
                     "'reel rename on') to re-enable.\n", encoding="utf-8")


# ── the per-drive record ─────────────────────────────────────────────────────
# Stored at <sync_root>/.reel/mirror/<device-id>.json:
#   { "name": "IC RECORDER", "label": "IC RECORDER", "id": "...",
#     "files": { "REC_FILE/FOLDER01/250608_1432.mp3":
#                  {"size": 1234, "mtime": 1718, "final": "REC_FILE/FOLDER01/2025-..mp3"} } }
def manifest_dir(cfg: Config) -> Path:
    return cfg.sync_root / ".reel" / "mirror"


def _manifest_path(cfg: Config, dev: device.Device) -> Path:
    return manifest_dir(cfg) / f"{dev.id}.json"


def _load_manifest(p: Path) -> dict:
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_manifest(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def mirror_root_for(cfg: Config, name: str) -> Path:
    """The PC folder a drive is copied into: <library>/<drive name>/."""
    return cfg.sync_root / naming.safe_filename(name)


# ── reading the drive — everything, with nothing dropped silently ────────────
def _walk(root: Path, errors: list) -> tuple[list[str], list[tuple[Path, str]]]:
    """(dirs, files) under `root`, relative to it.

    `dirs` is *every* folder (so empty ones are recreated too); `files` is
    (abs_path, rel_posix) for every file. The only folders pruned are OS-protected
    or unreadable ones — and each prune, plus any directory we couldn't list, is
    appended to `errors` so the run can report it. Nothing vanishes quietly.
    """
    root = Path(root)
    dirs: list[str] = []
    files: list[tuple[Path, str]] = []
    if root.is_file():
        files.append((root, root.name))
        return dirs, files

    def on_err(e):
        errors.append(f"unreadable: {getattr(e, 'filename', e)}")

    for dirpath, dirnames, filenames in os.walk(root, onerror=on_err):
        keep = []
        for d in dirnames:
            if d.lower() in _SKIP_DIRS:
                errors.append(f"skipped system folder: {d}")
            else:
                keep.append(d)
        dirnames[:] = keep
        base = Path(dirpath)
        for d in dirnames:
            dirs.append((base / d).relative_to(root).as_posix())
        for fn in filenames:
            p = base / fn
            files.append((p, p.relative_to(root).as_posix()))
    files.sort(key=lambda t: t[1])
    dirs.sort()
    return dirs, files


# ── the rename rule — clean, sortable names, folders left intact ─────────────
def _renamed(path: Path, sig: str) -> str:
    """The tidy name for a copied file. Reuses reel's existing naming brains:
    recordings/audio get a date_time_reel-id stamp, photos & videos a sortable
    date prefix. Documents, archives and everything else (including dotfiles) keep
    their original name *exactly* — they're already on disk with a valid name, so
    we never touch them. 'Every name' means every name."""
    kind = file_kind(path)
    if kind == "Audio":
        when = naming.recorded_at(path)
        dt, _ = formats.find_date(path.stem)
        if dt:
            return naming.clean_name(path, when, sig)
        return naming.device_name(path, when, sig, kind)
    if kind in ("Photos", "Videos"):
        when = naming.captured_at(path)
        return naming.device_name(path, when, sig, kind)
    return path.name


# ── recognising a file that moved/renamed on the device ─────────────────────
def _find_relocated(src: Path, size: int, vanished: dict, mirror_root: Path,
                    hash_cache: dict) -> str | None:
    """If `src` (a 'new' file on the device) is byte-identical to a recorded file
    whose original path vanished from the device, return that old rel — its copy
    can simply be moved into place. Full-content hashes only; size pre-filter so
    we hash as little as possible. None = genuinely new."""
    candidates = [(rel, info) for rel, info in vanished.items()
                  if info.get("size") == size]
    if not candidates:
        return None
    src_hash = _content_hash(src)
    if src_hash is None:
        return None
    for rel, info in candidates:
        old_copy = mirror_root / info.get("final", rel)
        if not old_copy.exists():
            continue
        if old_copy not in hash_cache:
            hash_cache[old_copy] = _content_hash(old_copy)
        if hash_cache[old_copy] == src_hash:
            return rel
    return None


# ── disk-space pre-flight ────────────────────────────────────────────────────
# Always leave a little headroom so the destination never fills to the brim.
_SPACE_MARGIN = 64 * 1024 * 1024   # 64 MB


def _free_space(path: Path) -> int:
    """Bytes free on the disk that holds `path` — walking up to the first folder
    that actually exists (the library, or its parent, may not be created yet)."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return 0


def _bytes_needed(files, files_seen: dict, mirror_root: Path) -> int:
    """How many bytes this copy would actually write: the size of every file that
    isn't already sitting in the library unchanged. A conservative estimate (it
    doesn't try to predict the rare move/rename shortcut), so it errs toward
    warning rather than overfilling the disk."""
    need = 0
    for src, rel in files:
        try:
            size = src.stat().st_size
        except OSError:
            continue
        prev = files_seen.get(rel)
        if (prev and prev.get("size") == size
                and (mirror_root / prev.get("final", rel)).exists()):
            continue   # already copied and still here — no new space needed
        need += size
    return need


# ── the two-phase copy ───────────────────────────────────────────────────────
def mirror_device(cfg: Config, dev: device.Device, *,
                  on_scan_done=None, on_copy=None, on_copy_done=None,
                  on_rename=None) -> MirrorSummary:
    """Copy one drive into <library>/<drive name>/ verbatim, then rename in place.
    Callbacks (all optional), in order:
        on_scan_done(total_files)   after listing the drive
        on_copy(name)               per file in the copy pass (copied or skipped)
        on_copy_done(num_to_rename) copy pass finished
        on_rename(name)             per file in the rename pass
    """
    s = MirrorSummary(devices=[str(dev)], device_id=dev.id)
    mirror_root = mirror_root_for(cfg, dev.display)
    s.mirror_root = str(mirror_root)
    mpath = _manifest_path(cfg, dev)
    manifest = _load_manifest(mpath)
    manifest["name"] = dev.display
    manifest["label"] = dev.label
    manifest["id"] = dev.id
    files_seen: dict = manifest.setdefault("files", {})

    dirs, files = _walk(dev.root, s.errors)

    # Disk-space pre-flight: never start a copy that can't fit. Catches the classic
    # "900 GB drive → a library with 200 GB free" before a single byte is written.
    need = _bytes_needed(files, files_seen, mirror_root)
    free = _free_space(cfg.sync_root)
    if need + _SPACE_MARGIN > free:
        s.aborted = True
        s.need_bytes = need
        s.free_bytes = free
        return s

    if on_scan_done:
        on_scan_done(len(files))

    # recreate every folder first, including empty ones, so the tree is faithful
    mirror_root.mkdir(parents=True, exist_ok=True)
    locate.bind(cfg.sync_root)   # remember where the library is (follows moves)
    for d in dirs:
        try:
            (mirror_root / d).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            s.errors.append(f"{d}/: {type(e).__name__}: {e}")

    # files we recorded before that are no longer on the device — candidates for
    # "it was renamed/moved on the device, don't copy the bytes again"
    current_rels = {rel for _, rel in files}
    vanished = {rel: info for rel, info in files_seen.items()
                if rel not in current_rels}
    hash_cache: dict = {}

    # ── Phase 1: verbatim copy ───────────────────────────────────────────────
    fresh: list[tuple[Path, str]] = []     # (dest_path, original_rel) to rename
    for src, rel in files:
        try:
            st = src.stat()
        except OSError as e:
            s.errors.append(f"{rel}: cannot read ({type(e).__name__})")
            if on_copy:
                on_copy(src.name)
            continue

        prev = files_seen.get(rel)
        if (prev and prev.get("size") == st.st_size
                and int(prev.get("mtime", -1)) == int(st.st_mtime)):
            # already copied — but verify the copy is still on disk (the user may
            # have deleted it from the library; if so, copy it fresh again)
            if (mirror_root / prev.get("final", rel)).exists():
                s.skipped += 1
                if on_copy:
                    on_copy(src.name)
                continue

        # renamed/moved on the device? move our existing copy instead of re-copying
        old_rel = _find_relocated(src, st.st_size, vanished, mirror_root, hash_cache)
        if old_rel is not None:
            info = files_seen.pop(old_rel)
            vanished.pop(old_rel, None)
            old_copy = mirror_root / info.get("final", old_rel)
            # If we tidied this file's name, the tidy name (date + content id) is
            # still right — keep it, just in the new folder. If we never touched
            # the name, follow the device's new name exactly. (A recorder
            # renumbering a file in place may mean the copy is already exactly
            # where it belongs — then there's nothing to move.)
            we_renamed_it = old_copy.name != Path(old_rel).name
            if we_renamed_it:
                desired = (mirror_root / rel).parent / old_copy.name
            else:
                desired = mirror_root / rel
            try:
                if desired != old_copy:
                    desired = _unique(desired)
                    desired.parent.mkdir(parents=True, exist_ok=True)
                    old_copy.rename(desired)
                files_seen[rel] = {"size": st.st_size, "mtime": int(st.st_mtime),
                                   "final": desired.relative_to(mirror_root).as_posix()}
                s.relocated += 1
                if on_copy:
                    on_copy(src.name)
                continue
            except OSError:
                files_seen[old_rel] = info   # put it back; fall through to a copy

        dest = mirror_root / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            s.copied += 1
            s.bytes += st.st_size
            files_seen[rel] = {"size": st.st_size, "mtime": int(st.st_mtime), "final": rel}
            fresh.append((dest, rel))
        except Exception as e:
            s.errors.append(f"{rel}: {type(e).__name__}: {e}")
        if on_copy:
            on_copy(src.name)

    # ── Phase 2: rename, in place, inside the original folders ───────────────
    do_rename = renaming_on(cfg)
    if on_copy_done:
        on_copy_done(len(fresh) if do_rename else 0)
    for dest, rel in fresh:
        kind = file_kind(dest)
        s.by_category[kind] = s.by_category.get(kind, 0) + 1
        if not do_rename:
            continue
        try:
            sig = naming.signature(dest)
        except OSError:
            sig = "0000"
        final_path = dest
        new_name = _renamed(dest, sig)
        if new_name != dest.name:
            target = _unique(dest.with_name(new_name))
            try:
                dest.rename(target)
                final_path = target
                s.renamed += 1
            except OSError as e:
                s.errors.append(f"rename {rel}: {type(e).__name__}: {e}")
        files_seen[rel]["final"] = final_path.relative_to(mirror_root).as_posix()
        if on_rename:
            on_rename(final_path.name)

    _save_manifest(mpath, manifest)
    return s


# ── transfer: put a drive back, exactly as it was ────────────────────────────
def saved_drives(cfg: Config) -> list[dict]:
    """Every drive reel has copied (one record per drive)."""
    out = []
    d = manifest_dir(cfg)
    if d.exists():
        for p in sorted(d.glob("*.json")):
            m = _load_manifest(p)
            if m.get("files"):
                out.append(m)
    return out


def find_saved(cfg: Config, name: str | None = None, label: str = "") -> dict | None:
    """Pick which saved drive to restore: by name, else the only one, else one
    matching the target drive's label. None if it's genuinely ambiguous."""
    drives = saved_drives(cfg)
    if not drives:
        return None
    if name:
        for m in drives:
            if name.lower() in (m.get("name", "").lower(), m.get("label", "").lower()):
                return m
        return None
    if len(drives) == 1:
        return drives[0]
    if label:
        for m in drives:
            if m.get("label", "").lower() == label.lower():
                return m
    return None


def restore_drive(cfg: Config, con, m: dict, target_root: Path) -> dict:
    """Write a saved drive's files back onto `target_root`, under their *original*
    paths and original names — rebuilding the folder tree. Never overwrites a file
    already on the target."""
    mirror_root = mirror_root_for(cfg, m.get("name", ""))
    files = m.get("files", {})
    copied = skipped = missing = 0
    bar = con.progress()
    with bar:
        tid = bar.add_task("restoring", total=len(files), name="")
        for orig_rel, info in files.items():
            src = mirror_root / info.get("final", orig_rel)
            dst = target_root / orig_rel
            try:
                if not src.exists():
                    missing += 1
                elif dst.exists():
                    skipped += 1
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied += 1
            except Exception:
                missing += 1
            bar.update(tid, advance=1, name=Path(orig_rel).name)
    return {"copied": copied, "skipped": skipped, "missing": missing}

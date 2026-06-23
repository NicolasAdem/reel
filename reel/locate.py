"""
locate.py — always know where the library is, even after you move it.

The library folder (`Documents/reel`) is the most important thing reel owns, and
people move folders. So reel never hard-codes where it lives — it *finds* it:

  • A stable pointer lives at  ~/.reel/location.json  (in your home folder, which
    you don't move). It records the library's current absolute path + a unique id.

  • Inside the library sits a marker:  <library>/.reel/library_id  — the same id.

  • On every run reel reads the pointer. If the recorded folder is still there with
    the matching id, that's the library — instant, no searching. If the folder has
    moved (the recorded path is gone), reel searches the likely places — Documents,
    Desktop, your home folder, every drive — for the folder carrying that id, and
    quietly updates the pointer to wherever it now is. You move it; reel follows.

First run, or if the library can't be found anywhere, reel uses the default:
`Documents/reel`. Power users can still pin a fixed path in config.toml.
"""
from __future__ import annotations

import json
import os
import string
import sys
import uuid
from pathlib import Path


def default_root() -> Path:
    """Where the library lives unless told otherwise: a `reel` folder in Documents."""
    return Path.home() / "Documents" / "reel"


def _pointer_path() -> Path:
    return Path.home() / ".reel" / "location.json"


def _id_file(root: Path) -> Path:
    return Path(root) / ".reel" / "library_id"


def read_id(root: Path) -> str | None:
    try:
        return _id_file(root).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def load_pointer() -> dict:
    p = _pointer_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_pointer(root: Path, lib_id: str) -> None:
    p = _pointer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"sync_root": str(Path(root)), "id": lib_id},
                            indent=2, ensure_ascii=False), encoding="utf-8")


def bind(root: Path) -> str:
    """Mark `root` as the library and remember it in the pointer. Creates the
    marker id on first call; returns the library id. Call this whenever reel
    actually creates or writes to the library (setup, a copy)."""
    root = Path(root)
    (root / ".reel").mkdir(parents=True, exist_ok=True)
    lib_id = read_id(root)
    if not lib_id:
        lib_id = uuid.uuid4().hex
        try:
            _id_file(root).write_text(lib_id, encoding="utf-8")
        except OSError:
            pass
    save_pointer(root, lib_id)
    return lib_id


def resolve() -> Path:
    """The library's current location. Follows a moved folder; falls back to the
    default. Cheap when nothing moved (just reads the pointer)."""
    ptr = load_pointer()
    lib_id = ptr.get("id")
    recorded = ptr.get("sync_root")
    if recorded and lib_id:
        root = Path(recorded)
        if root.exists() and read_id(root) == lib_id:
            return root                      # still there — the fast path
        found = find_moved(lib_id)           # gone — go looking
        if found is not None:
            save_pointer(found, lib_id)
            return found
    return default_root()


# ── searching for a library that was moved ───────────────────────────────────
# Dir names we never descend into while searching — system, package, and cache
# folders that can't hold a user's library and would only slow us down.
_SKIP = {
    "windows", "program files", "program files (x86)", "programdata", "msocache",
    "$recycle.bin", "system volume information", "recovery", "perflogs", "users",
    "appdata", "node_modules", "site-packages", "__pycache__", ".git", ".venv",
    "venv", ".cache", "lost+found", ".trash", ".trashes",
}


def _search_roots() -> list[Path]:
    """Likely places a library could be, most-likely first."""
    home = Path.home()
    cands = [home / "Documents", home / "Desktop", home / "Downloads",
             home / "OneDrive" / "Documents", home / "OneDrive" / "Desktop",
             home / "OneDrive", home]
    if sys.platform == "win32":
        sysdrive = (os.environ.get("SystemDrive", "C:") + "\\").upper()
        # user drives (D:, E:, …) first — that's where people move big folders
        for letter in string.ascii_uppercase:
            r = Path(f"{letter}:\\")
            if r.exists() and str(r).upper() != sysdrive:
                cands.append(r)
        cands.append(Path(sysdrive))
    else:
        cands += [Path("/Volumes"), Path("/media"), Path("/mnt"), Path("/")]
    out, seen = [], set()
    for c in cands:
        try:
            key = str(c.resolve()).lower()
        except Exception:
            key = str(c).lower()
        if key in seen or not c.exists():
            continue
        seen.add(key)
        out.append(c)
    return out


def find_moved(lib_id: str, max_depth: int = 6) -> Path | None:
    """Search the likely roots for the library folder carrying `lib_id`. Returns
    the first match, or None. Depth-limited and prunes system/cache folders, so a
    library sitting under Documents/Desktop/a drive root is found quickly."""
    if not lib_id:
        return None
    for root in _search_roots():
        hit = _scan(root, lib_id, max_depth)
        if hit is not None:
            return hit
    return None


def _scan(start: Path, lib_id: str, max_depth: int) -> Path | None:
    stack = [(start, 0)]
    while stack:
        d, depth = stack.pop()
        # is *this* folder the library?
        try:
            if _id_file(d).is_file() and read_id(d) == lib_id:
                return d
        except OSError:
            pass
        if depth >= max_depth:
            continue
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    name = entry.name.lower()
                    if name in _SKIP or name.startswith("$"):
                        continue
                    stack.append((Path(entry.path), depth + 1))
        except OSError:
            continue
    return None

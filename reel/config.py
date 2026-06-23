"""config.py — set it once. Every value has a sensible default."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


@dataclass
class Config:
    # where copies land (your "reel" library) — a 'reel' folder in Documents. This
    # is just the fallback default; the real location is resolved by locate.py,
    # which follows the folder if you move it.
    sync_root: Path = Path.home() / "Documents" / "reel"

    # how the ICD-UX570 shows up
    device_labels: list[str] = field(
        default_factory=lambda: ["IC RECORDER", "MEMORY CARD", "IC RECORDER MEMORY CARD"])
    delete_from_device: bool = False   # safe default: copy, never wipe the recorder

    # watch mode
    watch_interval_sec: int = 4
    close_on_unplug: bool = True   # close the terminal window when the recorder is removed

    # terminal theme: "light" (default) or "dark"
    theme: str = "light"

    @property
    def profile_path(self) -> Path:
        return self.sync_root / ".reel" / "profile.json"


def resolve_path(explicit: str | os.PathLike | None = None) -> Path | None:
    """Find config.toml wherever you run `reel` from. First match wins:
      1. an explicit --config path
      2. ./config.toml            (the folder you're standing in)
      3. ~/.reel/config.toml      (a stable per-user spot)
      4. config.toml next to the installed package (the project folder)
    Returns None if none exist -> reel runs on built-in defaults."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path.cwd() / "config.toml")
    candidates.append(Path.home() / ".reel" / "config.toml")
    candidates.append(Path(__file__).resolve().parent.parent / "config.toml")
    for c in candidates:
        if c.exists():
            return c
    return None


def load(path: str | os.PathLike | None) -> Config:
    from . import locate
    cfg = Config()
    data = {}
    if path is not None and Path(path).exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)

    def g(section, key, default):
        return data.get(section, {}).get(key, default)

    # Where the library lives. If config.toml pins an explicit path, honour it.
    # Otherwise let locate.py find it — including after you've moved the folder.
    pinned = data.get("library", {}).get("sync_root")
    if pinned:
        cfg.sync_root = Path(pinned).expanduser()
    else:
        cfg.sync_root = locate.resolve()

    cfg.device_labels = g("device", "labels", cfg.device_labels)
    cfg.delete_from_device = bool(g("device", "delete_after_sync", False))
    cfg.watch_interval_sec = int(g("watch", "interval_sec", cfg.watch_interval_sec))
    cfg.close_on_unplug = bool(g("watch", "close_on_unplug", cfg.close_on_unplug))
    cfg.theme = g("ui", "theme", cfg.theme)
    return cfg

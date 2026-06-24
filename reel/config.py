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

    # transcripts: after each copy, turn new MP3s into text next to them
    # (fully local, via faster-whisper). "small" is a good default; bump to
    # "medium" or "large-v3" for noticeably better accuracy (esp. names, jargon,
    # and non-English) at the cost of speed. language None = auto-detect.
    transcribe_enabled: bool = True
    transcribe_model: str = "small"
    transcribe_language: str | None = None
    # optional spelling/vocabulary hint fed to the model as context — list the
    # proper nouns and jargon it keeps getting wrong (names, places, terms) and it
    # will spell them right far more often. None = no hint.
    transcribe_initial_prompt: str | None = None
    # ONLY transcribe files that live in (or under) a recordings folder — matched by
    # name anywhere in the path, case-insensitive. On a Sony IC recorder that's
    # 'REC_FILE'; the rest covers other devices. Everything else (MUSIC, SOUND
    # EFFECTS, …) is ignored. Empty list = transcribe everywhere.
    transcribe_only_folders: list[str] = field(default_factory=lambda: [
        "REC_FILE", "RECORDINGS", "VOICE RECORDINGS", "VOICE", "VOICE MEMOS"])
    # belt-and-braces cap: even inside a recordings folder, skip anything absurdly
    # long or large (it isn't a voice memo). 0 = no cap on that dimension.
    transcribe_max_minutes: float = 25.0
    transcribe_max_mb: float = 40.0

    # after each copy, file recordings (and their transcripts) into
    # <library>/<year>/<month>/ folders, months lowercase. True by default.
    organize_by_date: bool = True

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
    cfg.transcribe_enabled = bool(g("transcribe", "enabled", cfg.transcribe_enabled))
    cfg.transcribe_model = g("transcribe", "model", cfg.transcribe_model)
    cfg.transcribe_language = g("transcribe", "language", cfg.transcribe_language)
    cfg.transcribe_initial_prompt = g("transcribe", "initial_prompt", cfg.transcribe_initial_prompt)
    cfg.transcribe_only_folders = g("transcribe", "only_folders", cfg.transcribe_only_folders)
    cfg.transcribe_max_minutes = float(g("transcribe", "max_minutes", cfg.transcribe_max_minutes))
    cfg.transcribe_max_mb = float(g("transcribe", "max_mb", cfg.transcribe_max_mb))
    cfg.organize_by_date = bool(g("organize", "by_date", cfg.organize_by_date))
    return cfg

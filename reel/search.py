"""
search.py — `reel find`: dig up a recording by what was said in it, instantly.

Every recording reel transcribes leaves a plain-text note beside it
(`<name>-transcript.txt`). `reel find "phone number"` reads those notes, finds the
recordings that mention your words, and shows them best-match-first with a short
snippet — so you can find the one you mean without listening to a hundred.

Why plain keyword search and not an AI model? Because it's the most *reel* answer:
nothing to download, no model to load, nothing leaves your machine, and it's
instant even on a big library. The transcripts are just text files, so if you ever
want fancier (ask Claude, run a local model), they're right there to point at — but
for "find that note", fast local search is the efficient tool.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import formats
from .config import Config
from .transcribe import _SUFFIX

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff"}


@dataclass
class Hit:
    recording: Path   # the audio file the note belongs to (best guess)
    note: Path        # the <name>-transcript.txt
    score: int        # total keyword occurrences (content + name)
    matched: int      # how many distinct query words appeared
    snippet: str      # a short excerpt, with the matched words marked up


def _audio_for(note: Path) -> Path:
    """The recording a note belongs to: '<stem>-transcript.txt' → '<stem>.<audio>'.
    Returns the first matching audio sibling, else the bare stem path."""
    stem = note.name[: -len(_SUFFIX + ".txt")]
    for ext in _AUDIO_EXTS:
        cand = note.with_name(stem + ext)
        if cand.exists():
            return cand
    return note.with_name(stem)


def _snippet(text: str, terms: list[str], width: int = 200) -> str:
    """A readable excerpt centred on the first match, with the words highlighted."""
    low = text.lower()
    hits = [low.find(t) for t in terms if low.find(t) >= 0]
    pos = min(hits) if hits else -1
    if pos < 0:
        body, lead = text[:width], False
    else:
        start = max(0, pos - width // 3)
        body, lead = text[start:start + width], start > 0
    body = re.sub(r"\s+", " ", body).strip()
    for t in terms:                       # mark each occurrence (case-insensitive)
        body = re.sub(re.escape(t), lambda m: f"[accent]{m.group(0)}[/accent]", body, flags=re.I)
    return ("…" if lead else "") + body + ("…" if len(text) > width else "")


def find_notes(cfg: Config, query: str) -> list[Hit]:
    """Every transcribed recording whose note (or name) mentions the query words,
    best match first. A match needs at least one word; more distinct words and more
    occurrences rank higher."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    root = Path(cfg.sync_root)
    if not root.exists():
        return []
    hits: list[Hit] = []
    for note in root.rglob("*" + _SUFFIX + ".txt"):
        if ".reel" in note.parts:
            continue
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hay = (text + " " + note.name).lower()
        counts = [hay.count(t) for t in terms]
        total = sum(counts)
        if total == 0:
            continue
        hits.append(Hit(recording=_audio_for(note), note=note, score=total,
                        matched=sum(1 for c in counts if c > 0),
                        snippet=_snippet(text, terms)))
    hits.sort(key=lambda h: (h.matched, h.score), reverse=True)
    return hits


def run_find(cfg: Config, con, query: str, limit: int = 10) -> None:
    """The `reel find` command: search the notes and print the matches."""
    q = (query or "").strip()
    if not q:
        con.warn('what should I look for?  e.g.  reel find "phone number"')
        return
    hits = find_notes(cfg, q)
    if not hits:
        con.warn(f'nothing in your notes mentions "{q}".')
        con.dim("(reel searches the recordings it has transcribed — music is skipped.)")
        return
    shown = min(len(hits), limit)
    con.info(f'{len(hits)} recording(s) mention "{q}" — best match first:')
    con.space()
    for h in hits[:limit]:
        name = h.recording.stem
        when, _ = formats.find_date(name)
        date = f"   [muted]{when:%Y-%m-%d %H:%M}[/muted]" if when else ""
        try:
            where = h.recording.parent.relative_to(cfg.sync_root).as_posix()
        except ValueError:
            where = str(h.recording.parent)
        con.panel(f"{name}{date}", f"{h.snippet}\n\n[muted]{where}[/muted]")
    if len(hits) > shown:
        con.dim(f"…and {len(hits) - shown} more — add another word to narrow it down.")

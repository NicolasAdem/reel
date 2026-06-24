"""
ask.py — `reel find`: ask about your recordings in plain English.

This is the one way in. You ask the way you'd ask a person —

    reel find give me a summary of today's notes
    reel find what was my first recording about?
    reel find the interview at Bucky's, about a month ago
    reel find the phone number John gave me a couple of months back
    reel find funny memories of my family in Belgium

— and reel answers, citing which recording and when.

How it works, and why this way:
  reel already knows *when* every recording was made (from its filename) and *what*
  was said (from its transcript). So reel hands Claude the whole set of transcripts,
  in time order, each stamped with its date — plus today's date. That's all Claude
  needs to reason about time ("today", "last week", "my first recording") and meaning
  ("funny", "the interview") at once. No keyword guessing, no separate search index —
  the notes reel already wrote, read the way you'd read them.

Reaching Claude, in order: the `claude` command (Claude Code) if installed — your
own Claude, no API key; else the Anthropic API if a key is set; else it falls back
to a plain keyword search so `reel find` always does something.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from . import formats, search
from .config import Config
from .transcribe import _SUFFIX

# How much transcript text to hand Claude at once. A personal recording library
# fits comfortably; only a very large one trips this, and then we focus on the
# most relevant + recent and say so.
_CHAR_BUDGET = 180_000

# reel's own stamped names carry the time too (2026-06-05_2242_reel-9A70).
_REEL_STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})[_-](\d{2})(\d{2})")


def _recorded_at(stem: str) -> datetime | None:
    """When a recording was made — date *and* time when the name has it (reel's
    stamp), else whatever date is baked into the filename, else None."""
    m = _REEL_STAMP.search(stem)
    if m:
        try:
            return datetime(*(int(g) for g in m.groups()))
        except ValueError:
            pass
    dt, _ = formats.find_date(stem)
    return dt


def _gather_context(cfg: Config, question: str) -> tuple[str, int, int, bool]:
    """The transcripts handed to Claude: every recording, in chronological order,
    each headed by its name, recorded date/time, and folder. If the whole library
    fits, all of it goes (best answers); if not, we keep the most relevant +
    recent and flag it. Returns (context, included, total, truncated)."""
    root = Path(cfg.sync_root)
    if not root.exists():
        return "", 0, 0, False
    terms = [t for t in question.lower().split() if t]

    items = []  # (when, score, recording_path, text)
    for note in root.rglob("*" + _SUFFIX + ".txt"):
        if ".reel" in note.parts:          # skip reel's own bookkeeping
            continue
        try:
            text = note.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if not text:                       # silent recording — nothing to read
            continue
        rec = search._audio_for(note)
        when = _recorded_at(rec.stem)
        score = sum(text.lower().count(t) for t in terms) if terms else 0
        items.append((when, score, rec, text))

    total = len(items)
    if not items:
        return "", 0, 0, False

    # Does the whole thing fit? (Newest content matters most when choosing what to
    # drop, so size the budget against the full set first.)
    full = sum(len(t) for *_rest, t in items)
    truncated = full > _CHAR_BUDGET

    if truncated:
        # Keep the most relevant to the question, then the most recent, until full.
        ranked = sorted(
            items,
            key=lambda it: (it[1], it[0].timestamp() if it[0] else 0.0),
            reverse=True,
        )
        kept, used = [], 0
        for it in ranked:
            blk = len(it[3])
            if used + blk > _CHAR_BUDGET and kept:
                break
            kept.append(it)
            used += blk
        items = kept

    # Present chronologically (oldest first) so "first recording" and timelines read naturally.
    items.sort(key=lambda it: (it[0] is not None, it[0] or datetime.min))

    blocks = []
    for when, _score, rec, text in items:
        try:
            where = rec.parent.relative_to(cfg.sync_root).as_posix()
        except ValueError:
            where = str(rec.parent)
        when_s = when.strftime("%A %Y-%m-%d %H:%M") if when else "date unknown"
        blocks.append(f"### {rec.stem}  —  recorded {when_s}  ({where})\n{text}\n")
    return "\n".join(blocks), len(items), total, truncated


def _instruction(question: str, truncated: bool) -> str:
    """What we tell Claude to do with the recordings."""
    now = datetime.now()
    note = ("\n\nNote: this person has a large library, so you're seeing the most "
            "relevant and most recent recordings, not every one.") if truncated else ""
    return (
        "You are reel — you help someone explore their own voice recordings. "
        f"Today is {now:%A, %B %d, %Y}, the current time is {now:%H:%M}. "
        "You're given the transcripts of their recordings as context, in chronological "
        "order; each is headed by its recording name, the date and time it was recorded, "
        "and its folder. Answer their request from these recordings. Reason freely about "
        "time (\"today\", \"last week\", \"a month ago\", \"a few years ago\", \"my first "
        "recording\" = the earliest one) and about meaning, not just exact words — match "
        "what they *mean* (\"funny\", \"the interview\", \"the phone number from John\"). "
        "Summarize across several recordings when that's what's asked. Be warm, natural, "
        "and concise — like a friend who remembers. When you mention a recording, give a "
        "friendly date (\"your note from last Tuesday\") and quote the words that matter. "
        "If nothing fits, say so kindly and mention what you do have nearby in time. Never "
        "invent anything that isn't in the recordings."
        f"{note}\n\nTheir request: {question}"
    )


def _ask_via_cli(question: str, context: str, truncated: bool, timeout: int = 240) -> str | None:
    """Ask through the `claude` command (Claude Code). Recordings go in on stdin
    (closed, so it doesn't wait), instruction + request as the prompt."""
    exe = shutil.which("claude")
    if not exe:
        return None
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW — no flash
    try:
        r = subprocess.run([exe, "-p", _instruction(question, truncated)],
                           input=context, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           **kwargs)
        return (r.stdout or "").strip() or None
    except Exception:
        return None


def _ask_via_api(question: str, context: str, truncated: bool) -> str | None:
    """Ask through the Anthropic API — only if the package is installed and a key
    is set. None otherwise (so we fall through to keyword search)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except Exception:
        return None
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1500,
            messages=[{"role": "user",
                       "content": _instruction(question, truncated)
                       + "\n\nThe recordings:\n" + context}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text.strip() or None
    except Exception:
        return None


def run_ask(cfg: Config, con, question: str | None = None) -> None:
    """`reel find <plain-English request>` — ask reel about your recordings."""
    q = (question or "").strip()
    if not q:
        con.info("Ask me anything about your recordings — in plain words.")
        con.dim('e.g.  "a summary of today\'s notes"  ·  "what was my first recording about?"')
        try:
            q = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            con.space()
            return
    if not q:
        con.warn("nothing to look for — try again whenever.")
        return

    status = con.live_status("reading through your recordings…")
    status.start()
    context, n, total, truncated = _gather_context(cfg, q)
    if not context:
        status.stop()
        con.warn("no transcribed recordings yet to look through.")
        con.dim("(plug in your recorder — reel writes a transcript for each recording as it copies.)")
        return

    scope = f"{n} of {total}" if truncated else f"all {total}"
    status.update(f"thinking — going through {scope} recording(s)…")
    answer = _ask_via_cli(q, context, truncated) or _ask_via_api(q, context, truncated)
    status.stop()

    if answer is None:
        con.dim("Claude isn't reachable here, so here are keyword matches instead.")
        con.dim("(for plain-English answers, install Claude Code — the `claude` command.)")
        con.space()
        search.run_find(cfg, con, q)
        return

    con.space()
    con.type_out(answer)
    con.space()
    tail = f"— from {n} of your {total} recordings" if truncated else f"— from all {total} of your recordings"
    con.dim(f"{tail}, on your machine")

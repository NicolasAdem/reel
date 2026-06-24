"""
ask.py — `reel find`: ask about your recordings in plain English.

This is the one way in. You ask the way you'd ask a person —

    reel find give me a summary of today's notes
    reel find what was my first recording about?
    reel find the interview at Bucky's, about a month ago
    reel find the phone number John gave me a couple of months back
    reel find funny memories of my family in Belgium

— and reel answers, citing which recording and when, and prints a clickable link
to each recording it found so you can open it in your media player with one click.

How it works, and why this way:
  reel already knows *when* every recording was made (from its filename) and *what*
  was said (from its transcript). So reel hands Claude the whole set of transcripts,
  in time order, each stamped with its date — plus today's date. That's all Claude
  needs to reason about time ("today", "last week", "my first recording") and meaning
  ("funny", "the interview") at once. No keyword guessing, no separate search index —
  the notes reel already wrote, read the way you'd read them.

  Claude is driven as a *one-shot* search assistant, not a chat partner: a focused
  system prompt replaces Claude Code's interactive persona, so `reel find` answers
  the question directly instead of asking "what would you like to know?". The answer
  ends with machine-readable `FILE:` lines naming the recordings it used; reel turns
  those into clickable links and never shows them as raw text.

Reaching Claude, in order: the `claude` command (Claude Code) if installed — your
own Claude, no API key; else the Anthropic API if a key is set; else it falls back
to a plain keyword search so `reel find` always does something.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
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

# A line in Claude's answer that names a recording it used:  "FILE: <stem>".
# Tolerant of markdown the model might add (bullets, bold, backticks).
_FILE_LINE = re.compile(r"^[\s\-\*•>]*\*{0,2}FILE:\*{0,2}\s*(.+?)\s*$", re.IGNORECASE)


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


def _gather_context(cfg: Config, question: str) -> tuple[str, int, int, bool, list]:
    """The transcripts handed to Claude: every recording, in chronological order,
    each headed by its name, recorded date/time, and folder. If the whole library
    fits, all of it goes (best answers); if not, we keep the most relevant +
    recent and flag it. Returns (context, included, total, truncated, items),
    where items is the list of (when, score, recording_path, text) actually sent —
    so the caller can turn the recordings Claude names back into clickable links."""
    root = Path(cfg.sync_root)
    if not root.exists():
        return "", 0, 0, False, []
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
        return "", 0, 0, False, []

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
    return "\n".join(blocks), len(items), total, truncated, items


# The instruction reel hands Claude, as the single -p prompt. It does double duty:
# it turns Claude Code from a chatty interactive agent into a one-shot search box
# (the cure for "what would you like to know?"), AND it asks for the trailing
# FILE: lines reel turns into clickable links.
#
# Why one prompt and not --system-prompt? On Windows `claude` is a .CMD batch
# wrapper, and a second large multi-line argument gets mangled by cmd.exe's
# argument parsing — the model then sees garbled instructions and "finds no query".
# A single -p prompt with the recordings on stdin is the combination that works
# reliably on every platform.
def _instruction(question: str, truncated: bool) -> str:
    """What we tell Claude to do with the recordings (the whole -p prompt)."""
    now = datetime.now()
    note = ("\n\nNote: this person has a large library, so you're seeing the most "
            "relevant and most recent recordings, not every one — say so if it "
            "matters.") if truncated else ""
    return (
        "You are reel, a search assistant for someone's own voice-recording "
        "transcripts. This is a ONE-SHOT command, not a conversation: they typed a "
        "single request and cannot reply to you, so answer it directly, fully, and "
        "right now. Do NOT ask a clarifying question. Do NOT open with a greeting or "
        "with offers like 'what would you like to know?' / 'what would you like to "
        "explore?' / 'I've got your recordings loaded up' — there is nobody to answer "
        "you. Lead with the answer itself. Do not use any tools; answer only from the "
        "transcripts given to you as input.\n\n"
        f"Today is {now:%A, %B %d, %Y}; the current time is {now:%H:%M}. "
        "The transcripts of their recordings are provided to you as input, in "
        "chronological order; each starts with a header line "
        "'### <filename-stem>  —  recorded <weekday date time>  (<folder>)' followed "
        "by that recording's transcript.\n\n"
        "Reason about time relative to today: 'today', 'yesterday', 'last week', 'a "
        "month ago'; 'my first recording' = the earliest; 'my last N recordings' / "
        "'my latest' = the N most recent by recorded date. Match by MEANING, not just "
        "exact words ('funny', 'the interview', 'the phone number John gave me'). When "
        "asked for a list (e.g. 'my last 3 recordings'), actually list each one with "
        "its date and a one-line gist. Summarize across several recordings when that's "
        "what's asked. Be warm, natural, and concise — like a friend who remembers. "
        "Quote the words that matter and give friendly dates. If nothing matches, say "
        "so kindly and mention what you do have nearby in time. Never invent anything "
        "that isn't in the recordings.\n\n"
        "WRITE IN PLAIN TEXT ONLY. No Markdown of any kind: no asterisks, no **bold** "
        "or *italics*, no backticks, no '#' headings, no '>' quote marks, and no bullet "
        "characters ('-', '*', '•'). Just ordinary sentences. If you list items, number "
        "them like '1.' and '2.' on their own lines. Put quotes in plain double quotes, "
        "not in italics.\n\n"
        "FORMAT: after your answer, output one line for EACH recording you referenced "
        "or listed, in the order you mention them, exactly as 'FILE: <filename-stem>' "
        "— copying the stem verbatim from that recording's '###' header (no extension, "
        "no path, no quotes). A program reads these lines to build clickable links, so "
        "they must be exact. Put them at the very end, nothing after. If no recording "
        "is relevant, output no FILE: lines."
        f"{note}\n\nTheir request: {question}"
    )


def _ask_via_cli(question: str, context: str, truncated: bool, timeout: int = 240) -> str | None:
    """Ask through the `claude` command (Claude Code). Recordings go in on stdin
    (closed, so it doesn't wait); the instruction + request is the single -p prompt."""
    exe = shutil.which("claude")
    if not exe:
        return None
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW — no flash
    # CRITICAL (Windows): `claude` is a .CMD batch wrapper, and cmd.exe truncates a
    # command-line argument at the first newline — which would silently cut off the
    # tail of our prompt, INCLUDING the user's actual request ("Their request: …").
    # The model then sees only the opening persona + the transcripts and reports "no
    # search query". So flatten the prompt to a single line: collapse every run of
    # whitespace (newlines included) to one space. Reads the same to the model.
    prompt = " ".join(_instruction(question, truncated).split())
    try:
        r = subprocess.run([exe, "-p", prompt],
                           input=context, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           **kwargs)
        if r.returncode != 0:
            return None
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
            model="claude-sonnet-4-6",      # fast and more than capable for retrieval
            max_tokens=1500,
            messages=[{"role": "user",
                       "content": _instruction(question, truncated)
                       + "\n\nThe recordings:\n" + context}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text.strip() or None
    except Exception:
        return None


def _split_answer(answer: str) -> tuple[str, list[str]]:
    """Separate Claude's prose from the trailing 'FILE: <stem>' lines. Returns
    (clean_answer, [stems]) — the stems in the order the model named them."""
    stems: list[str] = []
    kept: list[str] = []
    for line in answer.splitlines():
        m = _FILE_LINE.match(line)
        if m:
            stem = m.group(1).strip().strip("`*_\"' ").strip()
            if stem:
                stems.append(stem)
        else:
            kept.append(line)
    return "\n".join(kept).strip(), stems


def _resolve_stem(raw: str, by_stem: dict) -> tuple | None:
    """Turn a stem Claude named back into the (recording_path, when) we sent it.
    Exact match first, then case-insensitive, then a forgiving substring match —
    so a small wording slip still lands on the right recording."""
    s = raw.strip()
    if s in by_stem:
        return by_stem[s]
    low = s.lower()
    for stem, info in by_stem.items():
        if stem.lower() == low:
            return info
    for stem, info in by_stem.items():
        sl = stem.lower()
        if low and (low in sl or sl in low):
            return info
    return None


_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_MD_UNDER = re.compile(r"__([^_]+)__")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_MD_QUOTE = re.compile(r"(?m)^\s*>\s?")
_MD_BULLET = re.compile(r"(?m)^\s*[-*•]\s+")
_MD_FENCE = re.compile(r"```[a-zA-Z0-9]*\n?")


def _strip_markdown(text: str) -> str:
    """Reduce a model's answer to clean plain prose: no asterisks, bold, headings,
    backticks, block quotes or bullet glyphs — just the words. (We also ask Claude
    for plain text, but this guarantees it even when a stray marker slips through.)"""
    t = _MD_FENCE.sub("", text).replace("`", "")
    t = _MD_LINK.sub(r"\1", t)
    t = _MD_BOLD.sub(r"\1", t)
    t = _MD_UNDER.sub(r"\1", t)
    t = _MD_ITALIC.sub(r"\1", t)
    t = _MD_HEADING.sub("", t)
    t = _MD_QUOTE.sub("", t)
    t = _MD_BULLET.sub("", t)
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _open_media(path: Path) -> bool:
    """Open a recording in the system's default player (so it just plays). On
    Windows that's whatever handles .mp3 — on this machine, the Media Player app."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))         # noqa: S606 — intended: default player
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except Exception:
        return False


def _last_find_path(cfg: Config) -> Path:
    return Path(cfg.sync_root) / ".reel" / "last_find.json"


def _save_last(cfg: Config, paths: list[Path]) -> None:
    """Remember the recordings from the latest find, so `reel play N` can open one
    even in a terminal where clicking the link isn't supported."""
    try:
        store = _last_find_path(cfg)
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps([str(p) for p in paths]), encoding="utf-8")
    except Exception:
        pass


def _print_file_link(con, rec: Path, when=None, index=None) -> None:
    """Print one recording as a clickable, play-on-click link. The path is turned
    into a properly percent-encoded file URI (so folders with spaces like 'IC
    RECORDER' still open), and clicking it launches the default media player. Links
    the audio file when present, otherwise its folder."""
    target = rec if rec.suffix else rec.parent
    label = rec.name if rec.suffix else f"{rec.stem} (folder)"
    try:
        uri = target.as_uri()               # correct %20 encoding for spaces etc.
    except Exception:
        uri = "file:///" + str(target).replace("\\", "/")
    num = f"[muted]{index}.[/muted] " if index else ""
    date = f"   [muted]{when:%Y-%m-%d %H:%M}[/muted]" if when else ""
    try:
        con.c.print(f"  {num}[accent]▶[/accent] [link={uri}]{label}[/link]{date}")
    except Exception:                       # no rich — plain, still openable path
        print(f"  {index or '▶'}  {target}")


def _show_links(con, recs: list[tuple], limit: int = 8) -> None:
    """Print the playable recordings beneath an answer — numbered, clickable, and
    with one quiet hint for terminals that don't do clickable links. No timestamps,
    no log chrome: just the files."""
    if not recs:
        return
    con.space()
    shown = recs[:limit]
    for i, (rec, when) in enumerate(shown, 1):
        _print_file_link(con, rec, when, index=i)
    hint = "click a file to play — or run  reel play 1"
    try:
        con.c.print(f"  [muted]{hint}[/muted]")
    except Exception:
        print(f"  ({hint})")


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
    context, n, total, truncated, items = _gather_context(cfg, q)
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

    clean, stems = _split_answer(answer)
    clean = _strip_markdown(clean)

    # The answer, plain — nothing before it, no log line after it.
    con.space()
    con.type_out(clean)

    # Turn the recordings Claude named into clickable, playable links. If it named
    # none, fall back to fast keyword hits so there's still something to play.
    by_stem = {rec.stem: (rec, when) for when, _s, rec, _t in items}
    recs: list[tuple] = []
    seen = set()
    for stem in stems:
        info = _resolve_stem(stem, by_stem)
        if info and info[0] not in seen:
            recs.append(info)
            seen.add(info[0])
    if not recs:
        for h in search.find_notes(cfg, q)[:5]:
            if h.recording not in seen:
                recs.append((h.recording, _recorded_at(h.recording.stem)))
                seen.add(h.recording)
    _save_last(cfg, [rec for rec, _w in recs])
    _show_links(con, recs)


def run_play(cfg: Config, con, which=None) -> None:
    """`reel play [N]` — play a recording from your most recent `reel find`,
    in the system's default media player. N is its number in that list (default 1).
    A guaranteed way to play even where the terminal can't open clickable links."""
    store = _last_find_path(cfg)
    paths: list[Path] = []
    if store.exists():
        try:
            paths = [Path(p) for p in json.loads(store.read_text(encoding="utf-8"))]
        except Exception:
            paths = []
    if not paths:
        con.warn("nothing to play yet — search first, e.g.  reel find my last recording")
        return
    try:
        n = int(which) if which not in (None, "") else 1
    except (TypeError, ValueError):
        con.warn(f"which one? give a number 1–{len(paths)}, e.g.  reel play 1")
        return
    if n < 1 or n > len(paths):
        con.warn(f"there are {len(paths)} to choose from — pick 1 to {len(paths)}.")
        return
    target = paths[n - 1]
    if not target.exists():
        con.warn(f"that recording isn't here anymore: {target.name}")
        return
    if _open_media(target):
        con.ok(f"playing {target.name}")
    else:
        con.warn(f"couldn't open it — it's here: {target}")

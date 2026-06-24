"""
transcribe.py — turn copied recordings into text, fully on your own machine.

At the end of every copy, reel looks through your library for MP3s that don't
have a transcript yet, listens to each one, and writes the words out next to it
as a plain .txt — same name, with '-transcript' on the end. So 'meeting.mp3'
gets 'meeting-transcript.txt' sitting right beside it.

It's incremental: a file that already has its transcript is skipped, so this only
ever does the new work. And it's fully local — the speech-to-text runs on your PC
(faster-whisper), nothing is uploaded anywhere.

Speech-to-text (faster-whisper) ships with reel, so this works out of the box.
The first transcript downloads the small model once (needs internet that one time);
after that it's fully local. If the engine is somehow missing, reel just says so
once and carries on copying — your files are never held up by it.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config

# The suffix we hang on the transcript file, before the .txt.
_SUFFIX = "-transcript"

# One model per process, loaded lazily the first time we actually need it (it's
# the slow, heavy part). Cached so a library full of recordings only pays once.
_MODEL = None
_MODEL_KEY = None


def transcript_path(mp3: Path) -> Path:
    """Where 'song.mp3' keeps its words: 'song-transcript.txt', right alongside."""
    return mp3.with_name(mp3.stem + _SUFFIX + ".txt")


def find_untranscribed(sync_root: Path) -> list[Path]:
    """Every MP3 in the library that doesn't have its transcript yet.

    We skip reel's own '.reel' bookkeeping folder, and any MP3 whose
    '<name>-transcript.txt' already exists next to it."""
    root = Path(sync_root)
    if not root.exists():
        return []
    out: list[Path] = []
    for mp3 in root.rglob("*"):
        if mp3.suffix.lower() != ".mp3" or not mp3.is_file():
            continue
        if ".reel" in mp3.parts:          # don't transcribe internal bookkeeping
            continue
        if transcript_path(mp3).exists():
            continue                      # already done — leave it be
        out.append(mp3)
    return sorted(out)


def _duration_minutes(mp3: Path) -> float | None:
    """Length of an MP3 in minutes, read cheaply from its header (mutagen, already
    a dependency). None if it can't be determined."""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(str(mp3))
        length = getattr(getattr(audio, "info", None), "length", None)
        return (length / 60.0) if length else None
    except Exception:
        return None


def _in_recordings_folder(mp3: Path, cfg: Config) -> bool:
    """True if the file lives in (or under) a recordings folder we care about —
    e.g. the recorder's 'REC_FILE' tree. Matched by folder name anywhere in the
    path. An empty allow-list means 'transcribe everywhere'."""
    only = [s.lower() for s in (getattr(cfg, "transcribe_only_folders", None) or [])]
    if not only:
        return True
    parts = {p.lower() for p in mp3.parts}
    return any(s in parts for s in only)


def _too_big(mp3: Path, cfg: Config) -> bool:
    """True for files we deliberately skip — long or large ones (music, soundtracks),
    which aren't voice memos and would grind for ages. Length is the real signal;
    size is the fallback when a file's length can't be read."""
    max_min = getattr(cfg, "transcribe_max_minutes", 0) or 0
    max_mb = getattr(cfg, "transcribe_max_mb", 0) or 0
    if max_mb:
        try:
            if mp3.stat().st_size / (1024 * 1024) > max_mb:
                return True
        except OSError:
            pass
    if max_min:
        mins = _duration_minutes(mp3)
        if mins is not None and mins > max_min:
            return True
    return False


def _load_model(cfg: Config):
    """Load (once) the local speech-to-text model. Returns the model, or None if
    the faster-whisper add-on isn't installed."""
    global _MODEL, _MODEL_KEY
    key = (cfg.transcribe_model,)
    if _MODEL is not None and _MODEL_KEY == key:
        return _MODEL
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    # int8 on CPU keeps it light and works on any machine without a GPU.
    _MODEL = WhisperModel(cfg.transcribe_model, device="cpu", compute_type="int8")
    _MODEL_KEY = key
    return _MODEL


def _transcribe_one(model, mp3: Path, language: str | None,
                    initial_prompt: str | None = None) -> str:
    """Listen to one file and return its text (may be empty for silence).

    Two quality levers beyond the model size:
      - vad_filter trims silence before transcribing, which both speeds things up
        and stops the model from hallucinating words into quiet gaps.
      - initial_prompt seeds the decoder with your own vocabulary (names, places,
        jargon) so it spells them the way you do — e.g. 'en passant', not 'amputant'.
    """
    segments, _info = model.transcribe(
        str(mp3),
        language=language or None,
        vad_filter=True,
        beam_size=5,
        initial_prompt=initial_prompt or None,
    )
    return "".join(seg.text for seg in segments).strip()


def transcribe_library(cfg: Config, con) -> int:
    """The end-of-session pass: find every MP3 without a transcript and make one.
    Returns how many transcripts were written this time."""
    if not getattr(cfg, "transcribe_enabled", True):
        return 0

    written = 0
    found = find_untranscribed(cfg.sync_root)
    if found:
        # Only the recordings: files inside a recordings folder (REC_FILE, …) — or
        # already filed under a <year>/<month> date folder — and not absurdly
        # long/large. Music and sound effects are ignored.
        from . import organize          # lazy: organize imports us back
        pending = [p for p in found
                   if (_in_recordings_folder(p, cfg)
                       or organize.in_date_folder(p, cfg.sync_root))
                   and not _too_big(p, cfg)]
        skipped = len(found) - len(pending)
        if skipped:
            con.dim(f"skipping {skipped} file(s) outside the recordings folder (music, sound effects, …)")

        if pending:
            model = _load_model(cfg)
            if model is None:
                # There IS work to do but the add-on is missing — say it once,
                # plainly, and move on. Copying is never blocked by this.
                con.space()
                con.warn(f"{len(pending)} recording(s) still need transcripts, but the "
                         "text add-on isn't installed yet.")
                con.dim("turn recordings into text — one-time setup:  pip install faster-whisper")
            else:
                con.space()
                con.info(f"writing transcripts for {len(pending)} new recording(s)…")
                bar = con.progress()
                with bar:
                    tid = bar.add_task("transcribing", total=len(pending), name="")
                    for mp3 in pending:
                        bar.update(tid, name=mp3.name)
                        try:
                            text = _transcribe_one(model, mp3, cfg.transcribe_language,
                                                   cfg.transcribe_initial_prompt)
                            transcript_path(mp3).write_text(text + "\n", encoding="utf-8")
                            written += 1
                        except Exception as e:
                            # One bad file must never sink the rest — note it, carry on.
                            con.err(f"couldn't transcribe {mp3.name}: {e}")
                        finally:
                            bar.update(tid, advance=1)
                if written:
                    con.ok(f"transcribed {written} recording(s) — text saved next to each one.")

    return written


def retranscribe_library(cfg: Config, con) -> int:
    """Re-do the transcripts you already have, with the current model and settings.
    Use this after raising the model size or changing the vocabulary hint, to bring
    older recordings up to the new quality. Deletes each in-scope transcript and
    lets the normal pass rewrite it."""
    root = Path(cfg.sync_root)
    if not root.exists():
        con.warn("no library yet — nothing to re-transcribe.")
        return 0
    from . import organize              # lazy: organize imports us back
    removed = 0
    for mp3 in root.rglob("*"):
        if mp3.suffix.lower() != ".mp3" or not mp3.is_file():
            continue
        if ".reel" in mp3.parts:
            continue
        if not (_in_recordings_folder(mp3, cfg) or organize.in_date_folder(mp3, cfg.sync_root)):
            continue
        tp = transcript_path(mp3)
        if tp.exists():
            try:
                tp.unlink()
                removed += 1
            except OSError:
                pass
    if not removed:
        con.info("no existing transcripts to redo — run a normal copy to make some.")
        return 0
    con.info(f"re-transcribing {removed} recording(s) with the '{cfg.transcribe_model}' "
             "model — this can take a few minutes…")
    return transcribe_library(cfg, con)

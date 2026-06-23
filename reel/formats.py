"""
formats.py — the "art of the data". How we name files *well* without a neural net.

We never invent meaning. We extract the meaning that's already there but hidden:
the date a photo was taken (encoded in a known filename template), whether a name
is a real word or just a camera serial, the noise tokens worth dropping. EXIF and
ID3 tags are read elsewhere (naming.py); this module is the filename intelligence.

Two jobs:
  • find_date(stem)   → the timestamp baked into a filename, by known template
  • clean_label / is_meaningful → tell a real name from boilerplate camera noise
"""
from __future__ import annotations

import re
from datetime import datetime

# Tokens that carry no meaning — camera/phone/app prefixes and generic words. When
# a name is *only* these (plus digits), it's boilerplate and we'd rather use a date.
NOISE = {
    # camera / phone capture prefixes
    "img", "dsc", "dscf", "dscn", "mvi", "vid", "pxl", "gopr", "gh", "dji",
    "p", "pict", "photo", "video", "pic", "image", "dcim", "mov", "clip",
    # messaging / capture-source counters
    "aud", "ptt", "wa", "screenshot",  # 'screenshot' is noise as a *token*, but see note
    # generic audio boilerplate
    "track", "audio", "recording", "rec", "voice", "sound", "untitled", "new",
    "file", "copy", "capture", "snap", "burst",
}
# 'screenshot' we actually like to KEEP as a label, so it's excluded from NOISE
# for the media path; remove it here so clean_label preserves it.
NOISE.discard("screenshot")

_TOKEN = re.compile(r"[A-Za-z]+|\d+")


def _dt(y, mo, d, h=0, mi=0, s=0):
    """Build a datetime, or None if the numbers aren't a real date/time."""
    try:
        if y < 100:               # 2-digit year (IC recorder etc.) → 20xx
            y += 2000
        if not (1970 <= y <= 2100):
            return None
        return datetime(y, mo, d, h, mi, s)
    except (ValueError, TypeError):
        return None


def _g(m, name, default=0):
    """An optional numeric group's int value, or `default` if it didn't match."""
    try:
        v = m.group(name)
    except Exception:
        return default
    return int(v) if v else default


# Date templates, most specific (with time) first. Each entry: (regex, builder).
# `search`ed against the filename stem; first one that yields a real datetime wins.
_PATTERNS = [
    # WhatsApp:  IMG-20240615-WA0001 / VID-... (date only)
    (re.compile(r"(?:IMG|VID|AUD|PTT)-(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})-WA\d+", re.I),
     lambda m: _dt(int(m["y"]), int(m["mo"]), int(m["d"]))),
    # Signal:  signal-2024-06-15-14-30-22
    (re.compile(r"signal[-_](?P<y>\d{4})[-_](?P<mo>\d{2})[-_](?P<d>\d{2})[-_]"
                r"(?P<h>\d{2})[-_](?P<mi>\d{2})[-_](?P<s>\d{2})", re.I),
     lambda m: _dt(int(m["y"]), int(m["mo"]), int(m["d"]), int(m["h"]), int(m["mi"]), int(m["s"]))),
    # Full stamp:  20240615_143022 / 20240615T143022 / 20240615-143022 / 20240615143022
    (re.compile(r"(?<!\d)(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})[ _\-T]?"
                r"(?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})(?!\d)"),
     lambda m: _dt(int(m["y"]), int(m["mo"]), int(m["d"]), int(m["h"]), int(m["mi"]), int(m["s"]))),
    # YYYYMMDD_HHMM
    (re.compile(r"(?<!\d)(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})[ _\-T](?P<h>\d{2})(?P<mi>\d{2})(?!\d)"),
     lambda m: _dt(int(m["y"]), int(m["mo"]), int(m["d"]), int(m["h"]), int(m["mi"]))),
    # Screenshots:  2024-06-15 at 14.30.22 / 2024-06-15_14-30-22 / 2024.06.15-14.30
    (re.compile(r"(?<!\d)(?P<y>\d{4})[\-_.](?P<mo>\d{2})[\-_.](?P<d>\d{2})"
                r"(?:[ _]?(?:at[ _])?(?P<h>\d{2})[.\-:_](?P<mi>\d{2})(?:[.\-:_](?P<s>\d{2}))?)?", re.I),
     lambda m: _dt(int(m["y"]), int(m["mo"]), int(m["d"]),
                   _g(m, "h"), _g(m, "mi"), _g(m, "s"))),
    # IC recorder / some phones:  YYMMDD_HHMM   (240615_1430)
    (re.compile(r"(?<!\d)(?P<y>\d{2})(?P<mo>\d{2})(?P<d>\d{2})[_\-](?P<h>\d{2})(?P<mi>\d{2})(?!\d)"),
     lambda m: _dt(int(m["y"]), int(m["mo"]), int(m["d"]), int(m["h"]), int(m["mi"]))),
    # Date only:  20240615 / 2024-06-15 / 2024_06_15
    (re.compile(r"(?<!\d)(?P<y>\d{4})[\-_.]?(?P<mo>\d{2})[\-_.]?(?P<d>\d{2})(?!\d)"),
     lambda m: _dt(int(m["y"]), int(m["mo"]), int(m["d"]))),
]


def find_date(stem: str) -> tuple[datetime | None, str | None]:
    """The timestamp baked into a filename, plus the exact text that encoded it
    (so the caller can strip it). (None, None) if no known template matches."""
    for rx, build in _PATTERNS:
        for m in rx.finditer(stem):
            dt = build(m)
            if dt:
                return dt, m.group(0)
    return None, None


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _keep(tok: str) -> bool:
    return tok.lower() not in NOISE and not tok.isdigit()


def is_meaningful(stem: str) -> bool:
    """True if the name has a real word — not just a camera serial / counter."""
    return any(_keep(t) and any(c.isalpha() for c in t) for t in _tokens(stem))


def clean_label(text: str) -> str:
    """Drop noise prefixes and bare numbers; join what's left. '' if nothing real
    remains (the caller then falls back to a short content id)."""
    return "_".join(t for t in _tokens(text) if _keep(t))

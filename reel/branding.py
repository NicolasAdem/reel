"""
branding.py â€” reel's identity in one place.

The brand is always lowercase: it's "reel", never "Reel" or "REEL".
Clean and modern: a calm wordmark, light by default, dark on request.
Colours are chosen to read on a WHITE terminal first; dark just brightens them.
"""

NAME = "reel"
VERSION = "3.5.0"
TAGLINE = "plug it in, copied"

# A small, tasteful lowercase wordmark. Printed once at the top of a run.
LOGO = r"""
                 _
  _ __ ___  ___ | |   Â·  {tag}
 | '__/ _ \/ _ \| |
 | | |  __/  __/| |
 |_|  \___|\___||_|   {ver}
"""

# Big "Welcome" wordmark, shown on first-time setup.
WELCOME_ART = r"""
__        __   _
\ \      / /__| | ___ ___  _ __ ___   ___
 \ \ /\ / / _ \ |/ __/ _ \| '_ ` _ \ / _ \
  \ V  V /  __/ | (_| (_) | | | | | |  __/
   \_/\_/ \___|_|\___\___/|_| |_| |_|\___|
"""

# Semantic styles per theme. Keys are used by console.py to build a rich Theme.
# Light = default (assumes a white/bright terminal background).
THEMES = {
    "light": {
        "brand":   "bold #0b5fa5",   # deep blue wordmark
        "accent":  "#0b5fa5",
        "ok":      "bold #1a7f37",   # green
        "warn":    "bold #9a6700",   # amber-brown
        "err":     "bold #cf222e",   # red
        "muted":   "#6e7781",        # grey
        "value":   "default",        # the terminal's own fg â€” readable on any bg
        "bar":     "#0b5fa5",
        "bar_bg":  "#d0d7de",
    },
    "dark": {
        "brand":   "bold #4493f8",
        "accent":  "#4493f8",
        "ok":      "bold #3fb950",
        "warn":    "bold #d29922",
        "err":     "bold #f85149",
        "muted":   "#8b949e",
        "value":   "default",
        "bar":     "#4493f8",
        "bar_bg":  "#30363d",
    },
}

# â”€â”€ Any-device support â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The *kind* of device reel thinks it's looking at â€” used only for the glyph and
# friendly label in messages. Every kind is copied exactly the same way.
DEVICE_GLYPH = {
    "recorder": "â–¤",
    "camera":   "â–£",
    "music":    "â™ª",
    "phone":    "â–¢",
    "generic":  "â–¸",
}
DEVICE_LABEL = {
    "recorder": "voice recorder",
    "camera":   "camera",
    "music":    "music stick",
    "phone":    "phone",
    "generic":  "USB drive",
}

# File kinds â€” how copied files are tallied in the summary (and which naming rule
# applies). Files are never moved between folders by kind.
FILE_KINDS = ["Photos", "Videos", "Audio", "Documents", "Archives", "Other"]
FILE_KIND_GLYPH = {
    "Photos":    "â–¦",
    "Videos":    "â–·",
    "Audio":     "â™ª",
    "Documents": "â–¥",
    "Archives":  "â–£",
    "Other":     "Â·",
}
FILE_KIND_COLOR = {
    "Photos":    "magenta",
    "Videos":    "blue",
    "Audio":     "cyan",
    "Documents": "green",
    "Archives":  "yellow",
    "Other":     "white",
}

# The lookups the summary code uses to render whatever buckets a copy produced.
LABEL_GLYPH = FILE_KIND_GLYPH
LABEL_COLOR = FILE_KIND_COLOR

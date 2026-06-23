#!/usr/bin/env python3
"""Launcher. Same as `python -m reel ...`."""
import sys
from reel.__main__ import main
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

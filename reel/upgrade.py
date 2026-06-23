"""
upgrade.py — `reel upgrade`: pull the latest reel from PyPI, in one command.

reel is published as `reel-sync`, so an upgrade is really just
`pip install --upgrade reel-sync`. Two wrinkles this module handles for you:

  • It checks PyPI first and tells you the version jump (or that you're current),
    so the command is safe to run any time — it does nothing if there's nothing new.

  • On Windows, the running `reel.exe` launcher is locked while `reel upgrade`
    runs, so pip can't replace it. We hand the actual install to a small detached
    helper that waits for this process to exit, runs pip in its own window, and
    then restarts the background watcher on the new version. You just see "updating
    in a new window…" and this one steps aside.

A development checkout (`pip install -e .`) is detected and left alone — there's
nothing on PyPI newer than your own working tree, and pip shouldn't clobber it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

PACKAGE = "reel-sync"
_PYPI_JSON = f"https://pypi.org/pypi/{PACKAGE}/json"


# ── version helpers ──────────────────────────────────────────────────────────
def _ver_tuple(v: str) -> tuple:
    """A lenient (major, minor, patch, …) tuple. Stops at the first non-digit in
    each dotted part, so '3.1.0' and even '3.1.0rc1' compare sensibly enough for
    'is there a newer release?'."""
    out = []
    for part in str(v).split("."):
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return tuple(out)


def is_newer(latest: str, current: str) -> bool:
    return _ver_tuple(latest) > _ver_tuple(current)


def latest_version(timeout: float = 6.0) -> str | None:
    """The newest version of reel-sync on PyPI, or None if PyPI can't be reached."""
    try:
        req = urllib.request.Request(_PYPI_JSON, headers={"User-Agent": "reel-upgrade"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["info"]["version"]
    except Exception:
        return None


def is_editable_install() -> bool:
    """True if reel is running from a source checkout (pyproject.toml sits next to
    the package) rather than an installed wheel. pip-upgrade doesn't apply there."""
    return (Path(__file__).resolve().parent.parent / "pyproject.toml").exists()


# ── the command ──────────────────────────────────────────────────────────────
def run(cfg, con) -> None:
    from . import __version__
    cur = __version__
    con.info(f"reel v{cur} — checking PyPI for a newer version…")
    latest = latest_version()

    if latest is None:
        con.warn("couldn't reach PyPI. Check your internet connection and try again.")
        con.dim("(or update manually:  pip install --upgrade reel-sync)")
        return
    if not is_newer(latest, cur):
        con.ok(f"You're already on the latest version (v{cur}). Nothing to do. 🎬")
        return

    con.info(f"New version available:  v{cur}  →  [value]v{latest}[/value]")

    if is_editable_install():
        con.warn("this is a development install (pip install -e .) — pip won't update it.")
        con.dim("update your checkout with 'git pull' (or reinstall from PyPI).")
        return

    _apply(cfg, con, latest)


# Standalone helper run in a fresh process *after* `reel upgrade` exits, so the
# locked reel.exe is free to be replaced. Uses only stdlib + plain `python -m`,
# never imports the reel package mid-replacement. {py}/{pkg} are filled in below.
_WIN_HELPER = (
    "import subprocess, sys, time\n"
    "print('reel updater - installing the latest version...')\n"
    "print()\n"
    "time.sleep(2)\n"          # let reel.exe fully exit so pip can replace it
    "r = subprocess.run([{py}, '-m', 'pip', 'install', '--upgrade', '{pkg}'])\n"
    "print()\n"
    "if r.returncode == 0:\n"
    "    print('Updated. Restarting reel in the background...')\n"
    "    subprocess.run([{py}, '-m', 'reel', 'auto', 'restart'])\n"
    "    print('Done - reel is running the new version. You can close this window.')\n"
    "else:\n"
    "    print('Update failed. Try running:  pip install --upgrade reel-sync')\n"
    "input('\\nPress Enter to close...')\n"
)


def _apply(cfg, con, latest: str) -> None:
    py = sys.executable
    if sys.platform == "win32":
        helper = _WIN_HELPER.format(py=repr(py), pkg=PACKAGE)
        CREATE_NEW_CONSOLE = 0x00000010
        try:
            subprocess.Popen([py, "-c", helper],
                             creationflags=CREATE_NEW_CONSOLE, close_fds=True)
        except Exception as e:
            con.err(f"couldn't start the updater: {e}")
            con.dim("update manually:  pip install --upgrade reel-sync")
            return
        con.ok(f"Updating to v{latest} in a new window — this one can close now.")
        con.dim("reel will pick the new version right back up.")
        import os
        os._exit(0)   # release the locked reel.exe launcher for pip to replace
    else:
        con.info(f"updating to v{latest}…")
        code = subprocess.run([py, "-m", "pip", "install", "--upgrade", PACKAGE]).returncode
        if code != 0:
            con.err("pip couldn't complete the update.")
            con.dim("try:  pip install --upgrade reel-sync")
            return
        restart_watcher(cfg)
        con.ok(f"Updated to v{latest}. 🎬")


def restart_watcher(cfg) -> None:
    """Make sure the always-on watcher is running the freshly-installed code:
    install at login (idempotent), stop any old watcher, launch a new one."""
    from . import autostart
    try:
        autostart.install()
        autostart.stop_running(cfg)
        autostart.launch_background(cfg)
    except Exception:
        pass

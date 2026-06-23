"""
autostart.py — make reel truly hands-off. It launches itself at login and waits,
invisibly, in the background. The moment you plug a drive in, a window pops up and
shows the sync (logo + progress bars); when it's done the window tucks itself to the
taskbar as a calm "all synced" spinner; when you unplug, the window vanishes and the
background watcher goes back to waiting.

  reel auto            turn it on  (install at login + start the watcher now)
  reel auto off        turn it off (remove from login + stop the watcher)
  reel auto status     is it installed / running right now?
  reel auto run        the hidden background watcher (what login launches)
  reel auto session    the visible per-drive sync window (what the watcher pops open)

Reliability over cleverness: the watcher polls every couple of seconds for a drive
and only opens a window on an absent→present transition (so a window that exits early
never spams). A 2–3s poll is effectively instant. (Event-driven `WM_DEVICECHANGE`
wake is a roadmap nicety, not a correctness need.)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config


# ── where the login launcher and runtime files live ──────────────────────────
def _startup_dir() -> Path:
    return (Path(os.environ.get("APPDATA", Path.home()))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")


def _launcher_path(startup: Path | None = None) -> Path:
    return (startup or _startup_dir()) / "reel.vbs"


# Older versions used a different launcher filename; clean it up so we never leave
# two launchers behind after a rename of the brand.
_LEGACY_LAUNCHERS = ("Reel auto-sync.vbs",)


def _remove_legacy(startup: Path) -> None:
    for name in _LEGACY_LAUNCHERS:
        old = startup / name
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass


def _pythonw() -> Path:
    """The windowed (no-console) interpreter, so the watcher runs invisibly."""
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return cand if cand.exists() else exe


# The watcher's runtime files live in a STABLE spot (~/.reel), not inside the
# library — so they keep working even after you move the library folder.
def _runtime_dir() -> Path:
    return Path.home() / ".reel"


def _pid_path(cfg: Config) -> Path:
    return _runtime_dir() / "auto.pid"


def _log_path(cfg: Config) -> Path:
    return _runtime_dir() / "auto.log"


def _pause_path(cfg: Config) -> Path:
    return _runtime_dir() / "auto.paused"


# ── pause / resume the watcher (used by `reel transfer`) ──────────────────────
# A flag file, not a process kill: the running watcher checks it each tick and
# does nothing while it's there. So a restore can write to a card without the
# watcher popping a window or trying to re-sync mid-transfer.
def pause(cfg: Config) -> None:
    p = _pause_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")


def resume(cfg: Config) -> None:
    try:
        _pause_path(cfg).unlink()
    except OSError:
        pass


def is_paused(cfg: Config) -> bool:
    return _pause_path(cfg).exists()


# ── install / uninstall the at-login launcher ────────────────────────────────
def install(startup: Path | None = None) -> Path:
    """Drop a hidden launcher into the Startup folder so reel watches from login.
    A .vbs (window style 0) starts pythonw with no flash and no console at all."""
    path = _launcher_path(startup)
    path.parent.mkdir(parents=True, exist_ok=True)
    _remove_legacy(path.parent)              # drop any old capitalised launcher
    cmd = f'""{_pythonw()}"" -m reel auto run'   # "" → " once inside the VBS string
    path.write_text(
        "' reel — copies any drive at login (hidden). Delete this file to disable.\r\n"
        f'CreateObject("WScript.Shell").Run "{cmd}", 0, False\r\n',
        encoding="utf-8")
    return path


def uninstall(startup: Path | None = None) -> bool:
    path = _launcher_path(startup)
    if path.exists():
        path.unlink()
        return True
    return False


def is_installed(startup: Path | None = None) -> bool:
    return _launcher_path(startup).exists()


# ── start / stop the running watcher ─────────────────────────────────────────
def launch_background(cfg: Config) -> None:
    """Start the hidden watcher right now, so the user needn't log out and in."""
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen([str(_pythonw()), "-m", "reel", "auto", "run"],
                         creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                         close_fds=True)
    else:
        subprocess.Popen([sys.executable, "-m", "reel", "auto", "run"],
                         start_new_session=True)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True,
                             creationflags=0x08000000)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running_pid(cfg: Config) -> int | None:
    p = _pid_path(cfg)
    if not p.exists():
        return None
    try:
        pid = int(p.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return pid if _pid_alive(pid) else None


def stop_running(cfg: Config) -> bool:
    pid = running_pid(cfg)
    if pid is None:
        return False
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=0x08000000)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    try:
        _pid_path(cfg).unlink()
    except OSError:
        pass
    return True


# ── the resident watcher ─────────────────────────────────────────────────────
# The hidden background process does ONE thing: notice when a drive is plugged in,
# and pop open a *visible* console that shows the sync (logo, progress bars), tucks
# itself to the taskbar when done, and closes when you unplug. Then it waits again.
def _device_present(cfg: Config) -> bool:
    from . import device
    return bool(device.find_devices(cfg))


def _console_python() -> Path:
    """python.exe (with a console), even if we're running under pythonw.exe."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return cand
    return exe


def open_sync_window(wait: bool = True) -> subprocess.Popen:
    """Pop a fresh, visible console running the per-device sync UI. Blocks (when
    `wait`) until that window closes — which happens when the drive is unplugged."""
    args = [str(_console_python()), "-m", "reel", "auto", "session"]
    if sys.platform == "win32":
        CREATE_NEW_CONSOLE = 0x00000010
        proc = subprocess.Popen(args, creationflags=CREATE_NEW_CONSOLE)
    else:
        proc = subprocess.Popen(args)
    if wait:
        proc.wait()
    return proc


def run_resident(cfg: Config) -> None:
    """The hidden background loop: when a drive appears, open the visible sync
    window and wait for it to close (on unplug); then keep waiting for the next.
    Crash-safe — only opens on an absent→present transition, so a window that
    exits early never spams. Logs to .reel/auto.log."""
    pidp = _pid_path(cfg)
    pidp.parent.mkdir(parents=True, exist_ok=True)
    pidp.write_text(str(os.getpid()), encoding="utf-8")
    logf = open(_log_path(cfg), "a", encoding="utf-8", buffering=1)

    def log(msg: str) -> None:
        logf.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
        logf.flush()

    log("reel auto: watcher started — waiting for drives.")
    interval = min(max(1, cfg.watch_interval_sec), 3)
    was_present = False
    try:
        while True:
            try:
                if is_paused(cfg):           # a restore is in progress — stand down
                    was_present = False
                    time.sleep(interval)
                    continue
                present = _device_present(cfg)
                if present and not was_present:
                    log("drive detected — opening sync window.")
                    open_sync_window(wait=True)       # blocks until the window closes
                    log("sync window closed — back to waiting.")
                    was_present = _device_present(cfg)  # re-check (usually unplugged now)
                else:
                    was_present = present
            except Exception as e:
                log(f"resident error: {type(e).__name__}: {e}")
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        log("reel auto: watcher stopped.")
        try:
            pidp.unlink()
        except OSError:
            pass

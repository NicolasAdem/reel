"""
notify.py — a quiet native toast after a background copy ("reel — copied 12 files
from KINGSTON"). Complements the pop-up window: the window shows the live copy, the
toast leaves a summary in the notification centre for when you're looking elsewhere.

Zero dependencies, by design. On Windows it asks the OS to show a real toast via the
built-in WinRT notifier (no tray icon to manage, no ghost icons). Anywhere else, or
if anything goes wrong, it's a silent no-op — a notification must never break a sync.
"""
from __future__ import annotations

import subprocess
import sys


def _ps_lit(s: str, limit: int) -> str:
    """Make text safe inside a single-quoted PowerShell string."""
    s = "".join(ch for ch in s if ch >= " ")  # drop control chars
    return s[:limit].replace("'", "''")


def toast(title: str, message: str) -> bool:
    """Show a toast. Returns True if the OS accepted it; never raises."""
    if sys.platform != "win32":
        return False
    t = _ps_lit(title, 60)
    m = _ps_lit(message, 180)
    script = (
        "$ErrorActionPreference='Stop';"
        "[void][Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$e=$x.GetElementsByTagName('text');"
        f"[void]$e.Item(0).AppendChild($x.CreateTextNode('{t}'));"
        f"[void]$e.Item(1).AppendChild($x.CreateTextNode('{m}'));"
        "$n=[Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'reel').Show($n);"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=10, creationflags=0x08000000)  # CREATE_NO_WINDOW
        return r.returncode == 0
    except Exception:
        return False

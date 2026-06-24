"""console.py — reel's terminal voice. Rich if available, plain print otherwise.

Theme defaults to LIGHT (colours tuned for a white background); pass theme="dark"
to brighten. Exposes a single progress-bar helper used by the sync run.
"""
from __future__ import annotations

from datetime import datetime

from . import branding

try:
    from rich.console import Console
    from rich.theme import Theme
    from rich.panel import Panel
    from rich.progress import (Progress, SpinnerColumn, BarColumn, TextColumn,
                               TimeRemainingColumn, MofNCompleteColumn)
    _RICH = True
except Exception:  # pragma: no cover
    _RICH = False


class Reel:
    """One console, themed once. Everything prints through here."""

    def __init__(self, theme: str = "light"):
        self.theme_name = theme if theme in branding.THEMES else "light"
        pal = branding.THEMES[self.theme_name]
        self.pal = pal
        if _RICH:
            self.c = Console(theme=Theme({
                "brand": pal["brand"], "accent": pal["accent"], "ok": pal["ok"],
                "warn": pal["warn"], "err": pal["err"], "muted": pal["muted"],
                "value": pal["value"],
            }))
        else:
            self.c = None

    # --- chrome ---------------------------------------------------------
    def logo(self) -> None:
        art = branding.LOGO.format(tag=branding.TAGLINE, ver=f"v{branding.VERSION}")
        if _RICH:
            self.c.print(f"[brand]{art}[/brand]")
        else:
            print(art)

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def log(self, kind: str, msg: str) -> None:
        tag = {"ok": " OK ", "warn": "WARN", "err": "FAIL",
               "info": "  » ", "dim": "  · "}.get(kind, "    ")
        style = {"ok": "ok", "warn": "warn", "err": "err",
                 "info": "accent", "dim": "muted"}.get(kind, "value")
        if _RICH:
            self.c.print(f"[muted]{self._ts()}[/muted] [{style}]{tag}[/{style}] {msg}")
        else:
            print(f"{self._ts()} {kind.upper():>4} {msg}")

    def info(self, m): self.log("info", m)
    def ok(self, m): self.log("ok", m)
    def warn(self, m): self.log("warn", m)
    def err(self, m): self.log("err", m)
    def dim(self, m): self.log("dim", m)

    def panel(self, title: str, body: str) -> None:
        if _RICH:
            self.c.print(Panel(body, title=title, border_style="accent",
                               title_align="left", padding=(0, 1)))
        else:
            print(f"== {title} ==\n{body}\n")

    def rule(self, text: str = "") -> None:
        if _RICH:
            self.c.rule(f"[accent]{text}[/accent]" if text else "")
        else:
            print(("-- " + text + " ").ljust(60, "-") if text else "-" * 60)

    # --- big wordmarks + celebration -----------------------------------
    def _big(self, art: str, style: str = "brand"):
        """Center a multi-line ASCII wordmark in the given style."""
        from rich.text import Text
        from rich.align import Align
        self.c.print(Align.center(Text(art.strip("\n"), style=style)))

    def _sprinkle(self, rows: int = 3, frames: int = 8):
        """A gentle, brief confetti drift (transient — erased afterwards)."""
        import random
        import time
        from rich.text import Text
        from rich.live import Live
        from rich.align import Align

        glyphs = "·•✦✧∗"
        palette = ["cyan", "blue", "magenta", "green", "bright_cyan", "bright_blue"]
        width = min((self.c.size.width or 72), 66)

        def row() -> Text:
            t = Text()
            for _ in range(max(6, width // 3)):
                t.append(random.choice(glyphs) + "  ", style=random.choice(palette))
            return t
        try:
            with Live(refresh_per_second=10, console=self.c, transient=True) as live:
                for _ in range(frames):
                    block = Text()
                    for _ in range(rows):
                        block.append_text(row())
                        block.append("\n")
                    live.update(Align.center(block))
                    time.sleep(0.06)
        except Exception:
            pass

    def celebrate(self, lines: list[str]) -> None:
        """First-run welcome: a gentle sprinkle, the big WELCOME, a readable note."""
        if not _RICH:
            print(branding.WELCOME_ART)
            for ln in lines:
                print("  " + ln)
            print()
            return
        self.c.print()
        self._sprinkle(rows=3, frames=8)
        self._big(branding.WELCOME_ART, style="accent")
        self.c.print()
        body = "\n".join(lines)          # default fg -> readable on any terminal
        self.c.print(Panel(body, border_style="accent", padding=(1, 3)))

    def splash(self) -> None:
        """What `reel` (no command) shows: the big wordmark + a quick map."""
        self.logo()
        if _RICH:
            self._sprinkle(rows=1, frames=5)
        body = (
            "Plug in any USB drive, SD card or recorder — reel copies the\n"
            "whole thing into a 'reel' folder in your Documents, then tidies\n"
            "the names. Always on. Fully local.\n\n"
            "[accent]First time here[/accent]      reel setup     (run once — that's all)\n"
            "[accent]Back onto a stick[/accent]    reel transfer\n"
            "[accent]Name-tidying[/accent]         reel rename on|off\n"
            "[accent]Update reel[/accent]          reel upgrade\n\n"
            "[muted]Details[/muted]              reel help"
        )
        if _RICH:
            self.c.print(Panel(body, title="welcome to reel", title_align="left",
                               border_style="accent", padding=(1, 3)))
        else:
            print("\nwelcome to reel\n  reel setup | transfer | rename | upgrade | --help\n")

    def space(self) -> None:
        if _RICH:
            self.c.print()
        else:
            print()

    def close_terminal(self, delay: float = 0.0) -> None:
        """Close the whole terminal window (not just exit to the prompt).

        We target the *console window* itself rather than a parent PID, because
        the launcher chain (cmd -> reel.exe -> python) means our parent isn't the
        shell. Every process attached to a console shares one window; closing it
        (and killing the process that owns it) takes the whole window down — no
        matter how many launcher layers sit in between. Default: immediate.
        """
        import os
        import sys
        import time
        if delay and delay > 0:
            time.sleep(delay)
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                import subprocess
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    owner = wintypes.DWORD(0)
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                    if owner.value:
                        subprocess.run(["taskkill", "/PID", str(owner.value), "/T", "/F"],
                                       creationflags=0x08000000, capture_output=True)
            except Exception:
                pass
        os._exit(0)

    def minimize_terminal(self) -> None:
        """Drop the window to the taskbar — as if you'd clicked the '–' button.
        Used after the first sync: the work's visible, then it tucks itself away
        and keeps watching quietly until you unplug."""
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        except Exception:
            pass

    def live_status(self, message: str):
        """A spinner that stays up across polls (no flicker). Update its text
        with .update("..."); .stop()/.start() around other output."""
        if _RICH:
            return self.c.status(f"[accent]{message}[/accent]", spinner="dots")
        return _DummyStatus()

    def type_out(self, text: str, cps: int = 160) -> None:
        """Print `text` with a gentle typing animation — character by character,
        like it's being written out. Falls back to a plain print when there's no
        real terminal, or when the text is long enough that animating would just
        be tedious. Plain text only (no markup), since it's a model's answer."""
        import sys
        import time
        text = (text or "").rstrip()
        if not text:
            return
        # Make the text safe for this terminal's encoding up front — a Windows
        # console is often cp1252, and a model's answer can carry emoji or other
        # characters it can't encode. Without this, writing one would crash.
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        text = text.encode(enc, "replace").decode(enc, "replace")
        if not sys.stdout.isatty() or len(text) > 4000 or cps <= 0:
            print(text)
            return
        delay = 1.0 / cps
        try:
            for ch in text:
                sys.stdout.write(ch)
                sys.stdout.flush()
                time.sleep(delay)
            sys.stdout.write("\n")
            sys.stdout.flush()
        except Exception:
            print(text)

    def ask_name(self, sidekick_word: str = "sidekick") -> str:
        """Prompt the user to name their reel. Enter keeps the default."""
        if _RICH:
            self.c.print(f"\n[accent]One thing first[/accent] — your reel is your own "
                         f"little {sidekick_word}. What do you want to call it?")
            self.c.print("[muted](press Enter to just keep \"reel\")[/muted]")
        else:
            print(f"\nName your {sidekick_word} (Enter to keep \"reel\"):")
        try:
            name = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            name = ""
        return name or "reel"

    def confirm(self, question: str, default: bool = False) -> bool:
        """A yes/no prompt. Destructive actions default to No."""
        hint = "[y/N]" if not default else "[Y/n]"
        if _RICH:
            self.c.print(f"[warn]{question}[/warn] [muted]{hint}[/muted]")
        else:
            print(f"{question} {hint}")
        try:
            ans = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if not ans:
            return default
        return ans in ("y", "yes")

    def greeting(self, name: str | None) -> None:
        """Time-aware, cheeky hello when the copy window opens."""
        import random
        from datetime import datetime
        h = datetime.now().hour
        if 5 <= h < 12:
            tod = "Good morning"
        elif 12 <= h < 17:
            tod = "Good afternoon"
        elif 17 <= h < 22:
            tod = "Good evening"
        else:
            tod = random.choice(["Burning the midnight oil", "Working late, I see",
                                 "Up at this hour"])
        if name and name != "reel":
            quip = random.choice([
                f'You named me "{name}", apparently. ...could\'ve been worse.',
                f'"{name}." Bold choice. It\'s grown on me, honestly.',
                f'Still "{name}", I see. I\'ve made my peace with it.',
                f'They call me "{name}" around here. Not complaining — today.',
            ])
            tail = "Anyway — let's get your stuff safely copied over."
        else:
            quip = "We haven't been properly introduced (run `reel setup` to name me),"
            tail = "but let's get your stuff copied over anyway."
        if _RICH:
            self.c.print(f"\n[accent]{tod}.[/accent] [value]{quip}[/value]")
            self.c.print(f"[muted]{tail}[/muted]\n")
        else:
            print(f"\n{tod}. {quip}\n{tail}\n")

    def already_setup(self) -> None:
        msg = "Already set up  :)"
        if _RICH:
            self.c.print(Panel(f"[ok]{msg}[/ok]\n[muted]reel's good to go — it's "
                               f"watching in the background. Just plug something in.[/muted]",
                               border_style="ok", padding=(1, 3)))
        else:
            print(f"\n{msg}\nreel's good to go — it's watching in the background. "
                  "Just plug something in.\n")

    # --- help -----------------------------------------------------------
    def help_screen(self) -> None:
        """A clean, grouped command reference (prettier than argparse)."""
        self.logo()
        groups = [
            ("The whole product", [
                ("setup", "Run once. reel installs itself and copies every drive you plug in — forever"),
                ("transfer  [name]", "Put a copied drive back onto a blank stick (original folders & names)"),
                ("rename  on/off", "The automatic name-tidying — on by default; off = pure 1:1 copies"),
                ("find  <request>", "Ask about your recordings in plain English — time-aware, by meaning"),
                ("play  [N]", "Play recording N from your last find (default 1) in your media player"),
                ("organize", "File recordings into <year>/<month> folders (automatic after each copy)"),
            ]),
            ("Keeping it fresh", [
                ("retranscribe", "Redo existing transcripts with the current model/settings (better accuracy)"),
                ("upgrade", "Update reel to the latest version (also: reel --upgrade)"),
                ("--version", "Print the installed version"),
            ]),
        ]
        if not _RICH:
            print("\nUSAGE: reel <command> [options]\n")
            for title, rows in groups:
                print(f"  {title}")
                for cmd, desc in rows:
                    print(f"    {cmd:<14} {desc}")
                print()
            print("  Options")
            print("    --theme light|dark   terminal colours (default: light)")
            print("    --config <path>      use a specific config.toml\n")
            return

        from rich.table import Table
        from rich.text import Text
        self.c.print(Text("USAGE  ", style="muted").append("reel <command> [options]", style="value"))
        self.c.print()
        for title, rows in groups:
            t = Table(show_header=False, box=None, padding=(0, 2, 0, 2))
            t.add_column(justify="left", no_wrap=True)
            t.add_column(justify="left")
            for cmd, desc in rows:
                t.add_row(f"[accent]{cmd}[/accent]", f"[value]{desc}[/value]")
            self.c.print(f"[muted]{title}[/muted]")
            self.c.print(t)
            self.c.print()
        opts = Table(show_header=False, box=None, padding=(0, 2, 0, 2))
        opts.add_column(no_wrap=True); opts.add_column()
        opts.add_row("[accent]--theme[/accent] light|dark", "[value]terminal colours (default: light)[/value]")
        opts.add_row("[accent]--config[/accent] <path>", "[value]use a specific config.toml[/value]")
        self.c.print("[muted]Options[/muted]")
        self.c.print(opts)
        self.c.print()
        self.c.print(f"[muted]Run [/muted][accent]reel[/accent][muted] on its own for the welcome screen.[/muted]")

    # --- progress -------------------------------------------------------
    def progress(self):
        """Context-manager progress bar. Falls back to a tiny text ticker."""
        if _RICH:
            return Progress(
                SpinnerColumn(style="accent"),
                TextColumn("[value]{task.description}", justify="left"),
                BarColumn(bar_width=34, complete_style=self.pal["bar"],
                          finished_style="ok", pulse_style="accent"),
                MofNCompleteColumn(),
                TextColumn("[muted]{task.fields[name]}"),
                TimeRemainingColumn(),
                console=self.c, transient=False,
            )
        return _PlainProgress()


class _DummyStatus:
    """No-rich stand-in for rich's Status (used by live_status)."""
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def start(self): pass
    def stop(self): pass
    def update(self, *a, **k): pass


class _PlainProgress:
    """No-rich fallback that mimics the slice of the Progress API we use,
    supporting more than one concurrent task."""
    def __enter__(self): return self
    def __exit__(self, *a): print()
    def __init__(self): self._tasks = {}
    def add_task(self, description, total=0, name=""):
        tid = len(self._tasks)
        self._tasks[tid] = {"desc": description, "total": total, "done": 0}
        return tid
    def update(self, task, advance=0, name="", **k):
        t = self._tasks.get(task)
        if t is None:
            return
        t["done"] += advance
        print(f"\r{t['desc']} {t['done']}/{t['total']}  {name[:40]:<40}", end="")
        if t["done"] >= t["total"]:
            print()

"""
__main__.py — the reel command line. Three commands; the rest is automatic.

  reel setup               run once. Names your reel and installs the always-on
                           watcher: from then on, plugging anything in copies it
                           to Documents/reel — every folder, every file — then
                           tidies names. Always running; nothing else to do.
  reel transfer [name]     put a copied drive back onto a blank stick, in its
                           original layout (original folders, original names).
  reel rename [on|off]     the automatic name-tidying. On by default; turn it
                           off for a pure 1:1 copy. The copy itself never changes.
  reel find <request>      ask about your recordings in plain English — reel reads
                           the transcripts and answers, aware of time and meaning:
                             reel find a summary of today's notes
                             reel find what was my first recording about?
                             reel find the interview at Bucky's about a month ago
                           Uses Claude Code if installed; no words → it prompts you.
                           Each answer ends with clickable links — click one to play.
  reel play [N]            play a recording from your last `reel find` (N = its
                           number in that list, default 1) in your media player.
  reel retranscribe        redo the transcripts you already have with the current
                           model/settings — use after raising accuracy in config.
  reel organize            file every recording (and its note) into
                           <library>/<year>/<month>/ folders (months lowercase).
                           Runs automatically after each copy; this re-scans now.
  reel upgrade             update reel to the latest version (also: reel --upgrade).
  reel --version           print the version and exit.

Internal (what the watcher runs for itself — not for humans):
  reel auto run            the hidden background watcher (launched at login)
  reel auto session        the visible per-drive copy window the watcher pops open
  reel auto restart        stop the watcher and relaunch it (used after an upgrade)

Global:  --config path/to/config.toml   --theme light|dark
"""
from __future__ import annotations

import argparse
import sys

from .config import load, resolve_path


def build_parser():
    # shared options accepted both before AND after the subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS)
    common.add_argument("--theme", choices=["light", "dark"], default=argparse.SUPPRESS)

    p = argparse.ArgumentParser(prog="reel", parents=[common],
                                description="reel — plug it in, copied")
    sub = p.add_subparsers(dest="cmd")  # optional: bare `reel` -> splash
    sub.add_parser("setup", parents=[common])
    pt = sub.add_parser("transfer", parents=[common])
    pt.add_argument("name", nargs="?")
    pr = sub.add_parser("rename", parents=[common])
    pr.add_argument("state", nargs="?", choices=["on", "off"])
    pf = sub.add_parser("find", parents=[common])
    pf.add_argument("query", nargs="*")
    ppl = sub.add_parser("play", parents=[common])
    ppl.add_argument("which", nargs="?")
    sub.add_parser("retranscribe", parents=[common])
    sub.add_parser("organize", parents=[common])
    sub.add_parser("upgrade", parents=[common])
    pa = sub.add_parser("auto", parents=[common])     # internal: the watcher's own entry points
    pa.add_argument("action", nargs="?", choices=["run", "session", "restart"])
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # Friendly front doors, handled before argparse:
    #   reel            -> welcome splash
    #   reel help / -h  -> clean command reference
    #   reel --upgrade  -> alias for `reel upgrade` (how people expect to type it)
    #   reel --version  -> print the version
    if argv and argv[0] in ("--upgrade", "-U"):
        argv[0] = "upgrade"
    if argv and argv[0] in ("--version", "-V"):
        from . import __version__
        print(f"reel {__version__}")
        return 0
    if not argv or argv[0] in ("help", "-h", "--help"):
        from .console import Reel
        con = Reel(theme=load(resolve_path(None)).theme)
        con.splash() if not argv else con.help_screen()
        return 0

    args = build_parser().parse_args(argv)
    cfg = load(resolve_path(getattr(args, "config", None)))
    theme = getattr(args, "theme", None)
    if theme:
        cfg.theme = theme

    from .console import Reel
    con = Reel(theme=cfg.theme)

    if not args.cmd:
        con.splash()
        return 0

    if args.cmd == "setup":
        from .runner import first_setup
        con.logo()
        first_setup(cfg, con)

    elif args.cmd == "transfer":
        con.logo()
        from .runner import transfer_restore
        transfer_restore(cfg, con, getattr(args, "name", None))

    elif args.cmd == "rename":
        from . import mirror
        con.logo()
        state = getattr(args, "state", None)
        if state == "off":
            mirror.set_renaming(cfg, False)
            con.ok("renaming is OFF — from now on it's a pure 1:1 copy, names untouched.")
            con.dim("(files already renamed stay as they are; turn it back on with  reel rename on)")
        elif state == "on":
            mirror.set_renaming(cfg, True)
            con.ok("renaming is ON — new copies get tidy, sortable names (folders never move).")
        else:
            on = mirror.renaming_on(cfg)
            con.info(f"renaming is {'ON' if on else 'OFF'}.")
            con.dim("  reel rename off   → pure 1:1 copies, names untouched")
            con.dim("  reel rename on    → tidy, sortable names (the default)")

    elif args.cmd == "find":
        # Ask about your recordings in plain English (time-aware, by meaning).
        # No words → it prompts you. Falls back to keyword search if Claude is away.
        from .ask import run_ask
        run_ask(cfg, con, " ".join(getattr(args, "query", []) or []).strip() or None)

    elif args.cmd == "play":
        # Play a recording from the last find — no logo, just open it and go.
        from .ask import run_play
        run_play(cfg, con, getattr(args, "which", None))

    elif args.cmd == "retranscribe":
        from .transcribe import retranscribe_library
        con.logo()
        retranscribe_library(cfg, con)

    elif args.cmd == "organize":
        from .organize import organize_library
        con.logo()
        n = organize_library(cfg, con)
        if not n:
            con.info("everything's already filed by date — nothing to move.")

    elif args.cmd == "upgrade":
        con.logo()
        from .upgrade import run as run_upgrade
        run_upgrade(cfg, con)

    elif args.cmd == "auto":
        # Internal entry points for the always-on watcher. Not in the help on
        # purpose — `reel setup` is the only thing a person ever needs to run.
        from . import autostart
        action = getattr(args, "action", None)
        if action == "run":
            autostart.run_resident(cfg)          # the hidden background watcher
        elif action == "session":
            # the visible per-device window the watcher pops open: logo, progress
            # bars, then it minimises itself and closes when you unplug.
            from .watch import auto_sync
            from .runner import load_profile
            con.logo()
            con.greeting(load_profile(cfg).get("name"))
            auto_sync(cfg, con, minimize_after_first=True, notify=True)
        elif action == "restart":
            # used by `reel upgrade` after pip finishes: bring the watcher back
            # up on the freshly-installed code.
            from .upgrade import restart_watcher
            restart_watcher(cfg)
        else:
            con.dim("reel runs itself — just plug something in. (Run 'reel setup' "
                    "if you haven't yet.)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

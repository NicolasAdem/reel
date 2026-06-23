"""
runner.py — run one copy with live progress bars and a tidy summary.

Used by the background watcher's pop-up window (`reel auto session`). Also home
to first-time setup, which installs the always-on watcher, and `reel transfer`.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import branding, device, mirror, profiles
from .config import Config


# ── the reel's name (its "profile") ──────────────────────────────────────────
def load_profile(cfg: Config) -> dict:
    p = cfg.profile_path
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_profile(cfg: Config, name: str) -> None:
    p = cfg.profile_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": name,
                             "named": datetime.now().isoformat(timespec="seconds")},
                            ensure_ascii=False, indent=2), encoding="utf-8")


def _setup_flag(cfg: Config) -> Path:
    return cfg.sync_root / ".reel" / "setup_complete"


def is_setup_done(cfg: Config) -> bool:
    return _setup_flag(cfg).exists()


def mark_setup_done(cfg: Config) -> None:
    flag = _setup_flag(cfg)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")


def first_setup(cfg: Config, con) -> None:
    """The one command you run. Name your reel, and it installs itself as an
    always-on background watcher — at login and starting right now. From then on,
    plugging anything in just works; there is nothing else to remember."""
    from . import autostart, locate
    if is_setup_done(cfg):
        con.already_setup()
        # self-heal: bind the library (in case it moved) and make sure exactly one
        # watcher is installed and running on the current code.
        locate.bind(cfg.sync_root)
        autostart.install()
        autostart.stop_running(cfg)
        autostart.launch_background(cfg)
        con.dim(f"your library: {cfg.sync_root}")
        return
    con.celebrate([
        "Plug in your recorder — or any USB drive, SD card, anything — and I",
        "copy the whole thing into a 'reel' folder in your Documents: every",
        "folder, every file, exactly as it is. Then I tidy the file names.",
        "Nothing left behind, nothing copied twice, nothing to click.",
        "",
        "Give me a name, and I'll take it from here — starting now, and every",
        "time you log in. You never need to run anything again.",
    ])
    name = con.ask_name()
    save_profile(cfg, name)
    cfg.sync_root.mkdir(parents=True, exist_ok=True)
    locate.bind(cfg.sync_root)           # record where the library is, for good
    autostart.install()
    autostart.stop_running(cfg)          # clear out any stale watcher first
    autostart.launch_background(cfg)
    mark_setup_done(cfg)
    con.space()
    con.ok(f'"{name}" is on duty. Plug something in whenever — a window will pop '
           f"up, copy it, and tuck itself away. 🎬")
    con.dim(f"your library: {cfg.sync_root}")
    con.dim("move that folder anywhere you like — I'll follow it. you never lose it.")
    con.dim("put a copy back on a blank stick any time with:  reel transfer")


def _run_mirror_bar(cfg: Config, con, dev: device.Device) -> mirror.MirrorSummary:
    """One copy pass with two live bars: 'copying' (verbatim) then 'renaming'."""
    con.space()
    bar = con.progress()
    with bar:
        copy = {"id": None}
        ren = {"id": None}

        def on_scan_done(total):
            if total:
                copy["id"] = bar.add_task("copying ", total=total, name="")

        def on_copy(name):
            if copy["id"] is not None:
                bar.update(copy["id"], advance=1, name=name)

        def on_copy_done(n):
            if copy["id"] is not None:
                bar.update(copy["id"], name="done")
            if n:
                ren["id"] = bar.add_task("renaming", total=n, name="")

        def on_rename(name):
            if ren["id"] is not None:
                bar.update(ren["id"], advance=1, name=name)

        s = mirror.mirror_device(cfg, dev, on_scan_done=on_scan_done,
                                 on_copy=on_copy, on_copy_done=on_copy_done,
                                 on_rename=on_rename)
    return s


def sync_devices(cfg: Config, con) -> list[mirror.MirrorSummary]:
    """Find every plugged-in drive and copy it — automatically, no questions.
    Each drive is copied verbatim into <library>/<drive name>/ — every folder,
    every file — and only then are names tidied, in place."""
    devs = device.find_devices(cfg)
    if not devs:
        con.warn("no device found — plug in your recorder or a USB drive.")
        return []

    results: list[mirror.MirrorSummary] = []
    for dev in devs:
        kind = profiles.detect_kind(dev, cfg)
        _announce(con, dev, kind)
        s = _run_mirror_bar(cfg, con, dev)
        con.space()
        _mirror_summary(cfg, con, s)
        con.space()
        results.append(s)
    return results


# ── transfer — put a copy back onto a stick ───────────────────────────────────
def transfer_restore(cfg: Config, con, name: str | None) -> None:
    """Write a copied drive back onto the plugged-in stick in its *original*
    layout — original folders, original filenames. Pauses the watcher itself,
    restores, then resumes — one command, no fuss."""
    from . import autostart
    drives = mirror.saved_drives(cfg)
    if not drives:
        con.warn("nothing to restore yet — reel hasn't copied a drive. "
                 "Plug one in once first.")
        return

    targets = [d for d in device.find_devices(cfg)]
    if len(targets) == 0:
        con.warn("plug in the stick to transfer onto, then run it again.")
        return
    if len(targets) > 1:
        con.warn("more than one drive is plugged in — leave only the stick you "
                 "want to transfer onto, then run it again.")
        return
    target = targets[0]

    m = mirror.find_saved(cfg, name=name, label=target.label)
    if m is None:
        con.warn("you've copied more than one drive — tell me which one to put back:")
        for d in drives:
            con.dim(f'   reel transfer "{d.get("name")}"')
        return

    con.info(f"transferring ‘{m['name']}’ — {len(m.get('files', {}))} files "
             f"onto {target.display}  ({target.root})")
    con.dim("recreating the original folders & names · auto-copy paused for a moment")
    con.space()
    autostart.pause(cfg)
    try:
        r = mirror.restore_drive(cfg, con, m, target.root)
    finally:
        autostart.resume(cfg)
    con.space()
    msg = f"transferred {r['copied']} files"
    if r["skipped"]:
        msg += f" · {r['skipped']} already on the stick"
    if r["missing"]:
        msg += f" · {r['missing']} not in the copy (skipped)"
    con.ok(msg + f". {target.display} now matches the original. 🎬")


def _announce(con, dev, kind: str) -> None:
    glyph = branding.DEVICE_GLYPH.get(kind, "▸")
    label = branding.DEVICE_LABEL.get(kind, "device")
    con.info(f"{glyph}  {label} '{dev.display}' — copying everything over…")


def _mirror_summary(cfg: Config, con, s: mirror.MirrorSummary) -> None:
    """Report a copy pass: what was copied, what was renamed, where it landed,
    and — plainly — anything that couldn't be read, so no loss is ever silent."""
    if not s.devices:
        con.warn("no device found — plug something in.")
        return
    where = Path(s.mirror_root).name
    if s.copied == 0 and s.relocated == 0 and s.skipped:
        con.ok(f"up to date — {s.skipped} files already copied into '{where}'.")
    elif s.copied == 0 and s.relocated == 0 and not s.errors:
        con.warn("nothing new to copy.")
    else:
        lines = []
        for kind in branding.FILE_KINDS:
            n = s.by_category.get(kind, 0)
            if n:
                g = branding.LABEL_GLYPH.get(kind, "·")
                col = branding.LABEL_COLOR.get(kind, "white")
                lines.append(f"  [{col}]{g}[/{col}]  {kind:<12} {n}")
        mb = s.bytes / (1024 * 1024)
        body = "\n".join(lines)
        if lines:
            body += "\n\n"
        body += f"  copied {s.copied}"
        if s.renamed:
            body += f" · renamed {s.renamed}"
        if s.relocated:
            body += f" · {s.relocated} moved on the device (recognised, not re-copied)"
        body += (f" · {s.skipped} already here · {mb:.1f} MB\n"
                 f"  → {s.mirror_root}")
        con.panel(f"copied → {where}", body)
    # Surface every problem. Real read failures are errors; pruned system folders
    # are just notes (expected, and not user data).
    real = [e for e in s.errors if not e.startswith("skipped system folder")]
    notes = [e for e in s.errors if e.startswith("skipped system folder")]
    for e in real:
        con.err(e)
    for e in dict.fromkeys(notes):   # dedup the repeated recycle-bin / SVI notes
        con.dim(e)

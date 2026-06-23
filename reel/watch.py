"""
watch.py — the background copy loop. It pops the per-drive window, runs the copy,
tucks itself away when done, and closes when you unplug — hands-off.

It re-syncs whenever *anything* about the device changes:
  • you plug the recorder in            (device appears)
  • you drop a file onto it from the PC  (contents change)
  • you unplug and plug it back in       (device cycles)

How it knows: each tick it takes a cheap fingerprint of the device — every audio
file's path + size + modified-time (no hashing, just `stat`). If that differs
from what we last synced, it syncs. In-place changes are debounced one tick so a
half-finished copy never gets grabbed mid-write.
"""
from __future__ import annotations

from . import device
from .config import Config
from .runner import sync_devices


def _device_state(cfg: Config):
    """A cheap, hashable snapshot of *every* file on *every* plugged-in volume.
    None = nothing there.

    Keyed by each volume's stable id (not its drive letter), so re-plugging the
    same drive on a different letter reads as 'no change'. We fingerprint every
    file — audio or not — so dropping a `test.txt` onto the recorder (or any
    drive) is noticed immediately and triggers a sync."""
    devs = device.find_devices(cfg)
    if not devs:
        return None
    items = []
    for d in devs:
        for rec in device.scan(d.root):
            try:
                st = rec.path.stat()
                items.append((d.id, rec.rel, st.st_size, int(st.st_mtime)))
            except OSError:
                pass
    return tuple(sorted(items))


# A real unplug closes immediately; we only do one quick re-check (this many
# seconds) so a momentary USB blip doesn't kill the session.
_BLIP_RECHECK_SEC = 1

# After the first sync, linger a beat on the finished bars before tucking the
# window away — so it reads as "done!" instead of a window that flashed and fled.
_MINIMIZE_DELAY_SEC = 2

_QUIT = "(Ctrl + C to stop)"
MSG_WAITING = f"Whenever you're ready — plug something in and I'll take it from there.   {_QUIT}"
MSG_IDLE = f"All copied — safe to unplug now. I'll grab anything new, and bow out when you do.   {_QUIT}"
MSG_CONFIRM = "Spotted something new — letting it land safely, then I'll copy it…"
MSG_RECONNECT = "Lost sight of the drive for a second — hanging on…"


def _maybe_toast(results) -> None:
    """A quiet 'reel — copied N files from X' toast, when something was copied."""
    copied = sum(s.copied for s in results)
    if not copied:
        return
    names = [s.devices[0].split(" (")[0] for s in results if s.copied and s.devices]
    who = (" from " + ", ".join(dict.fromkeys(names))) if names else ""
    from . import notify
    notify.toast("reel — copied", f"{copied} file{'s' if copied != 1 else ''}{who}")


def auto_sync(cfg: Config, con, show_banner: bool = True,
              minimize_after_first: bool = False, notify: bool = False) -> None:
    import time

    if show_banner:
        con.panel("reel · watching", (
            "I'm watching now. Plug in your recorder or any USB drive and I'll copy\n"
            "the whole thing onto your PC — every folder, every file — then tidy the\n"
            "names. I tuck myself away when I'm done, and bow out when you unplug.\n\n"
            "[warn]Don't unplug while I'm still copying.[/warn] Wait for 'all copied' first.\n"
            f"→  (Or press Ctrl + C to stop me sooner.)"
        ))

    synced_for = None   # device snapshot we've already synced
    last = None         # previous tick's snapshot (debounce)
    minimized = False   # have we tucked the window away after the first sync?
    seen = False        # have we ever had the device this session?
    interval = max(1, cfg.watch_interval_sec)

    status = con.live_status(MSG_WAITING)
    status.start()
    try:
        while True:
            state = _device_state(cfg)

            if state is None:
                if seen:
                    # Recorder was here and is now gone. One quick re-check to
                    # rule out a momentary blip, then close right away.
                    status.update(f"[warn]{MSG_RECONNECT}[/warn]")
                    time.sleep(_BLIP_RECHECK_SEC)
                    if _device_state(cfg) is not None:
                        continue  # false alarm — carry on
                    status.stop()
                    if cfg.close_on_unplug:
                        con.close_terminal()  # immediate — actually closes the window
                    else:
                        con.ok("Unplugged — everything's copied. Stepping off. 👋")
                    return
                else:
                    synced_for, last = None, None
                    status.update(f"[accent]{MSG_WAITING}[/accent]")
            else:
                seen = True
                fresh = synced_for is None
                stable_change = (state != synced_for and state == last)
                if fresh or stable_change:
                    status.stop()
                    con.ok("Device detected — copying it over…" if fresh
                           else "Caught something new — copying it now…")
                    results = sync_devices(cfg, con)
                    if notify:
                        _maybe_toast(results)
                    synced_for = _device_state(cfg)
                    last = synced_for
                    status.start()
                    status.update(f"[accent]{MSG_IDLE}[/accent]")
                    # work's done and visible — let it sit a beat, then tuck the
                    # window down to the taskbar (no startled "what was that?")
                    if minimize_after_first and not minimized:
                        time.sleep(_MINIMIZE_DELAY_SEC)
                        con.minimize_terminal()
                        minimized = True
                else:
                    last = state
                    status.update(f"[accent]{MSG_IDLE if state == synced_for else MSG_CONFIRM}[/accent]")

            time.sleep(interval)
    except KeyboardInterrupt:
        status.stop()
        con.info("Alright, stepping off watch. Your stuff's safe — see you next time. 👋")
    finally:
        try:
            status.stop()
        except Exception:
            pass

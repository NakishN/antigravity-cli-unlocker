"""
Background guardian that keeps agy patched and protected according to active strategy.
"""

import os
import sys
import time

from antigravity_unlock.config import DEFAULT_STRATEGY, load_config
from antigravity_unlock.discovery import get_primary_agy
from antigravity_unlock.logging_utils import get_logger
from antigravity_unlock.pinner import enforce_strategy

logger = get_logger()

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except Exception:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object


class AgyWatchHandler(FileSystemEventHandler):
    def __init__(self, agy_path, callback):
        super().__init__()
        self.agy_path = os.path.abspath(agy_path)
        self.callback = callback

    def _maybe_trigger(self, path):
        if path and os.path.abspath(path) == self.agy_path:
            self.callback("filesystem event")

    def on_modified(self, event):
        if not event.is_directory:
            self._maybe_trigger(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._maybe_trigger(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._maybe_trigger(event.dest_path)


def _fingerprint(agy_path):
    """Cheap on-disk identity for the installed binary: ``(size, mtime_ns)``.

    Deliberately not a SHA-256: hashing 220 MB every tick is what makes a
    guardian expensive, and size+mtime is enough to notice that agy replaced
    itself.  The patch check that follows is the streamed signature census.
    """
    try:
        st = os.stat(agy_path)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


_last_fingerprint = None


def _run_check(trigger="scheduled", strategy=None, agy_path=None, include_optional=False):
    global _last_fingerprint

    # Fingerprint BEFORE the check, but stored AFTER it.  Storing the pre-check
    # value instead would make the guardian's own patch write look like an
    # external change on the next tick, logging "a self-update reverted the
    # patch" when nothing of the kind happened - noise that hides the real event.
    fp_seen = _fingerprint(agy_path) if agy_path else None
    externally_changed = (
        _last_fingerprint is not None
        and fp_seen is not None
        and fp_seen != _last_fingerprint
    )
    if externally_changed:
        logger.warning(
            "[%s] agy changed on disk (%s -> %s): a self-update reverted the "
            "patch, re-applying",
            trigger, _last_fingerprint, fp_seen,
        )

    ok, msg, changed = enforce_strategy(
        agy_path=agy_path, strategy=strategy, include_optional=include_optional
    )
    if changed:
        logger.info("[%s] %s", trigger, msg)
    elif not ok:
        logger.warning("[%s] %s", trigger, msg)
    else:
        logger.debug("[%s] %s", trigger, msg)

    if agy_path:
        _last_fingerprint = _fingerprint(agy_path)
    return ok


def run_guardian(stop_event=None, strategy=None):
    config = load_config()
    interval = max(5, int(config.get("check_interval_seconds", 30)))
    agy_path = get_primary_agy()
    active_strategy = strategy or config.get("strategy", DEFAULT_STRATEGY)
    include_optional = bool(config.get("include_optional", False))

    logger.info(
        "Guardian started (strategy=%s, pinned=%s, interval=%ss, watchdog=%s)",
        active_strategy,
        config.get("pinned_version", "unknown"),
        interval,
        WATCHDOG_AVAILABLE,
    )

    _run_check("startup", strategy=active_strategy, agy_path=agy_path,
               include_optional=include_optional)

    def _tick(trigger):
        # Re-resolve every tick: an agy self-update can move the binary, and a
        # guardian holding a stale path would silently stop protecting anything.
        current = get_primary_agy()
        _run_check(trigger, strategy=active_strategy, agy_path=current,
                   include_optional=include_optional)

    observer = None
    if WATCHDOG_AVAILABLE and agy_path:
        watch_dir = os.path.dirname(os.path.abspath(agy_path)) or "."
        handler = AgyWatchHandler(agy_path, _tick)
        observer = Observer()
        observer.schedule(handler, watch_dir, recursive=False)
        observer.start()
        logger.info("Filesystem watch enabled on %s", watch_dir)

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(interval)
            _tick("interval")
    except KeyboardInterrupt:
        logger.info("Guardian interrupted, shutting down")
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)

    return 0


"""
Background guardian that keeps agy pinned to the configured version.
"""

import os
import sys
import time

from antigravity_unlock.config import load_config
from antigravity_unlock.discovery import get_primary_agy
from antigravity_unlock.logging_utils import get_logger
from antigravity_unlock.pinner import ensure_pinned

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


def _run_check(trigger="scheduled"):
    ok, msg, changed = ensure_pinned()
    if changed:
        logger.info("[%s] %s", trigger, msg)
    elif not ok:
        logger.warning("[%s] %s", trigger, msg)
    else:
        logger.debug("[%s] %s", trigger, msg)
    return ok


def run_guardian(stop_event=None):
    config = load_config()
    interval = max(5, int(config.get("check_interval_seconds", 30)))
    agy_path = get_primary_agy()

    logger.info(
        "Guardian started (pinned=%s, interval=%ss, watchdog=%s)",
        config.get("pinned_version", "unknown"),
        interval,
        WATCHDOG_AVAILABLE,
    )

    _run_check("startup")

    observer = None
    if WATCHDOG_AVAILABLE and agy_path:
        watch_dir = os.path.dirname(os.path.abspath(agy_path)) or "."
        handler = AgyWatchHandler(agy_path, lambda reason: _run_check(reason))
        observer = Observer()
        observer.schedule(handler, watch_dir, recursive=False)
        observer.start()
        logger.info("Filesystem watch enabled on %s", watch_dir)

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(interval)
            _run_check("interval")
    except KeyboardInterrupt:
        logger.info("Guardian interrupted, shutting down")
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)

    return 0

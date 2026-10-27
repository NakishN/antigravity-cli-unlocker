"""
File logging utilities for Antigravity CLI Unlocker.
"""

import logging
import os

from antigravity_unlock.patcher import get_app_dir

LOG_FILENAME = "unlocker.log"
_LOGGER = None


def get_log_path():
    return os.path.join(get_app_dir(), LOG_FILENAME)


def get_logger(name="antigravity_unlocker"):
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = get_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    wanted = os.path.abspath(log_path)

    # Decide per handler *path*, not with `if not logger.handlers`.  The old
    # guard only asked whether the list was empty, so any pre-existing
    # StreamHandler - or a FileHandler left over from a different app dir -
    # silently suppressed file logging for the rest of the process.  Measured
    # 2026-10-07: the suite's first call bound the handler to the real
    # ~/.local/share/antigravity-unlocker/unlocker.log and no later call could
    # redirect it, so tests appended fake lines to the user's live log.
    file_handlers, stale = [], []
    for handler in logger.handlers:
        base = getattr(handler, "baseFilename", None)
        if base is None:
            continue
        (file_handlers if os.path.abspath(base) == wanted else stale).append(handler)

    for handler in stale:
        logger.removeHandler(handler)
        handler.close()

    if not file_handlers:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # FileHandler is itself a StreamHandler subclass, so exclude it explicitly.
    if not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    _LOGGER = logger
    return logger

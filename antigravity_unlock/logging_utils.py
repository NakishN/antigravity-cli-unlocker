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

    if not logger.handlers:
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        log_path = get_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    _LOGGER = logger
    return logger

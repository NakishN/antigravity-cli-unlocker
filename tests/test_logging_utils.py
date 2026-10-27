"""Tests for logging_utils, including the app-dir isolation the suite relies on."""

import os

from antigravity_unlock import logging_utils


def test_the_real_user_log_is_never_written_from_a_test_run():
    """A test run must not append to ~/.local/share/.../unlocker.log.

    ``get_logger`` memoizes a singleton whose FileHandler binds to whatever
    ``get_app_dir()`` returned at the moment of the *first* call.  Test modules
    are imported during collection, before the autouse ``_isolate_app_dir``
    fixture runs, so an import-time call would bind the handler to the real user
    log for the whole session.  Measured on 2026-10-07: a plain ``pytest -q``
    appended ~30 fake lines ("Pinned agy 1.1.9", version 9.9.9, /tmp/tmpXXXX
    paths) into the live log, where they read as genuine guardian activity.
    """
    logging_utils.get_logger().info("isolation-probe-marker")

    log_path = logging_utils.get_log_path()

    # The handler must follow the redirected app dir, not the user's home.
    assert not log_path.startswith(os.path.expanduser("~/.local/share/")), (
        f"logger is pointed at the real user app dir: {log_path}"
    )

    with open(log_path, encoding="utf-8") as handle:
        assert "isolation-probe-marker" in handle.read()


def test_every_handler_stays_inside_the_redirected_app_dir():
    """Even a pre-existing singleton cannot keep a handler on the real log."""
    logging_utils.get_logger().info("handler-probe")

    for handler in logging_utils.get_logger().handlers:
        base = getattr(handler, "baseFilename", None)
        if base is None:
            continue  # StreamHandler, harmless
        assert not base.startswith(os.path.expanduser("~/.local/share/")), (
            f"handler writes outside the tmp app dir: {base}"
        )
import sys
import os
import logging

import pytest

# Ensure project root is in sys.path for pytest
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


@pytest.fixture(autouse=True)
def _isolate_app_dir(tmp_path, monkeypatch):
    """Redirect get_app_dir() to a throwaway temp dir for every test.

    ``patcher.get_app_dir`` is the source of truth, but ``config``, ``pinner``
    and ``logging_utils`` each do ``from antigravity_unlock.patcher import
    get_app_dir``, binding their own module-level name. Historically the pinner
    tests mocked only ``pinner.get_app_dir``; ``save_config()`` still resolved
    ``config.get_app_dir`` and wrote the REAL
    ``~/.local/share/antigravity-unlocker/config.json``. That is how a 58-byte
    dummy pin (strategy=pin, pinned_size=58) leaked into a user's live config
    and caused the guardian to roll a freshly installed release back to 1.1.9.

    Patch every binding so no test can touch real user state.
    """
    app_dir = str(tmp_path / "app")
    os.makedirs(app_dir, exist_ok=True)
    for target in (
        "antigravity_unlock.patcher.get_app_dir",
        "antigravity_unlock.config.get_app_dir",
        "antigravity_unlock.pinner.get_app_dir",
        "antigravity_unlock.logging_utils.get_app_dir",
    ):
        monkeypatch.setattr(target, lambda _app_dir=app_dir: _app_dir)

    # The logger is a memoized singleton whose FileHandler binds to whatever
    # get_app_dir() returned at the moment of the *first* get_logger() call.
    # Test modules are imported during collection, i.e. before this fixture
    # ever runs, so an import-time get_logger() would bind the handler to the
    # real ~/.local/share/antigravity-unlocker/unlocker.log for the whole run.
    # Measured on 2026-10-07: a plain `pytest -q` appended ~30 fake lines
    # ("Pinned agy 1.1.9", version 9.9.9, /tmp/tmpXXXX paths) into the user's
    # live log, where they read as real guardian activity.  Drop the singleton so
    # each test rebuilds it against the tmp dir; monkeypatch restores the
    # original afterwards.
    monkeypatch.setattr("antigravity_unlock.logging_utils._LOGGER", None)

    # Resetting the memo alone is not enough: logging.getLogger() hands back the
    # *same* logger object, and get_logger() only adds a FileHandler when
    # `not logger.handlers`.  An import-time call during collection therefore
    # leaves the real user handler attached and no new one is ever created.  Drop
    # any file handler that is not inside this test's tmp app dir - both the real
    # user log and a stale tmp dir from an earlier test.
    logger = logging.getLogger("antigravity_unlocker")
    allowed = os.path.abspath(app_dir)
    for handler in list(logger.handlers):
        base = getattr(handler, "baseFilename", None)
        if base is not None and not os.path.abspath(base).startswith(allowed):
            logger.removeHandler(handler)
            handler.close()
    yield

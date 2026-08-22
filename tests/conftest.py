import sys
import os

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
    yield

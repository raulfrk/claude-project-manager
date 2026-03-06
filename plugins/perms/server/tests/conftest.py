from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_sandbox_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent sandbox detection from reading the real ~/.claude/settings.local.json."""
    nonexistent = tmp_path / "nonexistent-local-settings.json"
    monkeypatch.setattr("server.lib.storage._USER_LOCAL_SETTINGS", nonexistent)

"""Shared test fixtures for sandbox plugin tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.lib import storage


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all settings reads/writes to a temp directory."""
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(storage, "SETTINGS_PATH", settings_path)


def write_settings(tmp_path: Path, data: dict[str, Any]) -> Path:
    """Write a settings.json to the tmp_path and return its path."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(data, indent=2))
    return settings_path


def read_settings(tmp_path: Path) -> dict[str, Any]:
    """Read the settings.json from tmp_path."""
    settings_path = tmp_path / "settings.json"
    return json.loads(settings_path.read_text())  # type: ignore[no-any-return]

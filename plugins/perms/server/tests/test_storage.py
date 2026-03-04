"""Tests for server.lib.storage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib import storage
from server.lib.models import SettingsFile
from server.lib.storage import mcp_allow_entry


def test_allow_entries_for_path_adds_double_slash() -> None:
    entries = storage.allow_entries_for_path("/home/user/myproject")
    assert "Read(//home/user/myproject/**)" in entries
    assert "Edit(//home/user/myproject/**)" in entries


def test_allow_entries_strips_trailing_slash() -> None:
    a = storage.allow_entries_for_path("/home/user/proj/")
    b = storage.allow_entries_for_path("/home/user/proj")
    assert a == b


def test_allow_entries_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        storage.allow_entries_for_path("relative/path")


def test_load_missing_file_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nonexistent = tmp_path / "missing" / "settings.json"
    monkeypatch.setattr(storage, "_USER_SETTINGS", nonexistent)
    settings = storage.load("user")
    assert settings.permissions.allow == []
    assert not settings.path.exists()


def test_load_existing_file(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "model": "sonnet",
                "permissions": {"allow": ["Read(//home/user/proj/**)"]},
            }
        )
    )

    settings = storage.load("project", project_dir=tmp_path)
    assert settings.permissions.allow == ["Read(//home/user/proj/**)"]
    assert settings.raw.get("model") == "sonnet"


def test_save_creates_file_atomically(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//tmp/**)"]
    storage.save(sf)

    assert settings_path.exists()
    data = json.loads(settings_path.read_text())
    assert data["permissions"]["allow"] == ["Read(//tmp/**)"]


def test_save_preserves_existing_keys(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"model": "opus", "permissions": {}}))

    settings = storage.load("project", project_dir=tmp_path)
    settings.permissions.allow.append("Read(//foo/**)")
    storage.save(settings)

    data = json.loads(settings_path.read_text())
    assert data["model"] == "opus"
    assert "Read(//foo/**)" in data["permissions"]["allow"]


def test_mcp_allow_entry_format() -> None:
    assert mcp_allow_entry("proj") == "mcp__proj__*"
    assert mcp_allow_entry("claude_ai_Todoist") == "mcp__claude_ai_Todoist__*"


def test_mcp_allow_entry_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        mcp_allow_entry("")


def test_save_removes_empty_permissions(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"permissions": {"allow": []}}))

    settings = storage.load("project", project_dir=tmp_path)
    # permissions stays empty
    storage.save(settings)

    data = json.loads(settings_path.read_text())
    assert "permissions" not in data


def test_save_write_failure_reraises(tmp_path: Path) -> None:
    """An OSError during the write is re-raised to the caller."""
    settings_path = tmp_path / ".claude" / "settings.json"
    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//tmp/**)"]

    with patch("os.fdopen", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            storage.save(sf)


def test_save_write_failure_cleans_up_temp_file(tmp_path: Path) -> None:
    """When the write raises, the temp file is removed and does not linger."""
    settings_path = tmp_path / ".claude" / "settings.json"
    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//tmp/**)"]

    with patch("os.fdopen", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save(sf)

    # No .tmp files should remain in the parent directory
    tmp_files = list(settings_path.parent.glob("*.tmp"))
    assert tmp_files == [], f"Temp files were not cleaned up: {tmp_files}"


def test_save_write_failure_does_not_corrupt_original(tmp_path: Path) -> None:
    """When the write raises, the original settings.json is left intact."""
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    original_content = json.dumps({"permissions": {"allow": ["Read(//original/**)"]}})
    settings_path.write_text(original_content)

    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//new/**)"]

    with patch("os.fdopen", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save(sf)

    # Original file must be unchanged
    assert settings_path.read_text() == original_content

"""Tests for storage module — load, save, atomic write."""

from __future__ import annotations

import json
from pathlib import Path

from server.lib import storage
from server.lib.models import SettingsFile


class TestLoad:
    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        settings = storage.load()
        assert settings.permissions.allow == []
        assert settings.sandbox.enabled is False

    def test_load_valid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "permissions": {"allow": ["mcp__proj__*"]},
                    "sandbox": {"enabled": True, "filesystem": {"allowWrite": ["/tmp/test"]}},
                }
            )
        )
        settings = storage.load()
        assert "mcp__proj__*" in settings.permissions.allow
        assert settings.sandbox.enabled is True
        assert "/tmp/test" in settings.sandbox.filesystem.allow_write

    def test_load_corrupt_json_returns_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{invalid json")
        settings = storage.load()
        assert settings.permissions.allow == []

    def test_load_preserves_unknown_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"customKey": "value", "permissions": {"allow": []}}))
        settings = storage.load()
        assert settings.raw["customKey"] == "value"


class TestSave:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        settings = SettingsFile(path=path)
        settings.permissions.allow.append("mcp__test__*")
        storage.save(settings)
        assert path.exists()
        data = json.loads(path.read_text())
        assert "mcp__test__*" in data["permissions"]["allow"]

    def test_save_roundtrip_preserves_unknown_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        original = {
            "customKey": "value",
            "permissions": {"allow": ["mcp__x__*"], "ask": ["Edit(*)"]},
        }
        path.write_text(json.dumps(original))
        settings = storage.load()
        settings.permissions.allow.append("mcp__new__*")
        storage.save(settings)
        data = json.loads(path.read_text())
        assert data["customKey"] == "value"
        assert "ask" in data["permissions"]  # preserved via raw


class TestHelpers:
    def test_allow_entries_for_path(self) -> None:
        entries = storage.allow_entries_for_path("/home/user/projects")
        assert entries == ["Edit(//home/user/projects/**)"]

    def test_allow_entries_rejects_relative_path(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="absolute"):
            storage.allow_entries_for_path("relative/path")

    def test_mcp_allow_entry(self) -> None:
        assert storage.mcp_allow_entry("plugin_proj_proj") == "mcp__plugin_proj_proj__*"

    def test_mcp_allow_entry_rejects_empty(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="empty"):
            storage.mcp_allow_entry("")

    def test_mcp_allow_entry_rejects_double_underscore(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="__"):
            storage.mcp_allow_entry("evil__name")

    def test_mcp_allow_entry_rejects_wildcard(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="\\*"):
            storage.mcp_allow_entry("evil*")

    def test_skill_allow_entry(self) -> None:
        assert storage.skill_allow_entry("proj") == "Skill(proj:*)"

    def test_skill_allow_entry_rejects_empty(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="empty"):
            storage.skill_allow_entry("")

    def test_skill_allow_entry_rejects_special_chars(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            storage.skill_allow_entry("evil*")
        with pytest.raises(ValueError):
            storage.skill_allow_entry("evil(")
        with pytest.raises(ValueError):
            storage.skill_allow_entry("evil)")

"""Tests for storage module — load, save, atomic write."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

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


class TestAtomicWrite:
    def test_preserves_file_mode(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text("{}")
        target.chmod(0o600)

        storage._atomic_write(target, '{"updated": true}\n')

        mode_bits = stat.S_IMODE(target.stat().st_mode)
        assert mode_bits == 0o600

    def test_new_file_no_chmod_error(self, tmp_path: Path) -> None:
        target = tmp_path / "new_settings.json"
        assert not target.exists()

        storage._atomic_write(target, '{"new": true}\n')

        assert target.exists()
        assert json.loads(target.read_text()) == {"new": True}

    def test_symlink_resolved(self, tmp_path: Path) -> None:
        real_file = tmp_path / "real.json"
        real_file.write_text("{}")
        real_file.chmod(0o644)
        link = tmp_path / "link.json"
        link.symlink_to(real_file)

        storage._atomic_write(link, '{"via": "symlink"}\n')

        assert json.loads(real_file.read_text()) == {"via": "symlink"}
        mode_bits = stat.S_IMODE(real_file.stat().st_mode)
        assert mode_bits == 0o644

    def test_cleanup_on_write_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text("{}")

        with (
            patch("server.lib.storage.os.fdopen", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            storage._atomic_write(target, "boom")

        # Original file untouched
        assert target.read_text() == "{}"
        # No leftover .tmp files
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

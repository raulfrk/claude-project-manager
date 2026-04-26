"""Tests for plugins/proj/server/server/lib/sandbox/storage.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sandbox.storage as storage_mod

from server.lib.sandbox.models import (
    Permissions,
    SandboxConfig,
    SandboxFilesystem,
    SandboxNetwork,
    SettingsFile,
)
from server.lib.sandbox.storage import (
    allow_entries_for_path,
    load,
    mcp_allow_entry,
    save,
    skill_allow_entry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_settings_path(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    """Redirect the module-level SETTINGS_PATH to a tmp path."""
    monkeypatch.setattr(storage_mod, "SETTINGS_PATH", path)


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


class TestLoad:
    def test_returns_defaults_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / "settings.json"
        _patch_settings_path(monkeypatch, settings_path)

        sf = load()

        assert sf.permissions.allow == []
        assert sf.sandbox.enabled is False

    def test_returns_defaults_when_json_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{not valid json")
        _patch_settings_path(monkeypatch, settings_path)

        sf = load()

        assert sf.permissions.allow == []
        assert sf.sandbox.enabled is False

    def test_loads_valid_settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / "settings.json"
        data = {
            "permissions": {"allow": ["Edit(//foo/**)"]},
            "sandbox": {"enabled": True},
        }
        settings_path.write_text(json.dumps(data))
        _patch_settings_path(monkeypatch, settings_path)

        sf = load()

        assert sf.permissions.allow == ["Edit(//foo/**)"]
        assert sf.sandbox.enabled is True

    def test_path_attribute_matches_settings_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / "settings.json"
        _patch_settings_path(monkeypatch, settings_path)

        sf = load()

        assert sf.path == settings_path


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------


class TestSave:
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "settings.json"
        sf = SettingsFile(path=nested, permissions=Permissions(allow=["Edit(//x/**))"]))
        save(sf)
        assert nested.exists()

    def test_file_exists_after_save(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        sf = SettingsFile(path=settings_path)
        save(sf)
        assert settings_path.exists()

    def test_roundtrip_save_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / "settings.json"
        _patch_settings_path(monkeypatch, settings_path)

        original = SettingsFile(
            path=settings_path,
            permissions=Permissions(allow=["Edit(//proj/**)"], deny=["Edit(//secret/**)"]),
            sandbox=SandboxConfig(
                enabled=True,
                filesystem=SandboxFilesystem(allow_write=["/tmp"]),
                network=SandboxNetwork(allowed_domains=["github.com"]),
            ),
        )
        save(original)

        restored = load()

        assert restored.permissions.allow == ["Edit(//proj/**)"]
        assert restored.permissions.deny == ["Edit(//secret/**)"]
        assert restored.sandbox.enabled is True
        assert restored.sandbox.filesystem.allow_write == ["/tmp"]
        assert restored.sandbox.network.allowed_domains == ["github.com"]

    def test_save_produces_valid_json(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        sf = SettingsFile(
            path=settings_path,
            permissions=Permissions(allow=["Edit(//foo/**)"]),
        )
        save(sf)

        content = settings_path.read_text()
        parsed = json.loads(content)
        assert parsed["permissions"]["allow"] == ["Edit(//foo/**)"]

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"permissions": {"allow": ["old"]}}))

        sf = SettingsFile(
            path=settings_path,
            permissions=Permissions(allow=["new"]),
        )
        save(sf)

        parsed = json.loads(settings_path.read_text())
        assert parsed["permissions"]["allow"] == ["new"]


# ---------------------------------------------------------------------------
# allow_entries_for_path()
# ---------------------------------------------------------------------------


class TestAllowEntriesForPath:
    def test_returns_edit_rule(self) -> None:
        rules = allow_entries_for_path("/home/user/project")
        assert rules == ["Edit(//home/user/project/**)"]

    def test_trailing_slash_stripped(self) -> None:
        rules = allow_entries_for_path("/home/user/project/")
        assert rules == ["Edit(//home/user/project/**)"]

    def test_double_slash_prefix_in_rule(self) -> None:
        rules = allow_entries_for_path("/tmp")
        assert rules[0].startswith("Edit(//")

    def test_relative_path_raises(self) -> None:
        with pytest.raises(ValueError, match="absolute"):
            allow_entries_for_path("relative/path")

    def test_returns_list(self) -> None:
        result = allow_entries_for_path("/tmp")
        assert isinstance(result, list)

    def test_deep_path(self) -> None:
        rules = allow_entries_for_path("/a/b/c/d")
        assert rules == ["Edit(//a/b/c/d/**)"]


# ---------------------------------------------------------------------------
# skill_allow_entry()
# ---------------------------------------------------------------------------


class TestSkillAllowEntry:
    def test_basic_prefix(self) -> None:
        assert skill_allow_entry("proj") == "Skill(proj:*)"

    def test_worktree_prefix(self) -> None:
        assert skill_allow_entry("worktree") == "Skill(worktree:*)"

    def test_empty_prefix_raises(self) -> None:
        with pytest.raises(ValueError):
            skill_allow_entry("")

    def test_prefix_with_star_raises(self) -> None:
        with pytest.raises(ValueError):
            skill_allow_entry("proj*")

    def test_prefix_with_paren_raises(self) -> None:
        with pytest.raises(ValueError):
            skill_allow_entry("proj(x)")

    def test_result_format(self) -> None:
        result = skill_allow_entry("myskill")
        assert result.startswith("Skill(")
        assert result.endswith(":*)")


# ---------------------------------------------------------------------------
# mcp_allow_entry()
# ---------------------------------------------------------------------------


class TestMcpAllowEntry:
    def test_basic_server_name(self) -> None:
        assert mcp_allow_entry("plugin_proj_proj") == "mcp__plugin_proj_proj__*"

    def test_empty_server_name_raises(self) -> None:
        with pytest.raises(ValueError):
            mcp_allow_entry("")

    def test_server_name_with_double_underscore_raises(self) -> None:
        with pytest.raises(ValueError):
            mcp_allow_entry("bad__name")

    def test_server_name_with_star_raises(self) -> None:
        with pytest.raises(ValueError):
            mcp_allow_entry("bad*name")

    def test_result_format(self) -> None:
        result = mcp_allow_entry("myserver")
        assert result == "mcp__myserver__*"
        assert result.startswith("mcp__")
        assert result.endswith("__*")

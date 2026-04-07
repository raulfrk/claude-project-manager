"""Tests for installer.detect — installation detection."""

from __future__ import annotations

import json
from pathlib import Path


from installer.detect import (
    InstallState,
    _parse_installed_plugins,
    _parse_mcp_entries,
    _validate_yaml,
    create_backup,
    detect_existing,
    display_detection,
    is_clean,
)


class TestParseInstalledPlugins:
    def test_missing_dir(self, tmp_path: Path):
        assert _parse_installed_plugins(tmp_path / "nonexistent") == []

    def test_empty_dir(self, tmp_path: Path):
        assert _parse_installed_plugins(tmp_path) == []

    def test_discovers_plugins(self, tmp_path: Path):
        (tmp_path / "proj").mkdir()
        (tmp_path / "worktree").mkdir()
        (tmp_path / ".hidden").mkdir()  # should be ignored
        result = _parse_installed_plugins(tmp_path)
        assert result == ["proj", "worktree"]


class TestParseMcpEntries:
    def test_valid_entries(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "plugin_proj_proj": {},
                        "plugin_sandbox_sandbox": {},
                        "other_server": {},
                    }
                }
            )
        )
        result = _parse_mcp_entries(settings)
        assert result == ["plugin_proj_proj", "plugin_sandbox_sandbox"]

    def test_missing_file(self, tmp_path: Path):
        assert _parse_mcp_entries(tmp_path / "nope.json") == []

    def test_malformed_json(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text("not json")
        assert _parse_mcp_entries(settings) == []

    def test_no_mcp_servers_key(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"other": "data"}))
        assert _parse_mcp_entries(settings) == []


class TestValidateYaml:
    def test_valid_yaml(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("version: 1\n")
        assert _validate_yaml(path) is True

    def test_empty_yaml(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("")
        assert _validate_yaml(path) is False

    def test_missing_yaml(self, tmp_path: Path):
        assert _validate_yaml(tmp_path / "missing.yaml") is False


class TestDetectExisting:
    def test_clean_home(self, mock_home: Path):
        state = detect_existing()
        assert is_clean(state) is True

    def test_detects_proj_yaml(self, mock_home: Path):
        (mock_home / ".claude" / "proj.yaml").write_text("version: 1\n")
        state = detect_existing()
        assert state.proj_yaml is not None
        assert is_clean(state) is False

    def test_detects_worktree_yaml(self, mock_home: Path):
        (mock_home / ".claude" / "worktree.yaml").write_text("version: 1\n")
        state = detect_existing()
        assert state.worktree_yaml is not None

    def test_detects_cache_plugins(self, mock_home: Path):
        cache = mock_home / ".claude" / "plugins" / "cache" / "claude-project-manager"
        (cache / "proj").mkdir(parents=True)
        (cache / "sandbox").mkdir(parents=True)
        state = detect_existing()
        assert state.installed_plugins == ["proj", "sandbox"]

    def test_detects_mcp_entries(self, mock_home: Path):
        settings = mock_home / ".claude" / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"plugin_proj_proj": {}}}))
        state = detect_existing()
        assert state.mcp_entries == ["plugin_proj_proj"]


class TestIsClean:
    def test_clean_state(self):
        assert is_clean(InstallState()) is True

    def test_dirty_proj_yaml(self):
        state = InstallState(proj_yaml=Path("/fake"))
        assert is_clean(state) is False

    def test_dirty_mcp_entries(self):
        state = InstallState(mcp_entries=["plugin_proj_proj"])
        assert is_clean(state) is False


class TestDisplayDetection:
    def test_no_crash_on_clean(self, mock_console):
        display_detection(InstallState(), mock_console)

    def test_no_crash_with_plugins(self, mock_console, mock_home: Path):
        state = InstallState(
            proj_yaml=mock_home / ".claude" / "proj.yaml",
            installed_plugins=["proj", "sandbox"],
            mcp_entries=["plugin_proj_proj"],
        )
        # Just verify it doesn't raise
        display_detection(state, mock_console)


class TestCreateBackup:
    def test_creates_backup_dir(self, mock_home: Path):
        proj = mock_home / ".claude" / "proj.yaml"
        proj.write_text("version: 1\n")
        state = InstallState(proj_yaml=proj)
        backup_dir = create_backup(state)
        assert backup_dir.exists()
        assert (backup_dir / "proj.yaml").exists()

    def test_backup_includes_cache(self, mock_home: Path):
        cache = mock_home / ".claude" / "plugins" / "cache" / "claude-project-manager"
        (cache / "proj").mkdir(parents=True)
        (cache / "proj" / "plugin.json").write_text("{}")
        state = InstallState(cache_dir=cache)
        backup_dir = create_backup(state)
        assert (backup_dir / "cache" / "proj" / "plugin.json").exists()

    def test_backup_handles_missing_paths(self, mock_home: Path):
        """State references paths that don't exist on disk."""
        state = InstallState(
            proj_yaml=mock_home / ".claude" / "proj.yaml",
            worktree_yaml=mock_home / ".claude" / "worktree.yaml",
        )
        backup_dir = create_backup(state)
        assert backup_dir.exists()

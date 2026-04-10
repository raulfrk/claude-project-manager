"""Tests for config_init and config_update MCP tools — todoist_mcp_server field."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from server.lib import storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool


@pytest.mark.anyio
class TestConfigInitMcpServer:
    async def test_config_init_todoist_mcp_server_persisted(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        new_cfg_path = tmp_path / "proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", new_cfg_path)

        result = await call_tool(
            mcp_app,
            "config_init",
            tracking_dir=str(tmp_path / "tracking"),
            todoist_mcp_server="sentry",
        )

        assert "saved" in result.lower()
        loaded = storage.load_config()
        assert loaded.todoist.mcp_server == "sentry"

    async def test_config_init_default_todoist_mcp_server(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        new_cfg_path = tmp_path / "proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", new_cfg_path)

        await call_tool(
            mcp_app,
            "config_init",
            tracking_dir=str(tmp_path / "tracking"),
        )

        loaded = storage.load_config()
        assert loaded.todoist.mcp_server == "claude_ai_Todoist"

    async def test_config_load_shows_todoist_mcp_server(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_load")

        assert "todoist.mcp_server" in result
        assert "todoist.auto_sync" in result

    async def test_config_load_shows_todoist_auto_sync_false(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        new_cfg_path = tmp_path / "proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", new_cfg_path)

        await call_tool(
            mcp_app,
            "config_init",
            tracking_dir=str(tmp_path / "tracking"),
            todoist_auto_sync=False,
        )

        result = await call_tool(mcp_app, "config_load")

        assert "todoist.auto_sync: False" in result


@pytest.mark.anyio
class TestConfigUpdateMcpServer:
    async def test_config_update_todoist_mcp_server_persisted(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", todoist_mcp_server="custom")

        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.todoist.mcp_server == "custom"

    async def test_config_update_todoist_mcp_server_empty_rejected(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", todoist_mcp_server="")

        assert "Invalid todoist_mcp_server" in result
        loaded = storage.load_config()
        assert loaded.todoist.mcp_server == "claude_ai_Todoist"

    async def test_config_update_todoist_mcp_server_null_byte_rejected(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", todoist_mcp_server="valid\x00evil")

        assert "Invalid todoist_mcp_server" in result
        loaded = storage.load_config()
        assert loaded.todoist.mcp_server == "claude_ai_Todoist"

    async def test_config_update_omitting_todoist_mcp_server_leaves_field_unchanged(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        await call_tool(mcp_app, "config_update", todoist_mcp_server="sentry")

        await call_tool(mcp_app, "config_update", default_priority="high")

        loaded = storage.load_config()
        assert loaded.todoist.mcp_server == "sentry"


@pytest.mark.anyio
class TestConfigUpdateIntegrationFlags:
    async def test_sandbox_integration_true_plugin_present(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        settings_path = tmp_path / "settings.json"
        settings_path.write_text(
            json.dumps({"permissions": {"allow": ["mcp__plugin_sandbox_sandbox__*"]}})
        )
        monkeypatch.setattr("server.lib.sandbox_helpers._USER_SETTINGS", settings_path)

        result = await call_tool(mcp_app, "config_update", sandbox_integration=True)

        assert "updated" in result.lower()
        assert "Warning" not in result
        loaded = storage.load_config()
        assert loaded.sandbox_integration is True

    async def test_sandbox_integration_false_no_warning(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings_path = tmp_path / "settings_missing.json"
        monkeypatch.setattr("server.lib.sandbox_helpers._USER_SETTINGS", settings_path)

        result = await call_tool(mcp_app, "config_update", sandbox_integration=False)

        assert "Warning" not in result
        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.sandbox_integration is False

    async def test_omitting_both_flags_leaves_them_unchanged(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({}))
        monkeypatch.setattr("server.lib.sandbox_helpers._USER_SETTINGS", settings_path)

        # Set initial values
        await call_tool(mcp_app, "config_update", sandbox_integration=False)
        await call_tool(mcp_app, "config_update", worktree_integration=False)

        # Update an unrelated field — both integration flags must stay unchanged
        result = await call_tool(mcp_app, "config_update", default_priority="high")

        assert "Warning" not in result
        loaded = storage.load_config()
        assert loaded.sandbox_integration is False
        assert loaded.worktree_integration is False


@pytest.mark.anyio
class TestConfigArchiveDestination:
    async def test_config_update_archive_destination_persisted(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", archive_destination="/tmp/arch")

        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.archive.destination == "/tmp/arch"

    async def test_config_load_shows_archive_destination(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_load")

        assert "archive.destination" in result


class TestGitTrackingConfig:
    @pytest.mark.anyio
    async def test_config_init_git_tracking(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(
            mcp_app,
            "config_init",
            git_tracking_enabled=True,
            git_tracking_github_enabled=True,
            git_tracking_github_repo_format="my-{project-name}",
        )
        assert "saved" in result.lower()
        loaded = storage.load_config()
        assert loaded.git_tracking.enabled is True
        assert loaded.git_tracking.github_enabled is True
        assert loaded.git_tracking.github_repo_format == "my-{project-name}"

    @pytest.mark.anyio
    async def test_config_update_git_tracking(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_update", git_tracking_enabled=True)
        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.git_tracking.enabled is True
        assert loaded.git_tracking.github_enabled is False  # unchanged

    @pytest.mark.anyio
    async def test_config_load_shows_git_tracking(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_load")
        assert "git_tracking.enabled" in result
        assert "git_tracking.github_enabled" in result
        assert "git_tracking.github_repo_format" in result


@pytest.mark.anyio
class TestTeamModeConfig:
    async def test_config_init_with_team_mode_params(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        new_cfg_path = tmp_path / "proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", new_cfg_path)

        result = await call_tool(
            mcp_app,
            "config_init",
            tracking_dir=str(tmp_path / "tracking"),
            team_mode_enabled=True,
            team_mode_max_agents=6,
            team_mode_trust_level=2,
        )

        assert "saved" in result.lower()
        loaded = storage.load_config()
        assert loaded.team_mode.enabled is True
        assert loaded.team_mode.max_agents == 6
        assert loaded.team_mode.trust_level == 2

    async def test_config_load_displays_team_mode(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_load")

        assert "team_mode.enabled" in result
        assert "team_mode.max_agents" in result
        assert "team_mode.trust_level" in result

    async def test_config_update_modifies_team_mode_fields(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(
            mcp_app,
            "config_update",
            team_mode_enabled=True,
            team_mode_max_agents=8,
            team_mode_trust_level=3,
        )

        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.team_mode.enabled is True
        assert loaded.team_mode.max_agents == 8
        assert loaded.team_mode.trust_level == 3

    async def test_config_update_rejects_invalid_trust_level(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", team_mode_trust_level=5)

        assert "Invalid team_mode_trust_level" in result
        loaded = storage.load_config()
        assert loaded.team_mode.trust_level == 1  # unchanged default

    async def test_config_update_rejects_invalid_max_agents(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", team_mode_max_agents=0)

        assert "Invalid team_mode_max_agents" in result
        loaded = storage.load_config()
        assert loaded.team_mode.max_agents == 30  # unchanged default

    async def test_config_update_partial_team_mode_leaves_others_unchanged(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        # First set team_mode to non-default values
        await call_tool(
            mcp_app,
            "config_update",
            team_mode_enabled=True,
            team_mode_max_agents=6,
            team_mode_trust_level=2,
        )

        # Update only max_agents
        result = await call_tool(mcp_app, "config_update", team_mode_max_agents=10)

        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.team_mode.enabled is True  # unchanged
        assert loaded.team_mode.max_agents == 10  # updated
        assert loaded.team_mode.trust_level == 2  # unchanged

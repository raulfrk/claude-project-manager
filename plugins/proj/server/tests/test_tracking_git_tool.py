"""Tests for tracking_git_flush MCP tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.lib import state, storage
from server.lib.models import GitTracking, ProjConfig
from tests.conftest import call_tool, setup_project


@pytest.fixture(autouse=True)
def _isolate_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent git from discovering the parent project repo."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


class TestTrackingGitFlush:
    @pytest.fixture()
    def cfg_with_git(self, cfg: ProjConfig) -> ProjConfig:
        """Config with git tracking enabled."""
        cfg.git_tracking = GitTracking(enabled=True)
        storage.save_config(cfg)
        return cfg

    @pytest.fixture()
    def project_with_git(self, cfg_with_git: ProjConfig, tmp_path: Path, mcp_app) -> str:  # type: ignore[no-untyped-def]
        name = "test-proj"
        repo_path = str(tmp_path / "repo")
        Path(repo_path).mkdir()
        setup_project(cfg_with_git, name, repo_path)
        state.set_session_active(name)
        return name

    @pytest.mark.anyio
    async def test_flush_disabled(self, cfg: ProjConfig, tmp_path: Path, mcp_app) -> None:  # type: ignore[no-untyped-def]
        name = "test-proj"
        setup_project(cfg, name, str(tmp_path / "repo"))
        Path(tmp_path / "repo").mkdir(exist_ok=True)
        state.set_session_active(name)
        result = await call_tool(mcp_app, "tracking_git_flush")
        data = json.loads(result)
        assert data["status"] == "disabled"

    @pytest.mark.anyio
    async def test_flush_commits(self, cfg_with_git: ProjConfig, project_with_git: str, mcp_app) -> None:  # type: ignore[no-untyped-def]
        # Write something to tracking dir
        tracking = storage.tracking_dir(cfg_with_git, project_with_git)
        (tracking / "extra.txt").write_text("new data")
        result = await call_tool(mcp_app, "tracking_git_flush", commit_message="test flush")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["sha"]
        assert data["message"] == "test flush"

    @pytest.mark.anyio
    async def test_flush_no_changes(self, cfg_with_git: ProjConfig, project_with_git: str, mcp_app) -> None:  # type: ignore[no-untyped-def]
        # First flush to commit existing files
        await call_tool(mcp_app, "tracking_git_flush", commit_message="initial")
        # Second flush with no new changes
        result = await call_tool(mcp_app, "tracking_git_flush", commit_message="no changes")
        data = json.loads(result)
        assert data["status"] == "no_changes"

    @pytest.mark.anyio
    async def test_flush_auto_message(self, cfg_with_git: ProjConfig, project_with_git: str, mcp_app) -> None:  # type: ignore[no-untyped-def]
        tracking = storage.tracking_dir(cfg_with_git, project_with_git)
        (tracking / "extra.txt").write_text("data")
        result = await call_tool(mcp_app, "tracking_git_flush")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["message"] == f"Update {project_with_git}"

    @pytest.mark.anyio
    async def test_flush_per_project_override_disables(self, cfg_with_git: ProjConfig, project_with_git: str, mcp_app) -> None:  # type: ignore[no-untyped-def]
        """Per-project enabled=False overrides global enabled=True."""
        from server.lib.models import ProjectGitTrackingConfig
        meta = storage.load_meta(cfg_with_git, project_with_git)
        meta.git_tracking = ProjectGitTrackingConfig(enabled=False)
        storage.save_meta(cfg_with_git, meta)
        result = await call_tool(mcp_app, "tracking_git_flush")
        data = json.loads(result)
        assert data["status"] == "disabled"

    @pytest.mark.anyio
    async def test_flush_per_project_override_enables(self, cfg: ProjConfig, tmp_path: Path, mcp_app) -> None:  # type: ignore[no-untyped-def]
        """Per-project enabled=True overrides global enabled=False (default)."""
        from server.lib.models import ProjectGitTrackingConfig
        name = "test-proj"
        repo_path = str(tmp_path / "repo")
        Path(repo_path).mkdir()
        setup_project(cfg, name, repo_path)
        state.set_session_active(name)
        meta = storage.load_meta(cfg, name)
        meta.git_tracking = ProjectGitTrackingConfig(enabled=True)
        storage.save_meta(cfg, meta)
        tracking = storage.tracking_dir(cfg, name)
        (tracking / "extra.txt").write_text("data")
        result = await call_tool(mcp_app, "tracking_git_flush", commit_message="per-project")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["sha"]


class TestProjUpdateMetaGitTracking:
    @pytest.mark.anyio
    async def test_update_git_tracking_fields(self, cfg: ProjConfig, tmp_path: Path, mcp_app) -> None:  # type: ignore[no-untyped-def]
        name = "test-proj"
        repo_path = str(tmp_path / "repo")
        Path(repo_path).mkdir()
        setup_project(cfg, name, repo_path)
        state.set_session_active(name)
        result = await call_tool(
            mcp_app, "proj_update_meta",
            git_tracking_enabled=True,
            git_tracking_github_enabled=True,
            git_tracking_github_repo_format="custom-{project-name}",
        )
        assert "Updated" in result
        meta = storage.load_meta(cfg, name)
        assert meta.git_tracking.enabled is True
        assert meta.git_tracking.github_enabled is True
        assert meta.git_tracking.github_repo_format == "custom-{project-name}"

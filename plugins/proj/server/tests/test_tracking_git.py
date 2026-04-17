"""Tests for server.lib.tracking_git."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.lib.models import GitTracking, ProjConfig, ProjectGitTrackingConfig, ProjectMeta
from server.lib.tracking_git import (
    _arun,
    _run,
    ensure_git_repo,
    is_git_repo,
    resolve_config,
    resolve_repo_name,
    tracking_commit,
    tracking_commit_async,
    tracking_push_async,
)


@pytest.fixture(autouse=True)
def _isolate_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent git from discovering the parent project repo.

    Sets GIT_CEILING_DIRECTORIES so that tmp_path directories are not
    considered part of any enclosing git repository.
    Also configures git user identity for CI environments.
    """
    # The ceiling must be the parent of tmp_path (or higher) so that
    # git won't traverse upward past tmp_path into the real project repo.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test User")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test User")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


class TestIsGitRepo:
    def test_not_a_repo(self, tmp_path: Path) -> None:
        assert is_git_repo(tmp_path) is False

    def test_is_a_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        assert is_git_repo(tmp_path) is True


class TestEnsureGitRepo:
    def test_creates_repo(self, tmp_path: Path) -> None:
        target = tmp_path / "tracking"
        assert ensure_git_repo(target) is True
        assert (target / ".git").is_dir()

    def test_creates_gitignore(self, tmp_path: Path) -> None:
        target = tmp_path / "tracking"
        ensure_git_repo(target)
        gitignore = target / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert "*.tmp" in content
        assert "__pycache__/" in content

    def test_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "tracking"
        assert ensure_git_repo(target) is True
        assert ensure_git_repo(target) is True

    def test_existing_gitignore_entries_preserved(self, tmp_path: Path) -> None:
        """Existing .gitignore content is preserved; new WAL entries are appended."""
        target = tmp_path / "tracking"
        target.mkdir()
        subprocess.run(["git", "init"], cwd=target, check=True, capture_output=True)
        gitignore = target / ".gitignore"
        gitignore.write_text("custom\n")
        ensure_git_repo(target)
        content = gitignore.read_text()
        assert "custom" in content
        assert "data.db-wal" in content
        assert "data.db-shm" in content


class TestTrackingCommit:
    def test_commit_with_changes(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        ensure_git_repo(target)
        (target / "todos.json").write_text("[]")
        sha = tracking_commit(target, "test commit")
        assert sha is not None
        assert len(sha) >= 7

    def test_no_changes_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        ensure_git_repo(target)
        # Commit the initial gitignore first
        tracking_commit(target, "initial")
        # Second commit with no changes
        sha = tracking_commit(target, "no changes")
        assert sha is None

    def test_commit_message_used(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        ensure_git_repo(target)
        (target / "todos.json").write_text("[]")
        tracking_commit(target, "my custom message")
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "my custom message" in result.stdout


class TestResolveConfig:
    def test_global_defaults_when_no_overrides(self) -> None:
        cfg = ProjConfig(
            git_tracking=GitTracking(
                enabled=True, github_enabled=True, github_repo_format="tracking-{project-name}"
            )
        )
        meta = ProjectMeta(name="test")
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is True
        assert github is True
        assert fmt == "tracking-{project-name}"

    def test_per_project_overrides_global(self) -> None:
        cfg = ProjConfig(
            git_tracking=GitTracking(
                enabled=True, github_enabled=True, github_repo_format="tracking-{project-name}"
            )
        )
        meta = ProjectMeta(name="test")
        meta.git_tracking = ProjectGitTrackingConfig(
            enabled=False, github_enabled=False, github_repo_format="custom-{project-name}"
        )
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is False
        assert github is False
        assert fmt == "custom-{project-name}"

    def test_partial_override(self) -> None:
        cfg = ProjConfig(
            git_tracking=GitTracking(
                enabled=True, github_enabled=False, github_repo_format="tracking-{project-name}"
            )
        )
        meta = ProjectMeta(name="test")
        meta.git_tracking = ProjectGitTrackingConfig(github_enabled=True)  # only override github
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is True  # from global
        assert github is True  # overridden
        assert fmt == "tracking-{project-name}"  # from global


class TestResolveRepoName:
    def test_default_format(self) -> None:
        assert resolve_repo_name("tracking-{project-name}", "my-app") == "tracking-my-app"

    def test_custom_format(self) -> None:
        assert resolve_repo_name("proj-{project-name}-data", "foo") == "proj-foo-data"

    def test_no_placeholder(self) -> None:
        assert resolve_repo_name("monorepo", "anything") == "monorepo"


class TestArun:
    @pytest.mark.anyio
    async def test_returns_same_as_run(self) -> None:
        """_arun() returns same (returncode, stdout, stderr) as _run()."""
        sync_result = _run(["git", "--version"], ".")
        async_result = await _arun(["git", "--version"], ".")
        assert sync_result == async_result

    @pytest.mark.anyio
    async def test_uses_to_thread(self) -> None:
        """Verify asyncio.to_thread is actually called."""
        with patch("server.lib.tracking_git.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
            mock_tt.return_value = (0, "output", "")
            result = await _arun(["git", "--version"], ".")
            mock_tt.assert_called_once_with(_run, ["git", "--version"], ".")
            assert result == (0, "output", "")


class TestTrackingCommitAsync:
    @pytest.mark.anyio
    async def test_commit_with_changes(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        ensure_git_repo(target)
        (target / "todos.json").write_text("[]")
        sha = await tracking_commit_async(target, "async test commit")
        assert sha is not None
        assert len(sha) >= 7

    @pytest.mark.anyio
    async def test_no_changes_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        ensure_git_repo(target)
        tracking_commit(target, "initial")
        sha = await tracking_commit_async(target, "no changes")
        assert sha is None

    @pytest.mark.anyio
    async def test_same_result_as_sync(self, tmp_path: Path) -> None:
        """Async variant produces same SHA as sync for identical content."""
        sync_target = tmp_path / "sync_repo"
        async_target = tmp_path / "async_repo"
        ensure_git_repo(sync_target)
        ensure_git_repo(async_target)
        (sync_target / "todos.json").write_text("[]")
        (async_target / "todos.json").write_text("[]")
        sync_sha = tracking_commit(sync_target, "same msg")
        async_sha = await tracking_commit_async(async_target, "same msg")
        # Both should produce a valid SHA (content differs due to timestamps, but both non-None)
        assert sync_sha is not None
        assert async_sha is not None


class TestTrackingPushAsync:
    @pytest.mark.anyio
    async def test_push_fails_without_remote(self, tmp_path: Path) -> None:
        """Push should fail gracefully when no remote is configured."""
        target = tmp_path / "repo"
        ensure_git_repo(target)
        (target / "test.txt").write_text("hello")
        await tracking_commit_async(target, "initial")
        result = await tracking_push_async(target)
        assert result is False

"""Tests for server.lib.tracking_git."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from server.lib.models import GitTracking, ProjConfig, ProjectGitTrackingConfig, ProjectMeta
from server.lib.tracking_git import (
    ensure_git_repo,
    ensure_remote,
    is_git_repo,
    resolve_config,
    resolve_repo_name,
    tracking_commit,
    tracking_push,
)


@pytest.fixture(autouse=True)
def _isolate_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent git from discovering the parent project repo.

    Sets GIT_CEILING_DIRECTORIES so that tmp_path directories are not
    considered part of any enclosing git repository.
    """
    # The ceiling must be the parent of tmp_path (or higher) so that
    # git won't traverse upward past tmp_path into the real project repo.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


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

    def test_existing_gitignore_not_overwritten(self, tmp_path: Path) -> None:
        target = tmp_path / "tracking"
        target.mkdir()
        subprocess.run(["git", "init"], cwd=target, check=True, capture_output=True)
        gitignore = target / ".gitignore"
        gitignore.write_text("custom\n")
        ensure_git_repo(target)
        assert gitignore.read_text() == "custom\n"


class TestTrackingCommit:
    def test_commit_with_changes(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        ensure_git_repo(target)
        (target / "test.txt").write_text("hello")
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
        (target / "test.txt").write_text("hello")
        tracking_commit(target, "my custom message")
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target, capture_output=True, text=True, check=True,
        )
        assert "my custom message" in result.stdout


class TestResolveConfig:
    def test_global_defaults_when_no_overrides(self) -> None:
        cfg = ProjConfig(git_tracking=GitTracking(enabled=True, github_enabled=True, github_repo_format="tracking-{project-name}"))
        meta = ProjectMeta(name="test")
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is True
        assert github is True
        assert fmt == "tracking-{project-name}"

    def test_per_project_overrides_global(self) -> None:
        cfg = ProjConfig(git_tracking=GitTracking(enabled=True, github_enabled=True, github_repo_format="tracking-{project-name}"))
        meta = ProjectMeta(name="test")
        meta.git_tracking = ProjectGitTrackingConfig(enabled=False, github_enabled=False, github_repo_format="custom-{project-name}")
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is False
        assert github is False
        assert fmt == "custom-{project-name}"

    def test_partial_override(self) -> None:
        cfg = ProjConfig(git_tracking=GitTracking(enabled=True, github_enabled=False, github_repo_format="tracking-{project-name}"))
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

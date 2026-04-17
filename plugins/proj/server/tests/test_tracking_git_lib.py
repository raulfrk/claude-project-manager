"""Tests for server.lib.tracking_git — focused on _run, resolve_config, and core git ops."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib.models import GitTracking, ProjConfig, ProjectGitTrackingConfig, ProjectMeta
from server.lib.tracking_git import (
    _run,
    ensure_git_repo,
    is_git_repo,
    resolve_config,
    resolve_repo_name,
    tracking_commit,
)


@pytest.fixture(autouse=True)
def _isolate_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent git from discovering the parent project repo."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test User")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test User")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


# ---------------------------------------------------------------------------
# _run tests
# ---------------------------------------------------------------------------


class TestRun:
    def test_returns_tuple(self) -> None:
        """_run returns (returncode, stdout, stderr)."""
        rc, stdout, stderr = _run(["git", "--version"], ".")
        assert rc == 0
        assert "git" in stdout.lower()
        assert isinstance(stderr, str)

    def test_nonzero_returncode(self, tmp_path: Path) -> None:
        """Failed command returns nonzero rc."""
        rc, _stdout, _stderr = _run(["git", "status"], tmp_path)
        assert rc != 0

    def test_missing_executable_returns_1(self) -> None:
        """Missing executable → (1, '', 'command not found')."""
        rc, stdout, stderr = _run(["__nonexistent_cmd_xyz__"], ".")
        assert rc == 1
        assert stdout == ""
        assert "not found" in stderr

    def test_subprocess_error_returns_1(self) -> None:
        """subprocess.SubprocessError → (1, '', 'command not found')."""
        with patch("server.lib.tracking_git.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.SubprocessError("failure")
            rc, stdout, stderr = _run(["git", "status"], ".")
            assert rc == 1
            assert stdout == ""
            assert "not found" in stderr

    def test_captures_stdout(self) -> None:
        """stdout is captured correctly."""
        rc, stdout, _ = _run(["git", "--version"], ".")
        assert rc == 0
        assert stdout.strip() != ""

    def test_captures_stderr(self, tmp_path: Path) -> None:
        """stderr is captured (not sent to terminal)."""
        # git status in non-repo writes to stderr
        _rc, _stdout, stderr = _run(["git", "status"], tmp_path)
        assert isinstance(stderr, str)


# ---------------------------------------------------------------------------
# resolve_config tests
# ---------------------------------------------------------------------------


class TestResolveConfig:
    def test_global_defaults_used_when_meta_none(self) -> None:
        """None meta values fall through to global defaults."""
        cfg = ProjConfig(
            git_tracking=GitTracking(
                enabled=True,
                github_enabled=True,
                github_repo_format="tracking-{project-name}",
            )
        )
        meta = ProjectMeta(name="test")
        # meta.git_tracking fields are None by default
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is True
        assert github is True
        assert fmt == "tracking-{project-name}"

    def test_per_project_overrides_global(self) -> None:
        """Per-project non-None values override global."""
        cfg = ProjConfig(
            git_tracking=GitTracking(
                enabled=True,
                github_enabled=True,
                github_repo_format="tracking-{project-name}",
            )
        )
        meta = ProjectMeta(name="test")
        meta.git_tracking = ProjectGitTrackingConfig(
            enabled=False,
            github_enabled=False,
            github_repo_format="custom-{project-name}",
        )
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is False
        assert github is False
        assert fmt == "custom-{project-name}"

    def test_partial_override_only_github(self) -> None:
        """Partial override: only github_enabled set in meta, rest from global."""
        cfg = ProjConfig(
            git_tracking=GitTracking(
                enabled=True,
                github_enabled=False,
                github_repo_format="tracking-{project-name}",
            )
        )
        meta = ProjectMeta(name="test")
        meta.git_tracking = ProjectGitTrackingConfig(github_enabled=True)
        enabled, github, fmt = resolve_config(cfg, meta)
        assert enabled is True  # from global
        assert github is True  # overridden
        assert fmt == "tracking-{project-name}"  # from global

    def test_all_false_global(self) -> None:
        cfg = ProjConfig(
            git_tracking=GitTracking(enabled=False, github_enabled=False, github_repo_format="x")
        )
        meta = ProjectMeta(name="p")
        enabled, github, _fmt = resolve_config(cfg, meta)
        assert enabled is False
        assert github is False


# ---------------------------------------------------------------------------
# is_git_repo tests
# ---------------------------------------------------------------------------


class TestIsGitRepo:
    def test_not_a_repo(self, tmp_path: Path) -> None:
        assert is_git_repo(tmp_path) is False

    def test_is_a_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        assert is_git_repo(tmp_path) is True


# ---------------------------------------------------------------------------
# ensure_git_repo tests
# ---------------------------------------------------------------------------


class TestEnsureGitRepo:
    def test_creates_repo_and_dot_git(self, tmp_path: Path) -> None:
        target = tmp_path / "tracking"
        result = ensure_git_repo(target)
        assert result is True
        assert (target / ".git").is_dir()

    def test_creates_gitignore_with_expected_entries(self, tmp_path: Path) -> None:
        target = tmp_path / "tracking"
        ensure_git_repo(target)
        gitignore = target / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert "*.tmp" in content
        assert "__pycache__/" in content
        assert "*.pyc" in content

    def test_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "tracking"
        assert ensure_git_repo(target) is True
        assert ensure_git_repo(target) is True

    def test_existing_gitignore_entries_preserved(self, tmp_path: Path) -> None:
        """Existing .gitignore content is preserved; new WAL entries are appended."""
        target = tmp_path / "tracking"
        target.mkdir()
        subprocess.run(["git", "init"], cwd=target, check=True, capture_output=True)
        (target / ".gitignore").write_text("custom\n")
        ensure_git_repo(target)
        content = (target / ".gitignore").read_text()
        assert "custom" in content
        assert "data.db-wal" in content
        assert "data.db-shm" in content


# ---------------------------------------------------------------------------
# tracking_commit tests
# ---------------------------------------------------------------------------


class TestTrackingCommit:
    def test_returns_none_when_no_changes(self, tmp_path: Path) -> None:
        """No staged changes → returns None."""
        target = tmp_path / "repo"
        ensure_git_repo(target)
        tracking_commit(target, "initial")
        sha = tracking_commit(target, "no changes")
        assert sha is None

    def test_returns_short_sha_on_success(self, tmp_path: Path) -> None:
        """Returns short SHA string after successful commit."""
        target = tmp_path / "repo"
        ensure_git_repo(target)
        (target / "todos.json").write_text("[]")
        sha = tracking_commit(target, "first commit")
        assert sha is not None
        assert len(sha) >= 7
        assert sha == sha.strip()

    def test_commit_records_message(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        ensure_git_repo(target)
        (target / "todos.json").write_text("[]")
        tracking_commit(target, "my commit message")
        rc, log, _ = _run(["git", "log", "--oneline", "-1"], target)
        assert rc == 0
        assert "my commit message" in log


# ---------------------------------------------------------------------------
# resolve_repo_name tests
# ---------------------------------------------------------------------------


class TestResolveRepoName:
    def test_substitutes_project_name(self) -> None:
        assert resolve_repo_name("tracking-{project-name}", "my-app") == "tracking-my-app"

    def test_multiple_placeholder_substitution(self) -> None:
        assert resolve_repo_name("{project-name}-data-{project-name}", "foo") == "foo-data-foo"

    def test_no_placeholder(self) -> None:
        assert resolve_repo_name("monorepo", "anything") == "monorepo"

    def test_empty_project_name(self) -> None:
        assert resolve_repo_name("tracking-{project-name}", "") == "tracking-"

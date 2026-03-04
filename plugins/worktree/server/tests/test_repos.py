"""Tests for server.tools.repos functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib import storage
from server.lib.models import BaseRepo, WorktreeConfig
from server.tools.repos import add_repo, list_repos, remove_repo


@pytest.fixture()
def empty_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "worktree.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("WORKTREE_CONFIG", raising=False)
    return config_path


class TestAddRepo:
    def test_adds_valid_git_repo(self, tmp_path: Path, empty_config: Path) -> None:
        # tmp_path exists; mock is_git_repo to return True
        with patch("server.tools.repos.is_git_repo", return_value=True):
            result = add_repo("myapp", str(tmp_path))
        assert "Registered" in result
        assert "myapp" in result
        config = storage.load()
        assert any(r.label == "myapp" for r in config.base_repos)

    def test_rejects_non_git_path(self, tmp_path: Path, empty_config: Path) -> None:
        with patch("server.tools.repos.is_git_repo", return_value=False):
            result = add_repo("myapp", str(tmp_path))
        assert "Error" in result

    def test_rejects_nonexistent_path(self, empty_config: Path) -> None:
        result = add_repo("x", "/nonexistent/path/that/does/not/exist")
        assert "Error" in result or "does not exist" in result

    def test_rejects_duplicate_label(self, tmp_path: Path, empty_config: Path) -> None:
        config = WorktreeConfig(base_repos=[BaseRepo(label="myapp", path=str(tmp_path))])
        storage.save(config)
        with patch("server.tools.repos.is_git_repo", return_value=True):
            result = add_repo("myapp", str(tmp_path))
        assert "already exists" in result


class TestRemoveRepo:
    def test_removes_existing(self, tmp_path: Path, empty_config: Path) -> None:
        config = WorktreeConfig(base_repos=[BaseRepo(label="myapp", path=str(tmp_path))])
        storage.save(config)
        result = remove_repo("myapp")
        assert "Removed" in result
        assert storage.load().base_repos == []

    def test_no_match(self, empty_config: Path) -> None:
        result = remove_repo("nonexistent")
        assert "No repo" in result


class TestListRepos:
    def test_empty(self, empty_config: Path) -> None:
        result = list_repos()
        assert "No base repos" in result

    def test_shows_repos(self, tmp_path: Path, empty_config: Path) -> None:
        config = WorktreeConfig(
            base_repos=[BaseRepo(label="myapp", path=str(tmp_path), default_branch="main")]
        )
        storage.save(config)
        result = list_repos()
        assert "myapp" in result
        assert str(tmp_path) in result

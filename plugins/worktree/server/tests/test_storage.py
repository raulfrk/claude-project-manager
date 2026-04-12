"""Tests for server.lib.storage."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib import storage
from server.lib.models import BaseRepo, WorktreeConfig


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "worktree.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", path)
    monkeypatch.delenv("WORKTREE_CONFIG", raising=False)
    return path


def test_load_missing_returns_defaults(config_path: Path) -> None:
    config = storage.load()
    assert config.base_repos == []
    assert "worktrees" in config.default_worktree_dir


def test_save_and_load_roundtrip(config_path: Path) -> None:
    config = WorktreeConfig(
        default_worktree_dir="~/my-trees",
        base_repos=[BaseRepo(label="myapp", path="/home/user/myapp", default_branch="main")],
    )
    storage.save(config)

    loaded = storage.load()
    assert loaded.default_worktree_dir == "~/my-trees"
    assert len(loaded.base_repos) == 1
    assert loaded.base_repos[0].label == "myapp"
    assert loaded.base_repos[0].path == "/home/user/myapp"


def test_save_creates_parent_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nested = tmp_path / "deep" / "nested" / "worktree.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", nested)
    monkeypatch.delenv("WORKTREE_CONFIG", raising=False)
    storage.save(WorktreeConfig())
    assert nested.exists()


def test_save_writes_valid_yaml(config_path: Path) -> None:
    config = WorktreeConfig(base_repos=[BaseRepo(label="x", path="/x", default_branch="dev")])
    storage.save(config)
    with config_path.open() as f:
        data = yaml.safe_load(f)
    assert data["version"] == 1
    assert data["base_repos"][0]["label"] == "x"


def test_env_var_overrides_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom.yaml"
    monkeypatch.setenv("WORKTREE_CONFIG", str(custom))
    config = WorktreeConfig(default_worktree_dir="/custom/trees")
    storage.save(config)
    assert custom.exists()
    loaded = storage.load()
    assert loaded.default_worktree_dir == "/custom/trees"


def test_save_and_load_roundtrip_custom_default_branch(config_path: Path) -> None:
    """Save with default_branch='master', load back, verify it roundtrips."""
    config = WorktreeConfig(
        default_worktree_dir="~/my-trees",
        base_repos=[BaseRepo(label="myapp", path="/home/user/myapp", default_branch="master")],
    )
    storage.save(config)

    loaded = storage.load()
    assert len(loaded.base_repos) == 1
    assert loaded.base_repos[0].default_branch == "master"


def test_from_dict_missing_default_branch_defaults_to_main() -> None:
    """BaseRepo.from_dict() without default_branch key defaults to 'main'."""
    repo = BaseRepo.from_dict({"label": "x", "path": "/x"})
    assert repo.default_branch == "main"


def test_baserepo_to_dict_from_dict_roundtrip_custom_branch() -> None:
    """BaseRepo.to_dict() -> BaseRepo.from_dict() preserves custom default_branch."""
    original = BaseRepo(label="myapp", path="/home/user/myapp", default_branch="develop")
    restored = BaseRepo.from_dict(original.to_dict())
    assert restored.default_branch == "develop"
    assert restored.label == original.label
    assert restored.path == original.path


def test_from_dict_non_list_base_repos() -> None:
    """WorktreeConfig.from_dict handles non-list base_repos gracefully."""
    config = WorktreeConfig.from_dict({"base_repos": "not a list"})
    assert config.base_repos == []


def test_from_dict_filters_non_dict_entries() -> None:
    """WorktreeConfig.from_dict skips non-dict entries in base_repos."""
    config = WorktreeConfig.from_dict(
        {"base_repos": [{"label": "ok", "path": "/ok"}, "invalid", 42]}
    )
    assert len(config.base_repos) == 1
    assert config.base_repos[0].label == "ok"


# -- _atomic_write cleanup tests --


class TestAtomicWriteCleanup:
    """Tests for _atomic_write temp file cleanup on success and failure."""

    def test_no_orphaned_tmp_on_success(self, config_path: Path) -> None:
        """After a successful save, no .tmp files remain."""
        storage.save(WorktreeConfig())
        assert config_path.exists()
        assert list(config_path.parent.glob("*.tmp")) == []

    def test_write_failure_cleans_tmp(self, config_path: Path) -> None:
        """OSError during write removes temp file and re-raises."""
        # Pre-populate so we can verify original is untouched
        config_path.write_text("original content")

        import unittest.mock as mock

        def failing_fdopen(fd: int, mode: str) -> object:
            # Close the fd so it doesn't leak, then raise
            import os as _os

            _os.close(fd)
            raise OSError("disk full")

        with (
            mock.patch.object(storage.os, "fdopen", side_effect=failing_fdopen),
            pytest.raises(OSError, match="disk full"),
        ):
            storage.save(WorktreeConfig())

        # No orphaned temp files
        assert list(config_path.parent.glob("*.tmp")) == []
        # Original file untouched
        assert config_path.read_text() == "original content"

    def test_replace_failure_cleans_tmp(self, config_path: Path) -> None:
        """OSError during Path.replace removes temp file and re-raises."""
        import unittest.mock as mock

        with (
            mock.patch.object(Path, "replace", side_effect=OSError("permission denied")),
            pytest.raises(OSError, match="permission denied"),
        ):
            storage.save(WorktreeConfig())

        assert list(config_path.parent.glob("*.tmp")) == []

    def test_cleanup_failure_still_raises_original(self, config_path: Path) -> None:
        """If both write and cleanup fail, the original error propagates."""
        import unittest.mock as mock

        def failing_fdopen(fd: int, mode: str) -> object:
            import os as _os

            _os.close(fd)
            raise OSError("write error")

        with (
            mock.patch.object(storage.os, "fdopen", side_effect=failing_fdopen),
            mock.patch.object(Path, "unlink", side_effect=OSError("unlink failed")),
            pytest.raises(OSError, match="write error"),
        ):
            storage.save(WorktreeConfig())

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

"""Regression tests for git-worktree-aware cwd → project detection.

ctx_detect_project_name must resolve worktree cwds to the main repo path so
SessionStart hook auto-loads correctly when the user is working in a worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from server.lib.models import ProjConfig
from server.tools.context import ctx_detect_project_name
from tests.conftest import setup_project


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "README").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


def test_ctx_detect_resolves_worktree_to_project(cfg: ProjConfig, tmp_path: Path) -> None:
    """cwd inside a git worktree should resolve to the project tracking the main repo."""
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _init_git_repo(main_repo)

    worktree_path = tmp_path / "wt-feat"
    subprocess.run(
        [
            "git",
            "-C",
            str(main_repo),
            "worktree",
            "add",
            "-q",
            "-b",
            "feat",
            str(worktree_path),
        ],
        check=True,
    )

    setup_project(cfg, "myapp", str(main_repo))

    assert ctx_detect_project_name(str(worktree_path)) == "myapp"


def test_ctx_detect_resolves_worktree_subdir_to_project(cfg: ProjConfig, tmp_path: Path) -> None:
    """cwd in a SUBDIR of a worktree should still resolve correctly."""
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _init_git_repo(main_repo)

    worktree_path = tmp_path / "wt"
    subprocess.run(
        [
            "git",
            "-C",
            str(main_repo),
            "worktree",
            "add",
            "-q",
            "-b",
            "feat",
            str(worktree_path),
        ],
        check=True,
    )
    subdir = worktree_path / "sub" / "nested"
    subdir.mkdir(parents=True)

    setup_project(cfg, "myapp", str(main_repo))

    assert ctx_detect_project_name(str(subdir)) == "myapp"


def test_ctx_detect_direct_repo_cwd_still_works(cfg: ProjConfig, tmp_path: Path) -> None:
    """Non-worktree cwd inside the tracked repo still matches (no regression)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    setup_project(cfg, "myapp", str(repo))

    assert ctx_detect_project_name(str(repo)) == "myapp"


def test_ctx_detect_untracked_git_repo_returns_none(cfg: ProjConfig, tmp_path: Path) -> None:
    """A git repo (or worktree of one) not registered in any project must return None."""
    untracked = tmp_path / "untracked"
    untracked.mkdir()
    _init_git_repo(untracked)

    # Project tracks a DIFFERENT repo
    other = tmp_path / "other"
    other.mkdir()
    _init_git_repo(other)
    setup_project(cfg, "myapp", str(other))

    assert ctx_detect_project_name(str(untracked)) is None


def test_ctx_detect_non_git_cwd_returns_none(cfg: ProjConfig, tmp_path: Path) -> None:
    """cwd with no git repo and no path match returns None (no subprocess crash)."""
    plain = tmp_path / "plain"
    plain.mkdir()

    other = tmp_path / "other"
    other.mkdir()
    _init_git_repo(other)
    setup_project(cfg, "myapp", str(other))

    assert ctx_detect_project_name(str(plain)) is None


@pytest.mark.parametrize("missing", ["", "/path/does/not/exist/xyz"])
def test_ctx_detect_missing_cwd_returns_none(cfg: ProjConfig, tmp_path: Path, missing: str) -> None:
    """Empty or nonexistent cwd must not crash; returns None."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    setup_project(cfg, "myapp", str(repo))

    assert ctx_detect_project_name(missing) is None

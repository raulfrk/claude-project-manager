"""Tests for tracking_git.write_json_exports and flush explicit-staging behaviour."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from server.lib import sql_todos
from server.lib import tracking_git as tg
from server.lib.models import ProjConfig, Todo
from tests.conftest import make_v3_project


@pytest.fixture()
def v3(tmp_path: Path) -> tuple[ProjConfig, str]:
    """v3 project with git_tracking.enabled=True."""
    from server.lib.models import GitTracking

    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        git_tracking=GitTracking(enabled=True),
    )
    return make_v3_project(tmp_path, cfg, name="demo")


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd).stdout.strip()


def test_write_json_exports_produces_sorted_stable_output(v3: tuple[ProjConfig, str]) -> None:
    """Two calls with same data must produce byte-identical output."""
    cfg, name = v3
    proj_dir = Path(cfg.tracking_dir) / name
    t = Todo(
        id="1",
        title="A",
        status="pending",
        priority="medium",
        created="2026-01-01",
        updated="2026-01-01",
    )
    sql_todos.save_todos(cfg, name, [t])

    tg.write_json_exports(cfg, name)
    content1 = (proj_dir / "todos.json").read_text()
    tg.write_json_exports(cfg, name)
    content2 = (proj_dir / "todos.json").read_text()
    assert content1 == content2


def test_write_json_exports_creates_three_files(v3: tuple[ProjConfig, str]) -> None:
    cfg, name = v3
    proj_dir = Path(cfg.tracking_dir) / name
    tg.write_json_exports(cfg, name)

    assert (proj_dir / "todos.json").exists()
    assert (proj_dir / "archive.json").exists()
    assert (proj_dir / "decisions.json").exists()

    # Each file should be valid JSON
    for fname in ("todos.json", "archive.json", "decisions.json"):
        data = json.loads((proj_dir / fname).read_text())
        assert isinstance(data, list)


def test_write_json_exports_noop_when_git_tracking_disabled(
    tmp_path: Path, cfg: ProjConfig
) -> None:
    """write_json_exports is a no-op when git_tracking.enabled is False."""
    from server.lib.models import GitTracking

    cfg_disabled = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        git_tracking=GitTracking(enabled=False),
    )
    _, name = make_v3_project(tmp_path, cfg_disabled, name="demo2")
    proj_dir = Path(cfg_disabled.tracking_dir) / name

    # Should NOT raise, should not create files
    tg.write_json_exports(cfg_disabled, name)
    assert not (proj_dir / "todos.json").exists()


def test_tracking_git_flush_stages_only_allowed_paths(
    v3: tuple[ProjConfig, str], tmp_path: Path
) -> None:
    """tracking_commit stages exactly the allowed file paths, not arbitrary files."""
    cfg, name = v3
    proj_dir = Path(cfg.tracking_dir) / name

    # Init a git repo
    subprocess.run(["git", "init"], cwd=proj_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=proj_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=proj_dir, capture_output=True)

    # Write some files — allowed + one extra
    tg.write_json_exports(cfg, name)
    (proj_dir / "extra.yaml").write_text("should-not-be-staged\n")

    tg.tracking_commit(proj_dir, "test commit")

    staged = _git("show", "--stat", "--name-only", "HEAD", cwd=proj_dir)
    assert "todos.json" in staged or "archive.json" in staged or "decisions.json" in staged
    assert "extra.yaml" not in staged


def test_tracking_git_flush_does_not_stage_legacy_yaml_files(
    v3: tuple[ProjConfig, str],
) -> None:
    """Legacy todos.yaml / archive.yaml / decisions.yaml must never be staged."""
    cfg, name = v3
    proj_dir = Path(cfg.tracking_dir) / name

    subprocess.run(["git", "init"], cwd=proj_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=proj_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=proj_dir, capture_output=True)

    # Plant legacy YAML files on disk
    for fname in ("todos.yaml", "archive.yaml", "decisions.yaml"):
        (proj_dir / fname).write_text("[]\n")

    tg.write_json_exports(cfg, name)
    tg.tracking_commit(proj_dir, "flush commit")

    # Check staged: legacy yamls should not be tracked
    result = subprocess.run(
        ["git", "show", "--stat", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        cwd=proj_dir,
    )
    for legacy in ("todos.yaml", "archive.yaml", "decisions.yaml"):
        assert legacy not in result.stdout


def test_tracking_git_flush_gitignores_wal_files(
    v3: tuple[ProjConfig, str],
) -> None:
    """ensure_git_repo must write .gitignore entries for WAL side-car files."""
    cfg, _name = v3
    tracking_path = Path(cfg.tracking_dir)

    # Init repo + ensure gitignore updated
    tg.ensure_git_repo(tracking_path)

    gitignore = tracking_path / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert "data.db-wal" in content
    assert "data.db-shm" in content

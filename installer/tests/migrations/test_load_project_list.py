# installer/tests/migrations/test_load_project_list.py
"""Tests for load_project_list() — reads active-projects.yaml registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.cli import load_project_list


def _write_global_config(home: Path, tracking_dir: str) -> None:
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "proj.yaml").write_text(
        yaml.safe_dump({"tracking_dir": tracking_dir})
    )


def _write_registry(tracking_dir: Path, projects: dict) -> None:
    tracking_dir.mkdir(parents=True, exist_ok=True)
    (tracking_dir / "active-projects.yaml").write_text(
        yaml.safe_dump({"projects": projects})
    )


def test_load_returns_projects_from_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    tracking = home / "projects" / "tracking"
    _write_global_config(home, str(tracking))
    _write_registry(
        tracking,
        {
            "cpm": {"tracking_dir": str(tracking / "cpm"), "archived": False},
            "side": {"tracking_dir": str(tracking / "side"), "archived": False},
        },
    )
    monkeypatch.setattr(Path, "home", lambda: home)

    result = load_project_list()
    names = {p["name"] for p in result}
    assert names == {"cpm", "side"}
    paths = {p["path"] for p in result}
    assert str(tracking / "cpm") in paths
    assert str(tracking / "side") in paths


def test_load_skips_archived_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    tracking = home / "projects" / "tracking"
    _write_global_config(home, str(tracking))
    _write_registry(
        tracking,
        {
            "active": {"tracking_dir": str(tracking / "active"), "archived": False},
            "old": {"tracking_dir": str(tracking / "old"), "archived": True},
        },
    )
    monkeypatch.setattr(Path, "home", lambda: home)

    result = load_project_list()
    assert len(result) == 1
    assert result[0]["name"] == "active"


def test_load_returns_empty_when_global_config_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    # No ~/.claude/proj.yaml
    monkeypatch.setattr(Path, "home", lambda: home)

    result = load_project_list()
    assert result == []


def test_load_returns_empty_when_registry_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    tracking = home / "projects" / "tracking"
    _write_global_config(home, str(tracking))
    # tracking_dir exists but no active-projects.yaml
    tracking.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)

    result = load_project_list()
    assert result == []


def test_load_uses_default_tracking_dir_when_not_in_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    # proj.yaml exists but has no tracking_dir key
    (claude_dir / "proj.yaml").write_text("{}\n")
    # Default tracking_dir = ~/projects/tracking
    tracking = home / "projects" / "tracking"
    _write_registry(
        tracking,
        {"demo": {"archived": False}},
    )
    # Patch both Path.home() and HOME env var so expanduser("~") resolves correctly
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))

    result = load_project_list()
    assert len(result) == 1
    assert result[0]["name"] == "demo"
    # path should fall back to tracking_dir/name
    assert result[0]["path"] == str(tracking / "demo")

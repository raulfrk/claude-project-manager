"""Unit tests for sql_meta CRUD module."""

from __future__ import annotations

from datetime import date

import pytest

from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
)
from server.lib.sql_meta import load_index, load_meta, save_index, save_meta


def make_meta(name: str = "myproject") -> ProjectMeta:
    today = date.today().isoformat()
    return ProjectMeta(
        name=name,
        description="A test project",
        status="active",
        priority="high",
        repos=[RepoEntry(label="code", path="/home/user/myrepo")],
        dates=ProjectDates(created=today, last_updated=today),
        tags=["test", "sql"],
    )


class TestLoadMeta:
    def test_raises_when_project_not_in_db(self, cfg: ProjConfig) -> None:
        with pytest.raises(FileNotFoundError):
            load_meta(cfg, "nonexistent")

    def test_roundtrip(self, cfg: ProjConfig) -> None:
        meta = make_meta("myproject")
        save_meta(cfg, meta)
        loaded = load_meta(cfg, "myproject")
        assert loaded.name == "myproject"
        assert loaded.description == "A test project"
        assert loaded.status == "active"
        assert loaded.priority == "high"
        assert len(loaded.repos) == 1
        assert loaded.repos[0].label == "code"
        assert loaded.repos[0].path == "/home/user/myrepo"
        assert loaded.tags == ["test", "sql"]

    def test_repos_preserved(self, cfg: ProjConfig) -> None:
        meta = make_meta()
        meta.repos = [
            RepoEntry(label="code", path="/repo/main"),
            RepoEntry(label="docs", path="/repo/docs", claudemd=True),
        ]
        save_meta(cfg, meta)
        loaded = load_meta(cfg, "myproject")
        assert len(loaded.repos) == 2
        assert loaded.repos[0].label == "code"
        assert loaded.repos[1].label == "docs"
        assert loaded.repos[1].claudemd is True


class TestSaveMeta:
    def test_auto_bumps_last_updated(self, cfg: ProjConfig) -> None:
        meta = make_meta()
        meta.dates.last_updated = "2020-01-01"
        save_meta(cfg, meta)
        loaded = load_meta(cfg, "myproject")
        assert loaded.dates.last_updated == date.today().isoformat()

    def test_overwrites_existing(self, cfg: ProjConfig) -> None:
        meta = make_meta()
        save_meta(cfg, meta)
        meta.description = "Updated description"
        save_meta(cfg, meta)
        loaded = load_meta(cfg, "myproject")
        assert loaded.description == "Updated description"

    def test_sync_configs_preserved(self, cfg: ProjConfig) -> None:
        from server.lib.models import ProjectTodoistConfig

        meta = make_meta()
        meta.todoist_project_id = "todoist_proj_123"
        meta.trello_card_id = "trello_card_xyz"
        meta.todoist = ProjectTodoistConfig(root_only=True)
        save_meta(cfg, meta)
        loaded = load_meta(cfg, "myproject")
        assert loaded.todoist_project_id == "todoist_proj_123"
        assert loaded.trello_card_id == "trello_card_xyz"
        assert loaded.todoist.root_only is True


class TestLoadIndex:
    def test_empty_index(self, cfg: ProjConfig) -> None:
        index = load_index(cfg)
        assert index.projects == {}
        assert index.version == 1

    def test_roundtrip_multiple_projects(self, cfg: ProjConfig) -> None:
        today = date.today().isoformat()
        index = ProjectIndex(
            version=1,
            projects={
                "proj_a": ProjectEntry(name="proj_a", tracking_dir="/track/proj_a", created=today),
                "proj_b": ProjectEntry(
                    name="proj_b", tracking_dir="/track/proj_b", created=today, archived=True
                ),
            },
        )
        save_index(cfg, index)
        loaded = load_index(cfg)
        assert set(loaded.projects.keys()) == {"proj_a", "proj_b"}
        assert loaded.projects["proj_a"].tracking_dir == "/track/proj_a"
        assert loaded.projects["proj_b"].archived is True

    def test_entry_fields_preserved(self, cfg: ProjConfig) -> None:
        today = date.today().isoformat()
        entry = ProjectEntry(
            name="myapp",
            tracking_dir="/track/myapp",
            created=today,
            tags=["important", "web"],
            purgeable=False,
        )
        index = ProjectIndex(version=1, projects={"myapp": entry})
        save_index(cfg, index)
        loaded = load_index(cfg)
        e = loaded.projects["myapp"]
        assert e.name == "myapp"
        assert e.tags == ["important", "web"]
        assert e.purgeable is False


class TestSaveIndex:
    def test_replaces_existing_entries(self, cfg: ProjConfig) -> None:
        today = date.today().isoformat()
        index1 = ProjectIndex(
            version=1,
            projects={
                "old_proj": ProjectEntry(name="old_proj", tracking_dir="/t/old", created=today)
            },
        )
        save_index(cfg, index1)
        index2 = ProjectIndex(
            version=1,
            projects={
                "new_proj": ProjectEntry(name="new_proj", tracking_dir="/t/new", created=today)
            },
        )
        save_index(cfg, index2)
        loaded = load_index(cfg)
        assert "old_proj" not in loaded.projects
        assert "new_proj" in loaded.projects

    def test_empty_index_clears_all(self, cfg: ProjConfig) -> None:
        today = date.today().isoformat()
        index = ProjectIndex(
            version=1,
            projects={"proj": ProjectEntry(name="proj", tracking_dir="/t/proj", created=today)},
        )
        save_index(cfg, index)
        save_index(cfg, ProjectIndex(version=1, projects={}))
        loaded = load_index(cfg)
        assert loaded.projects == {}

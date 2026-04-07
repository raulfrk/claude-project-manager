"""Tests for proj_list_full MCP tool."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
)
from tests.conftest import call_tool


def _setup_project(
    cfg: ProjConfig,
    name: str,
    tmp_path: Path,
    *,
    archived: bool = False,
    todoist_project_id: str | None = None,
    trello_card_id: str | None = None,
    jira_issue_key: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
) -> None:
    """Helper to create a project with optional integrations."""
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")

    meta = ProjectMeta(
        name=name,
        description=description,
        repos=[RepoEntry(label="code", path=str(tmp_path / name))],
        dates=ProjectDates(created=today, last_updated=today),
        tags=tags or [],
        todoist_project_id=todoist_project_id,
        trello_card_id=trello_card_id,
        jira_issue_key=jira_issue_key,
    )
    storage.save_meta(cfg, meta)

    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(
        name=name,
        tracking_dir=str(proj_dir),
        created=today,
        archived=archived,
        archive_date=today if archived else None,
    )
    storage.save_index(cfg, index)


@pytest.fixture()
def base_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    """Provide a clean ProjConfig with isolated tracking dir."""
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(cfg)
    return cfg


@pytest.fixture()
def app_factory():
    """Return a factory to create a fresh MCP app."""

    def _make():
        from mcp.server.fastmcp import FastMCP

        from server.tools import config, projects, todos

        app = FastMCP("test-proj")
        config.register(app)
        projects.register(app)
        todos.register(app)
        return app

    return _make


@pytest.mark.asyncio
async def test_returns_all_active_projects(base_cfg, tmp_path, app_factory):
    """Returns all active projects with full metadata."""
    _setup_project(base_cfg, "alpha", tmp_path, description="First project", tags=["web"])
    _setup_project(base_cfg, "beta", tmp_path, description="Second project", tags=["api"])

    app = app_factory()
    result = await call_tool(app, "proj_list_full")
    data = json.loads(result)

    assert data["count"] == 2
    assert len(data["projects"]) == 2
    names = [p["name"] for p in data["projects"]]
    assert "alpha" in names
    assert "beta" in names

    alpha = next(p for p in data["projects"] if p["name"] == "alpha")
    assert alpha["description"] == "First project"
    assert alpha["tags"] == ["web"]
    assert alpha["status"] == "active"
    assert "repos" in alpha
    assert "dates" in alpha
    assert alpha["archived"] is False


@pytest.mark.asyncio
async def test_include_archived_true(base_cfg, tmp_path, app_factory):
    """include_archived=True includes archived projects in results."""
    _setup_project(base_cfg, "active-proj", tmp_path)
    _setup_project(base_cfg, "old-proj", tmp_path, archived=True)

    app = app_factory()

    # Default: exclude archived
    result_default = await call_tool(app, "proj_list_full")
    data_default = json.loads(result_default)
    assert data_default["count"] == 1
    assert data_default["projects"][0]["name"] == "active-proj"

    # include_archived=True
    result_all = await call_tool(app, "proj_list_full", include_archived=True)
    data_all = json.loads(result_all)
    assert data_all["count"] == 2
    names = [p["name"] for p in data_all["projects"]]
    assert "active-proj" in names
    assert "old-proj" in names


@pytest.mark.asyncio
async def test_integration_filter_todoist(base_cfg, tmp_path, app_factory):
    """integration_filter='todoist' filters to only projects with todoist_project_id."""
    _setup_project(base_cfg, "with-todoist", tmp_path, todoist_project_id="123456")
    _setup_project(base_cfg, "with-trello", tmp_path, trello_card_id="abc")
    _setup_project(base_cfg, "no-integrations", tmp_path)

    app = app_factory()
    result = await call_tool(app, "proj_list_full", integration_filter="todoist")
    data = json.loads(result)

    assert data["count"] == 1
    assert data["projects"][0]["name"] == "with-todoist"
    assert data["projects"][0]["integrations"]["todoist"] == "123456"


@pytest.mark.asyncio
async def test_missing_meta_skipped_with_warning(base_cfg, tmp_path, app_factory):
    """Missing meta.yaml is skipped with a warning in the response."""
    _setup_project(base_cfg, "good-proj", tmp_path)

    # Create an index entry without a meta.yaml on disk
    today = str(date.today())
    index = storage.load_index(base_cfg)
    index.projects["ghost-proj"] = ProjectEntry(
        name="ghost-proj",
        tracking_dir=str(Path(base_cfg.tracking_dir) / "ghost-proj"),
        created=today,
    )
    storage.save_index(base_cfg, index)
    # Do NOT create meta.yaml for ghost-proj

    app = app_factory()
    result = await call_tool(app, "proj_list_full")
    data = json.loads(result)

    assert data["count"] == 1
    assert data["projects"][0]["name"] == "good-proj"
    assert len(data["warnings"]) == 1
    assert "ghost-proj" in data["warnings"][0]
    assert "meta.yaml" in data["warnings"][0].lower() or "missing" in data["warnings"][0].lower()


@pytest.mark.asyncio
async def test_unknown_integration_filter_returns_error(base_cfg, tmp_path, app_factory):
    """Unknown integration_filter returns a JSON error."""
    _setup_project(base_cfg, "proj1", tmp_path)

    app = app_factory()
    result = await call_tool(app, "proj_list_full", integration_filter="github")
    data = json.loads(result)

    assert "error" in data
    assert "github" in data["error"].lower()
    assert "todoist" in data["error"].lower() or "valid" in data["error"].lower()

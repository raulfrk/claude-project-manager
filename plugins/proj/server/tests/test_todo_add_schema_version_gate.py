"""Tests for schema_version-gated flat-only enforcement in todo_add."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from server.lib import state
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    """Set up a project and activate it in session state."""
    setup_project(cfg, "demo", str(tmp_path))
    state.set_session_active("demo")
    return cfg, "demo"


@pytest.fixture()
def app(project: tuple[ProjConfig, str]):
    """Return a configured FastMCP app with config + todos registered."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects, todos

    a = FastMCP("test-gate")
    config.register(a)
    projects.register(a)
    todos.register(a)
    return a


def _set_schema_version(cfg: ProjConfig, project_name: str, v: int) -> None:
    path = Path(cfg.tracking_dir) / project_name / "proj.yaml"
    data = yaml.safe_load(path.read_text()) or {} if path.exists() else {"name": project_name}
    data["schema_version"] = v
    path.write_text(yaml.safe_dump(data))


# ── Legacy mode (schema_version=1): everything allowed ────────────────────────


@pytest.mark.asyncio
async def test_legacy_mode_allows_single_child_with_parent(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 1)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(app, "todo_add", title="child", parent=parent_id, project_name=name)
    )
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_legacy_mode_allows_batch_children(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 1)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="",
            parent=parent_id,
            children=json.dumps([{"title": "a"}, {"title": "b"}]),
            project_name=name,
        )
    )
    assert result.get("error") is None


# ── Flat mode (schema_version=2): nested args rejected ────────────────────────


@pytest.mark.asyncio
async def test_flat_mode_rejects_single_child_with_parent(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(app, "todo_add", title="child", parent=parent_id, project_name=name)
    )
    assert "error" in result
    assert "nested mode disabled" in result["error"]
    assert "schema_version" in result["error"]
    assert "group:" in result["error"]


@pytest.mark.asyncio
async def test_flat_mode_allows_single_flat_child_via_tag(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="child",
            tags=[f"group:{parent_id}"],
            project_name=name,
        )
    )
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_flat_mode_allows_batch_via_children_only_mode(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="",
            parent=parent_id,
            children=json.dumps([{"title": "a"}, {"title": "b"}]),
            project_name=name,
        )
    )
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_flat_mode_rejects_title_plus_parent_plus_children(app, project):
    """Ambiguous — title non-empty + parent means create_root_too_then_nest."""
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="root_too",
            parent=parent_id,
            children=json.dumps([{"title": "a"}]),
            project_name=name,
        )
    )
    assert "error" in result
    assert "nested mode disabled" in result["error"]


@pytest.mark.asyncio
async def test_flat_mode_allows_top_level_with_no_parent(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    result = json.loads(await call_tool(app, "todo_add", title="lone", project_name=name))
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_gate_reads_schema_version_fresh_each_call(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 1)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]

    # Legacy mode — parent allowed.
    result_legacy = json.loads(
        await call_tool(app, "todo_add", title="a", parent=parent_id, project_name=name)
    )
    assert result_legacy.get("error") is None

    # Switch to flat mode — same call now rejected.
    _set_schema_version(cfg, name, 2)
    result_flat = json.loads(
        await call_tool(app, "todo_add", title="b", parent=parent_id, project_name=name)
    )
    assert "error" in result_flat


@pytest.mark.asyncio
async def test_flat_mode_batch_path_auto_tags_children(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="",
            parent=parent_id,
            children=json.dumps([{"title": "child_a"}, {"title": "child_b"}]),
            project_name=name,
        ),
    )
    assert result.get("error") is None
    created = result.get("created", [])
    assert len(created) == 2
    for child in created:
        assert f"group:{parent_id}" in child.get("tags", [])
        assert child.get("parent") is None


@pytest.mark.asyncio
async def test_flat_mode_batch_path_dedups_existing_group_tag(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="",
            parent=parent_id,
            children=json.dumps(
                [
                    {"title": "c", "tags": [f"group:{parent_id}", "keep"]},
                ]
            ),
            project_name=name,
        ),
    )
    assert result.get("error") is None
    created = result["created"]
    tags = created[0]["tags"]
    assert tags.count(f"group:{parent_id}") == 1
    assert "keep" in tags


@pytest.mark.asyncio
async def test_legacy_mode_batch_path_sets_parent_field(app, project):
    cfg, name = project
    _set_schema_version(cfg, name, 1)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="",
            parent=parent_id,
            children=json.dumps([{"title": "c"}]),
            project_name=name,
        ),
    )
    assert result.get("error") is None
    created = result["created"]
    assert created[0]["parent"] == parent_id
    # No auto-tag in legacy mode
    assert f"group:{parent_id}" not in created[0].get("tags", [])


@pytest.mark.asyncio
async def test_flat_mode_nested_specs_tag_immediate_parent(app, project):
    """Nested children in a flat batch get their immediate parent's group tag,
    not the batch root's. Preserves tree structure via tag references."""
    cfg, name = project
    _set_schema_version(cfg, name, 2)
    r_parent = json.loads(await call_tool(app, "todo_add", title="parent", project_name=name))
    parent_id = r_parent["todo_id"]
    result = json.loads(
        await call_tool(
            app,
            "todo_add",
            title="",
            parent=parent_id,
            children=json.dumps(
                [
                    {
                        "title": "mid",
                        "children": [{"title": "leaf"}],
                    },
                ]
            ),
            project_name=name,
        ),
    )
    assert result.get("error") is None
    created = result["created"]
    assert len(created) == 2
    mid = next(c for c in created if c["title"] == "mid")
    leaf = next(c for c in created if c["title"] == "leaf")
    # mid is under the batch root
    assert f"group:{parent_id}" in mid["tags"]
    # leaf is under mid (NOT under batch root)
    assert f"group:{mid['id']}" in leaf["tags"]
    assert f"group:{parent_id}" not in leaf["tags"]

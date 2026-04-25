"""MCP tool tests via FastMCP call_tool interface."""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig, Todo
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path))
    state.set_session_active("myapp")
    return cfg, "myapp"


@pytest.mark.asyncio
class TestConfigMCPTools:
    async def test_config_load_returns_info(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_load")
        assert "tracking_dir" in result
        assert "projects_base_dir" in result

    async def test_config_init(
        self, mcp_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        new_cfg_path = tmp_path / "new_proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", new_cfg_path)
        result = await call_tool(mcp_app, "config_init", tracking_dir=str(tmp_path / "tracking2"))
        assert "saved" in result.lower()

    async def test_config_update(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_update", default_priority="high")
        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.default_priority == "high"

    async def test_config_update_projects_base_dir(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_update", projects_base_dir="~/projects")
        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.projects_base_dir == "~/projects"

    async def test_config_update_invalid_priority(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_update", default_priority="urgent")
        assert "Invalid default_priority" in result
        loaded = storage.load_config()
        assert loaded.default_priority == cfg.default_priority

    async def test_config_update_valid_priorities(self, mcp_app: Any, cfg: ProjConfig) -> None:
        for priority in ("low", "medium", "high"):
            result = await call_tool(mcp_app, "config_update", default_priority=priority)
            assert "updated" in result.lower()

    async def test_config_update_empty_tracking_dir(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_update", tracking_dir="")
        assert "Invalid tracking_dir" in result
        loaded = storage.load_config()
        assert loaded.tracking_dir == cfg.tracking_dir

    async def test_config_update_null_byte_in_path(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "config_update", tracking_dir="/tmp/foo\x00bar")
        assert "Invalid tracking_dir" in result

    async def test_config_update_empty_projects_base_dir(
        self, mcp_app: Any, cfg: ProjConfig
    ) -> None:
        result = await call_tool(mcp_app, "config_update", projects_base_dir="")
        assert "Invalid projects_base_dir" in result


@pytest.mark.asyncio
class TestProjectsMCPTools:
    async def test_proj_init(self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path) -> None:
        result = await call_tool(mcp_app, "proj_init", name="newapp", path=str(tmp_path))
        data = _json.loads(result)
        assert data.get("project_name") == "newapp"
        index = storage.load_index(cfg)
        assert "newapp" in index.projects

    async def test_proj_init_uses_projects_base_dir(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        cfg.projects_base_dir = str(tmp_path / "projects")
        storage.save_config(cfg)
        result = await call_tool(mcp_app, "proj_init", name="newapp")
        data = _json.loads(result)
        assert data.get("project_name") == "newapp"
        meta = storage.load_meta(cfg, "newapp")
        assert meta.repos[0].path == str((tmp_path / "projects" / "newapp").resolve())

    async def test_proj_init_no_path_no_base_dir_returns_error(
        self, mcp_app: Any, cfg: ProjConfig
    ) -> None:
        result = await call_tool(mcp_app, "proj_init", name="newapp")
        data = _json.loads(result)
        assert "No path provided" in data.get("error", "") or "projects_base_dir" in data.get(
            "error", ""
        )

    async def test_proj_list(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "proj_list")
        # proj_list returns plain string, not JSON
        assert "myapp" in result

    async def test_proj_get_active(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "proj_get_active")
        data = _json.loads(result)
        assert data.get("name") == "myapp"

    async def test_proj_archive(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "proj_archive")
        data = _json.loads(result)
        assert "Archived" in data.get("result", "") or data.get("project_name") == "myapp"
        index = storage.load_index(project[0])
        assert index.projects["myapp"].archived

    async def test_proj_update_meta(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "proj_update_meta", status="blocked")
        data = _json.loads(result)
        assert "Updated" in data.get("result", "")
        meta = storage.load_meta(project[0], "myapp")
        assert meta.status == "blocked"

    async def test_proj_add_repo(
        self, mcp_app: Any, project: tuple[ProjConfig, str], tmp_path: Path
    ) -> None:
        new_repo = str(tmp_path / "new_repo")
        Path(new_repo).mkdir()
        result = await call_tool(mcp_app, "proj_add_repo", repo_path=new_repo, label="docs")
        data = _json.loads(result)
        assert "docs" in data.get("result", "") or "docs" in str(data.get("paths", []))

    async def test_proj_remove_repo(
        self, mcp_app: Any, project: tuple[ProjConfig, str], tmp_path: Path
    ) -> None:
        # Add a second repo so we can remove one
        new_repo = str(tmp_path / "extra_repo")
        Path(new_repo).mkdir()
        await call_tool(mcp_app, "proj_add_repo", repo_path=new_repo, label="docs")
        result = await call_tool(mcp_app, "proj_remove_repo", label="docs")
        data = _json.loads(result)
        assert "Removed" in data.get("result", "")
        assert "docs" in data.get("result", "")
        meta = storage.load_meta(project[0], "myapp")
        assert len(meta.repos) == 1
        assert meta.repos[0].label == "code"

    async def test_proj_remove_repo_last_repo_guard(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "proj_remove_repo", label="code")
        data = _json.loads(result)
        assert "Cannot remove the last repo" in data.get("error", "")
        meta = storage.load_meta(project[0], "myapp")
        assert len(meta.repos) == 1

    async def test_proj_remove_repo_label_not_found(
        self, mcp_app: Any, project: tuple[ProjConfig, str], tmp_path: Path
    ) -> None:
        # Add a second repo so we pass the last-repo guard
        new_repo = str(tmp_path / "extra_repo")
        Path(new_repo).mkdir()
        await call_tool(mcp_app, "proj_add_repo", repo_path=new_repo, label="docs")
        result = await call_tool(mcp_app, "proj_remove_repo", label="nonexistent")
        data = _json.loads(result)
        assert "No repo with label" in data.get("error", "")
        assert "nonexistent" in data.get("error", "")


@pytest.mark.asyncio
class TestMultiDirInit:
    """Tests for multi-directory init (dirs parameter) and label uniqueness."""

    async def test_proj_init_with_dirs(self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path) -> None:
        dirs = [
            {"path": str(tmp_path / "src"), "label": "code"},
            {"path": str(tmp_path / "docs"), "label": "docs"},
        ]
        result = await call_tool(mcp_app, "proj_init", name="multidir", dirs=dirs)
        data = _json.loads(result)
        assert data.get("project_name") == "multidir"
        meta = storage.load_meta(cfg, "multidir")
        assert len(meta.repos) == 2
        assert meta.repos[0].label == "code"
        assert meta.repos[1].label == "docs"

    async def test_proj_init_dirs_and_path_rejects(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        dirs = [{"path": str(tmp_path / "src"), "label": "code"}]
        result = await call_tool(mcp_app, "proj_init", name="bad", path=str(tmp_path), dirs=dirs)
        data = _json.loads(result)
        assert (
            "either" in data.get("error", "").lower() or "not both" in data.get("error", "").lower()
        )

    async def test_proj_init_dirs_duplicate_label_rejects(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        dirs = [
            {"path": str(tmp_path / "a"), "label": "code"},
            {"path": str(tmp_path / "b"), "label": "code"},
        ]
        result = await call_tool(mcp_app, "proj_init", name="dup", dirs=dirs)
        data = _json.loads(result)
        assert "Duplicate label" in data.get("error", "")

    async def test_proj_init_dirs_missing_path_rejects(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        dirs = [{"path": "", "label": "code"}]
        result = await call_tool(mcp_app, "proj_init", name="nopath", dirs=dirs)
        data = _json.loads(result)
        assert "path" in data.get("error", "").lower()

    async def test_proj_init_dirs_missing_label_rejects(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        dirs = [{"path": str(tmp_path), "label": ""}]
        result = await call_tool(mcp_app, "proj_init", name="nolabel", dirs=dirs)
        data = _json.loads(result)
        assert "label" in data.get("error", "").lower()

    async def test_proj_init_legacy_path_still_works(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        result = await call_tool(mcp_app, "proj_init", name="legacy", path=str(tmp_path))
        data = _json.loads(result)
        assert data.get("project_name") == "legacy"
        meta = storage.load_meta(cfg, "legacy")
        assert len(meta.repos) == 1
        assert meta.repos[0].label == "code"

    async def test_proj_add_repo_label_uniqueness(
        self, mcp_app: Any, project: tuple[ProjConfig, str], tmp_path: Path
    ) -> None:
        """Attempting to add a repo with the same label as an existing one should fail."""
        new_repo = str(tmp_path / "new_repo")
        Path(new_repo).mkdir()
        result = await call_tool(mcp_app, "proj_add_repo", repo_path=new_repo, label="code")
        data = _json.loads(result)
        assert "already in use" in data.get("error", "")


@pytest.mark.asyncio
class TestTodosMCPTools:
    async def test_todo_add(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "todo_add", title="My first task")
        data = _json.loads(result)
        assert data.get("todo_id") == "1"

    async def test_todo_list(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Task 1")
        await call_tool(mcp_app, "todo_add", title="Task 2")
        result = await call_tool(mcp_app, "todo_list")
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Task 1" in titles
        assert "Task 2" in titles

    async def test_todo_complete(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Do it")
        result = await call_tool(mcp_app, "todo_complete", todo_id="1")
        data = _json.loads(result)
        assert data.get("todo_id") == "1"
        # Leaf todos are archived immediately — removed from active
        todos = storage.load_todos(project[0], "myapp")
        assert len(todos) == 0
        archived = storage.load_archived_todos(project[0], "myapp")
        assert archived[0].status == "done"

    async def test_todo_block(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Blocker")
        await call_tool(mcp_app, "todo_add", title="Blocked")
        result = await call_tool(mcp_app, "todo_update", todo_id="2", blocked_by_set=["1"])
        data = _json.loads(result)
        assert "Updated" in data.get("result", "")

    async def test_todo_ready(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Ready task")
        await call_tool(mcp_app, "todo_add", title="Blocked", blocked_by=["1"])
        result = await call_tool(mcp_app, "todo_ready")
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Ready task" in titles
        assert "Blocked" not in titles

    async def test_todo_add_with_parent(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Parent")
        result = await call_tool(mcp_app, "todo_add", parent="1", title="Child task")
        data = _json.loads(result)
        assert data.get("todo_id") == "1.1"
        todos = storage.load_todos(project[0], "myapp")
        child = next(t for t in todos if t.id == "1.1")
        # Flat model: parent-child via group tag, not parent field
        assert "group:1" in child.tags

    async def test_todo_add_with_parent_exposes_trello_checklist_id(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Parent")
        cfg, name = project
        todos = storage.load_todos(cfg, name)
        parent = next(t for t in todos if t.id == "1")
        parent.trello_checklist_id = "checklist-abc"
        storage.save_todos(cfg, name, todos)

        result = await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        data = _json.loads(result)
        assert data.get("parent_trello_checklist_id") == "checklist-abc"

    async def test_todo_add_with_explicit_parent(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Parent task")
        result = await call_tool(mcp_app, "todo_add", title="Child task", parent="1")
        data = _json.loads(result)
        assert data.get("todo_id") == "1.1"
        todos = storage.load_todos(project[0], "myapp")
        child = next(t for t in todos if t.id == "1.1")
        # Flat model: parent-child via group tag
        assert "group:1" in child.tags

    async def test_todo_add_with_invalid_parent_returns_error(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "todo_add", title="Orphan", parent="999")
        data = _json.loads(result)
        assert "not found" in data.get("error", "").lower()
        todos = storage.load_todos(project[0], "myapp")
        assert not todos

    async def test_todo_add_with_dot_notation_parent(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        result = await call_tool(mcp_app, "todo_add", title="Grandchild", parent="1.1")
        data = _json.loads(result)
        assert data.get("todo_id") == "1.1.1"
        todos = storage.load_todos(project[0], "myapp")
        grandchild = next(t for t in todos if t.id == "1.1.1")
        # Flat model: parent-child via group tag
        assert "group:1.1" in grandchild.tags

    async def test_todo_delete(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="To delete")
        result = await call_tool(mcp_app, "todo_delete", todo_id="1")
        data = _json.loads(result)
        assert "Deleted" in data.get("result", "")
        todos = storage.load_todos(project[0], "myapp")
        assert not todos

    async def test_todo_tree(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Root"
        assert len(data[0]["_children"]) == 1
        assert data[0]["_children"][0]["title"] == "Child"

    async def test_todo_tree_excludes_done_leaf_by_default(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Root"
        assert data[0]["_children"] == []

    async def test_todo_tree_includes_done_with_flag(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)
        assert len(data[0]["_children"]) == 1
        assert data[0]["_children"][0]["status"] == "done"

    async def test_todo_tree_keeps_done_parent_with_pending_child(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # Use todo_update to set parent status=done directly (bypasses archive logic)
        # to test tree filtering behaviour: done parent with pending child stays visible
        await call_tool(mcp_app, "todo_add", title="Parent")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        await call_tool(mcp_app, "todo_update", todo_id="1", status="done")
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        assert len(data) == 1
        assert data[0]["status"] == "done"
        assert len(data[0]["_children"]) == 1
        assert data[0]["_children"][0]["status"] == "pending"

    async def test_todo_tree_complex_hierarchy(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # Flat model: build hierarchy via group: tags; completing a todo archives it immediately
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child-A")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child-B")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child-C")
        await call_tool(mcp_app, "todo_add", parent="1.2", title="Grandchild-B1")
        # Complete Child-A (archives immediately)
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        root = data[0]
        # Child-A (1.1) archived — only Child-B and Child-C remain under root
        assert len(root["_children"]) == 2
        child_titles = {c["title"] for c in root["_children"]}
        assert child_titles == {"Child-B", "Child-C"}
        child_b = next(c for c in root["_children"] if c["title"] == "Child-B")
        assert len(child_b["_children"]) == 1
        assert child_b["_children"][0]["title"] == "Grandchild-B1"

    async def test_todo_tree_all_done_returns_empty(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        assert data == []

    async def test_todo_set_content_flag(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Research me")
        result = await call_tool(mcp_app, "todo_set_content_flag", todo_id="1", has_research=True)
        data = _json.loads(result)
        assert data.get("todo_id") == "1"
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].has_research

    async def test_todo_list_limit(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Task A")
        await call_tool(mcp_app, "todo_add", title="Task B")
        await call_tool(mcp_app, "todo_add", title="Task C")
        result = await call_tool(mcp_app, "todo_list", limit=2)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Task A" in titles
        assert "Task B" in titles
        assert "Task C" not in titles

    async def test_todo_list_offset(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Task A")
        await call_tool(mcp_app, "todo_add", title="Task B")
        await call_tool(mcp_app, "todo_add", title="Task C")
        result = await call_tool(mcp_app, "todo_list", offset=1)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Task A" not in titles
        assert "Task B" in titles
        assert "Task C" in titles

    async def test_todo_list_limit_and_offset(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task A")
        await call_tool(mcp_app, "todo_add", title="Task B")
        await call_tool(mcp_app, "todo_add", title="Task C")
        result = await call_tool(mcp_app, "todo_list", limit=1, offset=1)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Task A" not in titles
        assert "Task B" in titles
        assert "Task C" not in titles

    async def test_todo_list_limit_zero_returns_all(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task A")
        await call_tool(mcp_app, "todo_add", title="Task B")
        await call_tool(mcp_app, "todo_add", title="Task C")
        result = await call_tool(mcp_app, "todo_list", limit=0)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Task A" in titles
        assert "Task B" in titles
        assert "Task C" in titles

    async def test_todo_list_default_excludes_done(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Default status='active' omits done todos remaining in todos.yaml."""
        await call_tool(mcp_app, "todo_add", title="Pending")
        await call_tool(mcp_app, "todo_add", title="In Progress")
        await call_tool(mcp_app, "todo_add", title="Done")
        await call_tool(mcp_app, "todo_update", todo_id="2", status="in_progress")
        await call_tool(mcp_app, "todo_update", todo_id="3", status="done")
        result = await call_tool(mcp_app, "todo_list")
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Pending" in titles
        assert "In Progress" in titles
        assert "Done" not in titles

    async def test_todo_list_active_sentinel_same_as_default(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Explicit status='active' returns same result as default."""
        await call_tool(mcp_app, "todo_add", title="Pending")
        await call_tool(mcp_app, "todo_add", title="Done")
        await call_tool(mcp_app, "todo_update", todo_id="2", status="done")
        result_default = await call_tool(mcp_app, "todo_list")
        result_active = await call_tool(mcp_app, "todo_list", status="active")
        assert result_default == result_active

    async def test_todo_list_status_none_returns_all(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Explicit status=None opts out of the active filter and returns all."""
        await call_tool(mcp_app, "todo_add", title="Pending")
        await call_tool(mcp_app, "todo_add", title="Done")
        await call_tool(mcp_app, "todo_update", todo_id="2", status="done")
        result = await call_tool(mcp_app, "todo_list", status=None)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Pending" in titles
        assert "Done" in titles

    async def test_todo_list_status_open_returns_all_non_terminal(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """status='open' returns pending, in_progress, blocked but not done."""
        await call_tool(mcp_app, "todo_add", title="Pending")
        await call_tool(mcp_app, "todo_add", title="InProgress")
        await call_tool(mcp_app, "todo_update", todo_id="2", status="in_progress")
        await call_tool(mcp_app, "todo_add", title="Blocked")
        await call_tool(mcp_app, "todo_update", todo_id="3", status="blocked")
        await call_tool(mcp_app, "todo_add", title="Done")
        await call_tool(mcp_app, "todo_update", todo_id="4", status="done")
        result = await call_tool(mcp_app, "todo_list", status="open")
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Pending" in titles
        assert "InProgress" in titles
        assert "Blocked" in titles
        assert "Done" not in titles

    async def test_todo_ready_limit(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Ready A")
        await call_tool(mcp_app, "todo_add", title="Ready B")
        await call_tool(mcp_app, "todo_add", title="Ready C")
        result = await call_tool(mcp_app, "todo_ready", limit=2)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Ready A" in titles
        assert "Ready B" in titles
        assert "Ready C" not in titles

    async def test_todo_ready_offset(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Ready A")
        await call_tool(mcp_app, "todo_add", title="Ready B")
        await call_tool(mcp_app, "todo_add", title="Ready C")
        result = await call_tool(mcp_app, "todo_ready", offset=2)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Ready A" not in titles
        assert "Ready B" not in titles
        assert "Ready C" in titles

    async def test_todo_ready_limit_and_offset(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Ready A")
        await call_tool(mcp_app, "todo_add", title="Ready B")
        await call_tool(mcp_app, "todo_add", title="Ready C")
        result = await call_tool(mcp_app, "todo_ready", limit=1, offset=1)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Ready A" not in titles
        assert "Ready B" in titles
        assert "Ready C" not in titles

    async def test_todo_ready_limit_zero_returns_all(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Ready A")
        await call_tool(mcp_app, "todo_add", title="Ready B")
        result = await call_tool(mcp_app, "todo_ready", limit=0)
        todos = _json.loads(result)
        titles = [t.get("title") for t in todos]
        assert "Ready A" in titles
        assert "Ready B" in titles

    async def test_proj_identify_batches_simple(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # 1 → 2 → 3 (linear chain)
        await call_tool(mcp_app, "todo_add", title="A")
        await call_tool(mcp_app, "todo_add", title="B", blocked_by=["1"])
        await call_tool(mcp_app, "todo_add", title="C", blocked_by=["2"])
        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2", "3"])
        import json

        data = json.loads(result)
        assert data["batches"] == [["1"], ["2"], ["3"]]
        assert data["cycles"] == []
        assert data["missing"] == []

    async def test_proj_identify_batches_parallel(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # 1 and 2 independent, both block 3
        await call_tool(mcp_app, "todo_add", title="A")
        await call_tool(mcp_app, "todo_add", title="B")
        await call_tool(mcp_app, "todo_add", title="C", blocked_by=["1", "2"])
        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2", "3"])
        import json

        data = json.loads(result)
        assert set(data["batches"][0]) == {"1", "2"}
        assert data["batches"][1] == ["3"]

    async def test_proj_identify_batches_missing(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="A")
        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "999"])
        import json

        data = json.loads(result)
        assert "999" in data["missing"]
        assert data["batches"] == [["1"]]

    async def test_proj_identify_batches_cycle(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="A", blocked_by=["2"])
        await call_tool(mcp_app, "todo_add", title="B", blocked_by=["1"])
        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2"])
        import json

        data = json.loads(result)
        assert len(data["cycles"]) > 0


@pytest.mark.asyncio
class TestTodoUncomplete:
    async def test_uncomplete_done_todo(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        # Add a parent so completing child keeps it in active (not archived)
        await call_tool(mcp_app, "todo_add", title="Parent")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        # Now uncomplete it
        result = await call_tool(mcp_app, "todo_uncomplete", todo_id="1.1")
        data = _json.loads(result)
        assert data["id"] == "1.1"
        assert data["status"] == "pending"
        # Verify in storage
        todos = storage.load_todos(cfg, name)
        child = next(t for t in todos if t.id == "1.1")
        status = child.status.value if hasattr(child.status, "value") else child.status
        assert status == "pending"

    async def test_uncomplete_pending_todo_returns_error(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Pending task")
        result = await call_tool(mcp_app, "todo_uncomplete", todo_id="1")
        data = _json.loads(result)
        assert "error" in data
        assert "not completed" in data["error"]

    async def test_uncomplete_nonexistent_todo_returns_error(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "todo_uncomplete", todo_id="999")
        data = _json.loads(result)
        assert "error" in data
        assert "not found" in data["error"]


@pytest.mark.asyncio
class TestNotFoundResponses:
    async def test_todo_update_not_found(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "todo_update", todo_id="nonexistent-999")
        data = _json.loads(result)
        assert data["status"] == "not_found"
        assert data["todo_id"] == "nonexistent-999"

    async def test_proj_update_meta_not_found(self, mcp_app: Any, cfg: ProjConfig) -> None:
        state.set_session_active("nonexistent-project")
        result = await call_tool(
            mcp_app, "proj_update_meta", name="nonexistent-project", status="active"
        )
        data = _json.loads(result)
        assert data["status"] == "not_found"


@pytest.mark.asyncio
class TestContentMCPTools:
    async def test_set_and_get_requirements(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "content_set_requirements", todo_id="1", content="# Goals\nDo X")
        result = await call_tool(mcp_app, "content_get_requirements", todo_id="1")
        assert "Do X" in result

    async def test_set_and_get_research(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(
            mcp_app, "content_set_research", todo_id="1", content="# Research\nApproach: Y"
        )
        result = await call_tool(mcp_app, "content_get_research", todo_id="1")
        assert "Approach: Y" in result

    async def test_requirements_not_found(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "content_get_requirements", todo_id="T999")
        assert "No requirements" in result or "not found" in result.lower()

    async def test_get_requirements_under_limit_returns_full(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "content_set_requirements", todo_id="1", content="Short content")
        result = await call_tool(mcp_app, "content_get_requirements", todo_id="1", max_chars=4000)
        assert "Short content" in result
        assert "truncated" not in result

    async def test_get_requirements_over_limit_truncates(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "content_set_requirements", todo_id="1", content="A" * 100)
        result = await call_tool(mcp_app, "content_get_requirements", todo_id="1", max_chars=50)
        assert "A" * 50 in result
        assert "truncated" in result
        assert "50 chars omitted" in result
        assert "requirements.md" in result

    async def test_get_research_under_limit_returns_full(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "content_set_research", todo_id="1", content="Short research")
        result = await call_tool(mcp_app, "content_get_research", todo_id="1", max_chars=4000)
        assert "Short research" in result
        assert "truncated" not in result

    async def test_get_research_over_limit_truncates(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "content_set_research", todo_id="1", content="B" * 100)
        result = await call_tool(mcp_app, "content_get_research", todo_id="1", max_chars=50)
        assert "B" * 50 in result
        assert "truncated" in result
        assert "50 chars omitted" in result
        assert "research.md" in result

    async def test_get_requirements_max_chars_zero(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        content = "Some content"
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "content_set_requirements", todo_id="1", content=content)
        result = await call_tool(mcp_app, "content_get_requirements", todo_id="1", max_chars=0)
        assert "truncated" in result
        assert f"{len(content)} chars omitted" in result

    async def test_get_requirements_max_chars_very_large(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "content_set_requirements", todo_id="1", content="C" * 10)
        result = await call_tool(mcp_app, "content_get_requirements", todo_id="1", max_chars=999999)
        assert "CCCCCCCCCC" in result
        assert "truncated" not in result


@pytest.mark.asyncio
class TestContextMCPTools:
    async def test_ctx_session_start(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "ctx_session_start")
        assert "myapp" in result

    async def test_ctx_detect_project(
        self, mcp_app: Any, project: tuple[ProjConfig, str], tmp_path: Path
    ) -> None:
        result = await call_tool(mcp_app, "ctx_detect_project", cwd=str(tmp_path))
        assert "myapp" in result

    async def test_notes_append(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "notes_append", text="My important note")
        assert "appended" in result.lower()
        notes = storage.read_notes(project[0], "myapp")
        assert "My important note" in notes

    async def test_claudemd_write_read(
        self, mcp_app: Any, project: tuple[ProjConfig, str], tmp_path: Path
    ) -> None:
        cfg = project[0]
        cfg.claudemd_management = True
        storage.save_config(cfg)
        await call_tool(
            mcp_app, "claudemd_write", repo_path=str(tmp_path), content="# CLAUDE\nStatus: active"
        )
        result = await call_tool(mcp_app, "claudemd_read", repo_path=str(tmp_path))
        assert "Status: active" in result


@pytest.mark.asyncio
class TestTodoArchive:
    async def test_leaf_todo_archives_immediately(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Leaf task")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        active = storage.load_todos(project[0], "myapp")
        archived = storage.load_archived_todos(project[0], "myapp")
        assert len(active) == 0
        assert len(archived) == 1
        assert archived[0].id == "1"
        assert archived[0].status == "done"

    async def test_flat_child_archives_immediately_when_completed(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # Flat model: completing a child todo archives it immediately (no "wait for parent")
        await call_tool(mcp_app, "todo_add", title="Parent")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        result = await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        assert "archived" in result.lower()
        active = storage.load_todos(project[0], "myapp")
        archived = storage.load_archived_todos(project[0], "myapp")
        assert len(archived) == 1
        assert archived[0].id == "1.1"
        assert len(active) == 1  # parent still active

    async def test_flat_parent_archives_independently(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # Flat model: parent and children archive independently
        await call_tool(mcp_app, "todo_add", title="Parent")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child-A")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child-B")
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        result = await call_tool(mcp_app, "todo_complete", todo_id="1")
        assert "archived" in result.lower()
        active = storage.load_todos(project[0], "myapp")
        archived = storage.load_archived_todos(project[0], "myapp")
        # Only 1.1 + 1 archived; 1.2 still pending
        assert {t.id for t in archived} == {"1.1", "1"}
        assert any(t.id == "1.2" for t in active)

    async def test_flat_parent_can_complete_with_pending_children(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # Flat model: no constraint — parent completes independently
        await call_tool(mcp_app, "todo_add", title="Parent")
        await call_tool(mcp_app, "todo_add", parent="1", title="Pending-child")
        result = await call_tool(mcp_app, "todo_complete", todo_id="1")
        assert "archived" in result.lower()
        active = storage.load_todos(project[0], "myapp")
        archived = storage.load_archived_todos(project[0], "myapp")
        assert any(t.id == "1" for t in archived)
        assert any(t.id == "1.1" for t in active)  # child still active

    async def test_archive_cleans_blocking_refs(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Leaf")
        await call_tool(mcp_app, "todo_add", title="Blocked-by-leaf", blocked_by=["1"])
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        active = storage.load_todos(project[0], "myapp")
        remaining = next(t for t in active if t.id == "2")
        assert "1" not in remaining.blocked_by

    async def test_archive_preserves_all_fields(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(
            mcp_app, "todo_add", title="Tagged task", priority="high", tags=["important"]
        )
        await call_tool(mcp_app, "todo_update", todo_id="1", todoist_task_id="abc123")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        archived = storage.load_archived_todos(project[0], "myapp")
        t = archived[0]
        assert t.title == "Tagged task"
        assert t.priority == "high"
        assert "important" in t.tags
        assert t.todoist_task_id == "abc123"
        assert t.status == "done"

    async def test_deep_family_archives_together(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="L1")
        await call_tool(mcp_app, "todo_add", parent="1", title="L2")
        await call_tool(mcp_app, "todo_add", parent="1.1", title="L3")
        # Complete bottom-up: L3 (child), L2 (parent of L3, child of L1), L1 (root)
        await call_tool(mcp_app, "todo_complete", todo_id="1.1.1")
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        active = storage.load_todos(project[0], "myapp")
        archived = storage.load_archived_todos(project[0], "myapp")
        assert len(active) == 0
        assert {t.id for t in archived} == {"1", "1.1", "1.1.1"}

    async def test_archive_yaml_created_automatically(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        from server.lib.db import db_path, get_connection

        conn = get_connection(db_path(project[0], "myapp"))
        count = conn.execute(
            "SELECT COUNT(*) FROM archive_todos WHERE project=?", ("myapp",)
        ).fetchone()[0]
        conn.close()
        assert count >= 1

    async def test_multiple_archives_accumulate(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task A")
        await call_tool(mcp_app, "todo_add", title="Task B")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        await call_tool(mcp_app, "todo_complete", todo_id="2")
        archived = storage.load_archived_todos(project[0], "myapp")
        assert len(archived) == 2
        assert {t.title for t in archived} == {"Task A", "Task B"}


@pytest.mark.asyncio
class TestTodoGetArchive:
    async def test_todo_get_falls_back_to_archive(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Archived task")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        result = await call_tool(mcp_app, "todo_get", todo_id="1")
        data = _json.loads(result)
        assert data["id"] == "1"
        assert data["status"] == "done"
        assert data["title"] == "Archived task"

    async def test_todo_get_returns_not_found_for_missing(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "todo_get", todo_id="999")
        assert "not found" in result.lower()

    async def test_todo_get_prefers_active_over_archive(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Task A")
        await call_tool(mcp_app, "todo_add", title="Task B")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        # Task B is still active
        result = await call_tool(mcp_app, "todo_get", todo_id="2")
        data = _json.loads(result)
        assert data["id"] == "2"
        assert data["status"] == "pending"


@pytest.mark.asyncio
class TestTodoListAll:
    async def test_todo_list_all_merges_active_and_archived(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Active task")
        await call_tool(mcp_app, "todo_add", title="To archive")
        await call_tool(mcp_app, "todo_complete", todo_id="2")
        result = await call_tool(mcp_app, "todo_list_all")
        data = _json.loads(result)
        assert len(data) == 2
        titles = {t["title"] for t in data}
        assert titles == {"Active task", "To archive"}

    async def test_todo_list_excludes_archived(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Active")
        await call_tool(mcp_app, "todo_add", title="Archived")
        await call_tool(mcp_app, "todo_complete", todo_id="2")
        result = await call_tool(mcp_app, "todo_list")
        assert "Active" in result
        assert "Archived" not in result

    async def test_todo_list_all_status_filter(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Active")
        await call_tool(mcp_app, "todo_add", title="Done")
        await call_tool(mcp_app, "todo_complete", todo_id="2")
        result = await call_tool(mcp_app, "todo_list_all", status="done")
        data = _json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Done"

    async def test_todo_list_all_status_open_returns_non_terminal(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """status='open' on todo_list_all returns non-done/non-cancelled todos."""
        await call_tool(mcp_app, "todo_add", title="Active")
        await call_tool(mcp_app, "todo_add", title="Done")
        await call_tool(mcp_app, "todo_complete", todo_id="2")
        result = await call_tool(mcp_app, "todo_list_all", status="open")
        data = _json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Active"

    async def test_todo_list_all_empty_project(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "todo_list_all")
        assert "no todos" in result.lower()


@pytest.mark.asyncio
class TestTodoTreeMerge:
    async def test_todo_tree_include_done_merges_archive(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Leaf A")
        await call_tool(mcp_app, "todo_add", title="Leaf B")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)
        titles = {t["title"] for t in data}
        assert "Leaf A" in titles
        assert "Leaf B" in titles

    async def test_todo_tree_default_excludes_archive(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Active")
        await call_tool(mcp_app, "todo_add", title="Archived")
        await call_tool(mcp_app, "todo_complete", todo_id="2")
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        titles = {t["title"] for t in data}
        assert "Active" in titles
        assert "Archived" not in titles

    async def test_todo_tree_include_done_shows_archived_family(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(mcp_app, "todo_add", title="Parent")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        await call_tool(mcp_app, "todo_complete", todo_id="1.1")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Parent"
        assert data[0]["status"] == "done"
        assert len(data[0]["_children"]) == 1
        assert data[0]["_children"][0]["title"] == "Child"

    async def test_todo_tree_shows_orphaned_todo_under_orphaned_root(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """A todo with a missing parent appears under __orphaned__ synthetic root."""
        cfg, name = project
        # Inject a todo with a dangling group: tag (missing parent) directly via storage
        orphan = Todo(
            id="99",
            title="Lost Child",
            tags=["group:999"],
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_todos(cfg, name, [orphan])
        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)
        orphaned_roots = [node for node in data if node.get("id") == "__orphaned__"]
        assert len(orphaned_roots) == 1
        orphaned_node = orphaned_roots[0]
        assert orphaned_node["title"] == "⚠️ Orphaned"
        child_titles = [c["title"] for c in orphaned_node["_children"]]
        assert "Lost Child" in child_titles

    async def test_todo_tree_orphaned_done_excluded_without_include_done(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """A done orphaned todo is excluded when include_done=False."""
        cfg, name = project
        orphan = Todo(
            id="99",
            title="Done Orphan",
            tags=["group:999"],
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_todos(cfg, name, [orphan])
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        orphaned_roots = [node for node in data if node.get("id") == "__orphaned__"]
        assert len(orphaned_roots) == 0

    async def test_todo_tree_no_orphaned_node_when_all_parents_exist(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """No __orphaned__ node appears when all parent references are valid."""
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Child")
        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)
        orphaned_roots = [node for node in data if node.get("id") == "__orphaned__"]
        assert len(orphaned_roots) == 0

    async def test_todo_tree_archived_parent_child_renders_at_top_level(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """A child whose parent is archived (not deleted) renders at top level,
        not under __orphaned__."""
        cfg, name = project
        archived_parent = Todo(
            id="100",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos(cfg, name, [archived_parent])
        active_child = Todo(
            id="101",
            title="Active Child",
            tags=["group:100"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child])

        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)

        top_level_ids = [node.get("id") for node in data]
        assert "101" in top_level_ids, "child should appear at top level"
        orphaned_roots = [node for node in data if node.get("id") == "__orphaned__"]
        assert len(orphaned_roots) == 0, (
            "no __orphaned__ bucket should appear (parent exists, just archived)"
        )

    async def test_todo_tree_mixed_archived_and_deleted_parents(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Archived-parent child renders top level; deleted-parent child stays under
        __orphaned__."""
        cfg, name = project
        archived_parent = Todo(
            id="200",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos(cfg, name, [archived_parent])
        active_child_archived_parent = Todo(
            id="201",
            title="Child of Archived",
            tags=["group:200"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        active_child_deleted_parent = Todo(
            id="202",
            title="Child of Deleted",
            tags=["group:999"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child_archived_parent, active_child_deleted_parent])

        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)

        top_level_ids = [node.get("id") for node in data]
        assert "201" in top_level_ids, "archived-parent child renders at top level"
        orphaned_roots = [node for node in data if node.get("id") == "__orphaned__"]
        assert len(orphaned_roots) == 1, "__orphaned__ bucket appears for the deleted-parent child"
        orphaned_child_ids = [c.get("id") for c in orphaned_roots[0]["_children"]]
        assert orphaned_child_ids == ["202"], "only the deleted-parent child is in __orphaned__"

    async def test_todo_tree_archived_parent_with_include_done_nests_child(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """include_done=True merges archived into todo_map → child renders UNDER parent
        (existing behavior preserved)."""
        cfg, name = project
        archived_parent = Todo(
            id="300",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos(cfg, name, [archived_parent])
        active_child = Todo(
            id="301",
            title="Active Child",
            tags=["group:300"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child])

        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)

        parent_node = next((n for n in data if n.get("id") == "300"), None)
        assert parent_node is not None, "archived parent appears as root when include_done=True"
        child_ids = [c.get("id") for c in parent_node.get("_children", [])]
        assert "301" in child_ids, "child renders under archived parent when include_done=True"
        top_level_ids = [node.get("id") for node in data]
        assert top_level_ids.count("301") == 0, (
            "child is NOT at top level when parent is in todo_map"
        )

    async def test_todo_tree_compact_archived_parent_child_at_top_level(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Compact mode: archived-parent child appears at top level, no __orphaned__ line."""
        cfg, name = project
        archived_parent = Todo(
            id="400",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos(cfg, name, [archived_parent])
        active_child = Todo(
            id="401",
            title="Active Child",
            tags=["group:400"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child])

        result = await call_tool(mcp_app, "todo_tree", compact=True)
        data = _json.loads(result)

        lines = data["result"].splitlines()
        child_lines = [line for line in lines if "401" in line and "Active Child" in line]
        assert len(child_lines) == 1, "child line appears in compact output"
        orphaned_lines = [line for line in lines if "__orphaned__" in line or "Orphaned" in line]
        assert len(orphaned_lines) == 0, "no __orphaned__ line in compact output"


@pytest.mark.asyncio
class TestManualTagDisplay:
    """Tests for [manual] badge display in todo_list and todo_tree output.

    Both tools return JSON where tags are exposed via the `tags` field
    in each todo dict. These tests verify that manual-tagged todos have
    "manual" in their `tags`, and non-manual todos do not.
    """

    async def test_todo_list_shows_manual_tag_for_manual_todo(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_list includes 'manual' in tags for a manual-tagged todo."""
        await call_tool(mcp_app, "todo_add", title="Manual task", tags=["manual"])
        result = await call_tool(mcp_app, "todo_list")
        data = _json.loads(result)
        assert len(data) == 1
        assert "manual" in data[0]["tags"]

    async def test_todo_list_no_manual_tag_for_regular_todo(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_list does not include 'manual' in tags for a regular todo."""
        await call_tool(mcp_app, "todo_add", title="Regular task")
        result = await call_tool(mcp_app, "todo_list")
        data = _json.loads(result)
        assert len(data) == 1
        assert "manual" not in data[0]["tags"]

    async def test_todo_list_mixed_todos_only_manual_has_manual_tag(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """When a list contains both manual and non-manual todos, only the manual
        one has 'manual' in its tags field."""
        await call_tool(mcp_app, "todo_add", title="Regular task")
        await call_tool(mcp_app, "todo_add", title="Manual task", tags=["manual"])
        result = await call_tool(mcp_app, "todo_list")
        data = _json.loads(result)
        assert len(data) == 2
        by_title = {t["title"]: t for t in data}
        assert "manual" not in by_title["Regular task"]["tags"]
        assert "manual" in by_title["Manual task"]["tags"]

    async def test_todo_list_manual_tag_preserved_with_other_tags(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """A todo with multiple tags including 'manual' retains all tags in
        todo_list output."""
        await call_tool(
            mcp_app, "todo_add", title="Multi-tagged", tags=["manual", "review", "urgent"]
        )
        result = await call_tool(mcp_app, "todo_list")
        data = _json.loads(result)
        assert len(data) == 1
        assert "manual" in data[0]["tags"]
        assert "review" in data[0]["tags"]
        assert "urgent" in data[0]["tags"]

    async def test_todo_tree_shows_manual_tag_on_root(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_tree includes 'manual' in tags for a manual-tagged root todo."""
        await call_tool(mcp_app, "todo_add", title="Manual root", tags=["manual"])
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        assert len(data) == 1
        assert "manual" in data[0]["tags"]

    async def test_todo_tree_shows_manual_tag_on_child(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_tree includes 'manual' in tags for a manual-tagged child node
        nested inside _children."""
        await call_tool(mcp_app, "todo_add", title="Parent")
        await call_tool(mcp_app, "todo_add", parent="1", title="Manual child", tags=["manual"])
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        assert len(data) == 1
        root = data[0]
        assert "manual" not in root["tags"]
        assert len(root["_children"]) == 1
        child = root["_children"][0]
        assert child["title"] == "Manual child"
        assert "manual" in child["tags"]

    async def test_todo_tree_mixed_hierarchy_manual_tag_only_on_tagged_node(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """In a tree with mixed manual/non-manual nodes, 'manual' appears only
        in the tags of the manually-tagged node."""
        await call_tool(mcp_app, "todo_add", title="Root")
        await call_tool(mcp_app, "todo_add", parent="1", title="Regular child")
        await call_tool(mcp_app, "todo_add", parent="1", title="Manual child", tags=["manual"])
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        assert len(data) == 1
        root = data[0]
        assert "manual" not in root["tags"]
        assert len(root["_children"]) == 2
        children_by_title = {c["title"]: c for c in root["_children"]}
        assert "manual" not in children_by_title["Regular child"]["tags"]
        assert "manual" in children_by_title["Manual child"]["tags"]

    async def test_todo_tree_non_manual_root_has_empty_tags(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """A regular root todo has an empty tags list in todo_tree output."""
        await call_tool(mcp_app, "todo_add", title="Regular root")
        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)
        assert len(data) == 1
        assert data[0]["tags"] == []

    async def test_todo_add_with_iso_due_date(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_add accepts an ISO date string and persists it."""
        await call_tool(mcp_app, "todo_add", title="Dated task", due_date="2026-06-01")
        todos = storage.load_todos(project[0], "myapp")
        assert len(todos) == 1
        assert todos[0].due_date == "2026-06-01"

    async def test_todo_add_with_natural_language_due_date(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_add rejects non-YYYY-MM-DD due_date strings with an error message.

        The validation was added in e1bd1b6 to enforce ISO format only.
        """
        result = await call_tool(mcp_app, "todo_add", title="Task", due_date="next Friday")
        assert "YYYY-MM-DD" in result or "due_date" in result.lower()
        todos = storage.load_todos(project[0], "myapp")
        assert len(todos) == 0  # no todo created due to validation failure

    async def test_todo_add_without_due_date_defaults_to_none(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Omitting due_date in todo_add results in due_date=None."""
        await call_tool(mcp_app, "todo_add", title="No due date")
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].due_date is None

    async def test_todo_update_sets_due_date(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_update can set due_date on an existing todo."""
        await call_tool(mcp_app, "todo_add", title="Task")
        result = await call_tool(mcp_app, "todo_update", todo_id="1", due_date="2026-12-31")
        assert "Updated" in result
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].due_date == "2026-12-31"

    async def test_todo_update_due_date_none_leaves_existing_value(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Passing due_date=None (omitted) in todo_update leaves the existing due_date unchanged."""
        await call_tool(mcp_app, "todo_add", title="Task", due_date="2026-06-01")
        # Call todo_update without providing due_date — existing value must be preserved.
        await call_tool(mcp_app, "todo_update", todo_id="1", title="Updated title")
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].due_date == "2026-06-01"

    async def test_todo_update_overwrites_existing_due_date(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """todo_update replaces an existing due_date with a new value."""
        await call_tool(mcp_app, "todo_add", title="Task", due_date="2026-01-01")
        await call_tool(mcp_app, "todo_update", todo_id="1", due_date="2026-09-15")
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].due_date == "2026-09-15"


@pytest.mark.asyncio
class TestTodoUpdateSkipHooks:
    """Tests for _skip_hooks flag on todo_update."""

    async def test_skip_hooks_with_sync_field_only(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """skip_hooks=True + only sync field → _skip_hooks in result."""
        await call_tool(mcp_app, "todo_add", title="Task")
        raw = await call_tool(
            mcp_app, "todo_update", todo_id="1", todoist_task_id="t999", skip_hooks=True
        )
        data = _json.loads(raw)
        assert data.get("_skip_hooks") is True
        # Verify the field was actually written
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].todoist_task_id == "t999"

    async def test_skip_hooks_rejected_with_title(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """skip_hooks=True + title field → scope guard rejects, no _skip_hooks in result."""
        await call_tool(mcp_app, "todo_add", title="Task")
        raw = await call_tool(
            mcp_app,
            "todo_update",
            todo_id="1",
            title="New",
            todoist_task_id="t999",
            skip_hooks=True,
        )
        data = _json.loads(raw)
        assert "_skip_hooks" not in data

    async def test_no_skip_hooks_flag_normal(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Without _skip_hooks, result has no _skip_hooks key."""
        await call_tool(mcp_app, "todo_add", title="Task")
        raw = await call_tool(mcp_app, "todo_update", todo_id="1", todoist_task_id="t999")
        data = _json.loads(raw)
        assert "_skip_hooks" not in data

    async def test_skip_hooks_rejected_with_status(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """_skip_hooks + status field → rejected by scope guard."""
        await call_tool(mcp_app, "todo_add", title="Task")
        raw = await call_tool(
            mcp_app, "todo_update", todo_id="1", status="in_progress", skip_hooks=True
        )
        data = _json.loads(raw)
        assert "_skip_hooks" not in data

    async def test_skip_hooks_rejected_with_blocked_by_set(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """skip_hooks=True + blocked_by_set → scope guard rejects, no _skip_hooks in result."""
        await call_tool(mcp_app, "todo_add", title="Blocker")
        await call_tool(mcp_app, "todo_add", title="Task")
        raw = await call_tool(
            mcp_app,
            "todo_update",
            todo_id="2",
            blocked_by_set=["1"],
            skip_hooks=True,
        )
        data = _json.loads(raw)
        assert "_skip_hooks" not in data

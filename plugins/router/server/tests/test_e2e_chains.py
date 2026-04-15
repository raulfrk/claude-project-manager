"""End-to-end chain tests: fixtures and helpers.

Tests that hook chains (e.g. todo_add → todoist + trello) fire correctly
using real hook definitions from default-hooks.yaml with mocked HTTP transport.
Actual test functions are added in subsequent todos (481.3-481.5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import save
from server.tools.fire import hooks_fire

_PLUGINS_DIR = Path(__file__).resolve().parents[3]


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_post_hook():
    """Patch ``post_hook`` with tool-based routing.

    Returns an ``AsyncMock`` that records all calls.  The mock dispatches
    responses based on the ``target_tool`` kwarg:

    - ``todoist_add_tasks`` → success with ``{"successes": [{"id": "td-123"}]}``
    - ``todoist_complete_tasks`` → simple success
    - ``todoist_update_tasks`` → simple success
    - ``todoist_delete`` → simple success
    - ``todoist_add_projects`` → success with ``{"id": "proj-td-1"}``
    - ``todoist_find_projects`` → success with project list
    - ``todoist_verify_complete`` → verification pass
    - ``add_card_to_list`` → success with ``{"id": "card-tr-1"}``
    - ``move_card`` → simple success
    - ``get_card`` → success with card data
    - ``update_card_details`` → simple success
    - ``archive_card`` → simple success
    - ``batch_create_cards`` → success with batch card results
    - ``todo_update`` → simple success (feedback writeback)
    - ``proj_update_meta`` → simple success (feedback writeback)
    - ``proj_todoist_full_sync`` → simple success
    - Everything else → success with empty result
    """
    _TOOL_RESPONSES: dict[str, str | None] = {
        "todoist_add_tasks": json.dumps({"successes": [{"id": "td-123"}]}),
        "todoist_complete_tasks": json.dumps({"ok": True}),
        "todoist_update_tasks": json.dumps({"ok": True}),
        "todoist_delete": json.dumps({"ok": True}),
        "todoist_add_projects": json.dumps({"id": "proj-td-1"}),
        "todoist_find_projects": json.dumps({"projects": [{"id": "proj-td-1", "name": "test"}]}),
        "todoist_verify_complete": json.dumps({"status": "pass", "details": "task completed"}),
        "add_card_to_list": json.dumps({"id": "card-tr-1", "name": "test card"}),
        "move_card": json.dumps({"ok": True}),
        "get_card": json.dumps({"id": "card-tr-1", "name": "test project"}),
        "update_card_details": json.dumps({"ok": True}),
        "archive_card": json.dumps({"ok": True}),
        "batch_create_cards": json.dumps(
            {"successes": [{"id": "card-child-1"}, {"id": "card-child-2"}], "failures": []}
        ),
        "todo_update": json.dumps({"ok": True}),
        "proj_update_meta": json.dumps({"ok": True}),
        "proj_todoist_full_sync": json.dumps({"ok": True}),
    }

    async def _route(**kwargs: Any) -> FireResult:
        tool = kwargs.get("target_tool", "")
        hook_id = kwargs.get("hook_id", "unknown")
        result_body = _TOOL_RESPONSES.get(tool, json.dumps({"ok": True}))
        return FireResult(
            hook_id=hook_id,
            status_code=200,
            body=json.dumps({"ok": True, "result": result_body}),
            result=result_body,
        )

    mock = AsyncMock(side_effect=_route)
    with patch("server.tools.fire.post_hook", mock):
        yield mock


@pytest.fixture()
def proj_config(tmp_path: Path) -> Path:
    """Write a realistic proj.yaml with all sync integrations enabled.

    Returns the path to the written file.
    """
    config = {
        "sync": {
            "todoist": {
                "enabled": True,
                "auto_sync": True,
            },
            "trello": {
                "enabled": True,
                "auto_sync": True,
                "list_mappings": {
                    "tasks": "list-tasks-id",
                    "done": "list-done-id",
                    "archived": "list-archived-id",
                },
            },
        },
        "sandbox_integration": True,
    }
    config_path = tmp_path / "proj.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return config_path


# ── Source result factories ──────────────────────────────────────────────────


def make_todo_source(**overrides: Any) -> dict[str, Any]:
    """Return a dict matching ``_todo_hook_fields()`` output shape.

    All fields have sensible defaults; pass keyword args to override.
    """
    defaults: dict[str, Any] = {
        "todo_id": "t-001",
        "title": "Test todo",
        "priority": "medium",
        "tags": ["dev"],
        "notes": "",
        "due_date": None,
        "todoist_task_id": "td-task-100",
        "trello_project_card_id": "card-tr-proj-1",
        "trello_card_id": "card-tr-todo-1",
        "jira_issue_key": None,
        "project_name": "test-project",
        "todoist_project_id": "proj-td-1",
        "parent_todoist_task_id": None,
        "parent_trello_card_id": None,
        "parent_trello_checklist_id": None,
        # Resolved Trello list IDs for direct tool mapping hooks
        "trello_list_id": "list-tasks-id",
        "trello_done_list_id": "list-done-id",
        "trello_projects_list_id": "list-projects-id",
        "sync": {
            "trello": {
                "enabled": True,
                "auto_sync": True,
                "default_board_id": "board-1",
                "default_list_id": "list-default-id",
                "list_mappings": {
                    "tasks": "list-tasks-id",
                    "done": "list-done-id",
                    "projects": "list-projects-id",
                    "archived": "list-archived-id",
                },
            },
            "todoist": {
                "enabled": True,
                "auto_sync": True,
            },
        },
    }
    defaults.update(overrides)
    return defaults


def make_proj_source(**overrides: Any) -> dict[str, Any]:
    """Return a dict matching ``proj_init`` / ``proj_load_session`` source result shape."""
    defaults: dict[str, Any] = {
        "project_name": "test-project",
        "paths": ["/home/user/projects/test-project"],
        "mcp_servers": [],
        "todoist_project_id": "proj-td-1",
        "trello_card_id": "card-tr-1",
        "sync": {
            "trello": {
                "enabled": True,
                "auto_sync": True,
                "default_board_id": "board-1",
                "default_list_id": "list-default-id",
                "list_mappings": {
                    "tasks": "list-tasks-id",
                    "done": "list-done-id",
                    "projects": "list-projects-id",
                    "archived": "list-archived-id",
                },
            },
        },
    }
    defaults.update(overrides)
    return defaults


# ── Hook loading ─────────────────────────────────────────────────────────────


def load_real_hooks() -> HookRegistry:
    """Load actual default-hooks.yaml from todoist and trello plugins.

    Returns a merged ``HookRegistry`` containing hooks from both plugins
    with server entries for todoist, trello, and proj.
    """
    hooks: list[Hook] = []

    for plugin_name in ("todoist", "trello"):
        hooks_file = _PLUGINS_DIR / plugin_name / ".claude-plugin" / "default-hooks.yaml"
        if hooks_file.exists():
            with hooks_file.open() as f:
                raw = yaml.safe_load(f)
            if isinstance(raw, dict):
                raw_hooks = raw.get("hooks", [])
                if isinstance(raw_hooks, list):
                    for h in raw_hooks:
                        if isinstance(h, dict):
                            hooks.append(Hook.from_dict(h))

    return HookRegistry(
        hooks=hooks,
        servers={
            "todoist": {"url": "http://127.0.0.1:19106/hook"},
            "trello": {"url": "http://127.0.0.1:19104/hook"},
            "proj": {"url": "http://127.0.0.1:19102/hook"},
        },
    )


# ── Async helper ─────────────────────────────────────────────────────────────


async def fire_with_config(
    trigger_tool: str,
    source_result: dict[str, Any],
    config_path: Path,
    registry: HookRegistry,
    hooks_yaml: Path,
) -> dict[str, Any]:
    """Save registry, patch config + storage paths, and fire hooks.

    Returns the parsed JSON summary dict from ``hooks_fire``.
    """
    save(registry, hooks_yaml)
    failures_yaml = hooks_yaml.parent / "hooks-failures.yaml"

    with (
        patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
        patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        patch("server.lib.conditions._PROJ_CONFIG_PATH", config_path),
        patch(
            "server.tools.fire._resolve_server_url",
            side_effect=lambda name, _port: registry.servers.get(name, {}).get(
                "url", f"http://127.0.0.1:{_port}/hook"
            ),
        ),
    ):
        raw = await hooks_fire(
            trigger_tool=trigger_tool,
            source_result=json.dumps(source_result),
        )

    return json.loads(raw)


# ── Smoke test ───────────────────────────────────────────────────────────────


class TestFixturesLoadable:
    """Verify fixtures and helpers are functional."""

    def test_load_real_hooks_returns_hooks(self) -> None:
        registry = load_real_hooks()
        assert len(registry.hooks) > 0
        trigger_tools = {h.trigger_tool for h in registry.hooks}
        assert "todo_add" in trigger_tools
        assert "todo_complete" in trigger_tools
        assert "proj_init" in trigger_tools

    @pytest.mark.asyncio
    async def test_mock_post_hook_routes(self, mock_post_hook: AsyncMock) -> None:
        result = await mock_post_hook(
            hook_id="test", url="http://x", target_tool="todoist_add_tasks", params={}
        )
        assert result.ok
        assert "td-123" in (result.result or "")
        assert mock_post_hook.call_count == 1

    def test_proj_config_fixture(self, proj_config: Path) -> None:
        data = yaml.safe_load(proj_config.read_text())
        assert data["sync"]["todoist"]["enabled"] is True
        assert data["sync"]["trello"]["auto_sync"] is True
        assert data["sandbox_integration"] is True

    @pytest.mark.asyncio
    async def test_fire_with_config_helper(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source()
        result = await fire_with_config("todo_add", source, proj_config, registry, hooks_yaml)
        assert "hooks_fired" in result
        assert isinstance(result["errors"], list)


# ── CRUD chain tests ────────────────────────────────────────────────────────


def _calls_by_tool(mock: AsyncMock) -> dict[str, list[dict[str, Any]]]:
    """Group mock_post_hook calls by target_tool for easy assertion."""
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for call in mock.call_args_list:
        kw = call.kwargs
        tool = kw.get("target_tool", "")
        by_tool.setdefault(tool, []).append(kw)
    return by_tool


class TestCrudChains:
    """Verify todo CRUD triggers fire the correct todoist + trello hooks."""

    @pytest.mark.asyncio
    async def test_todo_add_fires_todoist_and_trello(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            title="Buy milk",
            priority="high",
            todoist_project_id="proj-td-1",
            trello_project_card_id="card-tr-proj-1",
        )
        result = await fire_with_config("todo_add", source, proj_config, registry, hooks_yaml)

        assert result["errors"] == []
        assert result["hooks_fired"] >= 2

        by_tool = _calls_by_tool(mock_post_hook)

        # Todoist hook fires with correct params
        assert "todoist_add_tasks" in by_tool
        td_params = by_tool["todoist_add_tasks"][0]["params"]
        assert td_params["tasks"][0]["content"] == "Buy milk"
        assert td_params["tasks"][0]["priority"] == "high"
        assert td_params["tasks"][0]["projectId"] == "proj-td-1"

        # Trello hook fires (add_card_to_list)
        assert "add_card_to_list" in by_tool
        tr_params = by_tool["add_card_to_list"][0]["params"]
        assert tr_params["name"] == "Buy milk"
        assert tr_params["list_id"] == "list-tasks-id"

        # Feedback writeback calls todo_update with mapped IDs
        assert "todo_update" in by_tool
        fb_calls = by_tool["todo_update"]
        fb_params_all = {k: v for call in fb_calls for k, v in call["params"].items()}
        assert "todoist_task_id" in fb_params_all or "trello_card_id" in fb_params_all

    @pytest.mark.asyncio
    async def test_todo_add_with_parent_fires_todoist_with_parent_id(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        """todo_add_child removed — todo_add(parent=) fires todoist-on-todo-add with parentId."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            title="Child task",
            parent_todoist_task_id="td-parent-1",
            parent_trello_card_id="card-tr-parent-1",
            todoist_project_id="proj-td-1",
        )
        result = await fire_with_config("todo_add", source, proj_config, registry, hooks_yaml)

        assert result["errors"] == []
        by_tool = _calls_by_tool(mock_post_hook)

        # Todoist child add with parentId via todoist-on-todo-add hook
        assert "todoist_add_tasks" in by_tool
        td_params = by_tool["todoist_add_tasks"][0]["params"]
        assert td_params["tasks"][0]["parentId"] == "td-parent-1"
        assert td_params["tasks"][0]["content"] == "Child task"

    @pytest.mark.asyncio
    async def test_todo_complete_fires_four_hooks(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            todoist_task_id="td-task-100",
            trello_card_id="card-tr-todo-1",
        )
        result = await fire_with_config("todo_complete", source, proj_config, registry, hooks_yaml)

        assert result["errors"] == []
        by_tool = _calls_by_tool(mock_post_hook)

        # Phase 1: todoist complete + trello move
        assert "todoist_complete_tasks" in by_tool
        td_params = by_tool["todoist_complete_tasks"][0]["params"]
        assert "td-task-100" in td_params["ids"]

        assert "move_card" in by_tool
        mc_params = by_tool["move_card"][0]["params"]
        assert mc_params["card_id"] == "card-tr-todo-1"
        assert mc_params["list_id"] == "list-done-id"

        # Phase 2: verification hooks
        assert "verification" in result
        verification = result["verification"]
        assert isinstance(verification, list)
        assert len(verification) >= 2
        hook_ids = {v["hook_id"] for v in verification}
        assert "verify-todoist-complete" in hook_ids
        assert "verify-trello-todo-card" in hook_ids

    @pytest.mark.asyncio
    async def test_todo_update_fires_todoist_and_trello(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            title="Updated title",
            todoist_task_id="td-task-100",
            trello_card_id="card-tr-todo-1",
        )
        result = await fire_with_config("todo_update", source, proj_config, registry, hooks_yaml)

        assert result["errors"] == []
        by_tool = _calls_by_tool(mock_post_hook)

        # Todoist update
        assert "todoist_update_tasks" in by_tool
        td_params = by_tool["todoist_update_tasks"][0]["params"]
        assert td_params["tasks"][0]["id"] == "td-task-100"
        assert td_params["tasks"][0]["content"] == "Updated title"

        # Trello update
        assert "update_card_details" in by_tool
        tr_params = by_tool["update_card_details"][0]["params"]
        assert tr_params["card_id"] == "card-tr-todo-1"
        assert tr_params["name"] == "Updated title"

    @pytest.mark.asyncio
    async def test_todo_delete_fires_todoist_and_trello(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            todoist_task_id="td-task-100",
            trello_card_id="card-tr-todo-1",
        )
        result = await fire_with_config("todo_delete", source, proj_config, registry, hooks_yaml)

        assert result["errors"] == []
        by_tool = _calls_by_tool(mock_post_hook)

        # Todoist delete
        assert "todoist_delete" in by_tool
        td_params = by_tool["todoist_delete"][0]["params"]
        assert td_params["id"] == "td-task-100"

        # Trello archive
        assert "archive_card" in by_tool
        tr_params = by_tool["archive_card"][0]["params"]
        assert tr_params["card_id"] == "card-tr-todo-1"


# ── Project chain tests ────────────────────────────────────────────────────


class TestProjectChains:
    """Verify project lifecycle triggers fire the correct todoist + trello hooks."""

    @pytest.mark.asyncio
    async def test_proj_init_fires_todoist_and_trello_with_feedback(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_proj_source(project_name="my-new-project")
        result = await fire_with_config("proj_init", source, proj_config, registry, hooks_yaml)

        assert result["errors"] == []
        assert result["hooks_fired"] >= 2

        by_tool = _calls_by_tool(mock_post_hook)

        # Todoist: todoist_add_projects fires with project name
        assert "todoist_add_projects" in by_tool
        td_params = by_tool["todoist_add_projects"][0]["params"]
        assert td_params["name"] == "my-new-project"

        # Trello: add_card_to_list fires with project name and resolved list ID
        assert "add_card_to_list" in by_tool
        tr_params = by_tool["add_card_to_list"][0]["params"]
        assert tr_params["name"] == "my-new-project"
        assert tr_params["list_id"] == "list-default-id"

        # Feedback writeback: proj_update_meta called with mapped IDs
        assert "proj_update_meta" in by_tool
        fb_calls = by_tool["proj_update_meta"]
        fb_params_all = {k: v for call in fb_calls for k, v in call["params"].items()}
        # todoist feedback maps id → todoist_project_id
        assert "todoist_project_id" in fb_params_all
        assert fb_params_all["todoist_project_id"] == "proj-td-1"
        # trello feedback maps id → trello_card_id (from add_card_to_list response)
        assert "trello_card_id" in fb_params_all
        assert fb_params_all["trello_card_id"] == "card-tr-1"

    @pytest.mark.asyncio
    async def test_proj_load_session_fires_three_hooks(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_proj_source(
            project_name="existing-project",
            todoist_project_id="proj-td-1",
            trello_card_id="card-tr-1",
        )
        result = await fire_with_config(
            "proj_load_session", source, proj_config, registry, hooks_yaml
        )

        assert result["errors"] == []
        assert result["hooks_fired"] >= 3

        by_tool = _calls_by_tool(mock_post_hook)

        # Todoist: todoist_find_projects fires
        assert "todoist_find_projects" in by_tool
        td_params = by_tool["todoist_find_projects"][0]["params"]
        assert td_params["name"] == "existing-project"

        # Todoist full sync: proj_todoist_full_sync fires (targets proj server)
        assert "proj_todoist_full_sync" in by_tool
        sync_params = by_tool["proj_todoist_full_sync"][0]["params"]
        assert sync_params["project_name"] == "existing-project"

        # Trello: get_card fires with trello_card_id
        assert "get_card" in by_tool
        tr_params = by_tool["get_card"][0]["params"]
        assert tr_params["card_id"] == "card-tr-1"

    @pytest.mark.asyncio
    async def test_proj_archive_non_blocking_trello(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_proj_source(
            project_name="archived-project",
            todoist_project_id="proj-td-1",
            trello_card_id="card-tr-1",
        )
        result = await fire_with_config("proj_archive", source, proj_config, registry, hooks_yaml)

        assert result["errors"] == []

        # Trello archive hook is non-blocking — appears as dispatched
        assert result["non_blocking_dispatched"] >= 1
        results_list = result.get("results", [])
        assert isinstance(results_list, list)
        dispatched_hooks = [
            r for r in results_list if isinstance(r, dict) and r.get("status") == "dispatched"
        ]
        assert len(dispatched_hooks) >= 1
        dispatched_tools = {r["target_tool"] for r in dispatched_hooks}
        assert "move_card" in dispatched_tools

        by_tool = _calls_by_tool(mock_post_hook)

        # Todoist: todoist_find_tasks fires as blocking
        assert "todoist_find_tasks" in by_tool


# ── Advanced chain tests ──────────────────────────────────────────────────


@pytest.fixture()
def proj_config_todoist_disabled(tmp_path: Path) -> Path:
    """proj.yaml with todoist auto_sync disabled, trello enabled."""
    config = {
        "sync": {
            "todoist": {"enabled": True, "auto_sync": False},
            "trello": {
                "enabled": True,
                "auto_sync": True,
                "list_mappings": {
                    "tasks": "list-tasks-id",
                    "done": "list-done-id",
                    "archived": "list-archived-id",
                },
            },
        },
        "sandbox_integration": True,
    }
    config_path = tmp_path / "proj.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return config_path


@pytest.fixture()
def proj_config_trello_disabled(tmp_path: Path) -> Path:
    """proj.yaml with trello disabled, todoist enabled."""
    config = {
        "sync": {
            "todoist": {"enabled": True, "auto_sync": True},
            "trello": {"enabled": False, "auto_sync": False},
        },
        "sandbox_integration": True,
    }
    config_path = tmp_path / "proj.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return config_path


@pytest.fixture()
def proj_config_both_disabled(tmp_path: Path) -> Path:
    """proj.yaml with both todoist and trello disabled."""
    config = {
        "sync": {
            "todoist": {"enabled": False, "auto_sync": False},
            "trello": {"enabled": False, "auto_sync": False},
        },
        "sandbox_integration": True,
    }
    config_path = tmp_path / "proj.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return config_path


class TestAdvancedChains:
    """Advanced chain tests: batch feedback, condition gating,
    fan-out, error handling, depth limits."""

    @pytest.mark.asyncio
    async def test_batch_add_children_array_feedback(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        """Fire todo_batch_add_children -- verify trello batch hook
        fires and array feedback maps per-child card IDs."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"

        # batch_create_cards returns per-card results with IDs
        source = make_todo_source(
            trello_card_id="card-tr-parent-1",
            trello_project_card_id="card-tr-proj-1",
        )
        source["created"] = [
            {"id": "child-1", "title": "Sub-task 1"},
            {"id": "child-2", "title": "Sub-task 2"},
        ]
        source["trello_batch_cards"] = [
            {"list_id": "list-tasks-id", "name": "Sub-task 1"},
            {"list_id": "list-tasks-id", "name": "Sub-task 2"},
        ]

        result = await fire_with_config(
            "todo_batch_add_children", source, proj_config, registry, hooks_yaml
        )

        assert result["errors"] == []
        by_tool = _calls_by_tool(mock_post_hook)

        # Trello batch_create_cards hook fires
        assert "batch_create_cards" in by_tool
        tr_params = by_tool["batch_create_cards"][0]["params"]
        assert isinstance(tr_params["cards"], list)
        assert len(tr_params["cards"]) == 2

        # Feedback writeback calls todo_update for each child
        assert "todo_update" in by_tool
        fb_calls = by_tool["todo_update"]
        fb_todo_ids = [call["params"].get("todo_id") for call in fb_calls]
        assert "child-1" in fb_todo_ids
        assert "child-2" in fb_todo_ids

    @pytest.mark.asyncio
    async def test_condition_gating_todoist_disabled(
        self,
        mock_post_hook: AsyncMock,
        proj_config_todoist_disabled: Path,
        tmp_path: Path,
    ) -> None:
        """Todoist auto_sync=false: todoist hooks skipped, trello hooks fire."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            title="Gated todo",
            todoist_project_id="proj-td-1",
            trello_project_card_id="card-tr-proj-1",
        )
        result = await fire_with_config(
            "todo_add", source, proj_config_todoist_disabled, registry, hooks_yaml
        )

        # Todoist hook skipped (requires auto_sync)
        skipped = result.get("skipped_hooks", [])
        skipped_ids = {s["hook_id"] for s in skipped}
        assert "todoist-on-todo-add" in skipped_ids

        # Trello hook fires (add_card_to_list)
        by_tool = _calls_by_tool(mock_post_hook)
        assert "add_card_to_list" in by_tool

    @pytest.mark.asyncio
    async def test_condition_gating_trello_disabled(
        self,
        mock_post_hook: AsyncMock,
        proj_config_trello_disabled: Path,
        tmp_path: Path,
    ) -> None:
        """Trello disabled: trello hooks skipped, todoist hooks fire."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            title="Gated todo",
            todoist_project_id="proj-td-1",
            trello_project_card_id="card-tr-proj-1",
        )
        result = await fire_with_config(
            "todo_add", source, proj_config_trello_disabled, registry, hooks_yaml
        )

        # Trello hook skipped
        skipped = result.get("skipped_hooks", [])
        skipped_ids = {s["hook_id"] for s in skipped}
        assert "trello-on-todo-add" in skipped_ids

        # Todoist hook fires
        by_tool = _calls_by_tool(mock_post_hook)
        assert "todoist_add_tasks" in by_tool

    @pytest.mark.asyncio
    async def test_condition_gating_both_disabled(
        self,
        mock_post_hook: AsyncMock,
        proj_config_both_disabled: Path,
        tmp_path: Path,
    ) -> None:
        """Both integrations disabled: all hooks skipped, none fire."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            title="Fully gated todo",
            todoist_project_id="proj-td-1",
            trello_project_card_id="card-tr-proj-1",
        )
        result = await fire_with_config(
            "todo_add", source, proj_config_both_disabled, registry, hooks_yaml
        )

        assert result["hooks_fired"] == 0
        skipped = result.get("skipped_hooks", [])
        assert len(skipped) >= 2
        skipped_ids = {s["hook_id"] for s in skipped}
        assert "todoist-on-todo-add" in skipped_ids
        assert "trello-on-todo-add" in skipped_ids

    @pytest.mark.asyncio
    async def test_feedback_writeback_failure(
        self,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        """Mock todo_update (feedback target) to return an error — primary hooks still succeed."""
        _TOOL_RESPONSES: dict[str, str | None] = {
            "todoist_add_tasks": json.dumps({"successes": [{"id": "td-123"}]}),
            "add_card_to_list": json.dumps({"id": "card-tr-todo-1", "name": "test"}),
        }

        async def _route_with_fb_fail(**kwargs: Any) -> FireResult:
            tool = kwargs.get("target_tool", "")
            hook_id = kwargs.get("hook_id", "unknown")
            if tool == "todo_update":
                return FireResult(
                    hook_id=hook_id,
                    status_code=200,
                    body=json.dumps({"ok": False, "error": "writeback failed"}),
                    error="writeback failed",
                )
            result_body = _TOOL_RESPONSES.get(tool, json.dumps({"ok": True}))
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body=json.dumps({"ok": True, "result": result_body}),
                result=result_body,
            )

        mock = AsyncMock(side_effect=_route_with_fb_fail)
        with patch("server.tools.fire.post_hook", mock):
            registry = load_real_hooks()
            hooks_yaml = tmp_path / "hooks.yaml"
            source = make_todo_source(
                title="Feedback fail test",
                todoist_project_id="proj-td-1",
                trello_project_card_id="card-tr-proj-1",
            )
            result = await fire_with_config("todo_add", source, proj_config, registry, hooks_yaml)

        by_tool = _calls_by_tool(mock)

        # Primary hooks succeed
        assert "todoist_add_tasks" in by_tool
        assert "add_card_to_list" in by_tool

        # Feedback was attempted but failed
        feedback = result.get("feedback", [])
        assert len(feedback) >= 1
        failed_fb = [f for f in feedback if not f.get("ok")]
        assert len(failed_fb) >= 1

    @pytest.mark.asyncio
    async def test_target_server_error_500(
        self,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        """Mock target tool to return HTTP 500 — error captured, no crash."""

        async def _route_500(**kwargs: Any) -> FireResult:
            tool = kwargs.get("target_tool", "")
            hook_id = kwargs.get("hook_id", "unknown")
            if tool == "todoist_add_tasks":
                return FireResult(
                    hook_id=hook_id,
                    status_code=500,
                    body="Internal Server Error",
                    error="HTTP 500",
                )
            result_body = json.dumps({"ok": True})
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body=json.dumps({"ok": True, "result": result_body}),
                result=result_body,
            )

        mock = AsyncMock(side_effect=_route_500)
        with patch("server.tools.fire.post_hook", mock):
            registry = load_real_hooks()
            hooks_yaml = tmp_path / "hooks.yaml"
            source = make_todo_source(
                title="Server error test",
                todoist_project_id="proj-td-1",
                trello_project_card_id="card-tr-proj-1",
            )
            result = await fire_with_config("todo_add", source, proj_config, registry, hooks_yaml)

        # No crash — result is well-formed
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) >= 1
        error_hooks = {e["hook_id"] for e in result["errors"]}
        assert "todoist-on-todo-add" in error_hooks

    @pytest.mark.asyncio
    async def test_depth_limit_enforcement(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        """Fire with depth=3 (at max) — verify depth_limited response."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source()

        from server.lib.storage import save

        save(registry, hooks_yaml)
        failures_yaml = hooks_yaml.parent / "hooks-failures.yaml"

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_config),
        ):
            from server.tools.fire import hooks_fire

            raw = await hooks_fire(
                trigger_tool="todo_add",
                source_result=json.dumps(source),
                depth=3,  # at default max_depth
            )

        result = json.loads(raw)
        assert result["depth_limited"] is True
        assert result["hooks_fired"] == 0
        assert result["depth"] == 3

    @pytest.mark.asyncio
    async def test_todo_add_without_external_ids_skips_hooks(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        """todo_add with no todoist_project_id and no trello IDs — hooks that
        require those IDs in their conditions should be skipped."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            title="No external IDs",
            todoist_project_id=None,
            trello_project_card_id=None,
            trello_card_id=None,
        )
        result = await fire_with_config("todo_add", source, proj_config, registry, hooks_yaml)

        # Hooks requiring todoist_project_id / trello IDs in conditions should skip
        skipped = result.get("skipped_hooks", [])
        skipped_ids = {s["hook_id"] for s in skipped}
        # todoist hook condition includes "project.todoist_project_id" — should skip
        assert "todoist-on-todo-add" in skipped_ids

    @pytest.mark.asyncio
    async def test_todo_uncomplete_fires_trello_move(
        self,
        mock_post_hook: AsyncMock,
        proj_config: Path,
        tmp_path: Path,
    ) -> None:
        """todo_uncomplete fires trello move_card back to tasks list."""
        registry = load_real_hooks()
        hooks_yaml = tmp_path / "hooks.yaml"
        source = make_todo_source(
            trello_card_id="card-tr-todo-1",
        )
        result = await fire_with_config(
            "todo_uncomplete", source, proj_config, registry, hooks_yaml
        )

        assert result["errors"] == []
        by_tool = _calls_by_tool(mock_post_hook)

        # Trello move_card fires to move card back to tasks list
        assert "move_card" in by_tool
        mc_params = by_tool["move_card"][0]["params"]
        assert mc_params["card_id"] == "card-tr-todo-1"

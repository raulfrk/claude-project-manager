"""Tests for default-hooks.yaml structure and hook tool behaviour."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import yaml

_HOOKS_PATH = Path(__file__).parent.parent.parent / ".claude-plugin" / "default-hooks.yaml"

_REQUIRED_FIELDS = {"id", "trigger_tool", "target_tool", "server", "param_mapping", "condition"}


class TestDefaultHooksYaml:
    def test_file_exists(self) -> None:
        assert _HOOKS_PATH.exists(), f"Missing {_HOOKS_PATH}"

    def test_loads_valid_yaml(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "hooks" in data

    def test_has_10_hooks(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        assert len(data["hooks"]) == 10

    def test_all_hooks_have_required_fields(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        for hook in data["hooks"]:
            missing = _REQUIRED_FIELDS - set(hook.keys())
            assert not missing, f"Hook {hook.get('id', '?')} missing fields: {missing}"

    def test_all_hook_ids_unique(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        ids = [h["id"] for h in data["hooks"]]
        assert len(ids) == len(set(ids)), f"Duplicate hook IDs: {ids}"

    def test_all_hooks_target_trello_server(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        for hook in data["hooks"]:
            assert hook["server"] == "trello", (
                f"Hook {hook['id']} server is {hook['server']}, expected 'trello'"
            )

    def test_param_mapping_is_dict(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        for hook in data["hooks"]:
            assert isinstance(hook["param_mapping"], dict), (
                f"Hook {hook['id']} param_mapping is not a dict"
            )

    def test_expected_hook_ids(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        ids = {h["id"] for h in data["hooks"]}
        expected = {
            "trello-on-proj-init",
            "trello-on-proj-load",
            "trello-on-proj-archive",
            "trello-on-todo-add",
            "trello-on-todo-complete",
            "trello-on-todo-uncomplete",
            "verify-trello-todo-card",
            "trello-on-todo-update",
            "trello-on-todo-delete",
            "trello-on-todo-add-child",
            "trello-on-todo-batch-add-children",
        }
        assert ids == expected


# -- trello_add_todo_card_hook ------------------------------------------------


class TestAddTodoCardHook:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        from server.tools.hooks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["trello_add_todo_card_hook"].fn

    def test_no_board_id_returns_error(self, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={},
        )
        tool = self._get_tool()
        result = json.loads(tool(name="task 1"))
        assert "error" in result
        assert "default_board_id" in result["error"]

    def test_creates_card_on_tasks_list(
        self,
        mock_trello_client: MagicMock,
        mocker: MagicMock,
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [
            {"id": "list-1", "name": "proj-tasks"},
        ]
        mock_trello_client.post.return_value = {"id": "card-new"}
        tool = self._get_tool()
        result = json.loads(tool(name="task 1"))
        assert result["card_id"] == "card-new"
        mock_trello_client.post.assert_called_once_with(
            "/cards",
            params={"idList": "list-1", "name": "task 1"},
        )

    def test_tasks_list_not_found(
        self,
        mock_trello_client: MagicMock,
        mocker: MagicMock,
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [
            {"id": "list-1", "name": "Other"},
        ]
        tool = self._get_tool()
        result = json.loads(tool(name="task 1"))
        assert "error" in result
        assert "proj-tasks" in result["error"]


# -- trello_add_child_card_hook -----------------------------------------------


class TestAddChildCardHook:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        from server.tools.hooks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["trello_add_child_card_hook"].fn

    def test_no_board_id_returns_error(self, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={},
        )
        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="parent-1", name="child"))
        assert "error" in result
        assert "default_board_id" in result["error"]

    def test_creates_card_and_attaches_to_parent(
        self,
        mock_trello_client: MagicMock,
        mocker: MagicMock,
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [
            {"id": "list-1", "name": "proj-tasks"},
        ]
        mock_trello_client.post.side_effect = [
            {"id": "child-card", "shortUrl": "https://trello.com/c/abc"},
            {"id": "attach-1"},  # attachment
        ]
        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="parent-1", name="child task"))
        assert result["card_id"] == "child-card"
        assert mock_trello_client.post.call_count == 2
        # Verify attachment call
        mock_trello_client.post.assert_any_call(
            "/cards/parent-1/attachments",
            params={"url": "https://trello.com/c/abc", "name": "child task"},
        )

    def test_creates_card_without_parent(
        self,
        mock_trello_client: MagicMock,
        mocker: MagicMock,
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [
            {"id": "list-1", "name": "proj-tasks"},
        ]
        mock_trello_client.post.return_value = {
            "id": "child-card",
            "shortUrl": "https://trello.com/c/abc",
        }
        tool = self._get_tool()
        result = json.loads(tool(parent_card_id=None, name="orphan task"))
        assert result["card_id"] == "child-card"
        # Only one post call (card creation, no attachment)
        assert mock_trello_client.post.call_count == 1


# -- trello_batch_add_child_cards_hook ----------------------------------------


class TestBatchAddChildCardsHook:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        from server.tools.hooks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["trello_batch_add_child_cards_hook"].fn

    def test_no_board_id_returns_error(self, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={},
        )
        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="p1", items=["a", "b"]))
        assert "error" in result
        assert "default_board_id" in result["error"]

    def test_creates_cards_and_attaches(
        self,
        mock_trello_client: MagicMock,
        mocker: MagicMock,
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [
            {"id": "list-1", "name": "proj-tasks"},
        ]
        mock_trello_client.post.side_effect = [
            {"id": "card-a", "shortUrl": "https://trello.com/c/a"},
            {"id": "attach-a"},  # attachment for a
            {"id": "card-b", "shortUrl": "https://trello.com/c/b"},
            {"id": "attach-b"},  # attachment for b
        ]
        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="parent-1", items=["a", "b"]))
        assert len(result["children"]) == 2
        assert result["children"][0]["card_id"] == "card-a"
        assert result["children"][1]["card_id"] == "card-b"
        assert not result["failures"]

    def test_handles_partial_failures(
        self,
        mock_trello_client: MagicMock,
        mocker: MagicMock,
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [
            {"id": "list-1", "name": "proj-tasks"},
        ]
        mock_trello_client.post.side_effect = [
            {"id": "card-a", "shortUrl": "https://trello.com/c/a"},
            {"id": "attach-a"},
            Exception("API error"),
        ]
        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="parent-1", items=["a", "b"]))
        assert len(result["children"]) == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["name"] == "b"


# -- trello_verify_card_hook --------------------------------------------------


class TestVerifyCardHook:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        from server.tools.hooks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["trello_verify_card_hook"].fn

    def test_no_card_id_returns_unverified(self) -> None:
        tool = self._get_tool()
        result = json.loads(tool(card_id=""))
        assert result["verified"] is False
        assert "No card_id" in result["error"]

    def test_card_found_returns_verified(
        self,
        mock_trello_client: MagicMock,
        mocker: MagicMock,
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"done": "Done"},
            },
        )
        mock_trello_client.get.side_effect = [
            {"id": "card-1", "name": "Task", "idList": "done-list", "closed": False},
            [{"id": "done-list", "name": "Done"}],  # board lists
        ]
        tool = self._get_tool()
        result = json.loads(tool(card_id="card-1"))
        assert result["verified"] is True
        assert result["card_id"] == "card-1"
        assert result["in_done_list"] is True


# -- Hook structure tests for card-based hooks ---------------------------------


class TestCardBasedHookStructure:
    def _load_hooks(self) -> list[dict]:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        return data["hooks"]

    def test_todo_add_hook_targets_card_creation(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-add"]
        assert hook["trigger_tool"] == "todo_add"
        assert hook["target_tool"] == "trello_add_todo_card_hook"
        assert hook["server"] == "trello"
        assert hook["blocking"] is True
        assert "sync.trello.enabled" in hook["condition"]
        assert hook["feedback_mapping"]["card_id"] == "trello_card_id"

    def test_todo_complete_hook_moves_card_to_done(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-complete"]
        assert hook["target_tool"] == "move_card"
        assert hook["param_mapping"]["list_id"] == "${sync.trello.list_mappings.done}"

    def test_todo_uncomplete_hook_moves_card_to_tasks(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-uncomplete"]
        assert hook["trigger_tool"] == "todo_uncomplete"
        assert hook["target_tool"] == "move_card"
        assert hook["param_mapping"]["list_id"] == "${sync.trello.list_mappings.tasks}"

    def test_todo_delete_hook_archives_card(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-delete"]
        assert hook["target_tool"] == "archive_card"
        assert hook["param_mapping"]["card_id"] == "${trello_card_id}"

    def test_todo_update_hook_updates_card_details(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-update"]
        assert hook["target_tool"] == "update_card_details"
        assert "name" in hook["param_mapping"]
        assert "desc" in hook["param_mapping"]

    def test_batch_add_children_hook_targets_batch_cards(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-batch-add-children"]
        assert hook["trigger_tool"] == "todo_batch_add_children"
        assert hook["target_tool"] == "trello_batch_add_child_cards_hook"
        assert hook["server"] == "trello"
        assert hook["blocking"] is True

    def test_add_child_hook_targets_child_card(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-add-child"]
        assert hook["trigger_tool"] == "todo_add_child"
        assert hook["target_tool"] == "trello_add_child_card_hook"
        assert hook["param_mapping"]["parent_card_id"] == "${parent_trello_card_id}"

    def test_proj_archive_hook_structure(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-proj-archive"]
        assert hook["trigger_tool"] == "proj_archive"
        assert hook["target_tool"] == "move_card"
        assert hook["server"] == "trello"
        assert hook["blocking"] is False
        assert "sync.trello.list_mappings.archived" in hook["condition"]

    def test_no_checklist_hooks_remain(self) -> None:
        """Verify no hooks reference checklist-based tools."""
        hooks = self._load_hooks()
        checklist_tools = {
            "add_checklist_item",
            "update_checklist_item",
            "rename_checklist_item",
            "delete_checklist_item",
            "delete_checklist",
            "trello_add_checklist_item_hook",
            "trello_batch_add_checklist_items_hook",
        }
        for hook in hooks:
            assert hook["target_tool"] not in checklist_tools, (
                f"Hook {hook['id']} still targets checklist tool {hook['target_tool']}"
            )

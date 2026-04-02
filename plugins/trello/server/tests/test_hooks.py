"""Tests for default-hooks.yaml structure and hook tool behaviour."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import yaml

_HOOKS_PATH = (
    Path(__file__).parent.parent.parent
    / ".claude-plugin"
    / "default-hooks.yaml"
)

_REQUIRED_FIELDS = {"id", "trigger_tool", "target_tool", "server", "param_mapping", "condition"}


class TestDefaultHooksYaml:
    def test_file_exists(self) -> None:
        assert _HOOKS_PATH.exists(), f"Missing {_HOOKS_PATH}"

    def test_loads_valid_yaml(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "hooks" in data

    def test_has_11_hooks(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        assert len(data["hooks"]) == 11

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
            "verify-trello-checklist-item",
            "trello-on-todo-update",
            "trello-on-todo-delete",
            "trello-on-todo-add-child",
            "trello-on-todo-batch-add-children",
        }
        assert ids == expected


# -- trello_batch_add_checklist_items_hook ------------------------------------


class TestBatchAddChecklistItemsHook:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP
        from server.tools.hooks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["trello_batch_add_checklist_items_hook"].fn

    def test_null_checklist_id_returns_warning(self) -> None:
        tool = self._get_tool()
        result = json.loads(tool(checklist_id=None, items=["a", "b"]))
        assert "warning" in result
        assert "trello_checklist_id is null" in result["warning"]

    def test_success_calls_batch_create(self, mock_trello_client: MagicMock) -> None:
        mock_trello_client.post.side_effect = [
            {"id": "item-1", "name": "a", "state": "incomplete"},
            {"id": "item-2", "name": "b", "state": "incomplete"},
        ]
        tool = self._get_tool()
        result = json.loads(tool(checklist_id="cl-abc", items=["a", "b"]))
        assert len(result["successes"]) == 2
        assert result["successes"][0]["id"] == "item-1"
        assert mock_trello_client.post.call_count == 2


# -- Hook structure tests for new hooks --------------------------------------


class TestNewHookStructure:
    def _load_hooks(self) -> list[dict]:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        return data["hooks"]

    def test_batch_add_children_hook_structure(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-batch-add-children"]
        assert hook["trigger_tool"] == "todo_batch_add_children"
        assert hook["target_tool"] == "trello_batch_add_checklist_items_hook"
        assert hook["server"] == "trello"
        assert hook["blocking"] is True
        assert "sync.trello.enabled" in hook["condition"]

    def test_proj_archive_hook_structure(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-proj-archive"]
        assert hook["trigger_tool"] == "proj_archive"
        assert hook["target_tool"] == "move_card"
        assert hook["server"] == "trello"
        assert hook["blocking"] is False
        assert "sync.trello.list_mappings.archived" in hook["condition"]

    def test_todo_uncomplete_hook_structure(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-uncomplete"]
        assert hook["trigger_tool"] == "todo_uncomplete"
        assert hook["target_tool"] == "update_checklist_item"
        assert hook["server"] == "trello"
        assert hook["blocking"] is True
        assert hook["param_mapping"]["state"] == "incomplete"

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

    def test_has_8_hooks(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        assert len(data["hooks"]) == 8

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
            "trello-on-todo-add",
            "trello-on-todo-complete",
            "verify-trello-checklist-item",
            "trello-on-todo-update",
            "trello-on-todo-delete",
            "trello-on-todo-add-child",
        }
        assert ids == expected


# -- trello_add_checklist_item_hook ------------------------------------------


class TestAddChecklistItemHook:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP
        from server.tools.hooks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["trello_add_checklist_item_hook"].fn

    def test_warning_when_checklist_id_is_none(self) -> None:
        tool = self._get_tool()
        result = json.loads(tool(checklist_id=None, name="Child todo"))
        assert "warning" in result
        assert "parent_trello_checklist_id is null" in result["warning"]

    def test_warning_when_checklist_id_is_empty_string(self) -> None:
        tool = self._get_tool()
        result = json.loads(tool(checklist_id="", name="Child todo"))
        assert "warning" in result

    def test_success_creates_checklist_item(self, mock_trello_client: MagicMock) -> None:
        mock_trello_client.post.return_value = {"id": "item-123", "name": "Child todo", "state": "incomplete"}
        tool = self._get_tool()
        result = json.loads(tool(checklist_id="cl-abc", name="Child todo"))
        assert result["id"] == "item-123"
        mock_trello_client.post.assert_called_once_with(
            "/checklists/cl-abc/checkItems", params={"name": "Child todo"}
        )

    def test_api_error_returns_error(self, mock_trello_client: MagicMock) -> None:
        mock_trello_client.post.side_effect = RuntimeError("Trello API error")
        tool = self._get_tool()
        result = json.loads(tool(checklist_id="cl-abc", name="Child todo"))
        assert "error" in result
        assert "Trello API error" in result["error"]

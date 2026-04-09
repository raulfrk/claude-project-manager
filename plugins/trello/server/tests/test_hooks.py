"""Tests for default-hooks.yaml structure after migration to direct tool mapping."""

from __future__ import annotations

from pathlib import Path

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
            "verify-trello-todo-card",
            "trello-on-todo-update",
            "trello-on-todo-delete",
            "trello-on-todo-add-child",
            "trello-on-todo-batch-add-children",
        }
        assert ids == expected


# -- Direct tool mapping validation -------------------------------------------


class TestDirectToolMapping:
    """Verify all hooks now target real Trello tools (not wrapper hooks)."""

    def _load_hooks(self) -> list[dict]:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        return data["hooks"]

    def test_no_wrapper_tools_referenced(self) -> None:
        """Ensure no hooks reference the deleted wrapper tools."""
        wrapper_tools = {
            "trello_add_card_hook",
            "trello_add_todo_card_hook",
            "trello_add_child_card_hook",
            "trello_batch_add_child_cards_hook",
            "trello_verify_card_hook",
        }
        hooks = self._load_hooks()
        for hook in hooks:
            assert hook["target_tool"] not in wrapper_tools, (
                f"Hook {hook['id']} still targets wrapper tool {hook['target_tool']}"
            )

    def test_proj_init_uses_add_card_to_list(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-proj-init"]
        assert hook["target_tool"] == "add_card_to_list"
        assert hook["param_mapping"]["list_id"] == "${sync.trello.default_list_id}"
        assert hook["param_mapping"]["name"] == "${project_name}"
        assert hook["blocking"] is True
        assert hook["feedback_mapping"]["id"] == "trello_card_id"

    def test_todo_add_uses_add_card_to_list(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-add"]
        assert hook["target_tool"] == "add_card_to_list"
        assert hook["param_mapping"]["list_id"] == "${trello_list_id}"
        assert hook["param_mapping"]["name"] == "${title}"
        assert hook["param_mapping"]["desc"] == "${notes}"
        assert hook["param_mapping"]["due"] == "${due_date}"
        assert hook["feedback_mapping"]["id"] == "trello_card_id"

    def test_todo_complete_uses_move_card(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-complete"]
        assert hook["target_tool"] == "move_card"
        assert hook["param_mapping"]["list_id"] == "${trello_done_list_id}"
        assert hook["param_mapping"]["card_id"] == "${trello_card_id}"

    def test_todo_uncomplete_uses_move_card(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-uncomplete"]
        assert hook["target_tool"] == "move_card"
        assert hook["param_mapping"]["list_id"] == "${trello_list_id}"

    def test_verify_uses_get_card(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["verify-trello-todo-card"]
        assert hook["target_tool"] == "get_card"
        assert hook["param_mapping"]["card_id"] == "${trello_card_id}"
        assert hook["verification"] is True

    def test_todo_add_child_uses_add_card_to_list(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-add-child"]
        assert hook["target_tool"] == "add_card_to_list"
        assert hook["param_mapping"]["list_id"] == "${trello_list_id}"
        assert hook["param_mapping"]["name"] == "${title}"
        assert hook["feedback_mapping"]["id"] == "trello_card_id"

    def test_batch_add_children_uses_batch_create_cards(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-batch-add-children"]
        assert hook["target_tool"] == "batch_create_cards"
        assert hook["param_mapping"]["cards"] == "${trello_batch_cards}"
        assert hook["feedback_mapping"]["successes[*].id"] == "trello_card_id"

    def test_todo_update_uses_update_card_details(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-update"]
        assert hook["target_tool"] == "update_card_details"
        assert "name" in hook["param_mapping"]
        assert "desc" in hook["param_mapping"]

    def test_todo_delete_uses_archive_card(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-delete"]
        assert hook["target_tool"] == "archive_card"
        assert hook["param_mapping"]["card_id"] == "${trello_card_id}"

    def test_proj_archive_uses_move_card(self) -> None:
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-proj-archive"]
        assert hook["target_tool"] == "move_card"
        assert hook["blocking"] is False

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

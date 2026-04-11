"""Tests for default-hooks.yaml: parse, validate structure, check all 7 hooks."""

from __future__ import annotations

from pathlib import Path

import yaml

_HOOKS_PATH = Path(__file__).parent.parent.parent / ".claude-plugin" / "default-hooks.yaml"

_REQUIRED_FIELDS = {
    "id",
    "trigger_tool",
    "target_tool",
    "server",
    "param_mapping",
    "blocking",
    "condition",
}


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

    def test_all_hooks_target_expected_server(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        cross_server = {"jira-full-sync-on-proj-load": "proj"}
        for hook in data["hooks"]:
            expected = cross_server.get(hook["id"], "jira")
            assert hook["server"] == expected, (
                f"Hook {hook['id']} server is {hook['server']}, expected '{expected}'"
            )

    def test_param_mapping_is_dict(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        for hook in data["hooks"]:
            assert isinstance(hook["param_mapping"], (dict, str)), (
                f"Hook {hook['id']} param_mapping is not a dict or str"
            )

    def test_expected_hook_ids(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        ids = {h["id"] for h in data["hooks"]}
        expected = {
            "jira-on-todo-add",
            "jira-on-todo-complete",
            "jira-on-todo-update",
            "jira-on-todo-delete",
            "jira-on-proj-init",
            "jira-on-proj-load",
            "jira-full-sync-on-proj-load",
            "jira-on-todo-batch-complete",
        }
        assert ids == expected

    def test_feedback_hooks_have_mapping(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        for hook in data["hooks"]:
            if "feedback_tool" in hook:
                assert "feedback_mapping" in hook, (
                    f"Hook {hook['id']} has feedback_tool but no feedback_mapping"
                )
                assert isinstance(hook["feedback_mapping"], dict), (
                    f"Hook {hook['id']} feedback_mapping is not a dict"
                )

    def test_full_sync_on_proj_load_hook(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        hooks_by_id = {h["id"]: h for h in data["hooks"]}
        hook = hooks_by_id["jira-full-sync-on-proj-load"]
        assert hook["trigger_tool"] == "proj_load_session"
        assert hook["target_tool"] == "proj_jira_full_sync"
        assert hook["server"] == "proj"
        assert hook["blocking"] is True
        assert "sync.jira.enabled" in hook["condition"]
        assert "sync.jira.auto_sync" in hook["condition"]
        assert "project.jira_issue_key" in hook["condition"]

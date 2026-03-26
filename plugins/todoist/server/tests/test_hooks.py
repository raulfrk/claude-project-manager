"""Tests for default-hooks.yaml: parse, validate structure, check all 7 hooks."""

from __future__ import annotations

from pathlib import Path

import yaml

_HOOKS_PATH = (
    Path(__file__).parent.parent.parent
    / ".claude-plugin"
    / "default-hooks.yaml"
)

_REQUIRED_FIELDS = {"id", "trigger_tool", "target_tool", "server", "param_mapping", "blocking", "condition"}


class TestDefaultHooksYaml:
    def test_file_exists(self) -> None:
        assert _HOOKS_PATH.exists(), f"Missing {_HOOKS_PATH}"

    def test_loads_valid_yaml(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "hooks" in data

    def test_has_7_hooks(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        assert len(data["hooks"]) == 7

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

    def test_all_hooks_target_todoist_server(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        for hook in data["hooks"]:
            assert hook["server"] == "todoist", (
                f"Hook {hook['id']} server is {hook['server']}, expected 'todoist'"
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
            "todoist-on-todo-add",
            "todoist-on-todo-complete",
            "todoist-on-todo-update",
            "todoist-on-todo-delete",
            "todoist-on-proj-init",
            "todoist-on-proj-load",
            "todoist-on-proj-archive",
        }
        assert ids == expected

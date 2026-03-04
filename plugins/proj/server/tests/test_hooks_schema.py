"""Validate hooks/hooks.json conforms to Claude Code's required schema.

Claude Code requires a two-level nesting for hooks:
  EventName → [{ "matcher": "...", "hooks": [{ "type": "command", ... }] }]

The flat structure (hook properties directly on the event array element) is rejected
with: "expected array, received undefined" at hooks.<Event>[0].hooks
"""

from __future__ import annotations

import json
from pathlib import Path


HOOKS_FILE = Path(__file__).parents[2] / "hooks" / "hooks.json"
PLUGIN_JSON = Path(__file__).parents[2] / ".claude-plugin" / "plugin.json"
STANDARD_HOOKS_PATH = "./hooks/hooks.json"

REQUIRED_EVENTS = ["SessionStart", "SessionEnd", "PreCompact"]


def _load_hooks() -> dict[str, object]:
    assert HOOKS_FILE.exists(), f"hooks.json not found at {HOOKS_FILE}"
    with HOOKS_FILE.open() as f:
        return json.load(f)  # type: ignore[return-value]


def test_hooks_file_is_valid_json() -> None:
    data = _load_hooks()
    assert isinstance(data, dict)


def test_hooks_top_level_key_exists() -> None:
    data = _load_hooks()
    assert "hooks" in data, "hooks.json must have a top-level 'hooks' key"
    assert isinstance(data["hooks"], dict)


def test_required_events_present() -> None:
    data = _load_hooks()
    hooks = data["hooks"]
    assert isinstance(hooks, dict)
    for event in REQUIRED_EVENTS:
        assert event in hooks, f"Missing required event: {event}"


def test_each_event_is_array_of_matcher_groups() -> None:
    """Each event must be an array of matcher group objects."""
    data = _load_hooks()
    hooks = data["hooks"]
    assert isinstance(hooks, dict)
    for event, groups in hooks.items():
        assert isinstance(groups, list), f"{event} must be an array"
        assert len(groups) > 0, f"{event} must have at least one matcher group"


def test_each_matcher_group_has_hooks_array() -> None:
    """The critical schema check: each group must have a 'hooks' sub-array.

    This is what Claude Code validates. The flat structure
    [{"type": "command", "command": "..."}] fails because 'hooks' is missing.
    """
    data = _load_hooks()
    hooks = data["hooks"]
    assert isinstance(hooks, dict)
    for event, groups in hooks.items():
        assert isinstance(groups, list)
        for i, group in enumerate(groups):
            assert isinstance(group, dict), f"{event}[{i}] must be an object"
            assert "hooks" in group, (
                f"{event}[{i}] is missing the required 'hooks' sub-array. "
                f"Claude Code rejects the flat structure — hook commands must be "
                f"nested inside a 'hooks' array within each matcher group."
            )
            assert isinstance(group["hooks"], list), (
                f"{event}[{i}].hooks must be an array"
            )
            assert len(group["hooks"]) > 0, (
                f"{event}[{i}].hooks must contain at least one hook"
            )


def test_each_hook_has_required_fields() -> None:
    """Each hook in the inner 'hooks' array must have 'type' and 'command'."""
    data = _load_hooks()
    hooks = data["hooks"]
    assert isinstance(hooks, dict)
    for event, groups in hooks.items():
        assert isinstance(groups, list)
        for i, group in enumerate(groups):
            assert isinstance(group, dict)
            inner = group.get("hooks", [])
            assert isinstance(inner, list)
            for j, hook in enumerate(inner):
                assert isinstance(hook, dict), f"{event}[{i}].hooks[{j}] must be an object"
                assert "type" in hook, f"{event}[{i}].hooks[{j}] missing 'type'"
                if hook["type"] == "command":
                    assert "command" in hook, (
                        f"{event}[{i}].hooks[{j}] command hook missing 'command'"
                    )


def test_plugin_json_does_not_reference_standard_hooks_path() -> None:
    """Regression test: plugin.json must NOT have "hooks": "./hooks/hooks.json".

    Claude Code auto-discovers hooks/hooks.json. Explicitly referencing it causes:
    "Duplicate hooks file detected: ./hooks/hooks.json resolves to already-loaded file"

    The "hooks" key in plugin.json is only for ADDITIONAL hook files beyond
    the standard auto-loaded hooks/hooks.json.
    """
    assert PLUGIN_JSON.exists(), f"plugin.json not found at {PLUGIN_JSON}"
    with PLUGIN_JSON.open() as f:
        manifest = json.load(f)

    hooks_ref = manifest.get("hooks")
    assert hooks_ref != STANDARD_HOOKS_PATH, (
        f'plugin.json must NOT contain "hooks": "{STANDARD_HOOKS_PATH}". '
        f"Claude Code auto-discovers hooks/hooks.json — referencing it explicitly "
        f"causes a duplicate hooks file error. Remove the 'hooks' key from plugin.json "
        f"or point it to a different (additional) hooks file."
    )


def test_matcher_is_string_if_present() -> None:
    data = _load_hooks()
    hooks = data["hooks"]
    assert isinstance(hooks, dict)
    for event, groups in hooks.items():
        assert isinstance(groups, list)
        for i, group in enumerate(groups):
            assert isinstance(group, dict)
            if "matcher" in group:
                assert isinstance(group["matcher"], str), (
                    f"{event}[{i}].matcher must be a string"
                )

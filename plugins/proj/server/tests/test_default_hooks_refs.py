# plugins/proj/server/tests/test_default_hooks_refs.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# adjust path-parents count if the layout differs when running from repo root:
# this file lives at plugins/proj/server/tests/ — 4 parents up is the repo root
REPO_ROOT = Path(__file__).resolve().parents[4]

JIRA_HOOKS = REPO_ROOT / "plugins" / "jira" / ".claude-plugin" / "default-hooks.yaml"
TODOIST_HOOKS = REPO_ROOT / "plugins" / "todoist" / ".claude-plugin" / "default-hooks.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _hook(hooks_doc: dict, hook_id: str) -> dict:
    for h in hooks_doc.get("hooks", []):
        if h.get("id") == hook_id:
            return h
    pytest.fail(f"hook {hook_id} not found in {hooks_doc.get('hooks', [])}")


def test_todoist_on_todo_add_labels_uses_synced_tags():
    hook = _hook(_load(TODOIST_HOOKS), "todoist-on-todo-add")
    # The Todoist hook maps over a list of tasks; labels is inside each task entry.
    tasks = hook["param_mapping"]["tasks"]
    assert isinstance(tasks, list)
    assert tasks[0]["labels"] == "${synced_tags}"


def test_jira_on_todo_add_labels_uses_synced_tags():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-add")
    assert hook["param_mapping"]["labels"] == "${synced_tags}"


def test_jira_on_todo_add_parent_key_references_parent_jira_issue_key():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-add")
    pk = hook["param_mapping"]["parent_key"]
    assert isinstance(pk, dict)
    assert pk["value"] == "${parent_jira_issue_key}"
    assert pk["omit_if_empty"] is True


def test_jira_on_todo_add_condition_unchanged():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-add")
    assert "sync.jira.enabled" in hook["condition"]
    assert "sync.jira.auto_sync" in hook["condition"]
    assert "project.jira_issue_key" in hook["condition"]

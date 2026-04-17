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
PROJ_HOOKS = REPO_ROOT / "plugins" / "proj" / ".claude-plugin" / "default-hooks.yaml"


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
    # Exact equality guards against any mutation (incl. `and` → `or`).
    assert hook["condition"] == (
        "sync.jira.enabled and sync.jira.auto_sync and project.jira_issue_key"
    )


def test_todoist_on_todo_add_parent_id_has_omit_if_empty():
    hook = _hook(_load(TODOIST_HOOKS), "todoist-on-todo-add")
    parent_id = hook["param_mapping"]["tasks"][0]["parentId"]
    assert isinstance(parent_id, dict)
    assert parent_id["value"] == "${parent_todoist_task_id}"
    assert parent_id["omit_if_empty"] is True


def test_proj_sandbox_hooks_migrated_to_proj_server():
    """Regression for todo 650: sandbox hooks folded from the old sandbox plugin
    (commit 0608506, feat(605.8)) must live in proj's default-hooks.yaml with
    ``server: proj``.  Stale entries in a user's hooks.yaml pointing at the
    removed ``server: sandbox`` cause ``sandbox_batch_setup`` to be routed to
    zombie socket processes whose working directory has been deleted, which
    surfaces as ``[Errno 2] No such file or directory`` during any
    ``proj_load_session`` call.
    """
    doc = _load(PROJ_HOOKS)
    expected_ids = {
        "sandbox-on-setup-permissions",
        "sandbox-on-revoke-permissions",
        "verify-sandbox-setup",
        "sandbox-on-proj-add-repo",
        "sandbox-on-proj-remove-repo",
    }
    present_ids = {h.get("id") for h in doc.get("hooks", [])}
    missing = expected_ids - present_ids
    assert not missing, f"missing migrated sandbox hooks: {missing}"

    for hook_id in expected_ids:
        hook = _hook(doc, hook_id)
        assert hook["server"] == "proj", (
            f"{hook_id}: server must be 'proj' (was '{hook['server']}') — "
            f"the old 'sandbox' server was removed in commit 0608506."
        )
        assert hook["condition"] == "sandbox_integration", (
            f"{hook_id}: condition must be 'sandbox_integration'."
        )


def test_proj_default_hooks_have_no_sandbox_server_references():
    """Regression for todo 650: no hook in proj's default-hooks.yaml may
    reference the (removed) ``sandbox`` server.  This keeps the router's
    orphan-detection pass able to drop any stale ``server: sandbox`` hooks
    that survived the 605.8 fold.
    """
    doc = _load(PROJ_HOOKS)
    offenders = [h["id"] for h in doc.get("hooks", []) if h.get("server") == "sandbox"]
    assert not offenders, f"hooks still referencing removed 'sandbox' server: {offenders}"


def test_jira_on_todo_update_labels_uses_synced_tags():
    # Raw JSON-string template form — `${synced_tags}` resolves via `resolve_template`
    # against the hook source dict (which always includes `synced_tags`).
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-update")
    updates_json = hook["param_mapping"]["updates_json"]
    assert isinstance(updates_json, str)
    assert "${synced_tags}" in updates_json
    assert "${tags}" not in updates_json


def test_todoist_on_todo_update_labels_uses_synced_tags():
    hook = _hook(_load(TODOIST_HOOKS), "todoist-on-todo-update")
    tasks = hook["param_mapping"]["tasks"]
    assert isinstance(tasks, list)
    assert tasks[0]["labels"] == "${synced_tags}"


def test_jira_on_todo_add_param_mapping_keyset_complete():
    # Guard against accidental field removal — asserts the full expected keyset.
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-add")
    assert set(hook["param_mapping"].keys()) == {
        "project_key",
        "summary",
        "description",
        "priority",
        "labels",
        "parent_key",
    }

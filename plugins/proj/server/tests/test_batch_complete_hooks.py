"""Wiring tests for todo_complete integration hooks (518.9).

These tests validate that the three plugin default-hooks.yaml files
declare the expected `todo_complete` trigger and map params
against the Phase 3 pre-enriched source payload. The full dispatch
cascade is exercised by end-to-end integration tests against a running
hooks server — these tests assert the static contract only.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_hooks(plugin: str) -> list[dict]:
    path = REPO_ROOT / "plugins" / plugin / ".claude-plugin" / "default-hooks.yaml"
    data = yaml.safe_load(path.read_text())
    hooks = data.get("hooks") or []
    return [h for h in hooks if isinstance(h, dict)]


def test_dispatches_to_todoist() -> None:
    """todoist default-hooks.yaml has a hook mapping todo_complete
    → todoist_complete_tasks with ids=${todoist_task_ids}."""
    hooks = _load_hooks("todoist")
    match = [
        h
        for h in hooks
        if h.get("trigger_tool") == "todo_complete"
        and h.get("target_tool") == "todoist_complete_tasks"
    ]
    assert len(match) == 1, (
        "expected exactly one todo_complete→todoist_complete_tasks hook in todoist"
    )
    hook = match[0]
    assert hook["server"] == "todoist"
    # Blocking so the dispatch wrapper waits for the aggregated result.
    assert hook.get("blocking") is True
    # Condition gates the hook on sync flags.
    assert "sync.todoist" in hook["condition"]
    # Param mapping pulls the plural list from the Phase 3 payload.
    pm = hook["param_mapping"]
    assert pm == {"ids": "${todoist_task_ids}"}


def test_dispatches_to_trello() -> None:
    """trello default-hooks.yaml has a hook mapping todo_complete
    → trello_batch_archive_cards with card_ids=${trello_card_ids}."""
    hooks = _load_hooks("trello")
    match = [
        h
        for h in hooks
        if h.get("trigger_tool") == "todo_complete"
        and h.get("target_tool") == "trello_batch_archive_cards"
    ]
    assert len(match) == 1, (
        "expected exactly one todo_complete→trello_batch_archive_cards hook in trello"
    )
    hook = match[0]
    assert hook["server"] == "trello"
    assert hook.get("blocking") is True
    assert "sync.trello" in hook["condition"]
    pm = hook["param_mapping"]
    assert pm == {"card_ids": "${trello_card_ids}"}


def test_dispatches_to_jira_with_updates_json() -> None:
    """jira default-hooks.yaml has a hook mapping todo_complete
    → jira_update_issues with updates_json=${jira_updates_json}.
    The pre-built JSON blob comes from Phase 3 enrichment so the hook
    template engine (which cannot iterate lists) can pass it verbatim."""
    hooks = _load_hooks("jira")
    match = [
        h
        for h in hooks
        if h.get("trigger_tool") == "todo_complete"
        and h.get("target_tool") == "jira_update_issues"
        and h.get("param_mapping", {}) == {"updates_json": "${jira_updates_json}"}
    ]
    assert len(match) == 1, (
        "expected exactly one todo_complete→jira_update_issues (batch) hook in jira"
    )
    hook = match[0]
    assert hook["server"] == "jira"
    assert hook.get("blocking") is True
    assert "sync.jira" in hook["condition"]
    pm = hook["param_mapping"]
    assert pm == {"updates_json": "${jira_updates_json}"}


def test_token_scrubbing() -> None:
    """scrub_secrets redacts common bearer-token patterns from error strings
    so batch-hook errors can never leak credentials through _hooks.errors
    or _hooks.structured_errors."""
    import sys

    shared = REPO_ROOT / "plugins" / "_shared"
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    from scrubbing import build_structured_error, scrub_secrets  # type: ignore[import-not-found]

    # Raw bearer token in error message.
    msg = "Authorization: Bearer sk_live_51Hxxxxxxxxxxxx1234 failed"
    scrubbed = scrub_secrets(msg)
    assert "sk_live_51Hxxxxxxxxxxxx1234" not in scrubbed
    assert "1234" in scrubbed  # last4 retained
    assert "****" in scrubbed

    # api_token assignment.
    msg2 = 'api_token="abcdefghijklmnop5678" rejected'
    scrubbed2 = scrub_secrets(msg2)
    assert "abcdefghijklmnop5678" not in scrubbed2
    assert "5678" in scrubbed2

    # Nested dict walk.
    obj = {
        "error": "connection failed",
        "detail": {"header": "Authorization: Bearer topsecret123456"},
    }
    cleaned = scrub_secrets(obj)
    assert cleaned["error"] == "connection failed"
    assert "topsecret123456" not in cleaned["detail"]["header"]

    # build_structured_error returns a scrubbed message field.
    err = build_structured_error(
        integration="todoist",
        failed_ids=["t1", "t2"],
        exc=RuntimeError("GET https://api/v1/tasks?token=supersecretvalue failed"),
        target_tool="todoist_complete_tasks",
    )
    assert err["integration"] == "todoist"
    assert err["failed_ids"] == ["t1", "t2"]
    assert err["target_tool"] == "todoist_complete_tasks"
    assert "supersecretvalue" not in err["message"]

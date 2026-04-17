# Jira Structured Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw-JSON-string `updates_json` templates in 4 jira hooks with structured `param_mapping` via two new wrapper tools.

**Architecture:** Extract `_update_issues_core(updates_json: str)` from existing `jira_update_issues`; add `jira_update_issue_fields` (single) and `jira_update_issues_bulk` (batch) wrapper tools that build JSON internally. Rewrite 4 hook yamls to use structured params. Add `jira_batch_updates: list[dict]` output field to `todo_batch_complete`.

**Tech Stack:** Python 3.12, FastMCP, pytest, ruff, basedpyright, YAML hooks. Repo: `/home/raul/worktrees/cpm/feat-655-jira-structured-hooks` (branch: `feat/655-jira-structured-hooks`).

**Spec:** `docs/superpowers/specs/2026-04-17-jira-structured-hooks-design.md`

---

## File Structure

**Create:**
- `plugins/jira/server/tests/test_update_issue_fields.py` — wrapper unit tests (single)
- `plugins/jira/server/tests/test_update_issues_bulk.py` — wrapper unit tests (bulk)

**Modify:**
- `plugins/jira/server/server/tools/issues.py` — extract `_update_issues_core`; add `_build_updates_json` helper + `FIELD_MAP`; add `jira_update_issue_fields` + `jira_update_issues_bulk` tools
- `plugins/jira/.claude-plugin/default-hooks.yaml` — rewrite 4 hooks to structured param_mapping
- `plugins/proj/server/server/tools/todos.py` — add `jira_batch_updates: list[dict]` to `todo_batch_complete` output; extend 90KB truncation logic to include it
- `plugins/proj/server/tests/test_default_hooks_refs.py` — update + add tests for structured form
- `plugins/proj/server/tests/test_batch_complete_hooks.py` — update hook assertion to structured shape
- `plugins/proj/server/tests/test_todos_batch_complete.py` — assert `jira_batch_updates` field present
- `plugins/jira/plugin.json` + `plugins/jira/.claude-plugin/marketplace.json` — version bump
- `plugins/proj/plugin.json` + `plugins/proj/.claude-plugin/marketplace.json` — version bump

**Test:**
- Run from repo root: `just test-jira` and `just test-proj` (or direct `pytest plugins/<name>/server/tests/`)

---

## Task 1: Extract `_update_issues_core` from `jira_update_issues`

Pure refactor — no behavior change. Existing tests stay green.

**Files:**
- Modify: `plugins/jira/server/server/tools/issues.py:266-304`

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `pytest plugins/jira/server/tests/test_issues.py::TestJiraUpdateIssues -v`
Expected: all pass.

- [ ] **Step 2: Add `_update_issues_core` at module level**

In `plugins/jira/server/server/tools/issues.py`, add after the `_get_done_statuses` function (around line 50, before `def register`):

```python
def _update_issues_core(updates_json: str) -> str:
    """Shared core for jira update tools. Loops PUT /rest/api/2/issue/{key}.
    Strips null-valued fields from each update. Returns JSON-encoded
    {successes: [...], failures: [...]}.
    """
    client = get_client()
    try:
        payload = json.loads(updates_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON: {exc}"})

    updates = payload.get("updates", [])
    if not updates:
        return json.dumps({"error": "Missing or empty 'updates' array in payload"})

    successes: list[dict[str, JsonValue]] = []
    failures: list[dict[str, JsonValue]] = []
    for idx, update in enumerate(updates):
        try:
            key = update.get("key", "")
            if not key:
                failures.append({"index": idx, "error": "Missing 'key' field"})
                continue
            raw_fields = update.get("fields", {})
            fields = {k: v for k, v in raw_fields.items() if v is not None}
            if not fields:
                failures.append({"index": idx, "key": key, "error": "No fields to update"})
                continue
            client.put(f"/rest/api/2/issue/{key}", json_body={"fields": fields})
            successes.append({"key": key, "status": "updated"})
        except RuntimeError as exc:
            failures.append({"index": idx, "key": update.get("key", ""), "error": str(exc)})
    return json.dumps({"successes": successes, "failures": failures})
```

- [ ] **Step 3: Rewrite `jira_update_issues` as thin delegate**

Replace the body of `jira_update_issues` (currently lines 274-304) with:

```python
    @app.tool(
        description=(
            "Update one or more Jira issues. updates_json is a JSON string with an 'updates' "
            "array. Each entry has 'key' (issue key, required) and 'fields' (dict of fields "
            "to update). Loops PUT /rest/api/2/issue/{key} for each entry. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def jira_update_issues(updates_json: str) -> str:
        return _update_issues_core(updates_json)
```

- [ ] **Step 4: Run existing tests — all still green**

Run: `pytest plugins/jira/server/tests/test_issues.py::TestJiraUpdateIssues plugins/jira/server/tests/test_contracts_issues.py plugins/jira/server/tests/test_issues_null_fields.py -v`
Expected: all pass unchanged.

- [ ] **Step 5: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-655-jira-structured-hooks
git add plugins/jira/server/server/tools/issues.py
git commit -m "refactor(jira): extract _update_issues_core from jira_update_issues (655)"
```

---

## Task 2: Add `FIELD_MAP` + `_build_updates_json` helper

Pure-function helper shared by both new wrappers. TDD.

**Files:**
- Create: none yet (adding to `issues.py`)
- Modify: `plugins/jira/server/server/tools/issues.py`
- Test: `plugins/jira/server/tests/test_update_issue_fields.py` (create)

- [ ] **Step 1: Create failing test file**

Create `plugins/jira/server/tests/test_update_issue_fields.py`:

```python
"""Tests for jira_update_issue_fields wrapper + shared helpers."""

from __future__ import annotations

import json

import pytest

from server.tools.issues import FIELD_MAP, _build_updates_json


class TestFieldMap:
    def test_summary_passthrough(self) -> None:
        assert FIELD_MAP["summary"]("Hello") == "Hello"

    def test_description_passthrough(self) -> None:
        assert FIELD_MAP["description"]("Body text") == "Body text"

    def test_priority_wrapped(self) -> None:
        assert FIELD_MAP["priority"]("High") == {"name": "High"}

    def test_labels_passthrough(self) -> None:
        assert FIELD_MAP["labels"](["a", "b"]) == ["a", "b"]

    def test_resolution_wrapped(self) -> None:
        assert FIELD_MAP["resolution"]("Done") == {"name": "Done"}


class TestBuildUpdatesJson:
    def test_single_item_all_fields(self) -> None:
        out = _build_updates_json([
            {
                "key": "PROJ-1",
                "summary": "S",
                "description": "D",
                "priority": "High",
                "labels": ["x"],
                "resolution": "Done",
            }
        ])
        parsed = json.loads(out)
        assert parsed == {
            "updates": [
                {
                    "key": "PROJ-1",
                    "fields": {
                        "summary": "S",
                        "description": "D",
                        "priority": {"name": "High"},
                        "labels": ["x"],
                        "resolution": {"name": "Done"},
                    },
                }
            ]
        }

    def test_none_fields_omitted(self) -> None:
        out = _build_updates_json([
            {"key": "PROJ-1", "summary": "S", "description": None, "priority": None}
        ])
        parsed = json.loads(out)
        assert parsed["updates"][0]["fields"] == {"summary": "S"}

    def test_multiple_items(self) -> None:
        out = _build_updates_json([
            {"key": "PROJ-1", "resolution": "Done"},
            {"key": "PROJ-2", "summary": "X"},
        ])
        parsed = json.loads(out)
        assert len(parsed["updates"]) == 2
        assert parsed["updates"][0]["fields"] == {"resolution": {"name": "Done"}}
        assert parsed["updates"][1]["fields"] == {"summary": "X"}

    def test_unknown_field_ignored(self) -> None:
        # Forward-compat: unknown keys are silently dropped rather than passed through.
        out = _build_updates_json([{"key": "PROJ-1", "summary": "S", "bogus": "x"}])
        parsed = json.loads(out)
        assert parsed["updates"][0]["fields"] == {"summary": "S"}

    def test_empty_list_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _build_updates_json([])

    def test_missing_key_raises(self) -> None:
        with pytest.raises(ValueError, match="key"):
            _build_updates_json([{"summary": "S"}])
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `pytest plugins/jira/server/tests/test_update_issue_fields.py -v`
Expected: FAIL with "ImportError: cannot import name 'FIELD_MAP'".

- [ ] **Step 3: Add `FIELD_MAP` + `_build_updates_json` to `issues.py`**

In `plugins/jira/server/server/tools/issues.py`, add after `_update_issues_core` (the function added in Task 1):

```python
FIELD_MAP: dict[str, object] = {
    "summary":     lambda v: v,
    "description": lambda v: v,
    "priority":    lambda v: {"name": v},
    "labels":      lambda v: v,
    "resolution":  lambda v: {"name": v},
}


def _build_updates_json(items: list[dict[str, object]]) -> str:
    """Build a Jira updates_json payload from a list of structured items.

    Each item must have a non-empty `key`. Optional fields are those in
    FIELD_MAP; None values are omitted. Unknown keys are ignored (forward
    compat). Raises ValueError on empty list or missing key.
    """
    if not items:
        raise ValueError("updates list is empty")
    built: list[dict[str, object]] = []
    for item in items:
        key = item.get("key", "")
        if not key:
            raise ValueError("each update requires a non-empty key")
        fields: dict[str, object] = {}
        for fname, transform in FIELD_MAP.items():
            val = item.get(fname)
            if val is None:
                continue
            fields[fname] = transform(val)  # type: ignore[operator]
        built.append({"key": key, "fields": fields})
    return json.dumps({"updates": built}, ensure_ascii=True)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest plugins/jira/server/tests/test_update_issue_fields.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/jira/server/server/tools/issues.py plugins/jira/server/tests/test_update_issue_fields.py
git commit -m "feat(jira): add FIELD_MAP + _build_updates_json helpers (655)"
```

---

## Task 3: Add `jira_update_issue_fields` tool

Single-issue structured wrapper. Warning when no fields to update.

**Files:**
- Modify: `plugins/jira/server/server/tools/issues.py`
- Test: `plugins/jira/server/tests/test_update_issue_fields.py`

- [ ] **Step 1: Append wrapper tests to test file**

Append to `plugins/jira/server/tests/test_update_issue_fields.py`:

```python
from unittest.mock import MagicMock

from mcp.server.fastmcp import FastMCP

from server.tools.issues import register


@pytest.fixture()
def issue_tools(mock_jira_client: MagicMock) -> dict:
    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraUpdateIssueFields:
    def test_all_fields(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issue_fields"](
            key="PROJ-1",
            summary="S",
            description="D",
            priority="High",
            labels=["bug"],
        )
        parsed = json.loads(result)
        assert parsed["successes"] == [{"key": "PROJ-1", "status": "updated"}]
        mock_jira_client.put.assert_called_once_with(
            "/rest/api/2/issue/PROJ-1",
            json_body={"fields": {
                "summary": "S", "description": "D",
                "priority": {"name": "High"}, "labels": ["bug"],
            }},
        )

    def test_only_resolution(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issue_fields"](key="PROJ-1", resolution="Done")
        parsed = json.loads(result)
        assert parsed["successes"] == [{"key": "PROJ-1", "status": "updated"}]
        mock_jira_client.put.assert_called_once_with(
            "/rest/api/2/issue/PROJ-1",
            json_body={"fields": {"resolution": {"name": "Done"}}},
        )

    def test_empty_key_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issue_fields"](key="", summary="S")
        parsed = json.loads(result)
        assert parsed == {"error": "key required", "key": ""}
        mock_jira_client.put.assert_not_called()

    def test_all_fields_none_returns_warning(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issue_fields"](key="PROJ-1")
        parsed = json.loads(result)
        assert parsed == {"warning": "no fields to update", "key": "PROJ-1"}
        mock_jira_client.put.assert_not_called()
```

- [ ] **Step 2: Run tests — expect failure (tool not registered)**

Run: `pytest plugins/jira/server/tests/test_update_issue_fields.py::TestJiraUpdateIssueFields -v`
Expected: FAIL with KeyError on `jira_update_issue_fields`.

- [ ] **Step 3: Register `jira_update_issue_fields` tool**

In `plugins/jira/server/server/tools/issues.py`, inside `def register(app: FastMCP)` (anywhere after the existing `jira_update_issues` tool), add:

```python
    @app.tool(
        description=(
            "Update a single Jira issue with structured fields. "
            "Any of summary/description/priority/labels/resolution may be supplied; "
            "None fields are omitted. Returns {successes: [...], failures: [...]} "
            "from jira_update_issues, or {error} if key is empty, or "
            "{warning} if no fields are supplied."
        ),
    )
    def jira_update_issue_fields(
        key: str,
        summary: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        resolution: str | None = None,
    ) -> str:
        if not key:
            return json.dumps({"error": "key required", "key": ""})
        item: dict[str, object] = {"key": key}
        if summary is not None:
            item["summary"] = summary
        if description is not None:
            item["description"] = description
        if priority is not None:
            item["priority"] = priority
        if labels is not None:
            item["labels"] = labels
        if resolution is not None:
            item["resolution"] = resolution
        if len(item) == 1:  # only 'key' present
            return json.dumps({"warning": "no fields to update", "key": key})
        return _update_issues_core(_build_updates_json([item]))
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest plugins/jira/server/tests/test_update_issue_fields.py -v`
Expected: all pass (helpers + 4 wrapper tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/jira/server/server/tools/issues.py plugins/jira/server/tests/test_update_issue_fields.py
git commit -m "feat(jira): add jira_update_issue_fields wrapper tool (655)"
```

---

## Task 4: Add `jira_update_issues_bulk` tool

Batch structured wrapper. Filter empty-fields items; warn if all filtered.

**Files:**
- Modify: `plugins/jira/server/server/tools/issues.py`
- Test: `plugins/jira/server/tests/test_update_issues_bulk.py` (create)

- [ ] **Step 1: Create failing test file**

Create `plugins/jira/server/tests/test_update_issues_bulk.py`:

```python
"""Tests for jira_update_issues_bulk wrapper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools.issues import register


@pytest.fixture()
def issue_tools(mock_jira_client: MagicMock) -> dict:
    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraUpdateIssuesBulk:
    def test_multi_item_updates(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issues_bulk"](
            updates=[
                {"key": "PROJ-1", "resolution": "Done"},
                {"key": "PROJ-2", "summary": "X", "priority": "High"},
            ]
        )
        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        calls = mock_jira_client.put.call_args_list
        assert calls[0] == (
            ("/rest/api/2/issue/PROJ-1",),
            {"json_body": {"fields": {"resolution": {"name": "Done"}}}},
        )
        assert calls[1] == (
            ("/rest/api/2/issue/PROJ-2",),
            {"json_body": {"fields": {"summary": "X", "priority": {"name": "High"}}}},
        )

    def test_empty_updates_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issues_bulk"](updates=[])
        parsed = json.loads(result)
        assert parsed == {"error": "updates list is empty"}
        mock_jira_client.put.assert_not_called()

    def test_missing_key_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issues_bulk"](
            updates=[{"key": "PROJ-1", "summary": "S"}, {"summary": "X"}]
        )
        parsed = json.loads(result)
        assert parsed == {"error": "each update requires a non-empty key"}
        mock_jira_client.put.assert_not_called()

    def test_all_items_no_fields_returns_warning(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issues_bulk"](
            updates=[{"key": "PROJ-1"}, {"key": "PROJ-2"}]
        )
        parsed = json.loads(result)
        assert parsed == {"warning": "no fields to update in any item", "count": 2}
        mock_jira_client.put.assert_not_called()

    def test_mixed_empty_and_filled_items(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issues_bulk"](
            updates=[
                {"key": "PROJ-1", "resolution": "Done"},
                {"key": "PROJ-2"},  # filtered
                {"key": "PROJ-3", "summary": "X"},
            ]
        )
        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert parsed["skipped_keys"] == ["PROJ-2"]
        assert mock_jira_client.put.call_count == 2
```

- [ ] **Step 2: Run tests — expect KeyError**

Run: `pytest plugins/jira/server/tests/test_update_issues_bulk.py -v`
Expected: FAIL with KeyError on `jira_update_issues_bulk`.

- [ ] **Step 3: Register `jira_update_issues_bulk` tool**

In `plugins/jira/server/server/tools/issues.py`, inside `def register(app: FastMCP)` (after the `jira_update_issue_fields` tool from Task 3), add:

```python
    @app.tool(
        description=(
            "Update multiple Jira issues with structured fields per item. "
            "`updates` is a list of dicts each having 'key' (required) and any of "
            "summary/description/priority/labels/resolution (None omitted). "
            "Items with only a key (no updatable fields) are filtered out and "
            "listed in 'skipped_keys'. Returns the jira_update_issues response shape "
            "plus 'skipped_keys' when applicable; or {error} for empty list / "
            "missing key; or {warning} if all items are empty."
        ),
    )
    def jira_update_issues_bulk(updates: list[dict]) -> str:
        if not updates:
            return json.dumps({"error": "updates list is empty"})
        for item in updates:
            if not item.get("key"):
                return json.dumps({"error": "each update requires a non-empty key"})

        # Split: items with at least one updatable field vs empty items.
        dispatchable: list[dict] = []
        skipped_keys: list[str] = []
        for item in updates:
            has_field = any(
                item.get(fname) is not None for fname in FIELD_MAP
            )
            if has_field:
                dispatchable.append(item)
            else:
                skipped_keys.append(item["key"])

        if not dispatchable:
            return json.dumps({
                "warning": "no fields to update in any item",
                "count": len(updates),
            })

        core_result = _update_issues_core(_build_updates_json(dispatchable))
        parsed = json.loads(core_result)
        if skipped_keys:
            parsed["skipped_keys"] = skipped_keys
        return json.dumps(parsed)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest plugins/jira/server/tests/test_update_issues_bulk.py -v`
Expected: all 5 pass.

- [ ] **Step 5: Run full jira test suite — confirm no regression**

Run: `pytest plugins/jira/server/tests/ -v`
Expected: all pass (existing + new).

- [ ] **Step 6: Commit**

```bash
git add plugins/jira/server/server/tools/issues.py plugins/jira/server/tests/test_update_issues_bulk.py
git commit -m "feat(jira): add jira_update_issues_bulk wrapper tool (655)"
```

---

## Task 5: Add `jira_batch_updates` field to `todo_batch_complete`

Emit structured list alongside existing `jira_updates_json` string. Extend 90KB truncation.

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py:1322-1378`
- Test: `plugins/proj/server/tests/test_todos_batch_complete.py`

- [ ] **Step 1: Add failing test for new field**

Append to `plugins/proj/server/tests/test_todos_batch_complete.py` (anywhere in the file; near existing `jira_updates_json` tests is ideal):

```python
def test_jira_batch_updates_field_present(tmp_path: Path) -> None:
    """todo_batch_complete emits jira_batch_updates: list[dict] alongside jira_updates_json."""
    # Use whatever scaffolding the adjacent tests use — look at
    # test_batch_complete_hooks.py or the top of this file for a fixture
    # that creates a project with jira_issue_key on meta + todos with
    # jira_issue_key. Create 2 todos, complete both, verify the result.
    #
    # The assertion:
    #   result["jira_batch_updates"] == [
    #       {"key": "PROJ-1", "resolution": "Done"},
    #       {"key": "PROJ-2", "resolution": "Done"},
    #   ]
    # Also assert result["jira_updates_json"] still present (backwards-compat).
    ...  # fill in fixture call per existing test shape
```

NOTE: Before running, read the top of `test_todos_batch_complete.py` and reuse its existing fixture pattern for creating a project + todos — do not reinvent. If no fixture fits, adapt from an adjacent passing test.

- [ ] **Step 2: Run test — expect fail (field missing)**

Run: `pytest plugins/proj/server/tests/test_todos_batch_complete.py::test_jira_batch_updates_field_present -v`
Expected: FAIL with KeyError or assertion error on missing `jira_batch_updates`.

- [ ] **Step 3: Add `jira_batch_updates` field in `todos.py`**

In `plugins/proj/server/server/tools/todos.py`, find the block around line 1322-1330 and modify:

Current:
```python
        jira_payload: dict[str, JsonValue] = {
            "updates": [
                {"key": key, "fields": {"resolution": {"name": "Done"}}} for key in jira_issue_keys
            ]
        }
        jira_updates_json: str = json.dumps(jira_payload, ensure_ascii=True)
```

Replace with:
```python
        jira_batch_updates: list[dict[str, JsonValue]] = [
            {"key": key, "resolution": "Done"} for key in jira_issue_keys
        ]
        # Legacy raw-JSON form retained for backwards compat with any
        # pre-655 hook cache still targeting jira_update_issues.
        jira_payload: dict[str, JsonValue] = {
            "updates": [
                {"key": key, "fields": {"resolution": {"name": "Done"}}} for key in jira_issue_keys
            ]
        }
        jira_updates_json: str = json.dumps(jira_payload, ensure_ascii=True)
```

Then find `result_data` construction (line 1347) and add the new field:
```python
        result_data: dict[str, JsonValue] = {
            "completed_ids": completed_ids,
            "skipped_ids": skipped_ids,
            "archived_ids": sorted(archive_family_ids),
            "invalid_ids": [],
            "project_name": name,
            "todoist_task_ids": todoist_task_ids,
            "trello_card_ids": trello_card_ids,
            "jira_issue_keys": jira_issue_keys,
            "jira_updates_json": jira_updates_json,
            "jira_batch_updates": jira_batch_updates,    # NEW
            "todoist_project_id": todoist_project_id_val,
            "trello_card_id": trello_card_id_val,
            "jira_project_key": jira_project_key_val,
            "is_batch": True,
        }
```

Then extend the truncation logic (around line 1363-1376):
```python
        if _estimate_size(result_data) > _MAX_SOURCE_BYTES:
            # Drop biggest whole fields first.
            if "jira_updates_json" in result_data:
                result_data["jira_updates_json"] = ""
                truncation_notes.append(
                    "jira_updates_json dropped: batch exceeded 90KB payload cap"
                )
            if _estimate_size(result_data) > _MAX_SOURCE_BYTES:
                result_data["jira_batch_updates"] = []
                truncation_notes.append(
                    "jira_batch_updates dropped: batch exceeded 90KB payload cap"
                )
            if _estimate_size(result_data) > _MAX_SOURCE_BYTES:
                result_data["jira_issue_keys"] = []
                truncation_notes.append("jira_issue_keys dropped: batch exceeded 90KB payload cap")
            if _estimate_size(result_data) > _MAX_SOURCE_BYTES:
                result_data["trello_card_ids"] = []
                truncation_notes.append("trello_card_ids dropped: batch exceeded 90KB payload cap")
```

- [ ] **Step 4: Run new + existing tests — all green**

Run: `pytest plugins/proj/server/tests/test_todos_batch_complete.py -v`
Expected: all pass including new test. Existing oversize-truncation tests still pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_todos_batch_complete.py
git commit -m "feat(proj): emit jira_batch_updates alongside jira_updates_json (655)"
```

---

## Task 6: Rewrite 4 jira hook yamls to structured param_mapping

**Files:**
- Modify: `plugins/jira/.claude-plugin/default-hooks.yaml`
- Test: `plugins/proj/server/tests/test_default_hooks_refs.py`, `plugins/proj/server/tests/test_batch_complete_hooks.py`

- [ ] **Step 1: Update default-hooks-refs tests (structured form assertions)**

Edit `plugins/proj/server/tests/test_default_hooks_refs.py`.

Replace the function `test_jira_on_todo_update_labels_uses_synced_tags` (the one testing raw-JSON form) with:

```python
def test_jira_on_todo_update_uses_structured_param_mapping():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-update")
    assert hook["target_tool"] == "jira_update_issue_fields"
    assert hook["param_mapping"]["key"] == "${jira_issue_key}"
    assert hook["param_mapping"]["summary"] == "${title}"
    assert hook["param_mapping"]["description"] == "${notes}"
    assert hook["param_mapping"]["priority"] == "${priority}"
    assert hook["param_mapping"]["labels"] == "${synced_tags}"
    # Regression: no raw updates_json key.
    assert "updates_json" not in hook["param_mapping"]


def test_jira_hooks_never_use_raw_updates_json():
    """Regression for 655 — no hook in jira/default-hooks.yaml may embed
    raw-JSON-string updates_json templates. All update flows go through
    structured jira_update_issue_fields / jira_update_issues_bulk."""
    doc = _load(JIRA_HOOKS)
    offenders = [
        h["id"]
        for h in doc.get("hooks", [])
        if "updates_json" in h.get("param_mapping", {})
    ]
    assert not offenders, f"hooks still use raw updates_json template: {offenders}"


def test_jira_on_todo_complete_uses_structured_resolution():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-complete")
    assert hook["target_tool"] == "jira_update_issue_fields"
    assert hook["param_mapping"] == {
        "key": "${jira_issue_key}",
        "resolution": "Done",
    }


def test_jira_on_todo_delete_uses_structured_resolution():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-delete")
    assert hook["target_tool"] == "jira_update_issue_fields"
    assert hook["param_mapping"] == {
        "key": "${jira_issue_key}",
        "resolution": "Won't Do",
    }


def test_jira_on_todo_batch_complete_uses_structured_bulk():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-batch-complete")
    assert hook["target_tool"] == "jira_update_issues_bulk"
    assert hook["param_mapping"] == {"updates": "${jira_batch_updates}"}
    assert hook["result_condition"] == {"is_batch": True}
```

- [ ] **Step 2: Run tests — expect fail**

Run: `pytest plugins/proj/server/tests/test_default_hooks_refs.py -v`
Expected: new jira-* tests fail (hook yaml still raw-JSON). The existing `test_jira_on_todo_add_*` tests keep passing (unchanged).

- [ ] **Step 3: Rewrite 4 hooks in `plugins/jira/.claude-plugin/default-hooks.yaml`**

Replace the `jira-on-todo-complete`, `jira-on-todo-update`, `jira-on-todo-batch-complete`, `jira-on-todo-delete` hooks (currently at lines 21-57) with:

```yaml
  - id: jira-on-todo-complete
    trigger_tool: todo_complete
    target_tool: jira_update_issue_fields
    server: jira
    param_mapping:
      key: "${jira_issue_key}"
      resolution: "Done"
    blocking: true
    condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"

  - id: jira-on-todo-update
    trigger_tool: todo_update
    target_tool: jira_update_issue_fields
    server: jira
    param_mapping:
      key: "${jira_issue_key}"
      summary: "${title}"
      description: "${notes}"
      priority: "${priority}"
      labels: "${synced_tags}"
    blocking: true
    condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"

  - id: jira-on-todo-batch-complete
    trigger_tool: todo_complete
    target_tool: jira_update_issues_bulk
    server: jira
    param_mapping:
      updates: "${jira_batch_updates}"
    blocking: true
    condition: "sync.jira.enabled and sync.jira.auto_sync"
    result_condition:
      is_batch: true

  - id: jira-on-todo-delete
    trigger_tool: todo_delete
    target_tool: jira_update_issue_fields
    server: jira
    param_mapping:
      key: "${jira_issue_key}"
      resolution: "Won't Do"
    blocking: true
    condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"
```

- [ ] **Step 4: Update `test_batch_complete_hooks.py`**

In `plugins/proj/server/tests/test_batch_complete_hooks.py`, find the two assertions referencing the old shape (around lines 82 and 92):

Current:
```python
        and h.get("param_mapping", {}) == {"updates_json": "${jira_updates_json}"}
```
and:
```python
    assert pm == {"updates_json": "${jira_updates_json}"}
```

Replace both with the new shape:
```python
        and h.get("param_mapping", {}) == {"updates": "${jira_batch_updates}"}
```
and:
```python
    assert pm == {"updates": "${jira_batch_updates}"}
```

Also update the docstring reference (line 73) from `updates_json=${jira_updates_json}` to `updates=${jira_batch_updates}` if present.

- [ ] **Step 5: Run all affected tests — expect PASS**

Run: `pytest plugins/proj/server/tests/test_default_hooks_refs.py plugins/proj/server/tests/test_batch_complete_hooks.py -v`
Expected: all pass.

- [ ] **Step 6: Run full proj + jira test suites — no regression**

Run: `pytest plugins/proj/server/tests/ plugins/jira/server/tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add plugins/jira/.claude-plugin/default-hooks.yaml \
        plugins/proj/server/tests/test_default_hooks_refs.py \
        plugins/proj/server/tests/test_batch_complete_hooks.py
git commit -m "feat(jira): rewrite 4 hooks to structured param_mapping (655)"
```

---

## Task 7: Version bumps

**Files:**
- Modify: `plugins/jira/plugin.json`
- Modify: `plugins/jira/.claude-plugin/marketplace.json`
- Modify: `plugins/proj/plugin.json`
- Modify: `plugins/proj/.claude-plugin/marketplace.json`

- [ ] **Step 1: Read current versions**

Run: `grep -h '"version"' plugins/jira/plugin.json plugins/jira/.claude-plugin/marketplace.json plugins/proj/plugin.json plugins/proj/.claude-plugin/marketplace.json`
Note the four values — they should be pair-matched (jira pair same, proj pair same).

- [ ] **Step 2: Bump jira minor version**

In `plugins/jira/plugin.json` and `plugins/jira/.claude-plugin/marketplace.json`, bump `"version"` minor digit (e.g. `5.0.0` → `5.1.0`). Both files must match exactly.

- [ ] **Step 3: Bump proj minor version**

In `plugins/proj/plugin.json` and `plugins/proj/.claude-plugin/marketplace.json`, bump `"version"` minor digit the same way. Proj is currently at `5.0.1` (post-650) — bump to `5.1.0`.

- [ ] **Step 4: Verify pair-matched**

Run: `grep -h '"version"' plugins/jira/plugin.json plugins/jira/.claude-plugin/marketplace.json plugins/proj/plugin.json plugins/proj/.claude-plugin/marketplace.json`
Expected: 2 pairs of matching values.

- [ ] **Step 5: Commit**

```bash
git add plugins/jira/plugin.json plugins/jira/.claude-plugin/marketplace.json \
        plugins/proj/plugin.json plugins/proj/.claude-plugin/marketplace.json
git commit -m "chore(versions): bump jira + proj minor for 655"
```

---

## Task 8: Final validation

**Files:** no changes — verification only.

- [ ] **Step 1: Full repo test suite**

Run: `pytest plugins/jira/server/tests/ plugins/proj/server/tests/ plugins/router/server/tests/ -v`
Expected: all pass.

- [ ] **Step 2: Lint + typecheck**

Run: `just lint` (or `ruff check plugins/jira plugins/proj && basedpyright plugins/jira/server/server/tools/issues.py plugins/proj/server/server/tools/todos.py`)
Expected: clean.

- [ ] **Step 3: Spot-check hook yaml parses + registry**

Run from repo root:
```bash
python -c "
import yaml
doc = yaml.safe_load(open('plugins/jira/.claude-plugin/default-hooks.yaml'))
for h in doc['hooks']:
    pm = h.get('param_mapping', {})
    assert 'updates_json' not in pm, h['id']
print('OK: no raw updates_json templates in jira hooks')
"
```
Expected: `OK: no raw updates_json templates in jira hooks`.

- [ ] **Step 4: Review git log**

Run: `git log --oneline feat/655-jira-structured-hooks ^dev`
Expected: 6-7 commits, each self-contained:
```
chore(versions): bump jira + proj minor for 655
feat(jira): rewrite 4 hooks to structured param_mapping (655)
feat(proj): emit jira_batch_updates alongside jira_updates_json (655)
feat(jira): add jira_update_issues_bulk wrapper tool (655)
feat(jira): add jira_update_issue_fields wrapper tool (655)
feat(jira): add FIELD_MAP + _build_updates_json helpers (655)
refactor(jira): extract _update_issues_core from jira_update_issues (655)
```

- [ ] **Step 5: Push branch**

```bash
git push -u origin feat/655-jira-structured-hooks
```

- [ ] **Step 6: Ready-to-merge summary**

Report to user:
- Branch: `feat/655-jira-structured-hooks`
- Commit count
- Test counts (jira + proj)
- Any follow-up concerns

User decides: FF-merge to dev (per CI convention) or open PR.

---

## Self-Review Notes

**Spec coverage:**
- Problem → Task 6 (replaces raw-JSON)
- Architecture wrappers → Tasks 3, 4
- `_update_issues_core` extraction → Task 1
- FIELD_MAP + `_build_updates_json` → Task 2
- Hook yaml rewrite → Task 6
- `jira_batch_updates` → Task 5
- Error handling (empty key/list/all-None/mixed-empty) → Tasks 3, 4 tests
- Testing coverage (new test files, updated refs test, batch_complete test) → Tasks 2-6
- Version bumps → Task 7
- Rollout order (tool before hook yaml) → Task sequencing 1→2→3→4→5→6

**Type consistency:**
- `jira_update_issue_fields` signature matches spec §Architecture.
- `jira_update_issues_bulk(updates: list[dict])` matches.
- `jira_batch_updates` item shape `{"key": str, "resolution": str}` consistent across Task 5 emission and Task 4 consumption.
- `_build_updates_json` raises ValueError (Task 2); wrappers translate to JSON error/warning shapes (Tasks 3, 4) — not inconsistent, just layered.

**Placeholder scan:**
- Task 5 Step 1 has a `...` for fixture adaptation — intentional, with explicit instruction to reuse existing fixture pattern. Not a placeholder in the "TBD" sense, it's a directive to read the file and adapt. Acceptable because the implementer must see the real fixture shape to write a working test.

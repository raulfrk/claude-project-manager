# Jira Integration Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 12 issues found in the Jira integration audit — from broken hooks to missing retry logic.

**Architecture:** 8 tasks ordered by severity. Tasks 1-3 are critical/quick fixes. Tasks 4-6 are medium-effort improvements. Tasks 7-8 are larger structural changes. Each task is independently committable.

**Tech Stack:** Python, YAML, pytest, httpx

---

## File Map

| File | Action | Task |
|------|--------|------|
| `~/.claude/hooks.yaml` | Modify (4 tool name fixes) | 1 |
| `plugins/proj/server/server/tools/jira_sync.py` | Modify (dedup constants, fix duplicate fields, add slugify limit, epic status check) | 2, 5, 6 |
| `plugins/jira/server/server/tools/issues.py` | Modify (exception specificity, pagination error) | 3, 7 |
| `plugins/jira/server/server/main.py` | Modify (register missing modules) | 4 |
| `plugins/jira/server/server/lib/client.py` | Modify (add retry wrapper) | 8 |
| `plugins/jira/.claude-plugin/default-hooks.yaml` | Modify (add priority/labels to update hook) | 5 |

---

### Task 1: Fix broken hooks.yaml tool references (CRITICAL)

**Files:**
- Modify: `~/.claude/hooks.yaml:231,249,355,595`

4 hooks reference `jira_bulk_update_issues` which doesn't exist. Correct name: `jira_update_issues`.

- [ ] **Step 1: Replace all 4 occurrences**

In `~/.claude/hooks.yaml`, replace every `jira_bulk_update_issues` with `jira_update_issues`:
- Line 231: `target_tool: jira_bulk_update_issues` → `target_tool: jira_update_issues`
- Line 249: same
- Line 355: same
- Line 595: same

Use `replace_all=true` on the Edit tool.

- [ ] **Step 2: Verify no occurrences remain**

Run: `grep "jira_bulk_update_issues" ~/.claude/hooks.yaml`

Expected: No matches.

- [ ] **Step 3: Verify correct tool name appears 4 times**

Run: `grep -c "jira_update_issues" ~/.claude/hooks.yaml`

Expected: 4 (the 4 hooks we fixed).

No commit needed — hooks.yaml is user config, not repo code.

---

### Task 2: Fix duplicate fields + deduplicate resolved-status constants

**Files:**
- Modify: `plugins/proj/server/server/tools/jira_sync.py:1090,1104-1110`

Two bugs:
1. Line 1090 hardcodes `resolved_statuses` locally instead of using module-level `_DONE_STATUSES` (line 1142)
2. Lines 1108-1110 duplicate `jira_issue_key` and `status` in the Todo constructor

- [ ] **Step 1: Replace local resolved_statuses with _DONE_STATUSES**

In `plugins/proj/server/server/tools/jira_sync.py`, replace:
```python
                        resolved_statuses = {"done", "resolved", "closed", "cancelled", "canceled"}
                        st_resolved = st_status.lower() in resolved_statuses
```
with:
```python
                        st_resolved = st_status.lower() in _DONE_STATUSES
```

- [ ] **Step 2: Fix duplicate fields in Todo constructor**

In `plugins/proj/server/server/tools/jira_sync.py`, replace the subtask Todo constructor that has duplicate fields:
```python
                            st_todo = Todo(
                                id=next_todo_id(meta, parent=parent_todo),
                                title=st_summary,
                                parent=parent_todo.id if parent_todo else None,
                                jira_issue_key=st_key,
                                status=TodoStatus.DONE if st_resolved else "pending",
                                jira_issue_key=st_key,
                                status=TodoStatus.DONE if st_resolved else "pending",
                                created=today,
                                updated=today,
                            )
```
with (removing the duplicate lines):
```python
                            st_todo = Todo(
                                id=next_todo_id(meta, parent=parent_todo),
                                title=st_summary,
                                parent=parent_todo.id if parent_todo else None,
                                jira_issue_key=st_key,
                                status=TodoStatus.DONE if st_resolved else "pending",
                                created=today,
                                updated=today,
                            )
```

- [ ] **Step 3: Run jira sync tests**

Run: `cd plugins/proj/server && python -m pytest tests/test_jira_sync.py -v --tb=short 2>&1 | tail -10`

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/server/server/tools/jira_sync.py
git commit -m "fix(jira): deduplicate resolved-status constant, remove duplicate Todo fields

Use module-level _DONE_STATUSES instead of inline set in subtask
handling. Remove duplicate jira_issue_key and status lines in
subtask Todo constructor.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Fix generic exception catch in jira_update_issues

**Files:**
- Modify: `plugins/jira/server/server/tools/issues.py:287`

- [ ] **Step 1: Narrow exception catch**

In `plugins/jira/server/server/tools/issues.py`, replace:
```python
            except Exception as exc:
                failures.append({"index": idx, "key": update.get("key", ""), "error": str(exc)})
```
with:
```python
            except RuntimeError as exc:
                failures.append({"index": idx, "key": update.get("key", ""), "error": str(exc)})
```

- [ ] **Step 2: Run jira tests**

Run: `cd plugins/jira/server && python -m pytest tests/test_issues.py -v --tb=short 2>&1 | tail -10`

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add plugins/jira/server/server/tools/issues.py
git commit -m "fix(jira): narrow exception catch in jira_update_issues to RuntimeError

Generic Exception catch was masking serialization bugs and attribute
errors. Only RuntimeError comes from client.put().

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Register missing Jira tool modules

**Files:**
- Modify: `plugins/jira/server/server/main.py:7-13`

13 tool modules exist but aren't registered. Register them all.

- [ ] **Step 1: Update main.py imports and registrations**

Replace the entire `plugins/jira/server/server/main.py`:
```python
"""Jira MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import (
    attachments,
    comments,
    components,
    init,
    issues,
    labels,
    links,
    metadata,
    projects,
    sprints,
    transitions,
    users,
    versions,
    watchers,
    worklogs,
)

mcp = FastMCP("jira")
enable_hook_dispatch(mcp)
init.register(mcp)
issues.register(mcp)
projects.register(mcp)
attachments.register(mcp)
comments.register(mcp)
components.register(mcp)
labels.register(mcp)
links.register(mcp)
metadata.register(mcp)
sprints.register(mcp)
transitions.register(mcp)
users.register(mcp)
versions.register(mcp)
watchers.register(mcp)
worklogs.register(mcp)


def main() -> None:
    run_dual(mcp, "jira", default_port=19105)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify all modules have register functions**

Run: `cd plugins/jira/server && python -c "from server.main import mcp; print(f'{len(mcp._tool_manager._tools)} tools registered')"`

Expected: Should print a number > 11 (was 11 with 3 modules).

- [ ] **Step 3: Run full jira test suite**

Run: `cd plugins/jira/server && python -m pytest tests/ -v --tb=short 2>&1 | tail -15`

Expected: All pass (contract tests may still error if respx not installed — that's pre-existing).

- [ ] **Step 4: Commit**

```bash
git add plugins/jira/server/server/main.py
git commit -m "feat(jira): register all 16 tool modules (was 3)

13 tool modules (attachments, comments, components, labels, links,
metadata, sprints, transitions, users, versions, watchers, worklogs)
were implemented but never registered with the MCP server.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Add priority/labels to Jira update hook

**Files:**
- Modify: `plugins/jira/.claude-plugin/default-hooks.yaml:28-35`

The update hook only syncs summary/description. Priority and label changes should also sync.

- [ ] **Step 1: Update param_mapping in default-hooks.yaml**

In `plugins/jira/.claude-plugin/default-hooks.yaml`, replace:
```yaml
  - id: jira-on-todo-update
    trigger_tool: todo_update
    target_tool: jira_update_issues
    server: jira
    param_mapping:
      updates_json: '{"updates": [{"key": "${jira_issue_key}", "fields": {"summary": "${title}", "description": "${notes}"}}]}'
    blocking: true
    condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"
```
with:
```yaml
  - id: jira-on-todo-update
    trigger_tool: todo_update
    target_tool: jira_update_issues
    server: jira
    param_mapping:
      updates_json: '{"updates": [{"key": "${jira_issue_key}", "fields": {"summary": "${title}", "description": "${notes}", "priority": {"name": "${priority}"}, "labels": ${tags}}}]}'
    blocking: true
    condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"
```

- [ ] **Step 2: Run hook validation tests**

Run: `cd plugins/jira/server && python -m pytest tests/test_hooks.py -v --tb=short`

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add plugins/jira/.claude-plugin/default-hooks.yaml
git commit -m "feat(jira): sync priority and labels on todo update hook

Previously only summary and description were synced on update.
Now priority and labels are included in the update payload.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Add slug length limit + epic status check

**Files:**
- Modify: `plugins/proj/server/server/tools/jira_sync.py:58-63` (slugify)
- Modify: `plugins/proj/server/server/tools/jira_sync.py:~1000-1010` (epic status)

- [ ] **Step 1: Add length limit to _slugify**

In `plugins/proj/server/server/tools/jira_sync.py`, replace:
```python
def _slugify(name: str) -> str:
    """Convert a name to a slug suitable for project names."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"
```
with:
```python
_MAX_SLUG_LENGTH = 80


def _slugify(name: str) -> str:
    """Convert a name to a slug suitable for project names."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")[:_MAX_SLUG_LENGTH].rstrip("-")
    return slug or "unnamed"
```

- [ ] **Step 2: Add epic status check in apply_mapping**

The implementer should read `jira_sync.py` around lines 1000-1010 where epics are processed. Find where the epic's root issue status is evaluated (or not). Add a check: if the epic's root issue is resolved, set the project's status to "done" and skip creating pending children. Read the code carefully to find the exact insertion point.

- [ ] **Step 3: Run jira sync tests**

Run: `cd plugins/proj/server && python -m pytest tests/test_jira_sync.py -v --tb=short 2>&1 | tail -10`

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/server/server/tools/jira_sync.py
git commit -m "fix(jira): add slug length limit (80 chars), check epic resolved status

Long epic names could exceed filesystem limits. Resolved epics now
skip child todo creation instead of creating pending children.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Fix silent pagination error in get_epic_issues

**Files:**
- Modify: `plugins/jira/server/server/tools/issues.py:107-117`

- [ ] **Step 1: Add error reporting on unexpected response shape**

In `plugins/jira/server/server/tools/issues.py`, replace the pagination loop body:
```python
                if not isinstance(data, dict):
                    break
                issues = data.get("issues", [])
                if not isinstance(issues, list):
                    break
                all_issues.extend(issues)
                total = data.get("total", 0)
                if not isinstance(total, int):
                    break
                start_at += len(issues)
                if start_at >= total or not issues:
                    break
```
with:
```python
                if not isinstance(data, dict):
                    return json.dumps({"issues": all_issues, "total": len(all_issues), "warning": "Unexpected response format, pagination stopped early"})
                issues = data.get("issues", [])
                if not isinstance(issues, list):
                    return json.dumps({"issues": all_issues, "total": len(all_issues), "warning": "Unexpected issues format, pagination stopped early"})
                all_issues.extend(issues)
                total = data.get("total", 0)
                if not isinstance(total, int):
                    total = len(all_issues)
                start_at += len(issues)
                if start_at >= total or not issues:
                    break
```

- [ ] **Step 2: Run jira tests**

Run: `cd plugins/jira/server && python -m pytest tests/test_issues.py -v --tb=short 2>&1 | tail -10`

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add plugins/jira/server/server/tools/issues.py
git commit -m "fix(jira): report warnings on unexpected pagination response shape

Previously pagination silently stopped on non-dict/non-list responses.
Now returns partial results with a warning field.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Add retry logic to Jira HTTP client

**Files:**
- Modify: `plugins/jira/server/server/lib/client.py:60-64`

The Jira client has no retry logic. Todoist/Trello use `retry_link()` from proj. The Jira client should retry on transient errors (429, 502, 503, 504) with exponential backoff.

- [ ] **Step 1: Add retry wrapper to client methods**

In `plugins/jira/server/server/lib/client.py`, add after the imports:
```python
import logging

_log = logging.getLogger(__name__)
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
```

Replace `_handle_response`:
```python
    def _handle_response(self, resp: httpx.Response) -> JsonValue:
        if resp.is_success:
            return cast("JsonValue", resp.json())
        msg = f"Jira API error {resp.status_code}: {resp.text}"
        raise RuntimeError(msg)
```
with:
```python
    def _handle_response(self, resp: httpx.Response) -> JsonValue:
        if resp.is_success:
            return cast("JsonValue", resp.json())
        msg = f"Jira API error {resp.status_code}: {resp.text}"
        raise RuntimeError(msg)

    def _request_with_retry(self, method: str, path: str, **kwargs: object) -> JsonValue:
        """Execute HTTP request with retry on transient errors."""
        import random

        last_exc: RuntimeError | None = None
        for attempt in range(_MAX_RETRIES):
            self._rate_limit()
            try:
                resp = getattr(self._client, method)(
                    f"{self._base_url}{path}", **kwargs
                )
                return self._handle_response(resp)
            except RuntimeError as exc:
                if not any(f"error {code}:" in str(exc) for code in _RETRYABLE_STATUS_CODES):
                    raise
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = min(_RETRY_BASE_DELAY * (2 ** attempt) + random.random(), 30.0)
                    _log.warning("Jira API retryable error (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES, exc)
                    time.sleep(delay)
        raise last_exc  # type: ignore[misc]
```

Then update `get`, `post`, `put`, `delete` to use `_request_with_retry` instead of direct `_client` calls. The implementer should read the existing methods and refactor them to call `_request_with_retry`.

- [ ] **Step 2: Run client tests**

Run: `cd plugins/jira/server && python -m pytest tests/test_client.py -v --tb=short`

Expected: All existing tests pass. May need to update mocks for the retry wrapper.

- [ ] **Step 3: Add retry test**

Add to `plugins/jira/server/tests/test_client.py`:
```python
class TestRetry:
    def test_retries_on_503(self, monkeypatch):
        """Client retries on transient 503 errors."""
        # Implementer: mock _client.get to return 503 twice then 200
        # Verify 3 calls made, final result returned
        pass  # implementer fills in based on existing mock patterns

    def test_no_retry_on_400(self, monkeypatch):
        """Client does not retry on 400 client errors."""
        # Implementer: mock _client.get to return 400
        # Verify only 1 call made, RuntimeError raised
        pass  # implementer fills in
```

The implementer should read existing test patterns in `test_client.py` and write complete tests following those patterns.

- [ ] **Step 4: Run full jira test suite**

Run: `cd plugins/jira/server && python -m pytest tests/ -v --tb=short 2>&1 | tail -15`

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/jira/server/server/lib/client.py plugins/jira/server/tests/test_client.py
git commit -m "feat(jira): add retry with exponential backoff for transient HTTP errors

Retries on 429/502/503/504 up to 3 times with jittered exponential
backoff. Non-retryable errors (4xx) propagate immediately.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Verification

After all tasks:

- [ ] `grep "jira_bulk_update_issues" ~/.claude/hooks.yaml` — 0 matches
- [ ] `cd plugins/proj/server && python -m pytest tests/test_jira_sync.py -v` — all pass
- [ ] `cd plugins/jira/server && python -m pytest tests/ -v` — all pass (contract test errors are pre-existing)
- [ ] Push to dev, CI green

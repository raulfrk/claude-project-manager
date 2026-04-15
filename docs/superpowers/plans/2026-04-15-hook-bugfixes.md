# Trello & Todoist Hook Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 bugs found during Trello/Todoist integration audit — wrong param mappings, missing result_condition guards, and missing url validation.

**Architecture:** Pure config + minimal code changes. Bugs 1-3 are YAML-only fixes in default-hooks.yaml files. Bug 4 is a one-line guard in attachments.py. Each fix has a corresponding test update.

**Tech Stack:** Python, YAML, pytest

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `plugins/todoist/.claude-plugin/default-hooks.yaml` | Modify (lines 89, 98) | Fix archive param mapping + add result_condition to verify hook |
| `plugins/todoist/server/tests/test_hooks.py` | Modify | Add tests for archive param mapping + verify hook result_condition |
| `plugins/trello/.claude-plugin/default-hooks.yaml` | Modify (line 63-71) | Add result_condition to single-todo-complete hook |
| `plugins/trello/server/tests/test_hooks.py` | Modify | Add test for result_condition on single-complete hook |
| `plugins/trello/server/server/tools/attachments.py` | Modify (line 22-30) | Add url validation |
| `plugins/trello/server/tests/test_others.py` | Modify (lines 446-452) | Update empty-url test to expect error |

---

### Task 1: Fix todoist-on-proj-archive param mapping

**Files:**
- Modify: `plugins/todoist/.claude-plugin/default-hooks.yaml:88-89`
- Test: `plugins/todoist/server/tests/test_hooks.py`

- [ ] **Step 1: Write failing test**

Add to `plugins/todoist/server/tests/test_hooks.py` at the end of the file:

```python
    def test_proj_archive_hook_param_mapping(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        hooks_by_id = {h["id"]: h for h in data["hooks"]}
        hook = hooks_by_id["todoist-on-proj-archive"]
        assert hook["trigger_tool"] == "proj_archive"
        assert hook["target_tool"] == "todoist_find_tasks"
        # param key must match todoist_find_tasks param name (snake_case)
        assert "project_id" in hook["param_mapping"], (
            f"Expected 'project_id' key, got: {list(hook['param_mapping'].keys())}"
        )
        # template var must match proj_archive return field
        assert hook["param_mapping"]["project_id"] == "${todoist_project_id}", (
            f"Expected '${{todoist_project_id}}', got: {hook['param_mapping']['project_id']}"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/todoist/server pytest tests/test_hooks.py::TestDefaultHooksYaml::test_proj_archive_hook_param_mapping -v`
Expected: FAIL — key is `projectId` not `project_id`, value is `${project_id}` not `${todoist_project_id}`

- [ ] **Step 3: Fix the hook YAML**

In `plugins/todoist/.claude-plugin/default-hooks.yaml`, change line 89 from:
```yaml
      projectId: ${project_id}
```
to:
```yaml
      project_id: ${todoist_project_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/todoist/server pytest tests/test_hooks.py -v`
Expected: ALL PASS (10 tests including the new one)

- [ ] **Step 5: Commit**

```bash
git add plugins/todoist/.claude-plugin/default-hooks.yaml plugins/todoist/server/tests/test_hooks.py
git commit -m "fix(todoist): todoist-on-proj-archive param mapping — project_id key + todoist_project_id var"
```

---

### Task 2: Add result_condition to trello-on-todo-complete

**Files:**
- Modify: `plugins/trello/.claude-plugin/default-hooks.yaml:63-71`
- Test: `plugins/trello/server/tests/test_hooks.py`

The `trello-on-todo-complete` hook currently fires for BOTH single and batch `todo_complete` results. In batch mode, `${trello_card_id}` resolves to the project's card (wrong) and `${trello_done_list_id}` is missing entirely. The batch-specific hook `trello-on-todo-complete-batch` already handles batch results correctly. Fix: add `result_condition` to exclude batch results from the single-todo hook.

Note: `result_condition` cannot use `is_batch: false` because `is_batch` is absent (not `false`) in single results. Instead, the batch hook already guards itself with `result_condition: {is_batch: true}`. For the single hook, we guard the opposite way: when `is_batch` is present and true in the source, `_evaluate_result_condition` checks `source.get(k) == v`. We need the inverse — skip when `is_batch` IS true. The cleanest fix is to NOT use result_condition (since the engine only supports equality checks) and instead tighten the condition. But the condition engine already resolves `todo.trello_card_id` from the source result's `trello_card_id` field — which in batch mode is the PROJECT's card, not a todo's. So the condition-based approach won't distinguish.

The correct fix: the router's `_evaluate_result_condition` returns True when `result_condition` is None, and when all k==v pairs match. We need `is_batch` to NOT be true. Since single results don't set `is_batch` at all, we can check `is_batch: false`. When `source.get("is_batch")` returns `None`, `None == false` is `False` in Python... wait, YAML `false` is Python `False`. `None == False` is `False` in Python. So this won't work.

Best approach: add a simple guard — check that `trello_done_list_id` exists in the source before firing. Since the condition engine only evaluates proj.yaml dot-paths, we need to use `result_condition`. But `result_condition` only supports equality. The cleanest option: explicitly set `is_batch: false` in single-todo `todo_complete` results, then use `result_condition: {is_batch: false}`.

- [ ] **Step 1: Write failing test for result_condition on single-complete hook**

Add to `plugins/trello/server/tests/test_hooks.py` at the end of `TestDirectToolMapping`:

```python
    def test_todo_complete_excludes_batch(self) -> None:
        """trello-on-todo-complete must not fire for batch results."""
        hooks = {h["id"]: h for h in self._load_hooks()}
        hook = hooks["trello-on-todo-complete"]
        assert hook.get("result_condition") == {"is_batch": False}, (
            "trello-on-todo-complete must have result_condition: {is_batch: false} "
            "to prevent firing on batch completions"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/trello/server pytest tests/test_hooks.py::TestDirectToolMapping::test_todo_complete_excludes_batch -v`
Expected: FAIL — no result_condition set

- [ ] **Step 3: Add is_batch: false to single-todo complete result in proj**

In `plugins/proj/server/server/tools/todos.py`, find the single-todo `todo_complete` return (around line 1264-1268). After line 1267 (`result_data["todoist_task_ids"] = ...`), add:

```python
        result_data["is_batch"] = False
```

- [ ] **Step 4: Add result_condition to trello hook YAML**

In `plugins/trello/.claude-plugin/default-hooks.yaml`, change lines 63-71 from:
```yaml
  - id: trello-on-todo-complete
    trigger_tool: todo_complete
    target_tool: move_card
    server: trello
    param_mapping:
      card_id: "${trello_card_id}"
      list_id: "${trello_done_list_id}"
    blocking: true
    condition: "sync.trello.enabled and sync.trello.auto_sync and todo.trello_card_id"
```
to:
```yaml
  - id: trello-on-todo-complete
    trigger_tool: todo_complete
    target_tool: move_card
    server: trello
    param_mapping:
      card_id: "${trello_card_id}"
      list_id: "${trello_done_list_id}"
    result_condition:
      is_batch: false
    blocking: true
    condition: "sync.trello.enabled and sync.trello.auto_sync and todo.trello_card_id"
```

- [ ] **Step 5: Run trello tests**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/trello/server pytest tests/test_hooks.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run proj tests for todo_complete**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/proj/server pytest -k "complete" -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add plugins/trello/.claude-plugin/default-hooks.yaml plugins/trello/server/tests/test_hooks.py plugins/proj/server/server/tools/todos.py
git commit -m "fix(trello): add result_condition to trello-on-todo-complete — prevent batch firing"
```

---

### Task 3: Add result_condition to verify-todoist-complete

**Files:**
- Modify: `plugins/todoist/.claude-plugin/default-hooks.yaml:93-101`
- Test: `plugins/todoist/server/tests/test_hooks.py`

The `verify-todoist-complete` hook maps `${todoist_task_id}` (singular), which doesn't exist in batch results (only `todoist_task_ids` plural). Same fix as Task 2 — add `result_condition: {is_batch: false}` so it only fires for single completions.

- [ ] **Step 1: Write failing test**

Add to `plugins/todoist/server/tests/test_hooks.py` at the end of the file:

```python
    def test_verify_todoist_complete_excludes_batch(self) -> None:
        with _HOOKS_PATH.open() as f:
            data = yaml.safe_load(f)
        hooks_by_id = {h["id"]: h for h in data["hooks"]}
        hook = hooks_by_id["verify-todoist-complete"]
        assert hook.get("result_condition") == {"is_batch": False}, (
            "verify-todoist-complete must have result_condition: {is_batch: false} "
            "to prevent firing on batch completions (singular todoist_task_id not in batch results)"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/todoist/server pytest tests/test_hooks.py::TestDefaultHooksYaml::test_verify_todoist_complete_excludes_batch -v`
Expected: FAIL — no result_condition set

- [ ] **Step 3: Fix the hook YAML**

In `plugins/todoist/.claude-plugin/default-hooks.yaml`, change lines 93-101 from:
```yaml
  - id: verify-todoist-complete
    trigger_tool: todo_complete
    target_tool: todoist_verify_complete
    server: todoist
    param_mapping:
      todoist_task_id: "${todoist_task_id}"
    blocking: true
    verification: true
    condition: "sync.todoist.enabled and sync.todoist.auto_sync"
```
to:
```yaml
  - id: verify-todoist-complete
    trigger_tool: todo_complete
    target_tool: todoist_verify_complete
    server: todoist
    param_mapping:
      todoist_task_id: "${todoist_task_id}"
    result_condition:
      is_batch: false
    blocking: true
    verification: true
    condition: "sync.todoist.enabled and sync.todoist.auto_sync"
```

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/todoist/server pytest tests/test_hooks.py -v`
Expected: ALL PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/todoist/.claude-plugin/default-hooks.yaml plugins/todoist/server/tests/test_hooks.py
git commit -m "fix(todoist): add result_condition to verify-todoist-complete — prevent batch firing"
```

---

### Task 4: Add url validation to add_attachment

**Files:**
- Modify: `plugins/trello/server/server/tools/attachments.py:22-30`
- Test: `plugins/trello/server/tests/test_others.py:446-452`

- [ ] **Step 1: Update existing test to expect error**

In `plugins/trello/server/tests/test_others.py`, replace the `test_empty_url_omitted` test (lines 446-452):

```python
    def test_empty_url_returns_error(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_attachments, mock_trello_client)
        result = json.loads(tools["add_attachment"]("c1"))
        assert "error" in result
        assert "url" in result["error"].lower()
        mock_trello_client.post.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/trello/server pytest tests/test_others.py::TestAddAttachment::test_empty_url_returns_error -v`
Expected: FAIL — currently calls API with empty params instead of returning error

- [ ] **Step 3: Add url validation**

In `plugins/trello/server/server/tools/attachments.py`, change lines 22-30 from:
```python
    @app.tool(description="Add an attachment to a card. At least url must be provided.")
    def add_attachment(card_id: str, url: str = "", name: str = "") -> str:
        client = get_client()
        params: dict[str, str] = {}
        if url:
            params["url"] = url
        if name:
            params["name"] = name
        attachment = client.post(f"/cards/{card_id}/attachments", params=params)
        return json.dumps(attachment)
```
to:
```python
    @app.tool(description="Add an attachment to a card. url is required.")
    def add_attachment(card_id: str, url: str = "", name: str = "") -> str:
        if not url:
            return json.dumps({"error": "url is required"})
        client = get_client()
        params: dict[str, str] = {"url": url}
        if name:
            params["name"] = name
        attachment = client.post(f"/cards/{card_id}/attachments", params=params)
        return json.dumps(attachment)
```

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/trello/server pytest tests/test_others.py::TestAddAttachment -v`
Expected: ALL PASS (3 tests)

- [ ] **Step 5: Run full trello test suite**

Run: `UV_CACHE_DIR=/tmp/claude/uv-cache uv run --directory plugins/trello/server pytest -v`
Expected: ALL PASS (266+ tests)

- [ ] **Step 6: Commit**

```bash
git add plugins/trello/server/server/tools/attachments.py plugins/trello/server/tests/test_others.py
git commit -m "fix(trello): add url validation to add_attachment"
```

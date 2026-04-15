# 605 Simplification (605.6–605.10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate redundant MCP tools across all plugins, fold 3 plugins into others, remove YAML legacy code, and ship 5.0.0.

**Architecture:** Single worktree branch. Linear execution: 605.6 (proj tool merges) → 605.7 (other plugin merges) → 605.8 (plugin folding) → 605.9 (file format cleanup) → 605.10 (version bump). Each commit bundles server changes + SKILL.md updates + test updates together — no intermediate inconsistent state.

**Tech Stack:** Python 3.12, FastMCP, pytest, uv, git

---

## Phase 605.6 — Proj Tool Merges

### Task 0: Setup

**Files:**
- No code changes

- [ ] **Step 1: Create worktree**

```bash
cd /home/raul/projects/claude-project-manager
# Use the worktree MCP tool or:
git worktree add /home/raul/worktrees/cpm/todo-605.6 -b todo-605.6
```

- [ ] **Step 2: Clear stale blocker on 605.6**

Use `mcp__plugin_proj_proj__todo_unblock` on todo 605.6 (blocked_by 605.3 which is done).

- [ ] **Step 3: Verify worktree + test baseline**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server
uv run pytest tests/ -q --tb=short
```
Expected: all tests pass (note count for regression baseline).

---

### Task 1: Remove todo_add_child

`todo_add_child` is fully redundant — `todo_add` already accepts `parent: str | None`. Callers simply use `todo_add(title=..., parent=parent_id)`.

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (remove `todo_add_child` function ~lines 1161–1232)
- Modify: `plugins/todoist/.claude-plugin/default-hooks.yaml` (remove `todoist-on-todo-add-child`)
- Modify: `plugins/trello/.claude-plugin/default-hooks.yaml` (remove `trello-on-todo-add-child`)
- Modify: `plugins/proj/server/server/tools/todos.py` (update `register()` docstring)
- Grep-check: all SKILL.md files calling `todo_add_child`
- Test: `plugins/proj/server/tests/test_todo_add.py` (create)

- [ ] **Step 1: Write failing test**

Create `plugins/proj/server/tests/test_todo_add.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock

def make_cfg():
    cfg = MagicMock()
    cfg.default_priority = "medium"
    return cfg

def test_todo_add_child_via_parent_param(tmp_path, monkeypatch):
    """todo_add with parent= creates a child — todo_add_child behaviour covered."""
    from server.tools.todos import register
    from fastmcp import FastMCP
    app = FastMCP("test")
    # patch storage to return empty project
    # ... (use existing test fixtures from test_projects.py)
    # Key assertion: todo_add called with parent="1" returns child id "1.1"
    pass  # replace with real fixture pattern from test_projects.py

def test_todo_add_child_tool_does_not_exist():
    """todo_add_child must not be registered after removal."""
    from server.tools.todos import register
    from fastmcp import FastMCP
    app = FastMCP("test")
    # Collect registered tool names
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    # Before register, empty. After register:
    register(app)
    tool_names_after = [t.name for t in app._tool_manager.list_tools()]
    assert "todo_add_child" not in tool_names_after
    assert "todo_add" in tool_names_after
```

- [ ] **Step 2: Run test to verify it fails (todo_add_child still exists)**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server
uv run pytest tests/test_todo_add.py::test_todo_add_child_tool_does_not_exist -v
```
Expected: FAIL — `todo_add_child` is still in tool list.

- [ ] **Step 3: Remove todo_add_child from todos.py**

In `plugins/proj/server/server/tools/todos.py`, delete the entire `todo_add_child` function definition (approx lines 1155–1232, from `@app.tool(description="Add a child todo under a parent todo.")` through the closing return).

Also remove `todo_add_child` from the `register()` docstring at the top of the function.

- [ ] **Step 4: Remove todoist-on-todo-add-child hook**

In `plugins/todoist/.claude-plugin/default-hooks.yaml`, delete the entire `todoist-on-todo-add-child` entry (the block starting with `- id: todoist-on-todo-add-child`). The existing `todoist-on-todo-add` hook already fires on `todo_add` and includes `parentId: "${parent_todoist_task_id}"` — it handles child adds.

- [ ] **Step 5: Remove trello-on-todo-add-child hook**

In `plugins/trello/.claude-plugin/default-hooks.yaml`, delete the `trello-on-todo-add-child` entry (trigger: `todo_add_child`). The existing `trello-on-todo-add` handles all adds.

- [ ] **Step 6: Check all SKILL.md callsites**

```bash
cd /home/raul/worktrees/cpm/todo-605.6
grep -r "todo_add_child" plugins/*/skills/ .claude/ --include="*.md" -l
```

For each file found, replace `todo_add_child(parent_id=X, title=Y, ...)` with `todo_add(title=Y, parent=X, ...)`.

- [ ] **Step 7: Run tests**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server
uv run pytest tests/ -q --tb=short
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
cd /home/raul/worktrees/cpm/todo-605.6
git add plugins/proj/server/server/tools/todos.py \
        plugins/todoist/.claude-plugin/default-hooks.yaml \
        plugins/trello/.claude-plugin/default-hooks.yaml \
        plugins/proj/server/tests/test_todo_add.py
# also any SKILL.md files changed
git commit -m "feat(605.6): remove todo_add_child — use todo_add(parent=) instead"
```

---

### Task 2: Fold todo_batch_add_children → todo_add

Add optional `children` + `blocking_pairs` params to `todo_add`. When `children` is provided, `todo_add` creates the parent (if `title` given) then batch-adds children atomically. Remove `todo_batch_add_children` as standalone tool.

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (extend `todo_add`, remove `todo_batch_add_children`)
- Modify: `plugins/trello/.claude-plugin/default-hooks.yaml` (remove `trello-on-todo-batch-add-children`)
- Test: `plugins/proj/server/tests/test_todo_add.py` (extend)

- [ ] **Step 1: Write failing test**

Add to `plugins/proj/server/tests/test_todo_add.py`:

```python
def test_todo_add_batch_children_tool_does_not_exist():
    """todo_batch_add_children must not be registered after removal."""
    from server.tools.todos import register
    from fastmcp import FastMCP
    app = FastMCP("test")
    register(app)
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "todo_batch_add_children" not in tool_names
    assert "todo_add" in tool_names
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_todo_add.py::test_todo_add_batch_children_tool_does_not_exist -v
```
Expected: FAIL.

- [ ] **Step 3: Extend todo_add signature**

In `plugins/proj/server/server/tools/todos.py`, update `todo_add` signature to add two optional params:

```python
@app.tool(description=(
    "Add a todo. Pass parent= to nest under an existing todo. "
    "Pass children= (JSON array of {title, priority?, tags?, notes?} objects) "
    "to atomically create child todos under this new todo. "
    "Pass blocking_pairs= (JSON array of [blocker_idx, blocked_idx] pairs, "
    "0-based into flattened children list) to set blocking relationships."
))
def todo_add(
    title: str,
    priority: str | None = None,
    tags: list[str] | None = None,
    blocked_by: list[str] | None = None,
    parent: str | None = None,
    notes: str = "",
    due_date: str | None = None,
    todoist_task_id: str | None = None,
    project_name: str | None = None,
    force_create: bool = False,
    children: str = "[]",          # JSON array of child specs
    blocking_pairs: str = "[]",    # JSON array of [blocker_idx, blocked_idx] pairs
) -> str:
```

After the existing todo creation logic (the part that creates and saves the parent todo), add:

```python
    # ── Batch children (optional) ─────────────────────────────────────
    child_specs_raw = children.strip()
    if child_specs_raw and child_specs_raw != "[]":
        import json as _json
        try:
            child_specs = _json.loads(child_specs_raw)
            bp = _json.loads(blocking_pairs.strip() or "[]")
        except _json.JSONDecodeError as e:
            return _json.dumps({"error": f"Invalid children JSON: {e}"})
        # delegate to the batch logic extracted from old todo_batch_add_children
        batch_result = _batch_add_children(cfg, name, todo, child_specs, bp, today)
        result_data = _json.loads(result_str)
        result_data["children_result"] = _json.loads(batch_result)
        return _json.dumps(result_data)
```

Extract the batch-add logic from the existing `todo_batch_add_children` function into a private helper `_batch_add_children(cfg, name, parent_todo, child_specs, blocking_pairs, today) -> str` that contains the core loop logic. This helper is called by both the new `todo_add(children=...)` path and is the extracted implementation.

Then delete the `todo_batch_add_children` function definition.

- [ ] **Step 4: Remove trello-on-todo-batch-add-children hook**

In `plugins/trello/.claude-plugin/default-hooks.yaml`, delete the `trello-on-todo-batch-add-children` entry. The `trello-on-todo-add` hook fires on `todo_add` and covers all add cases.

- [ ] **Step 5: Check SKILL.md callsites**

```bash
grep -r "todo_batch_add_children" plugins/*/skills/ .claude/ --include="*.md" -l
```

For each file: replace `todo_batch_add_children(parent_id=X, children=Y)` with `todo_add(parent=X, children=Y)`.

**Design note:** when `parent=` is provided but `title` is empty/omitted, `todo_add` should skip creating a root todo and only add the children under the existing parent. Add this branch to `todo_add`:

```python
if parent and (not title or title.strip() == "") and children and children.strip() != "[]":
    # children-only mode: add to existing parent, don't create a new root
    parent_todo = next((t for t in todos if t.id == parent), None)
    if not parent_todo:
        return json.dumps({"error": f"Parent todo '{parent}' not found."})
    return _batch_add_children(cfg, name, parent_todo, json.loads(children), json.loads(blocking_pairs or "[]"), today)
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/ -q --tb=short
```

- [ ] **Step 7: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py \
        plugins/trello/.claude-plugin/default-hooks.yaml \
        plugins/proj/server/tests/test_todo_add.py
git commit -m "feat(605.6): fold todo_batch_add_children into todo_add(children=)"
```

---

### Task 3: Merge todo_complete + todo_batch_complete

Merge into a single `todo_complete(todo_id=None, todo_ids=None, ...)`. The tool always returns `todoist_task_ids: list[str]` (wrapping single in a list). Consolidate the two completion hooks into one.

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py`
- Modify: `plugins/todoist/.claude-plugin/default-hooks.yaml`
- Modify: `plugins/trello/.claude-plugin/default-hooks.yaml`
- Modify: `plugins/jira/.claude-plugin/default-hooks.yaml`
- Modify: `plugins/proj/server/tests/test_todos_batch_complete.py`
- Test: add single-completion test

- [ ] **Step 1: Write failing test**

Add to `plugins/proj/server/tests/test_todos_batch_complete.py`:

```python
def test_todo_batch_complete_tool_does_not_exist():
    """todo_batch_complete must not be registered after removal."""
    from server.tools.todos import register
    from fastmcp import FastMCP
    app = FastMCP("test")
    register(app)
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "todo_batch_complete" not in tool_names
    assert "todo_complete" in tool_names

def test_todo_complete_single_returns_todoist_task_ids_list():
    """Single-todo complete always returns todoist_task_ids as a list."""
    # Use existing test fixtures
    # Call todo_complete(todo_id="1")
    # Assert result contains "todoist_task_ids": ["<id>"] (not just "todoist_task_id")
    pass  # fill in with project fixture pattern
```

- [ ] **Step 2: Run to verify fails**

```bash
uv run pytest tests/test_todos_batch_complete.py::test_todo_batch_complete_tool_does_not_exist -v
```

- [ ] **Step 3: Update todo_complete signature**

In `plugins/proj/server/server/tools/todos.py`, update `todo_complete` to accept both single and batch:

```python
@app.tool(description=(
    "Mark todos as done. Pass todo_id for a single todo, or "
    "todo_ids (list) for 2+ todos atomically. Prefer todo_ids for "
    "batches — fires one aggregated hook chain."
))
def todo_complete(
    todo_id: str | None = None,
    todo_ids: list[str] | None = None,
    note: str = "",
    project_name: str | None = None,
) -> str:
    if todo_ids and len(todo_ids) >= 2:
        # delegate to existing batch_complete logic (extracted into _batch_complete helper)
        return _batch_complete(todo_ids=todo_ids, note=note, project_name=project_name)
    if todo_id:
        # existing single-complete logic
        ...
        # At the end, ensure result includes todoist_task_ids for hook compat:
        result_data["todoist_task_ids"] = [todo.todoist_task_id] if todo.todoist_task_id else []
        return json.dumps(result_data)
    return json.dumps({"error": "Provide todo_id (single) or todo_ids (batch)."})
```

Extract the batch-complete body from the existing `todo_batch_complete` into `_batch_complete(todo_ids, note, project_name)`. Delete `todo_batch_complete` function.

- [ ] **Step 4: Consolidate completion hooks**

**todoist** (`plugins/todoist/.claude-plugin/default-hooks.yaml`):
- Update `todoist-on-todo-complete` param_mapping to use `todoist_task_ids` (list, works for both):
  ```yaml
  param_mapping:
    ids: "${todoist_task_ids}"
  condition: "sync.todoist.enabled and todo.todoist_task_id"
  ```
- Delete `todoist-on-todo-batch-complete` entry entirely.

**trello** (`plugins/trello/.claude-plugin/default-hooks.yaml`):
- Find the `trello-on-todo-batch-complete` entry (trigger: `todo_batch_complete`).
- Change its `trigger_tool` to `todo_complete`.
- Delete any separate single-complete trello hook that would double-fire. Check for duplicate.

**jira** (`plugins/jira/.claude-plugin/default-hooks.yaml`):
- Find `jira-on-todo-batch-complete` entry. Change `trigger_tool` to `todo_complete`.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/ -q --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py \
        plugins/todoist/.claude-plugin/default-hooks.yaml \
        plugins/trello/.claude-plugin/default-hooks.yaml \
        plugins/jira/.claude-plugin/default-hooks.yaml \
        plugins/proj/server/tests/test_todos_batch_complete.py
git commit -m "feat(605.6): merge todo_batch_complete into todo_complete(todo_ids=)"
```

---

### Task 4: Fold todo_block + todo_unblock → todo_update

Add `blocked_by_set: list[str] | None = None` to `todo_update`. When provided, replaces the todo's `blocked_by` list and syncs the `blocks` lists of affected todos. Remove `todo_block` and `todo_unblock` as standalone tools.

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py`
- Test: `plugins/proj/server/tests/test_todo_block_unblock.py` (create)

- [ ] **Step 1: Write failing test**

Create `plugins/proj/server/tests/test_todo_block_unblock.py`:

```python
def test_todo_block_unblock_tools_removed():
    from server.tools.todos import register
    from fastmcp import FastMCP
    app = FastMCP("test")
    register(app)
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "todo_block" not in tool_names
    assert "todo_unblock" not in tool_names
    assert "todo_update" in tool_names

def test_todo_update_blocked_by_set_replaces_blockers():
    """todo_update(blocked_by_set=[...]) replaces blocked_by and syncs blocks."""
    # Use existing fixture pattern
    # Create todos A, B, C. Set A blocked_by=[B].
    # Then todo_update(A, blocked_by_set=[C]) should result in A.blocked_by=[C], C.blocks=[A], B.blocks=[]
    pass
```

- [ ] **Step 2: Run to verify fails**

```bash
uv run pytest tests/test_todo_block_unblock.py::test_todo_block_unblock_tools_removed -v
```

- [ ] **Step 3: Add blocked_by_set to todo_update**

In `plugins/proj/server/server/tools/todos.py`, find `todo_update` and add `blocked_by_set: list[str] | None = None` to its parameters. In the function body, after the existing field update logic, add:

```python
    if blocked_by_set is not None:
        # Remove this todo from the blocks list of any currently blocking todos
        for blocker_id in todo.blocked_by:
            blocker = todo_map.get(blocker_id)
            if blocker and todo_id in blocker.blocks:
                blocker.blocks.remove(todo_id)
                blocker.updated = today
        # Set new blocked_by
        todo.blocked_by = blocked_by_set
        # Add this todo to the blocks list of new blockers
        for blocker_id in blocked_by_set:
            blocker = todo_map.get(blocker_id)
            if blocker and todo_id not in blocker.blocks:
                blocker.blocks.append(todo_id)
                blocker.updated = today
```

Then delete the `todo_block` and `todo_unblock` function definitions.

- [ ] **Step 4: Check SKILL.md callsites**

```bash
grep -r "todo_block\|todo_unblock" plugins/*/skills/ .claude/ --include="*.md" -l
```

Replace:
- `todo_block(todo_id=X, blocks_ids=[Y])` → `todo_update(todo_id=Y, blocked_by_set=[X])`
- `todo_unblock(todo_id=X)` → `todo_update(todo_id=X, blocked_by_set=[])`

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/ -q --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py \
        plugins/proj/server/tests/test_todo_block_unblock.py
# + any SKILL.md changes
git commit -m "feat(605.6): fold todo_block/todo_unblock into todo_update(blocked_by_set=)"
```

---

### Task 5: Merge proj_*_full_sync → proj_sync

Add a single `proj_sync(integration)` tool that dispatches to the appropriate sync function. Remove `proj_todoist_full_sync`, `proj_trello_full_sync`, `proj_jira_full_sync` as standalone tools. Update hook targets.

**Files:**
- Modify: `plugins/proj/server/server/tools/todoist_full_sync.py` (or create thin dispatcher)
- Modify: `plugins/proj/server/server/tools/jira_sync.py`
- Modify: `plugins/proj/server/server/tools/trello_full_sync.py`
- Modify: `plugins/proj/server/main.py` (register proj_sync, unregister old tools)
- Modify: `plugins/todoist/.claude-plugin/default-hooks.yaml` (update target)
- Modify: `plugins/jira/.claude-plugin/default-hooks.yaml` (update target)
- Test: `plugins/proj/server/tests/test_proj_sync.py` (create)

- [ ] **Step 1: Write failing test**

Create `plugins/proj/server/tests/test_proj_sync.py`:

```python
def test_old_full_sync_tools_removed():
    from server.main import create_app
    app = create_app()
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "proj_todoist_full_sync" not in tool_names
    assert "proj_trello_full_sync" not in tool_names
    assert "proj_jira_full_sync" not in tool_names
    assert "proj_sync" in tool_names

def test_proj_sync_rejects_unknown_integration():
    # call proj_sync(integration="unknown")
    # assert returns error JSON
    pass
```

- [ ] **Step 2: Run to verify fails**

```bash
uv run pytest tests/test_proj_sync.py::test_old_full_sync_tools_removed -v
```

- [ ] **Step 3: Add proj_sync tool**

In `plugins/proj/server/server/tools/todoist_full_sync.py`, add at the end of the `register()` function (or in a new file `tools/sync.py`):

```python
@app.tool(description=(
    "Run a full bidirectional sync for an integration. "
    "integration: 'todoist' | 'trello' | 'jira'"
))
def proj_sync(
    integration: str,
    project_name: str | None = None,
) -> str:
    from . import todoist_full_sync as _tds
    from . import trello_full_sync as _trs
    from . import jira_sync as _js
    dispatch = {
        "todoist": lambda: _tds._run_todoist_sync(project_name),
        "trello":  lambda: _trs._run_trello_sync(project_name),
        "jira":    lambda: _js._run_jira_sync(project_name),
    }
    fn = dispatch.get(integration)
    if fn is None:
        return json.dumps({"error": f"Unknown integration '{integration}'. Use: todoist, trello, jira."})
    return fn()
```

Extract the body of each `proj_*_full_sync` into a private `_run_*_sync(project_name)` function, then have both the old tool and `proj_sync` call it. Then delete the three old tool definitions.

- [ ] **Step 4: Update hook targets**

In `plugins/todoist/.claude-plugin/default-hooks.yaml`, find `todoist-full-sync-on-proj-load`:
```yaml
  - id: todoist-full-sync-on-proj-load
    trigger_tool: proj_load_session
    target_tool: proj_sync          # was: proj_todoist_full_sync
    server: proj
    param_mapping:
      project_name: "${project_name}"
      integration: "todoist"        # add this
```

In `plugins/jira/.claude-plugin/default-hooks.yaml`, find `jira-full-sync-on-proj-load`:
```yaml
  - id: jira-full-sync-on-proj-load
    trigger_tool: proj_load_session
    target_tool: proj_sync          # was: proj_jira_full_sync
    server: proj
    param_mapping:
      project_name: "${project_name}"
      integration: "jira"           # add this
```

Check `plugins/trello/.claude-plugin/default-hooks.yaml` for any full_sync hook (may not exist — trello sync may be manual only).

- [ ] **Step 5: Update migration script**

The migration script from 605.1 (`scripts/migrate-hooks.yaml` or similar) should rename stale trigger_tool values in user's `~/.claude/hooks.yaml`. Add entries for:
- `todo_add_child` → `todo_add`
- `todo_batch_add_children` → `todo_add`
- `todo_batch_complete` → `todo_complete`
- target `proj_todoist_full_sync` → `proj_sync` (with integration param)
- target `proj_jira_full_sync` → `proj_sync` (with integration param)

Find the migration script (grep for it in scripts/) and add these mappings to its trigger rename table.

- [ ] **Step 6: Check SKILL.md callsites**

```bash
grep -r "proj_todoist_full_sync\|proj_trello_full_sync\|proj_jira_full_sync" plugins/*/skills/ .claude/ --include="*.md" -l
```

Replace with `proj_sync(integration="todoist"|"trello"|"jira")`.

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/ -q --tb=short
```

- [ ] **Step 8: Commit**

```bash
git add plugins/proj/server/server/tools/ \
        plugins/todoist/.claude-plugin/default-hooks.yaml \
        plugins/jira/.claude-plugin/default-hooks.yaml \
        plugins/proj/server/tests/test_proj_sync.py
# + any SKILL.md changes, migration script
git commit -m "feat(605.6): merge proj_*_full_sync into proj_sync(integration=)"
```

---

### Task 6: 605.6 Verification

- [ ] **Step 1: Run full proj test suite**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Step 2: Grep for all removed tool names**

```bash
cd /home/raul/worktrees/cpm/todo-605.6
grep -r "todo_add_child\|todo_batch_add_children\|todo_batch_complete\|todo_block\b\|todo_unblock\|proj_todoist_full_sync\|proj_trello_full_sync\|proj_jira_full_sync" \
  plugins/*/skills/ .claude/ plugins/*/.*claude-plugin/ --include="*.md" --include="*.yaml" --include="*.yml" -l
```
Expected: no results (other than migration script and CHANGELOG).

---

## Phase 605.7 — Other Plugin Tool Merges

### Task 7: Trello tool merges

**Target:** ~43 → ~20 tools. Merge same-domain variants.

**Files:**
- `plugins/trello/server/server/tools/checklists.py`
- `plugins/trello/server/server/tools/cards.py`
- `plugins/trello/server/tests/test_checklists.py` + others

- [ ] **Step 1: Audit trello tools**

```bash
grep -n "^    @app.tool\|^def \|^async def " /home/raul/worktrees/cpm/todo-605.6/plugins/trello/server/server/tools/checklists.py
```

Run similar grep for cards.py, lists.py, others. List all tool names with their files.

- [ ] **Step 2: Identify merge candidates**

From audit, the known candidates per spec:
- `add_checklist_item` + `batch_add_checklist_items` → `add_checklist_item(items: list | single)`
- `update_checklist_item` + `batch_update_checklist_items` → `update_checklist_item(items: list | single)`
- Any other obvious single/batch pairs

- [ ] **Step 3: For each merge pair — write test, implement, update hooks, commit**

Follow the same pattern as Tasks 1–5:
1. Write failing test asserting old tool name gone + new signature present
2. Implement: extract logic to private helper, new combined function, delete old
3. Update any hook `trigger_tool` or `target_tool` references
4. Run `uv run pytest tests/ -q` — verify pass
5. Commit: `feat(605.7): merge trello <old_names> into <new_name>`

- [ ] **Step 4: Run full trello test suite**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/trello/server
uv run pytest tests/ -q --tb=short
```

---

### Task 8: Jira tool merges

**Target:** ~39 → ~15 tools.

- [ ] **Step 1: Audit jira tools** (same grep pattern as Task 7 Step 1)

- [ ] **Step 2: Identify merge candidates**

From spec: bulk + single variants for per-entity operations (issues, comments, etc.).

- [ ] **Step 3: For each merge pair — write test, implement, commit** (same pattern as Task 7 Step 3)

- [ ] **Step 4: Run full jira test suite**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/jira/server
uv run pytest tests/ -q --tb=short
```

---

### Task 9: Todoist / Sandbox / Worktree light merges

**Target:** todoist ~14→~8, sandbox ~14→~6, worktree ~13→~8.

- [ ] **Step 1: Audit each plugin** (grep for tool definitions)

- [ ] **Step 2: Identify light merge candidates** — only merge if genuinely redundant. Skip if semantically distinct.

- [ ] **Step 3: Implement + test + commit per plugin** (same pattern)

- [ ] **Step 4: Run test suites**

```bash
for plugin in todoist sandbox worktree; do
  echo "=== $plugin ===" && cd /home/raul/worktrees/cpm/todo-605.6/plugins/$plugin/server && uv run pytest tests/ -q --tb=short
done
```

---

## Phase 605.8 — Plugin Folding

### Task 10: Fold analyse → proj

analyse is a skill-only plugin (no MCP server). This is a file move + skill registration update.

**Files:**
- Move: `plugins/analyse/skills/review/SKILL.md` → `plugins/proj/skills/review/SKILL.md`
- Move: `plugins/analyse/skills/explore/SKILL.md` → already exists as `plugins/proj/skills/explore/SKILL.md` — check for conflicts
- Delete: `plugins/analyse/` directory
- Modify: `marketplace.json` (remove analyse entry)
- Modify: installer files (remove analyse from plugin list)
- Modify: `CLAUDE.md` skill reference table

- [ ] **Step 1: Check for skill conflicts**

```bash
ls /home/raul/worktrees/cpm/todo-605.6/plugins/proj/skills/
ls /home/raul/worktrees/cpm/todo-605.6/plugins/analyse/skills/
```

If `plugins/proj/skills/review/` already exists, compare content. If analyse version is older/same, discard. If newer, merge.

- [ ] **Step 2: Move analyse skills**

```bash
cp -r /home/raul/worktrees/cpm/todo-605.6/plugins/analyse/skills/review \
      /home/raul/worktrees/cpm/todo-605.6/plugins/proj/skills/review
# (if not already present)
```

- [ ] **Step 3: Update marketplace.json**

In `marketplace.json`, remove the `analyse` plugin entry entirely.

- [ ] **Step 4: Update installer**

```bash
grep -r "analyse" /home/raul/worktrees/cpm/todo-605.6/installer/ --include="*.py" -l
```

For each file: remove references to analyse plugin (installation step, plugin list, etc.).

- [ ] **Step 5: Update CLAUDE.md skill table**

Find `analyse:review` and `analyse:explore` entries in `CLAUDE.md`. Change to `proj:review` and `proj:explore`.

- [ ] **Step 6: Delete analyse plugin directory**

```bash
rm -rf /home/raul/worktrees/cpm/todo-605.6/plugins/analyse
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(605.8): fold analyse plugin into proj (skills/review, skills/explore)"
```

---

### Task 11: Fold zoxide → worktree

Move zoxide's 3 MCP tools (`zoxide_boost`, `zoxide_query`, `zoxide_remove`) into the worktree MCP server. Keep tool names identical (hook trigger_tool references unchanged).

**Files:**
- Copy: `plugins/zoxide/server/server/tools/zoxide.py` → `plugins/worktree/server/server/tools/zoxide.py`
- Modify: `plugins/worktree/server/server/main.py` (import + register zoxide tools)
- Modify: `plugins/worktree/server/pyproject.toml` (add zoxide deps if any)
- Delete: `plugins/zoxide/` directory
- Modify: `marketplace.json` (remove zoxide entry)
- Modify: installer (remove zoxide plugin)

- [ ] **Step 1: Read zoxide dependencies**

```bash
cat /home/raul/worktrees/cpm/todo-605.6/plugins/zoxide/server/pyproject.toml
```

Note any unique deps not in worktree's pyproject.toml.

- [ ] **Step 2: Copy zoxide tools into worktree**

```bash
cp /home/raul/worktrees/cpm/todo-605.6/plugins/zoxide/server/server/tools/zoxide.py \
   /home/raul/worktrees/cpm/todo-605.6/plugins/worktree/server/server/tools/zoxide.py
```

- [ ] **Step 3: Register zoxide tools in worktree main.py**

In `plugins/worktree/server/server/main.py`, add:

```python
from .tools import zoxide as _zoxide_tools
# in the register_all() or equivalent function:
_zoxide_tools.register(app)
```

- [ ] **Step 4: Add missing deps to worktree pyproject.toml**

If zoxide tools need deps (e.g. subprocess, pathlib — likely stdlib only), no changes needed. If third-party deps, add them.

- [ ] **Step 5: Write smoke test**

```bash
# in plugins/worktree/server/tests/ add:
def test_zoxide_tools_registered():
    from server.main import create_app
    app = create_app()
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "zoxide_boost" in tool_names
    assert "zoxide_query" in tool_names
    assert "zoxide_remove" in tool_names
```

- [ ] **Step 6: Run worktree tests**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/worktree/server
uv run pytest tests/ -q --tb=short
```

- [ ] **Step 7: Update marketplace.json + installer**

Remove zoxide plugin entry from `marketplace.json`. Remove from installer plugin list.

- [ ] **Step 8: Delete zoxide directory**

```bash
rm -rf /home/raul/worktrees/cpm/todo-605.6/plugins/zoxide
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(605.8): fold zoxide plugin into worktree MCP server"
```

---

### Task 12: Fold sandbox → proj

Move all ~14 sandbox tools into the proj MCP server. Tool names unchanged (hook dispatch unaffected).

**Files:**
- Copy: `plugins/sandbox/server/server/tools/settings.py` → `plugins/proj/server/server/tools/sandbox.py`
- Copy: `plugins/sandbox/server/server/lib/` → integrate into proj lib or import from local
- Modify: `plugins/proj/server/server/main.py` (register sandbox tools)
- Modify: `plugins/proj/server/pyproject.toml` (add sandbox deps if any)
- Delete: `plugins/sandbox/` directory
- Modify: `marketplace.json` (remove sandbox entry)
- Modify: installer

- [ ] **Step 1: Read sandbox server structure**

```bash
ls /home/raul/worktrees/cpm/todo-605.6/plugins/sandbox/server/server/
ls /home/raul/worktrees/cpm/todo-605.6/plugins/sandbox/server/server/lib/
cat /home/raul/worktrees/cpm/todo-605.6/plugins/sandbox/server/pyproject.toml
```

- [ ] **Step 2: Copy sandbox tools into proj**

```bash
cp /home/raul/worktrees/cpm/todo-605.6/plugins/sandbox/server/server/tools/settings.py \
   /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server/server/tools/sandbox.py
# Copy lib files needed by sandbox tools:
cp -r /home/raul/worktrees/cpm/todo-605.6/plugins/sandbox/server/server/lib/ \
      /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server/server/lib/sandbox/
```

Update imports in the copied file to reference the new lib path.

- [ ] **Step 3: Register sandbox tools in proj main.py**

```python
from .tools import sandbox as _sandbox_tools
_sandbox_tools.register(app)
```

- [ ] **Step 4: Write smoke test for sandbox in proj**

```python
def test_sandbox_tools_registered_in_proj():
    from server.main import create_app
    app = create_app()
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "sandbox_add_domain" in tool_names
    assert "sandbox_add_write_path" in tool_names
```

- [ ] **Step 5: Run proj tests**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server
uv run pytest tests/ -q --tb=short
```

- [ ] **Step 6: Update marketplace.json + installer**

Remove sandbox entry from `marketplace.json`. Remove from installer plugin list. Note: `settings.json` MCP allow rule `mcp__plugin_sandbox_sandbox__*` → users should reinstall; changelog documents this.

- [ ] **Step 7: Delete sandbox directory**

```bash
rm -rf /home/raul/worktrees/cpm/todo-605.6/plugins/sandbox
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(605.8): fold sandbox plugin into proj MCP server"
```

---

## Phase 605.9 — File Format Legacy Removal

### Task 13: Remove YAML fallback paths

**Files:**
- Modify: `plugins/proj/server/server/lib/migration.py`
- Modify: `plugins/proj/server/server/lib/sql_todos.py` (any YAML load paths)
- Keep: `archive.yaml.bak` fallback in `load_archived_todos` (disaster recovery)

- [ ] **Step 1: Find all YAML fallback paths**

```bash
grep -n "yaml\|\.yaml" /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server/server/lib/migration.py
grep -n "yaml\|\.yaml" /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server/server/lib/sql_todos.py
grep -rn "load_todos.*yaml\|todos\.yaml\|fallback.*yaml" /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server/server/lib/ --include="*.py"
```

- [ ] **Step 2: Remove fallback logic**

For each YAML fallback path found (other than `archive.yaml.bak` in `load_archived_todos`):
- If the code checks `if data.db exists → use sqlite, else load yaml`: remove the else branch, make sqlite the only path
- If `data.db` is missing, the code should now raise `FileNotFoundError` or a clear error message

- [ ] **Step 3: Run tests**

```bash
cd /home/raul/worktrees/cpm/todo-605.6/plugins/proj/server
uv run pytest tests/ -q --tb=short
```

Any test that relied on YAML fallback will now fail — update those tests to use a pre-seeded sqlite DB.

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/server/server/lib/migration.py \
        plugins/proj/server/server/lib/sql_todos.py
# + any test changes
git commit -m "feat(605.9): remove YAML fallback from storage layer — sqlite only"
```

---

## Phase 605.10 — Version Bump + Changelog

### Task 14: Version bump + CHANGELOG

**Files:**
- Modify: `plugins/*/plugin.json` (all remaining plugins: proj, trello, jira, todoist, worktree, router)
- Modify: `marketplace.json` (update versions for all plugins)
- Create: `CHANGELOG.md`

- [ ] **Step 1: Gate — verify all tests pass**

```bash
cd /home/raul/worktrees/cpm/todo-605.6
for plugin in proj trello jira todoist worktree router; do
  echo "=== $plugin ===" && (cd plugins/$plugin/server && uv run pytest tests/ -q --tb=short 2>&1 | tail -3)
done
```

All must pass before bumping.

- [ ] **Step 2: Bump all plugins to 5.0.0**

In each `plugins/<name>/plugin.json` (for proj, trello, jira, todoist, worktree, router — excluding removed plugins), set `"version": "5.0.0"`.

In `marketplace.json`, update version for each corresponding entry.

```bash
# Verify
grep -r '"version"' plugins/*/plugin.json marketplace.json | grep -v "5.0.0\|.venv"
```
Expected: no results (all at 5.0.0).

- [ ] **Step 3: Write CHANGELOG.md**

Create `CHANGELOG.md` at repo root:

```markdown
# Changelog

## 5.0.0 — 2026-04-15

Breaking changes. No backward-compat shims. Update skill files and hook configs on upgrade.

### Removed tools (use replacement)
- `todo_add_child(parent_id, title, ...)` → `todo_add(title, parent=parent_id, ...)`
- `todo_batch_add_children(parent_id, children)` → `todo_add(title, parent=parent_id, children=<json>)`
- `todo_batch_complete(todo_ids)` → `todo_complete(todo_ids=[...])`
- `todo_block(todo_id, blocks_ids)` → `todo_update(todo_id=blocked_id, blocked_by_set=[blocker_id])`
- `todo_unblock(todo_id)` → `todo_update(todo_id=todo_id, blocked_by_set=[])`
- `proj_todoist_full_sync()` → `proj_sync(integration="todoist")`
- `proj_trello_full_sync()` → `proj_sync(integration="trello")`
- `proj_jira_full_sync()` → `proj_sync(integration="jira")`
- [list trello/jira/todoist/sandbox/worktree merged tools from 605.7]

### Removed plugins (functionality folded)
- `analyse` → skills available as `proj:review`, `proj:explore`
- `zoxide` → tools (`zoxide_boost`, `zoxide_query`, `zoxide_remove`) now in `worktree` MCP server
- `sandbox` → tools now in `proj` MCP server

### Removed config fields (605.3, already shipped in 4.x)
- `team_mode.*`, `resilience.*`, `smart_gate.*` (→ single bool), `context_injection.*` (→ single bool)
- `claudemd_management`, `*_integration` flags

### Removed SKILL.md phases (605.4, already shipped in 4.x)
- Phase A.5b, C0, C0.5b, C1.5, B.5 removed from `/proj:run`
- `--with-adversarial-review` flag re-enables A.5b + C0.5b

### Hook migration
Run `scripts/migrate-hooks.sh` (or `python scripts/migrate_hooks.py`) to update `~/.claude/hooks.yaml`.
The script renames removed trigger_tool values and updates hook targets. Dry-run: `--dry-run`.

### Upgrade path
1. Run migration script: `python scripts/migrate_hooks.py --dry-run` then without `--dry-run`
2. Reinstall plugin: removes old MCP server entries (zoxide, sandbox), adds updated ones
3. Update any custom skill files that call removed tool names
```

- [ ] **Step 4: Commit**

```bash
git add plugins/*/plugin.json marketplace.json CHANGELOG.md
git commit -m "feat(605.10): bump all plugins to 5.0.0 + CHANGELOG"
```

---

### Task 15: Merge worktree to dev

- [ ] **Step 1: Final test pass on all plugins**

```bash
cd /home/raul/worktrees/cpm/todo-605.6
for plugin in proj trello jira todoist worktree router; do
  (cd plugins/$plugin/server && uv run pytest tests/ -q 2>&1 | tail -2)
done
```

- [ ] **Step 2: Rebase onto dev**

```bash
cd /home/raul/worktrees/cpm/todo-605.6
git fetch origin
git rebase origin/dev
```

Fix any conflicts. Re-run tests after rebase.

- [ ] **Step 3: Merge to dev**

```bash
cd /home/raul/projects/claude-project-manager
git checkout dev
git merge --ff-only todo-605.6
git push origin dev
```

- [ ] **Step 4: Mark todos complete**

Mark 605.6, 605.7, 605.8, 605.9, 605.10, 605 complete via `todo_batch_complete`.

- [ ] **Step 5: Remove worktree**

```bash
git worktree remove /home/raul/worktrees/cpm/todo-605.6
git branch -d todo-605.6
```

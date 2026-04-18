# Task 2 — Flat-Model Schema + Field Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the long-forgotten Task 2 of `2026-04-17-636-phase2-flat-model-cleanup.md`: drop the `parent`, `children`, `next_child_id` SQL columns + `Todo` dataclass fields + adapt every remaining caller that still reads them. Unblocks the `cpm-install --migrate` path (currently crashes with `no such column: parent` on `ensure_db` → `CREATE INDEX idx_todos_parent ON todos(parent)` because the migration dropped the columns but the server code still references them).

**Architecture:** Bottom-up in 7 tasks. Task 1 fixes the SQL layer (minimum change to unblock the migration crash). Tasks 2-6 adapt the remaining readers. Task 7 drops the model fields last — that produces loud `AttributeError`s on any remaining overlooked caller. Each task ends with a green `uv run pytest -q --no-cov`, a self-contained commit, and leaves the tree in a working state.

**Tech Stack:** Python 3.13, SQLite (stdlib), dataclasses, uv, pytest, FastMCP, basedpyright, ruff.

**Predicates:**
- 624 + 636-Task-1 + 636-Task-3 (e316aa4) already merged to dev
- Worktree: `/home/raul/worktrees/cpm/feat-636-task2-schema-field-cleanup`, branch `feat/636-task2-schema-field-cleanup`
- Baseline passes: `cd plugins/proj/server && uv run pytest -q --no-cov` — run once before starting
- Live DBs were rolled back to pre-migration snapshots; no real data depends on this branch landing

**Test-sweep commands:**
```bash
cd plugins/proj/server && uv run pytest -q --no-cov
cd plugins/proj/server && uv run ruff check . && uv run ruff format --check .
cd plugins/proj/server && uv run basedpyright server/
cd installer && uv run pytest -q --no-cov                   # should stay green — installer not touched
cd plugins/router/server && uv run pytest -q --no-cov       # should stay green — router not touched
```

---

## File Structure

**Modified files:**
- `plugins/proj/server/server/lib/db.py` — drop 3 cols from `_TODO_COLUMNS` + drop `CREATE INDEX idx_todos_parent`
- `plugins/proj/server/server/lib/sql_todos.py` — drop 3 keys from `_todo_to_row` + drop 3 kwargs from `_row_to_todo`
- `plugins/proj/server/server/lib/sql_archive.py` — drop 3 positions from `_todo_to_row` tuple + drop 3 col names from `_INSERT_COLS` + decrement `_PLACEHOLDERS` count (27→24)
- `plugins/proj/server/server/lib/ids.py` — replace `parent.next_child_id` counter with sibling-scan helper
- `plugins/proj/server/server/lib/models.py` — drop `Todo.parent`, `Todo.children`, `Todo.next_child_id` fields + corresponding `to_dict`/`from_dict` entries
- `plugins/proj/server/server/tools/content.py` — drop comment referring to `.parent` fallback (line 262)
- `plugins/proj/server/server/tools/todos.py` — drop `"children": t.children` key from `todo_analyze_graph` output (line 1844)
- `plugins/proj/server/server/tools/trello_sync.py` — drop `.parent`/`.children` reads; use group-tag lookup
- `plugins/proj/server/server/tools/trello_migration.py` — drop `.parent` reads; use group-tag lookup
- `plugins/proj/server/server/tools/migrate.py` — port ID-remap logic from `.parent`/`.children` fields to group-tag scanning
- `plugins/proj/server/server/tools/todoist_full_sync.py` — biggest file (~20 sites); replace `.parent`/`.children` reads with tag-based helpers
- Test files touched transitively (see each task)

**Not changed (out of scope):**
- `installer/migrations/**` — migration already produces the flat-schema DBs we need to support; no changes here
- Anything outside `plugins/proj/server/**`
- `plugins/proj/skills/**` — Task 4 of the parent plan deletes `flatten-children` skill; out of scope here

---

## Task 1: Unblock the migration crash — drop columns from the SQL layer

**Why first:** This commit alone makes `ensure_db` idempotent on a flat (post-migration) DB and makes `_todo_to_row`/`_row_to_todo` stop persisting the 3 fields. The `Todo` dataclass still has the fields (defaults kick in on read-back), so no downstream reader breaks — that's what Tasks 2-6 fix later.

**Files:**
- Modify: `plugins/proj/server/server/lib/db.py:19-47, 66`
- Modify: `plugins/proj/server/server/lib/sql_todos.py:21-59, 78-120`
- Modify: `plugins/proj/server/server/lib/sql_archive.py:21-64`
- Test: `plugins/proj/server/tests/test_db_flat_schema.py` (new)
- Test: `plugins/proj/server/tests/test_sql_todos.py` (existing — update)

- [ ] **Step 1: Write the failing schema-shape test**

Create `plugins/proj/server/tests/test_db_flat_schema.py`:

```python
"""Flat-schema invariants: no parent/children/next_child_id in todos or archive_todos."""
from __future__ import annotations

from pathlib import Path

from server.lib.db import ensure_db, get_connection
from server.lib.models import ProjConfig


def _col_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _index_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}


def test_ensure_db_creates_flat_todos_schema(tmp_path: Path) -> None:
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db = ensure_db(cfg, "demo")
    with get_connection(db) as conn:
        cols = _col_names(conn, "todos")
    assert "parent" not in cols, f"todos.parent must be dropped, got cols={sorted(cols)}"
    assert "children" not in cols, "todos.children must be dropped"
    assert "next_child_id" not in cols, "todos.next_child_id must be dropped"


def test_ensure_db_creates_flat_archive_schema(tmp_path: Path) -> None:
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db = ensure_db(cfg, "demo")
    with get_connection(db) as conn:
        cols = _col_names(conn, "archive_todos")
    assert "parent" not in cols
    assert "children" not in cols
    assert "next_child_id" not in cols


def test_ensure_db_has_no_parent_index(tmp_path: Path) -> None:
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db = ensure_db(cfg, "demo")
    with get_connection(db) as conn:
        indexes = _index_names(conn, "todos")
    assert "idx_todos_parent" not in indexes, (
        f"stale parent index must be dropped, got indexes={sorted(indexes)}"
    )


def test_ensure_db_idempotent_on_pre_migrated_db(tmp_path: Path) -> None:
    """Simulate the real bug: DB where `parent` col was dropped by the flat-todo
    migration. Re-opening must NOT try to CREATE INDEX on todos(parent).
    """
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db_path = tmp_path / "demo" / "data.db"
    # Minimal pre-migrated schema: flat todos, no parent col
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE todos (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'medium',
                created TEXT NOT NULL, updated TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]'
            )
        """)
        conn.execute("CREATE TABLE archive_todos AS SELECT * FROM todos WHERE 0")
    # This call must NOT raise sqlite3.OperationalError
    ensure_db(cfg, "demo")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/proj/server && uv run pytest tests/test_db_flat_schema.py -v --no-cov`

Expected: all 4 tests FAIL. Two fail with `assert "parent" not in cols`, one with `"idx_todos_parent" not in indexes`, and `test_ensure_db_idempotent_on_pre_migrated_db` fails with `sqlite3.OperationalError: no such column: parent`.

- [ ] **Step 3: Drop columns from `_TODO_COLUMNS` + drop the parent index in `db.py`**

In `plugins/proj/server/server/lib/db.py`, replace the `_TODO_COLUMNS` block + the index line:

```python
_TODO_COLUMNS = """
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    git_branch TEXT,
    git_commits TEXT NOT NULL DEFAULT '[]',
    blocks TEXT NOT NULL DEFAULT '[]',
    blocked_by TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    has_requirements INTEGER NOT NULL DEFAULT 0,
    has_research INTEGER NOT NULL DEFAULT 0,
    todoist_task_id TEXT,
    todoist_desc_synced TEXT NOT NULL DEFAULT '',
    trello_card_id TEXT,
    trello_checklist_id TEXT,
    trello_checklist_item_id TEXT,
    jira_issue_key TEXT,
    jira_comment_ids TEXT NOT NULL DEFAULT '[]',
    due_date TEXT,
    trello_sync_state TEXT
"""
```

And in `_SCHEMA_SQL`, DELETE this line:

```
CREATE INDEX IF NOT EXISTS idx_todos_parent ON todos(parent);
```

Do NOT drop the `idx_todos_project`, `idx_todos_project_status`, `idx_todos_todoist`, `idx_todos_trello`, `idx_todos_jira`, `idx_archive_project`, `idx_archive_project_status` indexes — they reference still-present columns.

- [ ] **Step 4: Drop `parent`/`children`/`next_child_id` keys in `sql_todos._todo_to_row` + `_row_to_todo`**

In `plugins/proj/server/server/lib/sql_todos.py`:

Delete lines 39-41 from `_todo_to_row`:
```python
        "parent": todo.parent,
        "children": json.dumps(todo.children),
        "next_child_id": todo.next_child_id,
```

Delete lines 98-100 from `_row_to_todo`:
```python
        parent=row["parent"],
        children=_safe_json_loads(row["children"], []),
        next_child_id=row["next_child_id"],
```

- [ ] **Step 5: Drop 3 positions from the `sql_archive._todo_to_row` tuple + shrink column lists**

In `plugins/proj/server/server/lib/sql_archive.py`:

Delete lines 32-34 from the tuple:
```python
        t.parent,
        json.dumps(t.children),
        t.next_child_id,
```

Replace the `_INSERT_COLS` constant (lines 55-62) with:
```python
_INSERT_COLS = """(
    id, project, title, status, priority, created, updated,
    tags, git_branch, git_commits,
    blocks, blocked_by, notes, has_requirements, has_research,
    todoist_task_id, todoist_desc_synced, trello_card_id,
    trello_checklist_id, trello_checklist_item_id, jira_issue_key,
    jira_comment_ids, due_date, trello_sync_state
)"""
```

Change `_PLACEHOLDERS` from 27 to 24:
```python
_PLACEHOLDERS = "(" + ", ".join(["?"] * 24) + ")"
```

- [ ] **Step 6: Run the new test file — expect all 4 tests pass**

Run: `cd plugins/proj/server && uv run pytest tests/test_db_flat_schema.py -v --no-cov`

Expected: 4 passed.

- [ ] **Step 7: Run the full sql_todos test — catch any fallout from the `Todo(parent=..., children=...)` defaults path**

Run: `cd plugins/proj/server && uv run pytest tests/test_sql_todos.py tests/test_sql_archive.py tests/test_storage.py -v --no-cov`

Expected: all pass (the fields default to `None`/`[]`/`1` on the dataclass — round-trip just loses them instead of persisting).

If `test_storage.py::test_save_load_roundtrip` asserts on `loaded.parent == "T001"` (see line 84: `Todo(id="T002", ..., parent="T001", ...)`), that's a test fixture bug that Task 6 cleans up. For now, xfail or delete the assertion line on parent if needed — but the test itself should otherwise pass.

- [ ] **Step 8: Run the whole suite**

Run: `cd plugins/proj/server && uv run pytest -q --no-cov 2>&1 | tail -30`

Expected: most pass. Note any new failures — they fall into two categories:
1. Tests that constructed `Todo(parent=X, children=[...])` and asserted on round-trip → Task 6 cleans them up. If a test already expected `parent=None` after round-trip (i.e., it was testing flat-model behavior proactively), it should now pass.
2. Tests that exercise `.parent`/`.children` READERS in production code (trello_sync, todoist_full_sync, etc.) → those are OK because reads still return the dataclass default. No crash expected.

Capture the exact failing-test list; each will be addressed in Tasks 2-6.

- [ ] **Step 9: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-636-task2-schema-field-cleanup
git add plugins/proj/server/server/lib/db.py \
        plugins/proj/server/server/lib/sql_todos.py \
        plugins/proj/server/server/lib/sql_archive.py \
        plugins/proj/server/tests/test_db_flat_schema.py
git commit -m "feat(proj/sql): drop parent/children/next_child_id columns + stale index (636 Task 2a)

Unblocks 'cpm-install --migrate' on already-flat DBs.
ensure_db is now idempotent on post-migration DBs and no longer tries
to CREATE INDEX idx_todos_parent ON todos(parent).

Todo dataclass still has the 3 fields (defaults to None/[]/1); Task 2f drops them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `ids.py` — derive next-child-id from sibling scan

**Why:** `next_todo_id(meta, parent=X)` returns `{parent.id}.{N}` where N is `parent.next_child_id`. Once Task 7 drops that field, we need another way to compute N. The flat model stores child membership via the `group:<parent.id>` tag, so scan siblings at add-time.

**Files:**
- Modify: `plugins/proj/server/server/lib/ids.py`
- Modify: `plugins/proj/server/tests/test_ids.py`

- [ ] **Step 1: Write the failing test for sibling-scan semantics**

Replace the test body of `plugins/proj/server/tests/test_ids.py` (keep existing imports) — add these tests:

```python
from server.lib.ids import next_todo_id
from server.lib.models import ProjectMeta, Todo


def _meta(n: int = 1) -> ProjectMeta:
    return ProjectMeta(name="demo", next_todo_id=n)


def test_root_id_from_meta_counter() -> None:
    meta = _meta(5)
    assert next_todo_id(meta) == "5"
    assert meta.next_todo_id == 6


def test_child_id_from_empty_siblings() -> None:
    parent = Todo(id="3", title="P", tags=[])
    meta = _meta()
    # First child: no existing siblings under group:3
    assert next_todo_id(meta, parent=parent, siblings=[]) == "3.1"


def test_child_id_increments_past_existing_siblings() -> None:
    parent = Todo(id="3", title="P")
    siblings = [
        Todo(id="3.1", title="C1", tags=["group:3"]),
        Todo(id="3.2", title="C2", tags=["group:3"]),
    ]
    meta = _meta()
    assert next_todo_id(meta, parent=parent, siblings=siblings) == "3.3"


def test_child_id_handles_out_of_order_siblings() -> None:
    parent = Todo(id="5", title="P")
    siblings = [
        Todo(id="5.3", title="C3", tags=["group:5"]),
        Todo(id="5.1", title="C1", tags=["group:5"]),
    ]
    meta = _meta()
    # Max seen child index is 3 → next is 4
    assert next_todo_id(meta, parent=parent, siblings=siblings) == "5.4"


def test_child_id_handles_nested_parent_id() -> None:
    parent = Todo(id="3.2", title="P")
    siblings = [Todo(id="3.2.1", title="C1", tags=["group:3.2"])]
    meta = _meta()
    assert next_todo_id(meta, parent=parent, siblings=siblings) == "3.2.2"
```

Remove the old `FakeTodo(next_child_id=...)` tests — `next_child_id` no longer exists as an input.

- [ ] **Step 2: Run test — expect FAIL on the new signature**

Run: `cd plugins/proj/server && uv run pytest tests/test_ids.py -v --no-cov`

Expected: FAIL with `TypeError: next_todo_id() got an unexpected keyword argument 'siblings'`.

- [ ] **Step 3: Rewrite `ids.py`**

Replace `plugins/proj/server/server/lib/ids.py` with:

```python
"""Todo ID generation (flat model — child IDs derived from sibling scan)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.lib.models import ProjectMeta, Todo


def next_todo_id(
    meta: ProjectMeta,
    parent: Todo | None = None,
    siblings: list[Todo] | None = None,
) -> str:
    """Return the next todo ID.

    - Root todos (no parent): returns str(meta.next_todo_id) and increments meta.
    - Child todos: returns ``f"{parent.id}.{N}"`` where N is max existing child
      sequence + 1, scanning *siblings* for ids shaped ``f"{parent.id}.<int>"``.
      Does NOT mutate any todo — callers own sibling state.

    *siblings* should be the list of todos already present in the project;
    pass [] for a fresh batch. Raises ValueError if a parent is given but
    siblings is None (prevents silent double-numbering bugs).
    """
    if parent is None:
        tid = str(meta.next_todo_id)
        meta.next_todo_id += 1
        return tid
    if siblings is None:
        raise ValueError("siblings= required when parent is given")
    prefix = f"{parent.id}."
    max_seen = 0
    for s in siblings:
        if not s.id.startswith(prefix):
            continue
        tail = s.id[len(prefix):]
        # Only count direct children (no further dots)
        if "." in tail:
            continue
        try:
            n = int(tail)
        except ValueError:
            continue
        max_seen = max(max_seen, n)
    return f"{prefix}{max_seen + 1}"
```

- [ ] **Step 4: Update the 3 production callers**

Grep for callers (expected: `plugins/proj/server/server/tools/todos.py:411`, `:683`, `plugins/proj/server/server/tools/todoist_full_sync.py:960`):

```bash
cd plugins/proj/server && grep -n "next_todo_id(" server/ -r --include="*.py"
```

For each call site, the caller already has the project's full todo list in scope. Adapt:

1. `server/tools/todos.py:411` (inside `_batch_add_children`): `all_todos` is in scope as `todos`. Add `siblings=todos` kwarg.

2. `server/tools/todos.py:683` (inside `todo_add` with parent): `todos` is the already-loaded list. Add `siblings=todos` kwarg.

3. `server/tools/todoist_full_sync.py:960` (inside child-creation loop): the local todos list is named `todos` (verify with a read of the enclosing function). Add `siblings=todos` kwarg.

Exact Edit for each — use Read first to get the current line and insert `siblings=todos` before the closing paren of the `next_todo_id(...)` call.

- [ ] **Step 5: Run ids tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_ids.py -v --no-cov`

Expected: 5 passed.

- [ ] **Step 6: Run the todos + todoist-sync caller tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_todos.py tests/test_todoist_full_sync.py tests/test_batch_add_children.py -q --no-cov 2>&1 | tail -20`

Expected: pass. Any failure is most likely the `.parent`/`.children` reads that Tasks 3-4 still have to fix — note the tests, move on.

- [ ] **Step 7: Commit**

```bash
git add plugins/proj/server/server/lib/ids.py \
        plugins/proj/server/tests/test_ids.py \
        plugins/proj/server/server/tools/todos.py \
        plugins/proj/server/server/tools/todoist_full_sync.py
git commit -m "feat(proj/ids): derive next-child-id from sibling scan, drop next_child_id dep (636 Task 2b)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Adapt `content.py`, `todos.py`, `trello_sync.py`, `trello_migration.py`

**Why group these:** Each has a small, local `.parent`/`.children` read that can be replaced 1:1 with a group-tag lookup — no restructure needed. Keeping them in one task keeps the commit contained.

**Helper to add first (used by this task and task 4):** A small utility `_parent_id_from_tags(tags)` already exists in `plugins/proj/server/server/tools/todos.py` as `_parent_id_from_tag`. Reuse it, don't reimplement. Import from there, or move it to `plugins/proj/server/server/lib/group_tags.py` to avoid an upward import from `tools/` into `lib/` — decide at first use. **Default: move the helper to `lib/group_tags.py`** with signature `def parent_id_from_tags(tags: list[str]) -> str | None`. Update the existing call site in `todos.py` to use the lib-level helper.

- [ ] **Step 1: Write a test for the lib-level group-tag helper**

Create `plugins/proj/server/tests/test_group_tags.py`:

```python
from server.lib.group_tags import parent_id_from_tags


def test_extracts_parent_id_from_group_tag() -> None:
    assert parent_id_from_tags(["group:3"]) == "3"


def test_extracts_nested_parent_id() -> None:
    assert parent_id_from_tags(["group:3.2"]) == "3.2"


def test_returns_none_when_no_group_tag() -> None:
    assert parent_id_from_tags(["feature", "urgent"]) is None


def test_ignores_malformed_group_tag() -> None:
    assert parent_id_from_tags(["group:"]) is None


def test_returns_first_group_tag_when_multiple() -> None:
    # Defensive — multiple group tags shouldn't exist, but pick a deterministic one
    assert parent_id_from_tags(["group:3", "group:5"]) == "3"
```

- [ ] **Step 2: Run test — expect FAIL (module missing)**

Run: `cd plugins/proj/server && uv run pytest tests/test_group_tags.py -v --no-cov`

Expected: `ModuleNotFoundError: No module named 'server.lib.group_tags'`.

- [ ] **Step 3: Create `plugins/proj/server/server/lib/group_tags.py`**

```python
"""Flat-model group-tag helpers: ``group:<parent_id>`` tags encode parent membership."""

from __future__ import annotations

_GROUP_PREFIX = "group:"


def parent_id_from_tags(tags: list[str]) -> str | None:
    """Return the parent id encoded in the first ``group:<id>`` tag, or None.

    The flat model stores parent membership on children as ``group:<parent.id>``.
    Returns None when no group tag is present or the tag has an empty id.
    """
    for tag in tags:
        if tag.startswith(_GROUP_PREFIX):
            pid = tag[len(_GROUP_PREFIX):]
            if pid:
                return pid
    return None
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd plugins/proj/server && uv run pytest tests/test_group_tags.py -v --no-cov` — Expected: 5 passed.

- [ ] **Step 5: Adopt the helper in `tools/todos.py` (kill duplicate)**

Grep for the existing private helper: `cd plugins/proj/server && grep -n "_parent_id_from_tag" server/tools/todos.py`. Replace each call with `parent_id_from_tags(...)`, add `from server.lib.group_tags import parent_id_from_tags` at module top, and delete the private helper function.

- [ ] **Step 6: Fix `tools/content.py:262` — drop `.parent` fallback**

Read lines 250-275 of `plugins/proj/server/server/tools/content.py` to capture the exact surrounding code. The block that currently does something like `parent_id = parent_id_from_tag(t.tags) or t.parent` becomes just `parent_id = parent_id_from_tags(t.tags)`. Also delete the `"# Flat model: parent pointer lives in group:<id> tag; fall back to .parent field"` comment.

- [ ] **Step 7: Fix `tools/todos.py:1844` — drop `"children"` key from `todo_analyze_graph` output**

In `plugins/proj/server/server/tools/todos.py`, read lines 1830-1860 to find the `todo_results.append({...})` block. Delete the single line:
```python
                    "children": t.children,
```
(Graph analysis uses `blocks`/`blocked_by`, not parent/child pointers — the children key was cruft.)

- [ ] **Step 8: Fix `tools/trello_sync.py` — drop `.parent`/`.children` reads**

Read `plugins/proj/server/server/tools/trello_sync.py:140-236` for exact shape, then:

1. Lines 144-146: the "Children" block in the description builder — in the flat model, a todo's children live on *siblings* with `group:<id>` tag, not on the todo itself. Delete the block entirely. The description still has Title / Due / Tags / Blocked-by / Notes — plenty of context.
2. Line 189: `roots = [t for t in todos if t.parent is None]` — in the flat model every non-child todo is a "root". Replace with:
   ```python
   from server.lib.group_tags import parent_id_from_tags
   roots = [t for t in todos if parent_id_from_tags(t.tags) is None]
   ```
3. Lines 211-235 `_topo_sort_todos`: the flat model has no parent/child topology, so topo-sort degenerates to "return todos in insertion order". Replace the function body with `return list(todos)` and delete the inner `_visit` logic. Keep the signature + docstring but update the docstring: `"""Return todos in insertion order (flat model has no tree topology)."""`.

- [ ] **Step 9: Fix `tools/trello_migration.py` — drop `.parent` reads**

Read `plugins/proj/server/server/tools/trello_migration.py:210-240` to capture the exact block, then replace the lookup that currently does `if todo.parent: parent = todo_map.get(todo.parent) ... "Failed to link todo {todo.id} to parent {todo.parent}"` with:

```python
from server.lib.group_tags import parent_id_from_tags

parent_id = parent_id_from_tags(todo.tags)
if parent_id:
    parent = todo_map.get(parent_id)
    if parent is None:
        errors.append(f"Failed to link todo {todo.id}: parent {parent_id} missing")
        continue
    # ... rest of the linking logic unchanged, but use `parent_id` in error messages
```

Update the `f"Failed to link todo {todo.id} to parent {todo.parent}: {e}"` message → `f"Failed to link todo {todo.id} to parent {parent_id}: {e}"`.

- [ ] **Step 10: Run the affected test suites**

Run:
```bash
cd plugins/proj/server && uv run pytest tests/test_content.py tests/test_todos_analyze_graph.py tests/test_trello_sync.py tests/test_trello_migration.py -q --no-cov
```

Expected: pass. If `test_trello_sync.py` asserts on `"Children:"` appearing in a description, update the test to reflect the flat model (description no longer has Children line).

- [ ] **Step 11: Commit**

```bash
git add plugins/proj/server/server/lib/group_tags.py \
        plugins/proj/server/server/tools/todos.py \
        plugins/proj/server/server/tools/content.py \
        plugins/proj/server/server/tools/trello_sync.py \
        plugins/proj/server/server/tools/trello_migration.py \
        plugins/proj/server/tests/test_group_tags.py \
        plugins/proj/server/tests/test_trello_sync.py
git commit -m "refactor(proj): adopt lib.group_tags + drop .parent/.children reads in content/todos/trello_* (636 Task 2c)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Adapt `todoist_full_sync.py` (biggest single file)

**Why separate:** ~20 sites read `.parent` / `.children` in this file. The sync logic is stateful: it builds local→remote mappings, handles orphans, and walks descendants to build Todoist task hierarchies. In the flat model, the "hierarchy" is one level deep (parent + direct children via `group:<id>` tag). No recursive descendant walk.

**File:**
- Modify: `plugins/proj/server/server/tools/todoist_full_sync.py`
- Modify: `plugins/proj/server/tests/test_todoist_full_sync.py` (big fixture update)

**Grep contract:** after this task completes, `grep -n '\.parent\b\|\.children\b' plugins/proj/server/server/tools/todoist_full_sync.py | grep -v path.parent` must return zero lines.

- [ ] **Step 1: Write a sync-level invariant test**

Append to `plugins/proj/server/tests/test_todoist_full_sync.py`:

```python
def test_full_sync_reads_no_parent_field(monkeypatch) -> None:
    """Defensive: any attr-read on Todo.parent in the sync path is a bug.

    Fails fast if production code regresses to reading `.parent` after this cleanup.
    """
    from server.lib.models import Todo
    accesses: list[str] = []
    orig_getattr = Todo.__getattribute__

    def recording_getattr(self, name: str):
        if name in ("parent", "children", "next_child_id"):
            accesses.append(name)
        return orig_getattr(self, name)

    monkeypatch.setattr(Todo, "__getattribute__", recording_getattr)

    # Drive a representative read-only sync path that exercises many of the
    # old .parent/.children sites. Use an existing fixture helper from this file
    # (e.g. `_run_fetch_and_diff_smoke(...)`). If no such helper exists, create
    # one that: loads 3 todos (1 root + 2 children via group tag), runs the
    # fetch half of full_sync, and asserts accesses == [].
    # Pseudocode — adapt to whatever helper exists in this test file:
    # _run_fetch_half(todos=[root, child1_with_group_tag, child2_with_group_tag])
    # assert accesses == [], f"production code read legacy fields: {accesses}"
```

*Implementer note:* the first time you run this test it fails by design — that's how you find the remaining `.parent`/`.children` sites. Treat each accessed name as a TODO for Step 3.

- [ ] **Step 2: Run the test — capture the full list of accesses from the failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todoist_full_sync.py::test_full_sync_reads_no_parent_field -v --no-cov 2>&1 | tail -40`

Expected: FAIL. Record the `accesses` list from the assertion message.

- [ ] **Step 3: For each access, convert `.parent` reads into group-tag reads**

Line-by-line conversion recipe (apply to every site found in Step 2 and in the earlier grep — representative examples from lines 218-2089):

- `if todoist_id and todo.parent:` → `if todoist_id and parent_id_from_tags(todo.tags):`
- `if not todo.parent:` → `if parent_id_from_tags(todo.tags) is None:`
- `linked_local.parent` → `parent_id_from_tags(linked_local.tags)`
- `local_child_parents.add(linked_local.parent)` → `pid = parent_id_from_tags(linked_local.tags); if pid: local_child_parents.add(pid)`
- `todo.parent in unlinked_ids` → `parent_id_from_tags(todo.tags) in unlinked_ids`
- `todo_map.get(todo.parent)` → `todo_map.get(parent_id_from_tags(todo.tags))`
- `"_parent_local_id": todo.parent` → `"_parent_local_id": parent_id_from_tags(todo.tags)`
- `if not local_todo.parent:` → `if parent_id_from_tags(local_todo.tags) is None:`
- `if orphan_todo.parent:` → `if parent_id_from_tags(orphan_todo.tags):`
- `if not todo.parent and not todo.children:` → `if parent_id_from_tags(todo.tags) is None and not _has_children_in(todos, todo):`
   - where `_has_children_in(todos, parent)` is a small helper: `return any(parent_id_from_tags(t.tags) == parent.id for t in todos)`
- `parent = todo_map.get(todo.parent)` (line 1793) → `parent_id = parent_id_from_tags(todo.tags); parent = todo_map.get(parent_id)`
- `stack = list(todo.children) if todo.children else []` (descendants walk) — in the flat model there's exactly one level of children; replace the recursive walk with a single scan:
  ```python
  def _direct_children(todos: list[Todo], parent_id: str) -> list[Todo]:
      return [t for t in todos if parent_id_from_tags(t.tags) == parent_id]
  ```
  Use at the call site instead of the recursive `stack`/`while` loop. Delete the recursive descendant function if it becomes unused.
- `parent_todo.children.append(todo.id)` (line 977 / 1080) — in the flat model, parent membership is on the CHILD (tag), not on the parent. Delete the `.append` call; ensure the child being created has `tags=[f"group:{parent_todo.id}"]` in its constructor. If the constructor is a few lines up, just add/verify the tag there.
- `if todo.children and todo.status in TERMINAL_STATUSES` (line 842) — flat model has no family-completion semantics (see Task 3 of the parent plan, e316aa4). If the surrounding branch implements family-propagation logic, DELETE the whole branch — that's dead code in the flat model. Leave only the non-family path.
- `"children_count": len(t.children)` (in context.py:539) — this one is in Task 3, but if it also appears here, do the same: `len(_direct_children(todos, t.id))`.

At module top, add:
```python
from server.lib.group_tags import parent_id_from_tags
```

- [ ] **Step 4: Update fixtures**

`tests/test_todoist_full_sync.py` constructs todos with `t.parent = "1"` (see lines 722, 846, 849). Replace each:

```python
# OLD
t.parent = parent
# NEW
t.tags = list(t.tags) + [f"group:{parent}"]
```

Similarly for `child1.parent = "1"` and any `children=["1.1", "1.2"]` in `Todo(...)` kwargs — drop the kwarg, add the tag on children instead.

- [ ] **Step 5: Run todoist sync tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_todoist_full_sync.py -q --no-cov 2>&1 | tail -30`

Expected: all pass, including the new invariant test `test_full_sync_reads_no_parent_field`.

- [ ] **Step 6: Verify no `.parent`/`.children` left in the file**

Run:
```bash
cd plugins/proj/server && grep -n '\.parent\b\|\.children\b' server/tools/todoist_full_sync.py | grep -v path.parent
```

Expected: empty output.

- [ ] **Step 7: Commit**

```bash
git add plugins/proj/server/server/tools/todoist_full_sync.py \
        plugins/proj/server/tests/test_todoist_full_sync.py
git commit -m "refactor(proj/todoist): resolve parent via group tag, drop .parent/.children reads (636 Task 2d)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Port `tools/migrate.py` (ID remap) to group tags

**Why:** `proj_migrate_ids` renumbers T-prefix IDs → numeric dot-notation. Current implementation walks the parent→children tree. Flat model: the "tree" is 1 level deep, encoded via `group:<id>` tags. Port the remap to walk that.

**Files:**
- Modify: `plugins/proj/server/server/tools/migrate.py`
- Modify: `plugins/proj/server/tests/test_migrate.py`

- [ ] **Step 1: Write a focused remap test**

In `plugins/proj/server/tests/test_migrate.py`, add (at the end of the existing `TestApplyRemap` or a new class):

```python
def test_remap_rewrites_group_tag_instead_of_parent_field(tmp_path) -> None:
    """Post-flat-model: parent membership is in a group:<id> tag, not .parent."""
    from server.tools.migrate import _apply_remap
    from server.lib.models import Todo

    parent = Todo(id="T1", title="P", tags=[])
    child = Todo(id="T2", title="C", tags=["group:T1"])
    id_map = {"T1": "1", "T2": "1.1"}
    _apply_remap([parent, child], id_map)
    assert parent.id == "1"
    assert child.id == "1.1"
    assert "group:1" in child.tags
    assert "group:T1" not in child.tags


def test_remap_rebuilds_id_mapping_from_group_tags(tmp_path) -> None:
    from server.tools.migrate import _build_id_mapping
    from server.lib.models import Todo

    # Two roots + one child under each
    todos = [
        Todo(id="Ta", title="A", created="2026-01-01", tags=[]),
        Todo(id="Tb", title="B", created="2026-01-02", tags=[]),
        Todo(id="Tc", title="C", created="2026-01-03", tags=["group:Ta"]),
        Todo(id="Td", title="D", created="2026-01-04", tags=["group:Tb"]),
    ]
    id_map = _build_id_mapping(todos)
    # Sorted by created: Ta=1, Tb=2, Tc=1.1, Td=2.1
    assert id_map["Ta"] == "1"
    assert id_map["Tb"] == "2"
    assert id_map["Tc"] == "1.1"
    assert id_map["Td"] == "2.1"
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd plugins/proj/server && uv run pytest tests/test_migrate.py::test_remap_rewrites_group_tag_instead_of_parent_field tests/test_migrate.py::test_remap_rebuilds_id_mapping_from_group_tags -v --no-cov`

Expected: FAIL (because `_apply_remap` still rewrites `todo.parent` and `_build_id_mapping` still walks by `.parent`).

- [ ] **Step 3: Rewrite the three helpers in `tools/migrate.py`**

In `plugins/proj/server/server/tools/migrate.py`, replace `_assign_ids`, `_build_id_mapping`, `_apply_remap`:

```python
from server.lib.group_tags import parent_id_from_tags

_GROUP_PREFIX = "group:"


def _assign_ids(
    parent_todos: list[Todo],
    all_todos: list[Todo],
    id_map: dict[str, str],
    prefix: str = "",
) -> None:
    """Recursively assign numeric dot-notation IDs, populating id_map."""
    for i, todo in enumerate(parent_todos, 1):
        new_id = f"{prefix}{i}" if prefix else str(i)
        id_map[todo.id] = new_id
        children = sorted(
            [t for t in all_todos if parent_id_from_tags(t.tags) == todo.id],
            key=lambda t: (t.created, t.id),
        )
        _assign_ids(children, all_todos, id_map, prefix=f"{new_id}.")


def _build_id_mapping(todos: list[Todo]) -> dict[str, str]:
    """Build old→new ID mapping for all todos, sorted by creation date.

    Root = any todo whose tags carry no group:<id> pointing at a known todo.
    """
    known_ids = {t.id for t in todos}
    roots = sorted(
        [
            t for t in todos
            if (pid := parent_id_from_tags(t.tags)) is None or pid not in known_ids
        ],
        key=lambda t: (t.created, t.id),
    )
    id_map: dict[str, str] = {}
    _assign_ids(roots, todos, id_map)
    return id_map


def _apply_remap(todos: list[Todo], id_map: dict[str, str]) -> None:
    """Apply id_map to each todo in-place: id, group:<parent> tag, blocks/blocked_by."""
    for todo in todos:
        todo.id = id_map.get(todo.id, todo.id)
        todo.tags = [
            f"{_GROUP_PREFIX}{id_map.get(tag[len(_GROUP_PREFIX):], tag[len(_GROUP_PREFIX):])}"
            if tag.startswith(_GROUP_PREFIX)
            else tag
            for tag in todo.tags
        ]
        todo.blocks = [id_map.get(b, b) for b in todo.blocks]
        todo.blocked_by = [id_map.get(b, b) for b in todo.blocked_by]
```

Also delete the `root_count = len([t for t in todos if t.parent is None])` line at :206 and recompute from the new mapping: `root_count = sum(1 for v in id_map.values() if "." not in v)`.

- [ ] **Step 4: Run the two new tests + existing suite**

Run: `cd plugins/proj/server && uv run pytest tests/test_migrate.py -q --no-cov 2>&1 | tail -20`

Expected: new tests pass. Any existing test that asserts on `todo.parent` or `todo.children` post-remap — update it to assert on the group tag.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/migrate.py \
        plugins/proj/server/tests/test_migrate.py
git commit -m "refactor(proj/migrate): remap IDs via group tags instead of parent field (636 Task 2e)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Drop `parent`, `children`, `next_child_id` from `Todo` dataclass

**Why last:** With SQL schema + ids + every reader already adapted, dropping the fields now produces AttributeError at exactly the spots that still read them (if any). That's the finish-line check.

**Files:**
- Modify: `plugins/proj/server/server/lib/models.py:906-981`
- Modify: any remaining test / fixture that still constructs `Todo(parent=..., children=..., next_child_id=...)`

- [ ] **Step 1: Write a dataclass-shape assertion**

Append to `plugins/proj/server/tests/test_models.py` (create the file if absent):

```python
from dataclasses import fields

from server.lib.models import Todo


def test_todo_has_no_legacy_tree_fields() -> None:
    names = {f.name for f in fields(Todo)}
    assert "parent" not in names
    assert "children" not in names
    assert "next_child_id" not in names
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd plugins/proj/server && uv run pytest tests/test_models.py::test_todo_has_no_legacy_tree_fields -v --no-cov`

Expected: FAIL (fields still present).

- [ ] **Step 3: Remove the three fields from the dataclass body**

In `plugins/proj/server/server/lib/models.py`, delete these 3 lines from the `Todo` dataclass (currently at 914-916):

```python
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    next_child_id: int = 1
```

Delete from `to_dict` (currently at 946-948):

```python
            "parent": self.parent,
            "children": self.children,
            "next_child_id": self.next_child_id,
```

Delete from `from_dict` (currently at 979-981):

```python
            parent=str(data["parent"]) if isinstance(data.get("parent"), str) else None,
            children=[str(x) for x in _list(data.get("children"))],
            next_child_id=_int(data.get("next_child_id"), 1),
```

- [ ] **Step 4: Run — expect PASS on the new test, failures on fixture code that still passes those kwargs**

Run: `cd plugins/proj/server && uv run pytest -q --no-cov 2>&1 | tail -50`

Expected: `test_todo_has_no_legacy_tree_fields` passes. Several tests fail with `TypeError: Todo.__init__() got an unexpected keyword argument 'parent'` (or `children`, or `next_child_id`).

- [ ] **Step 5: Fix the test fixtures — grep + edit each**

Run:
```bash
cd plugins/proj/server && grep -rn "parent=\|children=\|next_child_id=" tests/ --include="*.py" | grep -E "Todo\(|\.children|\.parent"
```

Known sites (from Task 2 intro grep):
- `tests/test_trello_sync.py:93, 186, 249, 250, 263, 264, 265, 272, 273, 1079, 1080` — `Todo(id=..., parent="X", children=["Y"])`. Replace each `parent="X"` with `tags=["group:X"]` (merge with any existing tags). Delete every `children=["..."]` kwarg — child membership lives on children's tags, not on parents.
- `tests/test_storage.py:84` — `Todo(id="T002", ..., parent="T001", ...)` → replace `parent="T001"` with `tags=["group:T001"]`.
- `tests/test_ids.py:29, 37, 47` — `FakeTodo(id="5", next_child_id=1)` — already superseded by Task 2. Delete these tests if they still exist.
- `tests/test_todoist_full_sync.py` — touched in Task 4; sanity-check nothing slipped through.
- `tests/test_jira_apply_mapping_flat.py:133` — `assert st_todo.parent is None` → either delete (field gone) or replace with `assert parent_id_from_tags(st_todo.tags) is None`.

Use the multiline Grep with `-l` to find all candidates:

```bash
cd plugins/proj/server && grep -rln "Todo(.*parent=\|Todo(.*children=\|Todo(.*next_child_id=" tests/
```

Edit each match by hand (these are short fixture construction sites — no need for a codemod).

- [ ] **Step 6: Run the full suite**

Run: `cd plugins/proj/server && uv run pytest -q --no-cov 2>&1 | tail -20`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add plugins/proj/server/server/lib/models.py \
        plugins/proj/server/tests/test_models.py \
        plugins/proj/server/tests/test_trello_sync.py \
        plugins/proj/server/tests/test_storage.py \
        plugins/proj/server/tests/test_ids.py \
        plugins/proj/server/tests/test_jira_apply_mapping_flat.py \
        plugins/proj/server/tests/test_todoist_full_sync.py
git commit -m "feat(proj/models): drop Todo.parent/.children/.next_child_id fields + fixture cleanup (636 Task 2f)

Completes 636 Phase 2 Task 2 (per docs/superpowers/plans/2026-04-17-636-phase2-flat-model-cleanup.md).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Final sweep + lint + cross-plugin smoke

**Files:** none modified (verification only). If anything fails, loop back to the relevant task.

- [ ] **Step 1: Run the full proj-server test suite**

```bash
cd plugins/proj/server && uv run pytest -q --no-cov 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 2: Run ruff + format check**

```bash
cd plugins/proj/server && uv run ruff check . && uv run ruff format --check .
```

Expected: no errors.

- [ ] **Step 3: Run basedpyright**

```bash
cd plugins/proj/server && uv run basedpyright server/
```

Expected: no errors. Any new "possibly unbound", "attribute not defined" — fix at source. Note: after dropping `Todo.parent`, basedpyright will surface any remaining `.parent` read as an error. Treat as a missed site and fix (then add a regression test that exercises that code path).

- [ ] **Step 4: Confirm untouched suites stay green**

```bash
cd installer && uv run pytest -q --no-cov 2>&1 | tail -5
cd plugins/router/server && uv run pytest -q --no-cov 2>&1 | tail -5
cd plugins/todoist/server && uv run pytest -q --no-cov 2>&1 | tail -5
cd plugins/trello/server && uv run pytest -q --no-cov 2>&1 | tail -5
cd plugins/jira/server && uv run pytest -q --no-cov 2>&1 | tail -5
```

Expected: all green. Any failure here is a blocker — either a test in that plugin imports `Todo.parent` (rare, but possible), or the commit accidentally touched a shared module. Diagnose + fix before merging.

- [ ] **Step 5: End-to-end smoke test on a fresh tracking dir**

```bash
TMPHOME=$(mktemp -d)
export HOME=$TMPHOME
# Point proj at the tempdir
mkdir -p $TMPHOME/.claude
cat > $TMPHOME/.claude/proj.yaml <<EOF
tracking_dir: $TMPHOME/tracking
EOF
mkdir -p $TMPHOME/tracking/smoke
cd plugins/proj/server && uv run python -c "
from server.lib import storage
from server.lib.models import ProjConfig, ProjectMeta, Todo
cfg = ProjConfig(tracking_dir='$TMPHOME/tracking')
# Seed a project
storage.save_meta(cfg, ProjectMeta(name='smoke'))
# Write flat schema-version
open('$TMPHOME/tracking/smoke/.schema-version', 'w').write('3\n')
# Add a parent + child via group tag
storage.save_todos(cfg, 'smoke', [
    Todo(id='1', title='P', created='2026-04-18', updated='2026-04-18'),
    Todo(id='1.1', title='C', created='2026-04-18', updated='2026-04-18', tags=['group:1']),
])
todos = storage.load_todos(cfg, 'smoke')
assert len(todos) == 2
assert sorted(t.id for t in todos) == ['1', '1.1']
print('OK')
"
```

Expected output: `OK`.

- [ ] **Step 6: Push the branch**

```bash
cd /home/raul/worktrees/cpm/feat-636-task2-schema-field-cleanup
git push -u origin feat/636-task2-schema-field-cleanup
```

- [ ] **Step 7: Open a PR against `dev`**

Use the existing PR template. Title: `feat(proj): finish 636 Phase 2 Task 2 — flat-model schema + field cleanup`. Body: summary + link to `docs/superpowers/plans/2026-04-17-636-phase2-flat-model-cleanup.md` Task 2.

- [ ] **Step 8: Watch CI; merge when green**

Follow the `feedback_624_merge_convention.md` rule: FF-merge to `dev` locally, push, watch CI. No GitHub PR merge — push to `dev` triggers CI.

---

## Implementer notes

- **Do not parallelize git-committing subagents.** Feedback memory `feedback_parallel_git_races.md`: disjoint file scopes still collide on the pre-commit stash + `git reset`. Run this plan sequentially in one worktree with one agent.
- **Grep before every fixture edit.** Dataclass field removal always surfaces unexpected call sites. Trust the test failures, fix at source, re-run.
- **`ids.next_todo_id` signature change is load-bearing.** Every caller MUST pass `siblings=todos`. Missing that kwarg is a silent bug (returns `.1` every time) until the regression test in Task 2 step 1 catches it.
- **Post-merge action (user's responsibility):** re-run `cpm-install --migrate` on local tracking dir to bring `.schema-version` to 2 (this plan only fixes the code that reads the flat schema; it does not change the migration wizard).

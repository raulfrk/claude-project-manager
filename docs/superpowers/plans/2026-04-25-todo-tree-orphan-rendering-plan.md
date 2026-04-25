# Todo Tree Orphan Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `todo_tree` to render children of archived/done parents at the top level (instead of under `__orphaned__`); reserve `__orphaned__` for genuinely deleted parents.

**Architecture:** Single function modification in `plugins/proj/server/server/tools/todos.py` (`todo_tree` fn, ~lines 1440-1500). Add an "archived parent" classification path: load archived todo IDs once; classify each `group:<id>`-tagged child as (a) parent in active set → under parent, (b) parent in archived set → top level, (c) parent doesn't exist → `__orphaned__`. Per managed rule 17, write failing tests first.

**Tech Stack:** Python 3.13, pytest, SQLite-backed storage (`sql_todos.load_archived_todos`).

**Spec:** `docs/superpowers/specs/2026-04-25-todo-tree-orphan-rendering-design.md`

---

## File Structure

| File | Responsibility | Modified by task |
|---|---|---|
| `plugins/proj/server/server/tools/todos.py` | `todo_tree` fn — orphan/group rendering logic | Task 2 |
| `plugins/proj/server/tests/test_mcp_tools.py` | `todo_tree` test cases — colocated with existing tree tests at lines 363-1140 | Task 1 (new tests) |

No new files. No new helpers extracted (the change is small + localized).

---

## Pre-Task Setup

Before starting any task, create an isolated worktree per project rules.

- [ ] **Step 1: Create worktree from dev**

```
mcp__plugin_worktree_worktree__wt_create(
  repo_label="cpm",
  branch="feat/733-todo-tree-orphan-rendering",
  new_branch=true
)
```

Expected: returns `worktree_path` like `/home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering`.

- [ ] **Step 2: Sync worktree to remote per managed rule 13**

```bash
cd <worktree_path>
git fetch origin
local_ahead=$(git rev-list origin/dev..dev)
if [ -z "$local_ahead" ]; then
  git reset --hard origin/dev
else
  git reset --hard dev
fi
git status
```

Expected: HEAD at the most recent dev commit; "nothing to commit, working tree clean".

- [ ] **Step 3: Sync uv groups for proj server (so pytest is available)**

```bash
cd <worktree_path>/plugins/proj/server
uv sync --all-groups
```

Expected: pytest available in venv. (Per cpm convention — fresh worktrees often lack dev deps.)

---

## Task 1: Add 4 new failing tests for the fix (RED commit per managed rule 17)

**Files:**
- Modify: `plugins/proj/server/tests/test_mcp_tools.py` — append 4 new tests next to the existing `__orphaned__` cluster (around line 1085-1140).

**Reference patterns** (read these first to understand fixture/conventions):
- `test_todo_tree_shows_orphaned_todo_under_orphaned_root` (line 1085) — uses `Todo(...)` direct injection via `storage.save_todos`, asserts `__orphaned__` synthetic root presence.
- `test_todo_tree_orphaned_done_excluded_without_include_done` (line 1108) — exclusion path.
- `test_todo_tree_no_orphaned_node_when_all_parents_exist` (line 1127) — negative case.

The new tests use `storage.save_archived_todos_append` from `lib/storage.py` (line 129) to inject archived-parent fixtures.

- [ ] **Step 1: Locate the insertion point**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering
grep -n 'test_todo_tree_no_orphaned_node_when_all_parents_exist' plugins/proj/server/tests/test_mcp_tools.py
```

Note the line number — the 4 new tests insert immediately after this test's body (before the next test class or end of file). Confirm by reading 20 lines starting at the matched line.

- [ ] **Step 2: Verify the existing imports cover everything you need**

```bash
head -50 plugins/proj/server/tests/test_mcp_tools.py | grep -E '^(from|import)'
```

Confirm at minimum: `storage` is imported (or `from server.lib import storage`). If `storage.save_archived_todos_append` is not already imported, add it via the existing import line — don't add a new line.

- [ ] **Step 3: Add Test 1 — archived parent + active child + include_done=False → child at top level (NEW behavior)**

Insert (after `test_todo_tree_no_orphaned_node_when_all_parents_exist`):

```python
    async def test_todo_tree_archived_parent_child_renders_at_top_level(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """A child whose parent is archived (not deleted) renders at top level, not under __orphaned__."""
        cfg, name = project
        # Archive a parent todo via direct storage injection
        archived_parent = Todo(
            id="100",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos_append(cfg, name, [archived_parent])
        # Active child references it via group: tag
        active_child = Todo(
            id="101",
            title="Active Child",
            tags=["group:100"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child])

        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)

        # Child should be a top-level node, NOT under __orphaned__
        top_level_ids = [node.get("id") for node in data]
        assert "101" in top_level_ids, "child should appear at top level"
        orphaned_roots = [node for node in data if node.get("id") == "__orphaned__"]
        assert len(orphaned_roots) == 0, "no __orphaned__ bucket should appear (parent exists, just archived)"
```

- [ ] **Step 4: Add Test 2 — mix: archived parent + deleted parent → archived child top-level, deleted child under __orphaned__**

```python
    async def test_todo_tree_mixed_archived_and_deleted_parents(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Archived-parent child renders top level; deleted-parent child stays under __orphaned__."""
        cfg, name = project
        archived_parent = Todo(
            id="200",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos_append(cfg, name, [archived_parent])
        active_child_archived_parent = Todo(
            id="201",
            title="Child of Archived",
            tags=["group:200"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        active_child_deleted_parent = Todo(
            id="202",
            title="Child of Deleted",
            tags=["group:999"],  # 999 doesn't exist anywhere
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child_archived_parent, active_child_deleted_parent])

        result = await call_tool(mcp_app, "todo_tree")
        data = _json.loads(result)

        top_level_ids = [node.get("id") for node in data]
        assert "201" in top_level_ids, "archived-parent child renders at top level"
        orphaned_roots = [node for node in data if node.get("id") == "__orphaned__"]
        assert len(orphaned_roots) == 1, "__orphaned__ bucket appears for the deleted-parent child"
        orphaned_child_ids = [c.get("id") for c in orphaned_roots[0]["_children"]]
        assert orphaned_child_ids == ["202"], "only the deleted-parent child is in __orphaned__"
```

- [ ] **Step 5: Add Test 3 — archived parent + include_done=True → child renders UNDER parent (regression: existing behavior unchanged)**

```python
    async def test_todo_tree_archived_parent_with_include_done_nests_child(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """include_done=True merges archived into todo_map → child renders UNDER parent (existing behavior preserved)."""
        cfg, name = project
        archived_parent = Todo(
            id="300",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos_append(cfg, name, [archived_parent])
        active_child = Todo(
            id="301",
            title="Active Child",
            tags=["group:300"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child])

        result = await call_tool(mcp_app, "todo_tree", include_done=True)
        data = _json.loads(result)

        # Parent is rendered as a root; child appears under it
        parent_node = next((n for n in data if n.get("id") == "300"), None)
        assert parent_node is not None, "archived parent appears as root when include_done=True"
        child_ids = [c.get("id") for c in parent_node.get("_children", [])]
        assert "301" in child_ids, "child renders under archived parent when include_done=True"
        # And NOT at top level as a sibling
        top_level_ids = [node.get("id") for node in data]
        assert top_level_ids.count("301") == 0, "child is NOT at top level when parent is in todo_map"
```

- [ ] **Step 6: Add Test 4 — compact mode w/ archived parent → child line at top level, NO __orphaned__ line**

```python
    async def test_todo_tree_compact_archived_parent_child_at_top_level(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Compact mode: archived-parent child appears at top level, no __orphaned__ line."""
        cfg, name = project
        archived_parent = Todo(
            id="400",
            title="Archived Parent",
            status="done",
            created="2026-01-01",
            updated="2026-01-01",
        )
        storage.save_archived_todos_append(cfg, name, [archived_parent])
        active_child = Todo(
            id="401",
            title="Active Child",
            tags=["group:400"],
            created="2026-01-02",
            updated="2026-01-02",
        )
        storage.save_todos(cfg, name, [active_child])

        result = await call_tool(mcp_app, "todo_tree", compact=True)
        data = _json.loads(result)

        # Compact returns a JSON envelope with `result` (string of lines), `count`, `truncated`
        lines = data["result"].splitlines()
        # Active child line should appear
        child_lines = [line for line in lines if "401" in line and "Active Child" in line]
        assert len(child_lines) == 1, "child line appears in compact output"
        # No __orphaned__ line
        orphaned_lines = [line for line in lines if "__orphaned__" in line or "Orphaned" in line]
        assert len(orphaned_lines) == 0, "no __orphaned__ line in compact output"
```

- [ ] **Step 7: Run the new tests to confirm they FAIL (RED)**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering/plugins/proj/server
uv run pytest tests/test_mcp_tools.py -k "test_todo_tree_archived_parent_child_renders_at_top_level or test_todo_tree_mixed_archived_and_deleted_parents or test_todo_tree_archived_parent_with_include_done_nests_child or test_todo_tree_compact_archived_parent_child_at_top_level" -v
```

Expected: 4 FAILS. The fail message will likely show the child appearing under `__orphaned__` instead of top level. Test 3 (`include_done=True`) may already pass since archived merges into todo_map in that mode — that's OK; it's a regression test guarding existing behavior.

- [ ] **Step 8: Verify the rest of the suite still passes (no accidental breakage)**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering/plugins/proj/server
uv run pytest tests/test_mcp_tools.py -v 2>&1 | tail -20
```

Expected: existing tests pass; only the 4 new tests fail (or 3 fail + 1 pass for test 3 if regression already holds).

- [ ] **Step 9: Commit RED**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering
git add plugins/proj/server/tests/test_mcp_tools.py
git commit -m "test(proj/733): failing tests for todo_tree archived-parent rendering"
```

---

## Task 2: Implement the fix (GREEN commit)

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` — `todo_tree` fn (~lines 1440-1500); the orphan-detection block at lines 1467-1477.

- [ ] **Step 1: Read the current `todo_tree` block to lock the line range**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering
sed -n '1440,1500p' plugins/proj/server/server/tools/todos.py
```

Expected output: from `def todo_tree(...)` through the orphan-detection block ending around line 1477. Note the exact lines for the Edit.

- [ ] **Step 2: Apply the fix**

Use Edit tool. Find the existing block:

```python
        roots = [todo_map[t.id] for t in todos if not parent_id_from_tags(t.tags)]
        if not include_done:
            roots = [r for r in (_filter_tree_node(root) for root in roots) if r is not None]
        # Detect orphaned todos: have a group tag pointing to a non-existent parent
        orphaned = [
            todo_map[t.id]
            for t in todos
            if parent_id_from_tags(t.tags) is not None
            and parent_id_from_tags(t.tags) not in todo_map
        ]
        if not include_done:
            orphaned = [o for o in orphaned if _filter_tree_node(o) is not None]
        if orphaned:
            roots.append({"id": "__orphaned__", "title": "⚠️ Orphaned", "_children": orphaned})
```

Replace with:

```python
        roots = [todo_map[t.id] for t in todos if not parent_id_from_tags(t.tags)]
        if not include_done:
            roots = [r for r in (_filter_tree_node(root) for root in roots) if r is not None]

        # Load archived IDs for parent-existence check (when not include_done; otherwise
        # archived already merged into todo_map above).
        archived_id_set: set[str] = set()
        if not include_done:
            archived_id_set = {t.id for t in storage.load_archived_todos(cfg, name)}

        # Children whose parent is archived render at top level (parent exists, just outside
        # the active render window). Tag preserved for provenance.
        archived_parent_children = [
            todo_map[t.id]
            for t in todos
            if (pid := parent_id_from_tags(t.tags)) is not None
            and pid not in todo_map
            and pid in archived_id_set
        ]
        if not include_done:
            archived_parent_children = [
                c for c in (_filter_tree_node(child) for child in archived_parent_children)
                if c is not None
            ]
        roots.extend(archived_parent_children)

        # Genuine orphans: parent doesn't exist in active OR archived sets.
        orphaned = [
            todo_map[t.id]
            for t in todos
            if (pid := parent_id_from_tags(t.tags)) is not None
            and pid not in todo_map
            and pid not in archived_id_set
        ]
        if not include_done:
            orphaned = [o for o in orphaned if _filter_tree_node(o) is not None]
        if orphaned:
            roots.append({"id": "__orphaned__", "title": "⚠️ Orphaned", "_children": orphaned})
```

- [ ] **Step 3: Run the 4 new tests — expect GREEN**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering/plugins/proj/server
uv run pytest tests/test_mcp_tools.py -k "test_todo_tree_archived_parent_child_renders_at_top_level or test_todo_tree_mixed_archived_and_deleted_parents or test_todo_tree_archived_parent_with_include_done_nests_child or test_todo_tree_compact_archived_parent_child_at_top_level" -v
```

Expected: all 4 PASS.

- [ ] **Step 4: Run the full `test_mcp_tools.py` suite to confirm no regressions in existing `todo_tree` tests**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering/plugins/proj/server
uv run pytest tests/test_mcp_tools.py -v 2>&1 | tail -30
```

Expected: all tests pass; especially the existing orphan tests (`test_todo_tree_shows_orphaned_todo_under_orphaned_root`, `test_todo_tree_orphaned_done_excluded_without_include_done`, `test_todo_tree_no_orphaned_node_when_all_parents_exist`, `test_todo_tree_include_done_merges_archive`, etc.).

- [ ] **Step 5: Commit GREEN**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering
git add plugins/proj/server/server/tools/todos.py
git commit -m "fix(proj/733): todo_tree renders archived-parent children at top level"
```

---

## Task 3: Full proj test suite + pre-commit verification

- [ ] **Step 1: Run the entire proj server test suite**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering/plugins/proj/server
uv run pytest -v 2>&1 | tail -30
```

Expected: all proj tests pass. (`test_analyze_graph.py` has its own orphan-related test at line 162 — should be unaffected since it tests batch-graph orphans, not tree rendering.)

- [ ] **Step 2: Run pre-commit on the changeset**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering
pre-commit run --all-files
```

Expected: all hooks pass (ruff, ruff-format, basedpyright, Auto-update README, Check _shared version bump). basedpyright may report on the new code path; the use of walrus `(pid := ...)` should be valid Python 3.8+ syntax and basedpyright should accept it.

- [ ] **Step 3: Manual smoke (reproduce the original bug condition)**

```bash
# In the worktree, set up a scratch project structure mirroring 727 → 729-732 archive cascade
# (or just use the 4 new tests above as the formal repro)
```

The 4 new tests in Task 1 ARE the manual smoke — they encode the original bug condition (727→archive, 729-732→orphaned). No additional manual repro needed.

---

## Task 4: Wiki ingest (post-ship followup per spec)

After the branch merges to dev, ingest the fix details into the wiki so future `/wiki:query "todo_tree orphan archived parent"` returns a direct hit. Per managed rule 25 (research synthesis) — wiki should capture the resolution.

- [ ] **Step 1: Decide ingest target**

Options:
- (a) New page `todo-tree-orphan-rendering` under `concepts/` — focused, easy to find.
- (b) Add a section to existing `[[flat-todo-model]]` page — keeps related content together.

Recommendation: (b). Less wiki sprawl. Add a `## todo_tree orphan rendering` section.

- [ ] **Step 2: Run `/wiki:ingest` against the spec + commit**

After merge to dev:
```
/wiki:ingest docs/superpowers/specs/2026-04-25-todo-tree-orphan-rendering-design.md
```

Or manually via `mcp__plugin_wiki_wiki__wiki_page_get` + edit + `wiki_page_write`.

This task is documented for the implementer but is OPTIONAL for the v1 ship — wiki ingest can happen after FF-merge.

---

## Task 5: Branch finishing (FF-merge to dev per project convention)

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Per managed rule 11. The skill walks through merge / PR / cleanup options.

- [ ] **Step 2: Per project memory `feedback_624_merge_convention` — pick FF-merge to dev (no PR)**

```bash
cd /home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering
git fetch origin
git rebase origin/dev   # ensure rebased onto latest dev
cd /home/raul/projects/claude-project-manager
git checkout dev
git merge --ff-only feat/733-todo-tree-orphan-rendering
git push origin dev
```

Expected: clean rebase (no conflicts — only 2 commits touching disjoint areas of `todos.py` + `test_mcp_tools.py`); FF-merge succeeds; push lands.

- [ ] **Step 3: Watch CI**

```bash
gh run list --branch dev --limit 1
gh run watch <run-id> --exit-status
```

Expected: green.

- [ ] **Step 4: Cleanup worktree + branch**

```
mcp__plugin_worktree_worktree__wt_remove(path="/home/raul/worktrees/cpm/feat-733-todo-tree-orphan-rendering")
```

```bash
cd /home/raul/projects/claude-project-manager
git branch -d feat/733-todo-tree-orphan-rendering
```

- [ ] **Step 5: Mark todo 733 done**

```
mcp__plugin_proj_proj__todo_complete(todo_id="733")
```

- [ ] **Step 6: Append-only log entry per managed rule 20**

```
mcp__plugin_proj_proj__notes_append(
  op="checkpoint",
  heading="733 todo_tree orphan rendering shipped",
  text="Render-side fix only. Children of archived parents now render at top level; __orphaned__ reserved for genuinely deleted parents. 4 new tests + 0 regressions."
)
```

---

## Self-Review

**Spec coverage check** — every spec section maps to a task:

| Spec section | Task |
|---|---|
| Problem statement | Task 1 (tests encode the bug); Task 2 (fix) |
| Goal — distinguish archived from deleted parents | Task 2 |
| Locked constraints (render-side only, tag preserved, header hidden when empty) | Task 2 (existing `if orphaned:` already handles header-hiding; no extra code) |
| Architecture (3-way classification table) | Task 2 Step 2 (impl matches the table exactly) |
| Tests (7 cases) | Task 1 adds 4 NEW; the 3 regression cases are already covered by existing tests in test_mcp_tools.py at lines 1085-1140 |
| Risks (huge archives, edge cases, future drift) | Task 3 Step 1 covers full-suite run; spec covers the rest |
| Wiki ingest followup | Task 4 |

Every spec requirement is mapped. No gaps.

**Placeholder scan** — no `TBD`, `TODO`, `Add appropriate`, `Similar to Task`, `Write tests for the above`. Each test has full code. Each step has exact commands + expected output.

**Type/name consistency** — IDs across tests: 100/101 (Test 1), 200/201/202 (Test 2), 300/301 (Test 3), 400/401 (Test 4). No collisions; no reuse. `archived_id_set` name consistent in impl. `archived_parent_children` name consistent in impl. `parent_id_from_tags` is the existing helper at line 463.

---

## Notes for the implementer

- **Strict TDD** per managed rule 17 — do NOT collapse Tasks 1+2 into one commit. Test commit FIRST. Fix commit SECOND.
- **Storage backend is SQLite** — `storage.load_archived_todos` returns `list[Todo]` (not YAML). The set comprehension `{t.id for t in storage.load_archived_todos(cfg, name)}` is the canonical pattern.
- **Walrus operator `:=`** — Python 3.8+ syntax; valid in Python 3.13 (project's target). basedpyright accepts it.
- **No revdiff for this session** — per session-scoped user preference; user will read the spec directly for review.
- **Wiki ingest (Task 4)** is OPTIONAL for v1 — can happen post-merge. Don't block on it.
- **Existing `__orphaned__` tests** (lines 1085-1140) already cover regression cases; no need to duplicate.

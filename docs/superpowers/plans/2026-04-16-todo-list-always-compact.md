# Always-Compact `/proj:todo list` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/proj:todo list` and `/proj:todo tree` default to compact one-line rendering, add `--full` as the opt-in escape hatch, and add a `compact` param to `todo_ready` so `list ready` participates in the same contract.

**Architecture:** Skill-level change to `plugins/proj/skills/todo/SKILL.md` that wires `compact=True` by default and parses `--full`. Small tool-layer change to `plugins/proj/server/server/tools/todos.py` adding a `compact` branch to `todo_ready` (mirrors the `todo_list` compact format). No change to MCP tool defaults — direct MCP callers still see `compact=False` unless they opt in.

**Tech Stack:** Python 3.11 + FastMCP, pytest (async + fixtures), uv for dep management, markdown skills.

**Spec:** `docs/superpowers/specs/2026-04-16-todo-list-always-compact-design.md`
**Worktree:** `/home/raul/worktrees/cpm/feat-todo-list-always-compact`
**Branch:** `feat/todo-list-always-compact`

---

## File Structure

Three files touched:

| File | Role | Change |
|---|---|---|
| `plugins/proj/server/server/tools/todos.py` | FastMCP tool registration for todo management | Add `compact: bool = False` param + compact-render branch to `todo_ready` (around line 1330). Update tool description. |
| `plugins/proj/server/tests/test_mcp_edge_cases.py` | pytest edge-case coverage for MCP tools | Add a `TestTodoReadyCompact` class with 3 cases + 1 new case in the existing `TestTodoListFilters` class. |
| `plugins/proj/skills/todo/SKILL.md` | User-facing skill prose the CLI loads | Update `list` and `tree` subcommand descriptions to parse `--full` and pass `compact=not_full` to the underlying tools. |

Everything runs from the worktree root. All commands below are relative to `/home/raul/worktrees/cpm/feat-todo-list-always-compact` unless absolute paths are shown.

---

## Task 1: Add `compact` param + compact branch to `todo_ready` (TDD)

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (around lines 1324–1350 — the `todo_ready` tool definition)
- Modify: `plugins/proj/server/tests/test_mcp_edge_cases.py` (add new test class at the end, before the `TestDueDateValidation` class or at the module tail)

- [ ] **Step 1.1: Write the failing tests**

Append to `plugins/proj/server/tests/test_mcp_edge_cases.py` (place after the existing `TestTodoListFilters` class, before `TestDueDateValidation`):

```python
# ---------------------------------------------------------------------------
# Gap tests: todo_ready compact mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTodoReadyCompact:
    @pytest.fixture()
    def project(self, cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        return cfg, "myapp"

    async def test_todo_ready_compact_with_results(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact=True returns pipe-delimited lines wrapped in a JSON envelope."""
        await call_tool(mcp_app, "todo_add", title="Ready A", priority="high")
        await call_tool(mcp_app, "todo_add", title="Ready B", tags=["review"])
        result = await call_tool(mcp_app, "todo_ready", compact=True)
        data = _json.loads(result)
        assert data["count"] == 2
        assert data["truncated"] == 0
        assert "Ready A" in data["result"]
        assert "Ready B" in data["result"]
        assert "|" in data["result"]
        # Each line shape: "<id> | <status> | <title> | <priority> | <tags>"
        assert data["result"].count("\n") == 1  # 2 todos -> 1 newline

    async def test_todo_ready_compact_empty(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact=True with no ready todos returns the plain string, not JSON."""
        result = await call_tool(mcp_app, "todo_ready", compact=True)
        assert result == "No todos ready to start."

    async def test_todo_ready_compact_parity(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact and non-compact responses cover the same set of todo IDs."""
        await call_tool(mcp_app, "todo_add", title="Alpha")
        await call_tool(mcp_app, "todo_add", title="Beta")
        await call_tool(mcp_app, "todo_add", title="Gamma")

        raw = await call_tool(mcp_app, "todo_ready")
        compact_raw = await call_tool(mcp_app, "todo_ready", compact=True)

        full_ids = {t["id"] for t in _json.loads(raw)}
        compact_data = _json.loads(compact_raw)
        compact_ids = {line.split(" | ", 1)[0] for line in compact_data["result"].split("\n")}

        assert full_ids == compact_ids
        assert compact_data["count"] == len(full_ids)
```

- [ ] **Step 1.2: Run the new tests — expect failure**

```bash
cd /home/raul/worktrees/cpm/feat-todo-list-always-compact
uv --directory plugins/proj/server run pytest tests/test_mcp_edge_cases.py::TestTodoReadyCompact -v
```

Expected: all 3 tests fail with a `TypeError` — `todo_ready() got an unexpected keyword argument 'compact'` (or the FastMCP equivalent: the tool rejects the unknown param).

- [ ] **Step 1.3: Add the `compact` param + branch to `todo_ready`**

In `plugins/proj/server/server/tools/todos.py`, replace the existing `todo_ready` registration (around lines 1324–1350) with the updated version below. Keep surrounding code untouched.

```python
    @app.tool(
        description=(
            "List todos that are ready to start (pending, no blockers). "
            "Use limit and offset for pagination (limit=0 means no limit). "
            "Set compact=True for one-line summaries to reduce context usage."
        )
    )
    def todo_ready(
        project_name: str | None = None,
        limit: int = 0,
        offset: int = 0,
        compact: bool = False,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        ready = _filter_todos(
            todos,
            status=TodoStatus.PENDING,
            tag=None,
            blocked=False,
            limit=limit,
            offset=offset,
        )
        if not ready:
            return "No todos ready to start."
        if compact:
            lines: list[str] = []
            for t in ready:
                tags_str = ",".join(t.tags) if t.tags else ""
                lines.append(f"{t.id} | {t.status} | {t.title} | {t.priority} | {tags_str}")
            return json.dumps(
                {"result": "\n".join(lines), "truncated": 0, "count": len(ready)}
            )
        return json.dumps([t.to_dict() for t in ready], indent=2)
```

Notes:
- `truncated` is always `0` because `todo_ready` does not support `max_items`; we include the key for shape-parity with `todo_list`/`todo_tree`.
- Empty-result branch stays above the compact branch to match `todo_list` behavior (empty → plain string, not JSON).
- Line format is identical to `todo_list`'s compact branch so consumers see one contract.

- [ ] **Step 1.4: Run the new tests — expect pass**

```bash
uv --directory plugins/proj/server run pytest tests/test_mcp_edge_cases.py::TestTodoReadyCompact -v
```

Expected: 3 passed.

- [ ] **Step 1.5: Run the full `todo_ready` test surface to confirm no regression**

```bash
uv --directory plugins/proj/server run pytest tests/test_mcp_tools.py -k todo_ready -v
```

Expected: all existing `todo_ready` tests still pass (5 tests: `test_todo_ready`, `test_todo_ready_limit`, `test_todo_ready_offset`, `test_todo_ready_limit_and_offset`, `test_todo_ready_limit_zero_returns_all`).

- [ ] **Step 1.6: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_mcp_edge_cases.py
git commit -m "feat(proj): add compact param to todo_ready

Mirrors todo_list / todo_tree compact rendering so /proj:todo list ready
can return one-line-per-todo summaries. Empty-result branch unchanged
(returns plain string). No change to existing non-compact behavior."
```

---

## Task 2: Confirm `todo_list(blocked=True, compact=True)` works end-to-end

The SKILL currently renders `list blocked` by calling `todo_list(status="pending")` and prose-filtering the result for non-empty `blocked_by`. The spec switches this to `todo_list(status="pending", blocked=True, compact=True)` so the server does the filtering and the compact path can apply. `todo_list` already supports both `blocked` and `compact` params independently (confirmed: `test_todo_list_blocked_filter` uses `blocked=True`; `test_todo_list_compact_mode` uses `compact=True`). This task adds a combined-filter test so the new SKILL path has coverage.

**Files:**
- Modify: `plugins/proj/server/tests/test_mcp_edge_cases.py` (append a test to the existing `TestTodoListFilters` class — right after `test_todo_list_blocked_false_filter` around line 294)

- [ ] **Step 2.1: Write the new test inside `TestTodoListFilters`**

Append the following method to the `TestTodoListFilters` class in `plugins/proj/server/tests/test_mcp_edge_cases.py`:

```python
    async def test_todo_list_blocked_compact(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """blocked=True combines with compact=True — only blocked todos, pipe-delimited."""
        await call_tool(mcp_app, "todo_add", title="Blocker")
        await call_tool(mcp_app, "todo_add", title="Blocked", blocked_by=["1"])
        await call_tool(mcp_app, "todo_add", title="Unrelated")
        result = await call_tool(mcp_app, "todo_list", blocked=True, compact=True)
        data = _json.loads(result)
        assert data["count"] == 1
        assert "Blocked" in data["result"]
        assert "Blocker" not in data["result"]
        assert "Unrelated" not in data["result"]
        assert "|" in data["result"]
```

- [ ] **Step 2.2: Run it — expect pass on first try**

```bash
cd /home/raul/worktrees/cpm/feat-todo-list-always-compact
uv --directory plugins/proj/server run pytest tests/test_mcp_edge_cases.py::TestTodoListFilters::test_todo_list_blocked_compact -v
```

Expected: 1 passed. (Both params already exist in `todo_list`; this test is characterization, not TDD.)

- [ ] **Step 2.3: Commit**

```bash
git add plugins/proj/server/tests/test_mcp_edge_cases.py
git commit -m "test(proj): cover todo_list blocked + compact combined filter

Locks in the contract the /proj:todo list blocked skill path will use
after it's rewired to call todo_list with server-side blocked filtering."
```

---

## Task 3: Update `/proj:todo` SKILL — `list` subcommand

Replace the `list` subcommand documentation so the skill instructs Claude to pass `compact=not_full` to the underlying tools and to parse a trailing `--full` flag.

**Files:**
- Modify: `plugins/proj/skills/todo/SKILL.md` (lines 39–73 — the `list` subcommand section)

- [ ] **Step 3.1: Read the current section to anchor the edit**

Current content (lines 39–73) begins with:

```
**list** [all|pending|ready|blocked] [--prio|--priorities] — list w/ optional filter
```

Replace the entire `**list** ... /proj:todo list --priorities alias for --prio` block with the version below. Keep the `**tree**` section header (line 75) exactly as it is for this task; that section is updated in Task 4.

- [ ] **Step 3.2: Apply the edit**

Use the `Edit` tool to replace:

```
**list** [all|pending|ready|blocked] [--prio|--priorities] — list w/ optional filter
 - Default (no filter): `mcp__plugin_proj_proj__todo_tree` — open tasks as hierarchy, done filtered out
 - `all`: `mcp__plugin_proj_proj__todo_tree` — all todos incl done as hierarchy
 - `ready`: `mcp__plugin_proj_proj__todo_ready` — no-blocker todos, flat list
 - `blocked`: `mcp__plugin_proj_proj__todo_list` w/ `status: "pending"`, filter to non-empty `blocked_by`
 - `--prio`/`--priorities` (combinable w/ `all`):
 1. `mcp__plugin_proj_proj__todo_tree` w/ `include_done=False` (or `True` if `all` also present)
 2. Flatten tree → collect all todo objects + nested `_children`
 3. Build open set: all IDs from flattened tree
 4. Each todo: filter `blocked_by` to only IDs in open set (resolves stale blockers)
 5. `mcp__plugin_proj_proj__proj_identify_batches` w/ all open set IDs
 6. Non-empty `cycles` → `### Circular Dependencies` warning listing each cycle
 7. Each batch (tier):
       ```
       ### Tier 0 — Start immediately
       - 🔲 **479** — Add /proj:prioritize skill *(high)* [blocks 474, 469, 471]
       - 🔲 **482** — Todo list by priority skill *(high)*

       ### Tier 1 — After Tier 0
       - 🔲 **474** — Verify hook feedback writeback *(medium)* [blocked by 479]
       ```
 8. Within tier: sort by priority (high→medium→low), then ID numerically
 9. If `all` also present: done todos in separate `### Completed` section after all tiers (✅ icon)
 - Examples:
 - `/proj:todo list --prio` — open todos grouped by blocking tiers
 - `/proj:todo list all --prio` — all todos incl done, grouped by tiers, completed separate
 - `/proj:todo list --priorities` — alias for --prio
```

with:

```
**list** [all|pending|ready|blocked] [--prio|--priorities] [--full] — list w/ optional filter

Parse flags:
 - `--full` present → `full_mode=True`, pass `compact=False` to underlying tool
 - `--full` absent → `full_mode=False`, pass `compact=True` to underlying tool (default behavior)
 - `--prio`/`--priorities` → `prio_mode=True` (overrides `--full`; always uses structured JSON internally)

Subcommand → tool map (set `C = not full_mode` except for `--prio` which always uses False):
 - Default (no filter): `mcp__plugin_proj_proj__todo_tree` w/ `include_done=False, compact=C` — open tasks hierarchy, done filtered out
 - `all`: `mcp__plugin_proj_proj__todo_tree` w/ `include_done=True, compact=C` — all todos incl done
 - `ready`: `mcp__plugin_proj_proj__todo_ready` w/ `compact=C` — no-blocker todos
 - `blocked`: `mcp__plugin_proj_proj__todo_list` w/ `status="pending", blocked=True, compact=C` — server-side blocked filter (no prose post-filter needed)

`--prio`/`--priorities` (combinable w/ `all`, ignores `--full`):
 1. `mcp__plugin_proj_proj__todo_tree` w/ `include_done=False, compact=False` (or `include_done=True` if `all` also present)
 2. Flatten tree → collect all todo objects + nested `_children`
 3. Build open set: all IDs from flattened tree
 4. Each todo: filter `blocked_by` to only IDs in open set (resolves stale blockers)
 5. `mcp__plugin_proj_proj__proj_identify_batches` w/ all open set IDs
 6. Non-empty `cycles` → `### Circular Dependencies` warning listing each cycle
 7. Each batch (tier):
       ```
       ### Tier 0 — Start immediately
       - 🔲 **479** — Add /proj:prioritize skill *(high)* [blocks 474, 469, 471]
       - 🔲 **482** — Todo list by priority skill *(high)*

       ### Tier 1 — After Tier 0
       - 🔲 **474** — Verify hook feedback writeback *(medium)* [blocked by 479]
       ```
 8. Within tier: sort by priority (high→medium→low), then ID numerically
 9. If `all` also present: done todos in separate `### Completed` section after all tiers (✅ icon)

Compact-mode rendering (default for non-`--prio` paths):
 - Tools return `{"result": "<lines>", "count": N, "truncated": K}`. Print the `result` string verbatim. Each line: `id | status | title | priority | tags` (or tree-indented for `todo_tree`).
 - If `truncated > 0`, the `result` string already ends with `... N more items`.

Full-mode rendering (when `--full` given):
 - Tools return indented JSON. Render as nested bullets w/ icons using the existing formatting rules in the bullet list below.

Rendering rules (apply to full-mode + `--prio` mode):
 - Nested bullets, 2-space indent per level. Icons: ✅=done, 🔄=in_progress, 🔲=pending. Bold ID, title, priority in italics. Use full exact title — never abbreviate. `"manual" in tags` → append `[manual]` after priority. Blocked → `[blocked by X]` inline. Blocks others → `[blocks Y]` inline. Tag matching `group:*` → extract value after `group:` → append `[group:<value>]` at end. Order: `_(priority)_ [manual] [blocked by X] [blocks Y] [group:X]`.
 - Example:
    ```
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual] [blocks 2.2] [group:623]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write skills _(medium)_
    ```

Examples:
 - `/proj:todo list` — open todos, compact one-line-per-todo
 - `/proj:todo list --full` — open todos, full structured rendering
 - `/proj:todo list all` — all todos incl done, compact
 - `/proj:todo list ready` — ready todos, compact
 - `/proj:todo list blocked` — blocked todos, compact
 - `/proj:todo list --prio` — open todos grouped by blocking tiers (compact-independent)
 - `/proj:todo list all --prio` — all todos incl done, grouped by tiers, completed separate
 - `/proj:todo list --priorities` — alias for --prio
```

Use the `Edit` tool with `old_string` set to the current block (everything from `**list** [all|pending|ready|blocked] [--prio|--priorities] — list w/ optional filter` through the `alias for --prio` line) and `new_string` set to the replacement above.

- [ ] **Step 3.3: Verify the edit**

```bash
grep -n "list --full" /home/raul/worktrees/cpm/feat-todo-list-always-compact/plugins/proj/skills/todo/SKILL.md
grep -n "blocked=True, compact=C" /home/raul/worktrees/cpm/feat-todo-list-always-compact/plugins/proj/skills/todo/SKILL.md
```

Expected: both grep hits return at least one matching line. If either returns nothing, re-apply the edit.

- [ ] **Step 3.4: Commit**

```bash
git add plugins/proj/skills/todo/SKILL.md
git commit -m "feat(proj/skill): default /proj:todo list to compact + add --full

- list/list all/list ready/list blocked default to compact rendering
- --full flag opts back into full structured JSON output
- list blocked now uses server-side blocked=True filter (no prose post-filter)
- --prio path unchanged (still requires structured JSON internally)"
```

---

## Task 4: Update `/proj:todo` SKILL — `tree` subcommand

**Files:**
- Modify: `plugins/proj/skills/todo/SKILL.md` (the `**tree**` subcommand section — currently lines 75–85)

- [ ] **Step 4.1: Apply the edit**

Use the `Edit` tool to replace the current `tree` block:

```
**tree** — todos as hierarchy
 - `mcp__plugin_proj_proj__todo_tree`
 - Nested bullets, 2-space indent. Same icons/bold ID/inline metadata as `list` (incl `[manual]`, `[blocked by X]`/`[blocks Y]`, `[group:X]`).
 - Example:
    ```
    - ✅ **1** — Implement storage layer _(medium)_
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual] [blocks 2.2] [group:623]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write tests _(low)_
    ```
```

with:

```
**tree** [--full] — todos as hierarchy

Parse flag:
 - `--full` absent (default) → call `mcp__plugin_proj_proj__todo_tree` w/ `compact=True`; print the returned `result` string verbatim (tree-indented one-liners).
 - `--full` present → call `mcp__plugin_proj_proj__todo_tree` w/ `compact=False`; render as nested bullets w/ 2-space indent using the rendering rules from the `list` section (icons, bold ID, inline metadata incl `[manual]`, `[blocked by X]`/`[blocks Y]`, `[group:X]`).

Example (full-mode):
    ```
    - ✅ **1** — Implement storage layer _(medium)_
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual] [blocks 2.2] [group:623]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write tests _(low)_
    ```
```

- [ ] **Step 4.2: Verify the edit**

```bash
grep -n "tree\] \[--full" /home/raul/worktrees/cpm/feat-todo-list-always-compact/plugins/proj/skills/todo/SKILL.md || \
grep -n "^\*\*tree\*\* \[--full\]" /home/raul/worktrees/cpm/feat-todo-list-always-compact/plugins/proj/skills/todo/SKILL.md
```

Expected: one grep returns the new heading line `**tree** [--full] — todos as hierarchy`.

- [ ] **Step 4.3: Commit**

```bash
git add plugins/proj/skills/todo/SKILL.md
git commit -m "feat(proj/skill): default /proj:todo tree to compact + add --full

/proj:todo tree now calls todo_tree(compact=True) by default and prints
the tool's one-liner output verbatim. --full opts into the existing
nested-bullet rendering."
```

---

## Task 5: Run the full `proj` test suite + contract smoke check

**Files:** None modified — verification only.

- [ ] **Step 5.1: Run the full proj server test suite**

```bash
cd /home/raul/worktrees/cpm/feat-todo-list-always-compact
uv --directory plugins/proj/server run pytest -x -q
```

Expected: all tests pass. If any fail:
1. If failure is in `test_mcp_edge_cases.py::TestTodoReadyCompact` or `::test_todo_list_blocked_compact` — bug in the new code; fix in the corresponding task.
2. If failure is elsewhere — read the assertion, check whether it's a pre-existing flake (CI perf thresholds, snapshot flakes). Re-run once before escalating.

- [ ] **Step 5.2: Sanity-grep the skill contract**

```bash
grep -cE "compact=(C|not full_mode|True)" plugins/proj/skills/todo/SKILL.md
```

Expected: `>= 4` (one match per list variant + one for tree).

- [ ] **Step 5.3: Verify `--prio` still passes `compact=False` internally**

```bash
grep -n "compact=False" plugins/proj/skills/todo/SKILL.md
```

Expected: at least one hit in the `--prio` description referring to `include_done=False, compact=False` or similar. The skill must not compact the `--prio` tool call because the skill flattens the tree itself.

- [ ] **Step 5.4: Check branch history**

```bash
git log --oneline dev..HEAD
```

Expected: 4 commits in order:
1. `feat(proj): add compact param to todo_ready ...`
2. `test(proj): cover todo_list blocked + compact combined filter`
3. `feat(proj/skill): default /proj:todo list to compact + add --full`
4. `feat(proj/skill): default /proj:todo tree to compact + add --full`

- [ ] **Step 5.5: Done**

No commit in this task — verification only. Mention to the user in the execution summary that Task 5 was verification-only and completed successfully.

---

## Done-Definition

1. `todo_ready(compact=True)` returns the same JSON envelope shape as `todo_list(compact=True)` (`{"result", "count", "truncated"}`), with `truncated` always `0`.
2. `todo_ready(compact=True)` with no ready todos returns the plain string `"No todos ready to start."`, not a JSON envelope (matches `todo_list`/`todo_tree`).
3. `plugins/proj/skills/todo/SKILL.md` instructs Claude to pass `compact=True` by default on all `list`/`tree` paths and `compact=False` when `--full` is given.
4. `list blocked` path in the skill uses `todo_list(status="pending", blocked=True, compact=<C>)` — no prose post-filter step for `blocked_by`.
5. `list --prio` continues to call `todo_tree(compact=False)` internally and its user-facing output is unchanged.
6. All proj-server pytest tests pass, including the 4 new tests (`test_todo_ready_compact_with_results`, `test_todo_ready_compact_empty`, `test_todo_ready_compact_parity`, `test_todo_list_blocked_compact`).
7. Branch `feat/todo-list-always-compact` contains exactly 4 new commits on top of `dev`.

## Out-of-Scope Reminders

- No change to MCP tool defaults (`compact=False` stays the default on the tool layer).
- No `max_items` support on `todo_ready`.
- No change to `todo_list_all`, `todo_add`, `todo_update`, `todo_complete`, `todo_delete`, `todo_get`, or any non-listing todo tool.
- No change to the `--prio`/`--priorities` user-visible rendering.

# Skill Polish + Hook Fixes (640-646) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land five themed commits on `feat/skill-polish-hook-fixes` that resolve todos 640-646: retarget stale todoist hook, polish SKILL.md, document `count` semantics, add `todo_ready` compact+limit test, and fix duplicate `wt_remove` hook firing.

**Architecture:** All work lives in a dedicated git worktree (`/home/raul/worktrees/cpm/feat-skill-polish-hook-fixes`). Each theme becomes one atomic commit. Test suite runs after every code commit. Final integration is gated behind explicit user approval (rebase + FF-merge to `dev`, no PR).

**Tech Stack:** Python (FastMCP, pytest, uv), YAML hook config, Markdown SKILL files, revdiff for spec review.

**Spec:** `docs/superpowers/specs/2026-04-16-skill-polish-hook-fixes-design.md`

---

## File Structure

| Path                                                              | Responsibility                                          | Touched by    |
| ----------------------------------------------------------------- | ------------------------------------------------------- | ------------- |
| `~/.claude/hooks.yaml` (runtime, uncommitted)                     | Router's active hook registry                           | Task 2        |
| `plugins/todoist/.claude-plugin/default-hooks.yaml`               | Todoist plugin's default hooks (already-correct source) | Task 2 (read) |
| `plugins/proj/skills/todo/SKILL.md`                               | `/proj:todo` skill prose                                | Task 3        |
| `plugins/proj/server/server/tools/todos.py`                       | todo_list/todo_tree/todo_ready MCP tools                | Task 4        |
| `plugins/proj/server/tests/test_mcp_edge_cases.py`                | MCP edge-case tests including `TestTodoReadyCompact`    | Task 5        |
| `plugins/_shared/hook_dispatch/dispatch.py` *(only if hypothesis b)* | Hook dispatch wrapping                                  | Task 6        |
| `~/.claude/hooks.yaml` *(only if hypothesis a)*                   | Registry dedup                                          | Task 6        |

---

## Task 1: Setup — Create Worktree + Branch

**Files:**
- Create worktree dir: `/home/raul/worktrees/cpm/feat-skill-polish-hook-fixes`

- [ ] **Step 1: Verify base branch is `dev` and clean**

Run (from `/home/raul/projects/claude-project-manager`):
```bash
git status --short && git branch --show-current
```
Expected: no pending changes, current branch `dev`. If not clean, commit/stash before proceeding.

- [ ] **Step 2: Create worktree via wt_create MCP tool**

Call MCP tool:
```python
mcp__plugin_worktree_worktree__wt_create(
    repo="cpm",
    branch="feat/skill-polish-hook-fixes",
    base="dev",
    path="/home/raul/worktrees/cpm/feat-skill-polish-hook-fixes",
)
```
Expected: returns worktree path. If `wt_create` can auto-resolve path, that's fine — just capture the returned path for subsequent steps.

- [ ] **Step 3: Confirm worktree layout**

Run:
```bash
cd /home/raul/worktrees/cpm/feat-skill-polish-hook-fixes && git branch --show-current && git log --oneline -n 1
```
Expected: branch `feat/skill-polish-hook-fixes`, HEAD matches latest `dev` commit.

> **All remaining tasks run with cwd = `/home/raul/worktrees/cpm/feat-skill-polish-hook-fixes`.**

---

## Task 2: Commit 1 — Retarget stale todoist hook (todo 640)

**Files:**
- Read: `plugins/todoist/.claude-plugin/default-hooks.yaml`
- Read/Edit: `~/.claude/hooks.yaml` (runtime, uncommitted)
- Possibly modify: `plugins/todoist/.claude-plugin/default-hooks.yaml` (only if plugin-side bug found)

- [ ] **Step 1: Read plugin's default hook definition**

```bash
grep -n "todoist-full-sync-on-proj-load" -A 6 plugins/todoist/.claude-plugin/default-hooks.yaml
```
Expected: block showing `target_tool: proj_sync`. If so, plugin default is already correct — proceed to registry check. If it still says `proj_todoist_full_sync`, plugin needs fixing too (unlikely based on pre-plan grep).

- [ ] **Step 2: Check runtime registry for stale target**

```bash
grep -n "proj_todoist_full_sync\|todoist-full-sync-on-proj-load" ~/.claude/hooks.yaml || echo "NOT_FOUND"
```
Expected outcomes:
- Block mentioning `target_tool: proj_todoist_full_sync` → stale; proceed to Step 3.
- Block mentioning `target_tool: proj_sync` → registry already in sync; verify via Step 5 and skip to Step 6 w/o editing.
- `NOT_FOUND` → hook isn't registered; nothing to fix, skip to Step 6.

- [ ] **Step 3: Edit `~/.claude/hooks.yaml` to retarget the hook**

Use the `Edit` tool with `old_string` = the stale hook block and `new_string` = the block from the plugin's `default-hooks.yaml`. Typical stale block shape:

```yaml
  - id: todoist-full-sync-on-proj-load
    trigger_tool: proj_load_session
    target_tool: proj_todoist_full_sync
    server: proj
    blocking: true
    condition: "sync.todoist.enabled"
```

Replace with the plugin-default block (copy exact text from `plugins/todoist/.claude-plugin/default-hooks.yaml:74-77+` to preserve formatting):

```yaml
  - id: todoist-full-sync-on-proj-load
    trigger_tool: proj_load_session
    target_tool: proj_sync
    server: proj
    blocking: true
    condition: "sync.todoist.enabled"
```

- [ ] **Step 4: Verify registry edit**

```bash
grep -n "todoist-full-sync-on-proj-load" -A 5 ~/.claude/hooks.yaml
```
Expected: single block, `target_tool: proj_sync`.

- [ ] **Step 5: Runtime verification — trigger proj_load_session**

Call MCP tool:
```python
mcp__plugin_proj_proj__proj_load_session(project_name="claude-project-manager")
```

Then inspect router invocations:
```python
mcp__plugin_router_router__router_invocations_tool(limit=10)
```

Expected: no entry with `status=error` + `error` mentioning `Unknown tool: proj_todoist_full_sync`. The `todoist-full-sync-on-proj-load` hook should either succeed or skip (condition evaluated false).

- [ ] **Step 6: Commit (if plugin YAML was NOT modified)**

Registry changes live in `~/.claude/hooks.yaml` (not committed). If no plugin YAML change was needed, this theme produces **zero file changes in the worktree** — commit an empty commit documenting the registry fix so the branch history still reflects the work:

```bash
git commit --allow-empty -m "fix(todoist): retarget todoist-full-sync-on-proj-load hook to proj_sync

Runtime ~/.claude/hooks.yaml had stale target_tool=proj_todoist_full_sync
from before the tool was renamed/folded into proj_sync. Plugin default
already correct; only the user's local registry needed resyncing.

Closes todo 640.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6b: Commit (if plugin YAML WAS modified — unlikely path)**

```bash
git add plugins/todoist/.claude-plugin/default-hooks.yaml
git commit -m "fix(todoist): retarget todoist-full-sync-on-proj-load hook to proj_sync

Plugin default hook was pointing at proj_todoist_full_sync which no
longer exists; target should be proj_sync (the unified sync entry
point used by other todoist hooks in the same file).

Closes todo 640.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Commit 2 — SKILL.md polish (todos 641 + 642 + 645)

**Files:**
- Modify: `plugins/proj/skills/todo/SKILL.md`

- [ ] **Step 1: 642 — Drop `pending` from list subcommand heading**

Use `Edit`:
- `old_string`: `**list** [all|pending|ready|blocked] [--prio|--priorities] [--full] — list w/ optional filter`
- `new_string`: `**list** [all|ready|blocked] [--prio|--priorities] [--full] — list w/ optional filter`

- [ ] **Step 2: 641 — Clarify `--prio` combo behavior**

Use `Edit`:
- `old_string`:
  ```
  `--prio`/`--priorities` (combinable w/ `all`, ignores `--full`):
  ```
- `new_string`:
  ```
  `--prio`/`--priorities` (combinable w/ `all` only; `ready`/`blocked` filters ignored when combined; ignores `--full`):
  ```

- [ ] **Step 3: 645 — Tighten line 42 (caveman pass)**

Use `Edit`:
- `old_string`: `- \`--full\` present → \`full_mode=True\`, pass \`compact=False\` to underlying tool`
- `new_string`: `- \`--full\` present → \`full_mode=True\`, pass \`compact=False\``

And:
- `old_string`: `- \`--full\` absent → \`full_mode=False\`, pass \`compact=True\` to underlying tool (default behavior)`
- `new_string`: `- \`--full\` absent → \`full_mode=False\`, pass \`compact=True\` (default)`

- [ ] **Step 4: 645 — Tighten full-mode rendering prose (near line 75)**

Use `Edit`:
- `old_string`: `Full-mode rendering (when \`--full\` given):\n - Tools return indented JSON. Render as nested bullets w/ icons using the existing formatting rules in the bullet list below.`
- `new_string`: `Full-mode rendering (when \`--full\` given):\n - Tools return indented JSON. Render as nested bullets w/ icons (rules below).`

- [ ] **Step 5: 645 — Tighten tree `--full` prose (near line 102)**

Use `Edit`:
- `old_string`: ` - \`--full\` present → call \`mcp__plugin_proj_proj__todo_tree\` w/ \`compact=False\`; render as nested bullets w/ 2-space indent using the rendering rules from the \`list\` section (icons, bold ID, inline metadata incl \`[manual]\`, \`[blocked by X]\`/\`[blocks Y]\`, \`[group:X]\`).`
- `new_string`: ` - \`--full\` present → call \`mcp__plugin_proj_proj__todo_tree\` w/ \`compact=False\`; render as nested bullets w/ 2-space indent (rules from \`list\` section: icons, bold ID, inline metadata incl \`[manual]\`, \`[blocked by X]\`/\`[blocks Y]\`, \`[group:X]\`).`

- [ ] **Step 6: Verify all edits present**

```bash
grep -n "pass compact=False\|pass compact=True\|combinable w/ \`all\` only\|rules below\|rules from \`list\` section" plugins/proj/skills/todo/SKILL.md
```
Expected: 5 matching lines, one per edit from Steps 1-5 (Step 1 verified separately via absence of `pending` in the heading).

- [ ] **Step 7: Commit**

```bash
git add plugins/proj/skills/todo/SKILL.md
git commit -m "docs(proj/skill): clarify --prio combos + drop pending filter + caveman tighten

- 641: --prio combo behavior documented (only combines w/ 'all'; other
  filters ignored).
- 642: 'pending' removed from list subcommand heading — had no tool
  mapping and was confusing (pre-existing drift).
- 645: caveman tighten around compact-flag lines + full-mode rendering
  references to match rest of SKILL.md style.

Closes todos 641, 642, 645.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Commit 3 — Document `count` semantics (todo 643)

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (docstrings at 700-707, 1325-1329, 1427-1434)

- [ ] **Step 1: Update `todo_list` docstring**

Use `Edit`:
- `old_string`:
  ```python
      "List todos for a project, with optional status/tag filters. "
      "status='active' (default) returns pending+in_progress only; "
      "status='open' returns all non-done/non-cancelled todos; "
      "pass status=None to return all statuses including done. "
      "Use limit and offset for pagination (limit=0 means no limit). "
      "Set compact=True for one-line summaries to reduce context usage. "
      "Set max_items>0 to truncate output."
  ```
- `new_string`:
  ```python
      "List todos for a project, with optional status/tag filters. "
      "status='active' (default) returns pending+in_progress only; "
      "status='open' returns all non-done/non-cancelled todos; "
      "pass status=None to return all statuses including done. "
      "Use limit and offset for pagination (limit=0 means no limit). "
      "Set compact=True for one-line summaries to reduce context usage. "
      "Set max_items>0 to truncate output. "
      "Compact envelope: count = number of filtered todo items returned."
  ```

- [ ] **Step 2: Update `todo_ready` docstring**

Use `Edit`:
- `old_string`:
  ```python
      "List todos that are ready to start (pending, no blockers). "
      "Use limit and offset for pagination (limit=0 means no limit). "
      "Set compact=True for one-line summaries to reduce context usage."
  ```
- `new_string`:
  ```python
      "List todos that are ready to start (pending, no blockers). "
      "Use limit and offset for pagination (limit=0 means no limit). "
      "Set compact=True for one-line summaries to reduce context usage. "
      "Compact envelope: count = number of ready todo items returned; "
      "truncated is hardcoded to 0 (no max_items support)."
  ```

- [ ] **Step 3: Update `todo_tree` docstring**

Use `Edit`:
- `old_string`:
  ```python
      "Return todos as a tree structure (JSON with nested children). "
      "By default excludes done todos; done parents are kept when they have "
      "non-done descendants. Pass include_done=True to return all todos. "
      "Set compact=True for indented one-line summaries to reduce context usage. "
      "Set max_items>0 to truncate output."
  ```
- `new_string`:
  ```python
      "Return todos as a tree structure (JSON with nested children). "
      "By default excludes done todos; done parents are kept when they have "
      "non-done descendants. Pass include_done=True to return all todos. "
      "Set compact=True for indented one-line summaries to reduce context usage. "
      "Set max_items>0 to truncate output. "
      "Compact envelope: count = number of root todos (children not counted)."
  ```

- [ ] **Step 4: Run test suite to confirm no regression**

```bash
uv run pytest plugins/proj/server/tests/ -x --no-header -q 2>&1 | tail -20
```
Expected: all tests pass. Docstring-only change should not affect any test.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py
git commit -m "docs(proj/mcp): document count field semantics per tool

Each compact-mode envelope's count field has slightly different
semantics (todo_list = filtered items, todo_tree = root nodes,
todo_ready = items). Document per tool rather than normalize to
preserve backward compat w/ any current consumers.

Closes todo 643.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Commit 4 — `todo_ready` compact+limit test (todo 644)

**Files:**
- Modify: `plugins/proj/server/tests/test_mcp_edge_cases.py` (add method in `TestTodoReadyCompact` class after existing `test_todo_ready_compact_parity` at line 365)

- [ ] **Step 1: Write the failing test**

Use `Edit` to insert a new method after `test_todo_ready_compact_parity` and before the class end (before line 366's comment `# Gap tests: todo_add / todo_update empty due_date validation`).

- `old_string`:
  ```python
          assert full_ids == compact_ids
          assert compact_data["count"] == len(full_ids)


  # ---------------------------------------------------------------------------
  # Gap tests: todo_add / todo_update empty due_date validation
  # ---------------------------------------------------------------------------
  ```
- `new_string`:
  ```python
          assert full_ids == compact_ids
          assert compact_data["count"] == len(full_ids)

      async def test_todo_ready_compact_with_limit(
          self, mcp_app: Any, project: tuple[ProjConfig, str]
      ) -> None:
          """compact=True composes with limit — count reflects returned items."""
          await call_tool(mcp_app, "todo_add", title="Ready 1")
          await call_tool(mcp_app, "todo_add", title="Ready 2")
          await call_tool(mcp_app, "todo_add", title="Ready 3")

          result = await call_tool(mcp_app, "todo_ready", compact=True, limit=1)
          data = _json.loads(result)

          assert data["count"] == 1
          assert data["truncated"] == 0  # todo_ready has no max_items
          # Single-line result has no embedded newline
          assert "\n" not in data["result"]
          assert "|" in data["result"]


  # ---------------------------------------------------------------------------
  # Gap tests: todo_add / todo_update empty due_date validation
  # ---------------------------------------------------------------------------
  ```

- [ ] **Step 2: Run the new test to confirm it passes**

```bash
uv run pytest plugins/proj/server/tests/test_mcp_edge_cases.py::TestTodoReadyCompact::test_todo_ready_compact_with_limit -v
```
Expected: PASS. (If it fails, inspect the output — most likely an import or fixture mismatch; align w/ the other tests in the same class.)

- [ ] **Step 3: Run the full edge-case test file**

```bash
uv run pytest plugins/proj/server/tests/test_mcp_edge_cases.py -v --no-header -q 2>&1 | tail -30
```
Expected: all pass (including existing 3 `TestTodoReadyCompact` tests + new one).

- [ ] **Step 4: Run full proj test suite**

```bash
uv run pytest plugins/proj/server/tests/ --no-header -q 2>&1 | tail -20
```
Expected: all pass, no regressions.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/tests/test_mcp_edge_cases.py
git commit -m "test(proj): todo_ready(compact=True, limit=N) pagination

Pin the contract that compact + limit compose correctly (count reflects
returned items, not total pool). Existing TestTodoReadyCompact tests
covered compact alone and limit alone, but not the combination.

Closes todo 644.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Commit 5 — wt_remove hook dedup (todo 646)

**Files (investigation-dependent):**
- Read: `~/.claude/hooks.yaml`, `plugins/_shared/hook_dispatch/dispatch.py`, `plugins/worktree/.claude-plugin/default-hooks.yaml`, `plugins/worktree/server/server/main.py`
- Possibly modify: `~/.claude/hooks.yaml` (hypothesis a) or `plugins/_shared/hook_dispatch/dispatch.py` (hypothesis b)

**Investigation time budget:** 30 minutes. If root cause unclear after that, go to Step 6 (escape hatch).

- [ ] **Step 1: Capture the duplicate chain on a fresh wt_remove**

Create a throwaway worktree, remove it, capture invocations. Use a disposable branch that won't matter if something goes wrong.

```bash
# From cwd = /home/raul/worktrees/cpm/feat-skill-polish-hook-fixes
```

Call:
```python
mcp__plugin_worktree_worktree__wt_create(
    repo="cpm",
    branch="probe/wt-remove-dup-646",
    base="dev",
    path="/home/raul/worktrees/cpm/probe-wt-remove-dup-646",
)

mcp__plugin_worktree_worktree__wt_remove(
    path="/home/raul/worktrees/cpm/probe-wt-remove-dup-646",
)
```

Then:
```python
mcp__plugin_router_router__router_invocations_tool(limit=20)
```

Capture the full chain. Note: (i) hook_ids that appear more than once, (ii) target_tools that appear more than once, (iii) errors.

- [ ] **Step 2: Check hypothesis (a) — registry duplication**

```bash
grep -n "worktree-on-wt-remove\|zoxide-on-wt-remove" ~/.claude/hooks.yaml
```
Expected (healthy): one `worktree-on-wt-remove-sandbox`, one `worktree-on-wt-remove-zoxide` (if still named that) OR one `zoxide-on-wt-remove`, each with a distinct `id`.

**If any hook_id appears more than once → hypothesis (a) confirmed.** Proceed to Step 3.
**If all hook_ids are unique → hypothesis (a) ruled out.** Skip to Step 4.

- [ ] **Step 3 (only if hypothesis a): Dedup registry**

Use `Edit` on `~/.claude/hooks.yaml` to remove the duplicate block(s). Keep only one entry per `hook_id`. Then re-run Step 1 to confirm the chain is clean, then proceed to Step 7.

- [ ] **Step 4: Check hypothesis (b) — double-wrap via duplicate enable_hook_dispatch**

```bash
grep -rn "enable_hook_dispatch" plugins/*/server/server/main.py
```
Expected: one call per plugin's main.py. If any plugin's main.py has two `enable_hook_dispatch(...)` calls, **hypothesis (b) confirmed** — proceed to Step 5.

If each plugin has exactly one call → hypothesis (b) ruled out. Skip to Step 6.

- [ ] **Step 5 (only if hypothesis b): Add idempotency guard to `enable_hook_dispatch`**

Use `Edit` on `plugins/_shared/hook_dispatch/dispatch.py`:
- `old_string`:
  ```python
  def enable_hook_dispatch(
      mcp: FastMCP,
      hooks_port: int = 19100,
      exclude: set[str] | list[str] | None = None,
  ) -> None:
      """Patch mcp.tool() so all subsequent registrations dispatch to the hooks server.

      The hooks server URL is resolved lazily on every dispatch call (not at startup),
      so that server restarts and startup ordering races don't cause permanent failures.

      Args:
          mcp: The FastMCP instance to patch.
          hooks_port: Port of the hooks server (default 19100). Only used with HOOK_TRANSPORT=tcp.
          exclude: Tool names to skip dispatch for.
      """
      excluded: set[str] = set(exclude) if exclude else set()
      original_tool = mcp.tool
  ```
- `new_string`:
  ```python
  def enable_hook_dispatch(
      mcp: FastMCP,
      hooks_port: int = 19100,
      exclude: set[str] | list[str] | None = None,
  ) -> None:
      """Patch mcp.tool() so all subsequent registrations dispatch to the hooks server.

      The hooks server URL is resolved lazily on every dispatch call (not at startup),
      so that server restarts and startup ordering races don't cause permanent failures.

      Idempotent: repeated calls on the same FastMCP instance are no-ops.

      Args:
          mcp: The FastMCP instance to patch.
          hooks_port: Port of the hooks server (default 19100). Only used with HOOK_TRANSPORT=tcp.
          exclude: Tool names to skip dispatch for.
      """
      if getattr(mcp, "_hook_dispatch_enabled", False):
          return
      excluded: set[str] = set(exclude) if exclude else set()
      original_tool = mcp.tool
  ```

Then find the `mcp.tool = patched_tool` line and add an idempotency flag right after:
- `old_string`:
  ```python
      mcp.tool = patched_tool  # type: ignore[assignment,method-assign]
  ```
- `new_string`:
  ```python
      mcp.tool = patched_tool  # type: ignore[assignment,method-assign]
      setattr(mcp, "_hook_dispatch_enabled", True)
  ```

Add a regression test. `enable_hook_dispatch` and `MagicMock` are already imported at the top of `plugins/_shared/tests/test_hook_dispatch.py` (lines 8 + 21). Use `Edit` to append a new test function at the end of the file:

```python


def test_enable_hook_dispatch_is_idempotent() -> None:
    """Calling enable_hook_dispatch twice must not double-wrap tools."""
    mcp = MagicMock()
    original_tool = MagicMock()
    mcp.tool = original_tool

    enable_hook_dispatch(mcp)
    first_patched = mcp.tool
    assert first_patched is not original_tool

    enable_hook_dispatch(mcp)
    second_patched = mcp.tool
    assert second_patched is first_patched, (
        "Second enable_hook_dispatch call must not re-patch mcp.tool"
    )
```

Run the new test:
```bash
uv run pytest plugins/_shared/tests/test_hook_dispatch.py::test_enable_hook_dispatch_is_idempotent -v
```
Expected: PASS.

Then re-run Step 1 to confirm live fix works.

- [ ] **Step 6: Escape hatch — defer if root cause unclear**

If neither (a) nor (b) cleanly matches the observed chain after the 30-min cap, **stop investigating**. Do not guess. Instead:

1. Append findings to todo 646 notes via `mcp__plugin_proj_proj__todo_notes_append(todo_id="646", text=<investigation-summary>)`. Include: the exact chain from Step 1, what hypotheses were ruled out, what remains unexplained.
2. **Skip remaining fix.** Leave 646 open.
3. Update the spec file to record the deferral. Use `Edit` on `docs/superpowers/specs/2026-04-16-skill-polish-hook-fixes-design.md` Acceptance Criteria section — add `(DEFERRED — see todo 646 notes)` after the 646 checkbox line.
4. Skip to Task 7 (Step 1). Commit 5 is skipped.

- [ ] **Step 7: Commit (only if a fix was applied in Step 3 or Step 5)**

If registry-only fix (Step 3):
```bash
git commit --allow-empty -m "fix(hooks): dedup wt_remove hook registry entries

Runtime ~/.claude/hooks.yaml had duplicate wt_remove hook entries
causing double-firing (same hook_id fired twice per wt_remove call).
Deduped to one entry per hook_id.

Closes todo 646.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If dispatch.py fix (Step 5):
```bash
git add plugins/_shared/hook_dispatch/dispatch.py plugins/_shared/tests/test_hook_dispatch.py
git commit -m "fix(hooks): make enable_hook_dispatch idempotent

Duplicate calls to enable_hook_dispatch on the same FastMCP instance
re-patched mcp.tool, causing subsequently-registered tools to fire
their hook chain twice on each invocation. Guard via a flag attribute;
add regression test.

Closes todo 646.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Run full test suite after fix**

```bash
uv run pytest plugins/ --no-header -q 2>&1 | tail -20
```
Expected: all pass.

---

## Task 7: Final verification

**Files:** none modified (verification only)

- [ ] **Step 1: Review commit history**

```bash
git log --oneline dev..HEAD
```
Expected: 4 or 5 commits (5 if 646 was fixed, 4 if deferred), in the order:
1. `fix(todoist): retarget todoist-full-sync...`
2. `docs(proj/skill): clarify --prio combos...`
3. `docs(proj/mcp): document count field semantics...`
4. `test(proj): todo_ready(compact=True, limit=N) pagination`
5. `fix(hooks): ...` (if 646 fixed)

- [ ] **Step 2: Full test suite one more time**

```bash
uv run pytest plugins/ --no-header -q 2>&1 | tail -20
```
Expected: all pass. Capture total count + pass count.

- [ ] **Step 3: Runtime verification of 640 fix**

Call:
```python
mcp__plugin_proj_proj__proj_load_session(project_name="claude-project-manager")
mcp__plugin_router_router__router_invocations_tool(limit=10)
```
Expected: no `Unknown tool: proj_todoist_full_sync` error.

- [ ] **Step 4: Runtime verification of 646 fix (only if fixed)**

Call:
```python
mcp__plugin_worktree_worktree__wt_create(
    repo="cpm",
    branch="probe/post-fix-646",
    base="dev",
    path="/home/raul/worktrees/cpm/probe-post-fix-646",
)
mcp__plugin_worktree_worktree__wt_remove(
    path="/home/raul/worktrees/cpm/probe-post-fix-646",
)
mcp__plugin_router_router__router_invocations_tool(limit=20)
```
Expected: each `hook_id` from the wt_remove chain appears exactly once; no duplicate firings; no "No such file or directory" errors from idempotency-violating secondary fires.

- [ ] **Step 5: Pause — ask user before merging**

Do NOT proceed to Task 8 automatically. Output to user:

> "All commits landed on `feat/skill-polish-hook-fixes`. Tests green (X/X). 640 and 644 verified at runtime. 646 [fixed + verified | deferred — see notes]. Ready to rebase onto dev and FF-merge?"

Wait for explicit "yes" / "go ahead" / equivalent. On any hesitation, ambiguous response, or "wait" — stop.

---

## Task 8: Integration (Gated — requires user approval from Task 7 Step 5)

**Files:** no file edits; git operations only

- [ ] **Step 1: Rebase worktree branch onto latest dev**

```bash
cd /home/raul/worktrees/cpm/feat-skill-polish-hook-fixes
git fetch origin
git rebase origin/dev
```
Expected: clean rebase, no conflicts. If conflicts arise, **stop and ask user** — do not resolve unilaterally.

- [ ] **Step 2: FF-merge into local dev**

```bash
cd /home/raul/projects/claude-project-manager
git checkout dev
git pull --ff-only origin dev
git merge --ff-only feat/skill-polish-hook-fixes
```
Expected: fast-forward merge succeeds. If not, `--ff-only` will error — stop and ask user.

- [ ] **Step 3: Push dev (exercises CI)**

```bash
git push origin dev
```
Expected: push succeeds; CI workflow fires on the `dev` branch per current discipline.

- [ ] **Step 4: Monitor CI — wait until green before cleanup**

```bash
gh run list --branch dev --limit 1
```
Then watch the latest run:
```bash
gh run watch $(gh run list --branch dev --limit 1 --json databaseId --jq '.[0].databaseId')
```
Expected: all jobs green.

- [ ] **Step 5: Cleanup — remove worktree (with confirm)**

Ask user: "CI green. Remove worktree `/home/raul/worktrees/cpm/feat-skill-polish-hook-fixes`?"

On yes:
```python
mcp__plugin_worktree_worktree__wt_remove(
    path="/home/raul/worktrees/cpm/feat-skill-polish-hook-fixes",
)
```

- [ ] **Step 6: Batch-complete todos**

Call:
```python
mcp__plugin_proj_proj__todo_batch_complete(
    ids=["640", "641", "642", "643", "644", "645", "646"],
    project_name="claude-project-manager",
)
```

**If 646 was deferred:** omit `"646"` from the ids list — leave 646 open.

Expected: all ids transition to `done`. Inspect the returned envelope for `_hooks.structured_errors` — if any Todoist/Trello/Jira sync failed for a specific id, surface the error to the user.

- [ ] **Step 7: Git-flush tracking**

```python
mcp__plugin_proj_proj__tracking_git_flush(
    commit_message="Run: 640-646 skill polish + hook fixes",
)
```

---

## Acceptance Criteria Summary

- [ ] 640 (Task 2): no `Unknown tool: proj_todoist_full_sync` error on `proj_load_session`.
- [ ] 641 (Task 3): SKILL.md `--prio` section documents combo behavior explicitly.
- [ ] 642 (Task 3): SKILL.md `list` heading no longer mentions `pending`.
- [ ] 643 (Task 4): `todo_list`, `todo_tree`, `todo_ready` docstrings each contain a `count` semantics line.
- [ ] 644 (Task 5): `test_todo_ready_compact_with_limit` present and passing.
- [ ] 645 (Task 3): SKILL.md lines 42, 75, 102 tightened per spec.
- [ ] 646 (Task 6): duplicate firing fixed + regression test *OR* investigation findings captured in notes + deferred.
- [ ] Task 7: full test suite green after final commit.
- [ ] Task 8: dev CI green; worktree cleaned up (on user confirm); todos batch-completed.

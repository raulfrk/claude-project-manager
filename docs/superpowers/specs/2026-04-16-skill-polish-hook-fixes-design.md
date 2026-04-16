# Spec: Skill Polish + Hook Fixes (640-646)

**Date**: 2026-04-16
**Branch**: `feat/skill-polish-hook-fixes`
**Worktree**: `/home/raul/worktrees/cpm/feat-skill-polish-hook-fixes`
**Base**: `dev`
**Scope**: Todos 640, 641, 642, 643, 644, 645, 646
**Integration**: Rebase onto `dev`, FF-merge, push `dev`. **No PR.** Pause and ask before merging.

## Motivation

Seven follow-up todos accumulated during recent work (feat/todo-list-always-compact branch + revdiff auto-review). Individually small; thematically mixed (hook bugs, SKILL.md polish, test gap, MCP docstring drift). Bundling into one branch keeps review cohesive while atomic commits per theme preserve revertability.

## Todo Summary

| ID  | Priority | Theme          | Summary                                                                |
| --- | -------- | -------------- | ---------------------------------------------------------------------- |
| 640 | medium   | hook bug       | `todoist-full-sync-on-proj-load` targets stale `proj_todoist_full_sync`|
| 641 | low      | SKILL docs     | `--prio` combo ambiguity w/ ready/blocked/pending                      |
| 642 | low      | SKILL docs     | `pending` in heading, no tool map row                                  |
| 643 | low      | MCP semantics  | `count` means different things across todo_list/todo_tree/todo_ready   |
| 644 | low      | test           | Missing test for `todo_ready(compact=True, limit=N)` pagination        |
| 645 | low      | SKILL polish   | Caveman-ultra tighten SKILL.md lines 42, 75, 102                       |
| 646 | low      | hooks bug      | Duplicate firing on `wt_remove` — 4 fires, 2 errors on missing path    |

## Commits (Themed, In Order)

### Commit 1 — `fix(todoist): retarget todoist-full-sync hook to proj_sync` (640)

**Already-fixed check**: `plugins/todoist/.claude-plugin/default-hooks.yaml:74-77` currently targets `proj_sync`. The runtime `~/.claude/hooks.yaml` is the suspected source of the stale `proj_todoist_full_sync` reference — registry sync drift.

**Steps**:
1. Grep `~/.claude/hooks.yaml` for `proj_todoist_full_sync`. If present → registry is stale.
2. Resync: either manually edit `~/.claude/hooks.yaml` to match plugin default, or use `router_register_tool` / equivalent to refresh the `todoist-full-sync-on-proj-load` entry.
3. If plugin default-hooks also has a stale copy (unlikely per grep), fix + bump plugin version.
4. Verify: call `proj_load_session` → inspect router invocations log → no "Unknown tool" error for this hook.

**Files**: `~/.claude/hooks.yaml` (runtime, not committed) + possibly `plugins/todoist/.claude-plugin/default-hooks.yaml` (committed, only if plugin-side bug found).

**Risk**: Low. No behavior change except removing a logged error.

**Test**: None (runtime config, no unit test path). Verify by observing clean invocations log.

---

### Commit 2 — `docs(proj/skill): clarify --prio combos + pending filter + caveman tighten` (641 + 642 + 645)

**Files**: `plugins/proj/skills/todo/SKILL.md`

**Edits**:

- **642** — Line 39: drop `pending` from `list` subcommand heading.
  - Before: `**list** [all|pending|ready|blocked] [--prio|--priorities] [--full]`
  - After: `**list** [all|ready|blocked] [--prio|--priorities] [--full]`
  - Rationale: no tool map row exists for `pending`; cheapest to remove from docs vs. add a code path no one uses.
- **641** — Line 52 (`--prio` section): append one-line combo rule.
  - Add after `combinable w/ all, ignores --full`: `(ready/blocked/pending ignored when combined with --prio)`.
  - Keeps the combo explicit without implementing dual routing.
- **645** — Caveman tighten:
  - Line 42: `pass compact=False to underlying tool` → `pass compact=False`
  - Line 75 (full-mode rendering): `Render as nested bullets w/ icons using the existing formatting rules in the bullet list below.` → `Render as nested bullets w/ icons (rules below).`
  - Line 102 (tree `--full`): `render as nested bullets w/ 2-space indent using the rendering rules from the list section (icons, bold ID, inline metadata incl [manual], [blocked by X]/[blocks Y], [group:X]).` → `render as nested bullets w/ 2-space indent (rules from list section: icons, bold ID, inline metadata incl [manual], [blocked by X]/[blocks Y], [group:X]).`

**Risk**: Low. SKILL.md prose only; no code change.

**Test**: None. Skill content is prose; verify by reading rendered output in a session.

---

### Commit 3 — `docs(proj/mcp): document count field semantics per tool` (643)

**Files**: MCP tool module(s) hosting `todo_list`, `todo_tree`, `todo_ready` — likely `plugins/proj/server/server/tools/todo.py` (confirm during implementation).

**Edits**: Extend each tool's docstring (the one visible to MCP consumers) with a one-line `count` clarification.

- `todo_list`: `count = number of filtered todo items returned`
- `todo_tree`: `count = number of root todos (children not counted)`
- `todo_ready`: `count = number of ready todo items returned`

**Risk**: Zero. Docstring-only change.

**Test**: None required. If existing tests import docstrings for any reason, adjust.

---

### Commit 4 — `test(proj): todo_ready(compact=True, limit=N) pagination` (644)

**Files**: Test file hosting `TestTodoReadyCompact` class — find via grep during implementation (likely `plugins/proj/server/tests/test_todo_ready.py` or a compact-specific file).

**New test**: `test_todo_ready_compact_with_limit`
- Arrange: seed N≥3 ready todos.
- Act: call `todo_ready(compact=True, limit=1)`.
- Assert:
  - `count == 1`
  - `truncated == 0` (per skill doc: `todo_ready` has no `max_items`, `truncated` is hardcoded 0)
  - `result` string contains exactly 1 line.

**Risk**: None. Pure additive test.

**Test command**: `uv run pytest plugins/proj/server/tests/test_todo_ready.py -v` (or equivalent).

---

### Commit 5 — `fix(hooks): deduplicate wt_remove hook firing` (646)

**Investigation phase** (required before changes):
1. Create throwaway worktree, call `wt_remove`, capture router invocations log.
2. Compare against reported chain in todo 646 notes: 4 fires, 2 duplicates.
3. Rule out hypotheses:
   - **(a) Registry duplication**: `~/.claude/hooks.yaml` has duplicate `worktree-on-wt-remove-sandbox` entries from stale syncs.
   - **(b) Double-wrap**: `enable_hook_dispatch` called twice → tool wrapped twice → fires hook twice per call.
   - **(c) Cascade**: `wt_remove` internally calls another tool that re-triggers the chain (depth-0 to depth-1 shouldn't repeat a hook, but worth checking).

**Fix paths**:
- If (a): dedupe registry entries; add a sync-time guard preventing duplicate `hook_id` insertions.
- If (b): add wrap guard (`if getattr(fn, "_hook_wrapped", False): return fn`).
- If (c): self-exclusion or `exclude` list extension on the worktree plugin's `enable_hook_dispatch` call.

**Escape hatch**: if root cause non-obvious after ≤30 min investigation, stop. Update 646 notes w/ findings + skip fix. File follow-up todo for dedicated cycle. **Do not guess.**

**Files**: depends on root cause. Likely `plugins/_shared/hook_dispatch/dispatch.py` (b) or `~/.claude/hooks.yaml` + sync logic (a).

**Risk**: Medium. Router plugin is foundational; regressions cascade. Hence the investigate-first gate.

**Test**: Add regression test for whichever root cause. E.g. for (b): unit test asserting `enable_hook_dispatch` is idempotent — calling it twice on the same `mcp` instance doesn't double-wrap any tool.

---

## Verification Gate (Before Merge)

After all 5 commits land on `feat/skill-polish-hook-fixes`:

1. `uv run pytest plugins/proj/server/tests/` — full proj test suite green.
2. Manual: call `proj_load_session` → confirm no 640 error.
3. Manual: call `wt_create` + `wt_remove` on throwaway worktree → confirm 646 chain clean (if 646 fixed; skip if deferred).
4. `git log --oneline dev..HEAD` — confirm 5 (or fewer if 646 deferred) commits match the plan.

## Integration Step (Gated)

**Pause + ask user before proceeding.**

On approval:
```bash
cd /home/raul/worktrees/cpm/feat-skill-polish-hook-fixes
git rebase dev                    # ensure on top of latest dev
cd /home/raul/projects/claude-project-manager
git checkout dev
git merge --ff-only feat/skill-polish-hook-fixes
git push origin dev               # exercises CI per current discipline
```

After push green: optionally remove worktree via `wt_remove` w/ user confirm.

## Risks + Mitigations

| Risk                                                                 | Mitigation                                                      |
| -------------------------------------------------------------------- | --------------------------------------------------------------- |
| 640 fix requires registry-side change only user can trigger          | Inspect `~/.claude/hooks.yaml` first; guide user if needed      |
| 646 root cause unclear                                               | 30-min investigation cap; escape to follow-up todo              |
| 643 docstring edits trigger MCP schema regen                         | If any regen step exists, re-run + commit generated output      |
| Test file path for 644 wrong                                         | Grep for `TestTodoReadyCompact` during impl; use found location |
| SKILL.md edits break `/proj:todo list` interpretation                | Diff vs. prior version via revdiff before merge                 |

## Out of Scope

- Normalizing `count` field across tools (643 option b). Documented, not normalized.
- Restoring `proj_todoist_full_sync` (640 option "restore tool"). Retarget is correct.
- Adding a `pending` tool-map row (642 option "add row"). Dropped from heading instead.
- Broader caveman pass across all SKILL.md files in the repo. Only the todo skill lines flagged in 645.
- Full idempotency rewrite of `sandbox_remove_write_path` / `zoxide_remove` (646 option "full fix"). Fix the duplicate firing root cause only.

## Acceptance Criteria

- [ ] 640: no "Unknown tool: proj_todoist_full_sync" error on next `proj_load_session`.
- [ ] 641: SKILL.md `--prio` section explicitly documents combo behavior.
- [ ] 642: SKILL.md `list` heading no longer mentions `pending`.
- [ ] 643: `todo_list` / `todo_tree` / `todo_ready` docstrings each contain a `count` semantics line.
- [ ] 644: new test `test_todo_ready_compact_with_limit` passes.
- [ ] 645: SKILL.md lines 42, 75, 102 tightened per spec.
- [ ] 646: either duplicate firing fixed + regression test, OR investigation findings captured in todo notes + follow-up filed.
- [ ] Test suite green after final commit.
- [ ] All todos (640-646) marked done via `todo_batch_complete`.

## Todo Completion

After merge, batch-complete via `mcp__plugin_proj_proj__todo_batch_complete`:
- Include 646 only if fixed. If deferred, mark 646 still open and complete 640-645 only.

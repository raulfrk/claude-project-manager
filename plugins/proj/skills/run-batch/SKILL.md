---
name: run-batch
description: Batch/range execution workflow for multiple todos. Extension of run skill.
allowed-tools: mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__proj_search_knowledge, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_batch_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_notes_append, mcp__proj__todo_notes_patch, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__tracking_git_flush, Read, Task, TaskCreate, TaskList, EnterPlanMode, ExitPlanMode, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__worktree__wt_add_repo, mcp__proj__proj_session_context, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, mcp__proj__proj_decision_log, AskUserQuestion
argument-hint: "<id-range|comma-list> [--steps ...] [--fast|--careful] [--max-parallel N] [--no-verify] [--no-interactive] [--with-adversarial-review]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Batch/range execution workflow. Extension of `run/SKILL.md` — all flag parsing, quality param mapping, flag compat checks, preflight check tables, adversarial agent specs, agent delegation protocols defined there. This file covers batch-specific orchestration only.

> Flags + quality param mapping + compat checks: see `plugins/proj/skills/_shared/flags.md`
> Error handling, escalation protocol, agent fallback: see `plugins/proj/skills/_shared/errors.md`
> Batch phase details mirror `run/SKILL.md` phase equivalents.

## Parse — Batch Input

Parse each token from $ARGUMENTS:
- `<range>:<level>` (e.g. `2-5:fast`) → parse error: "Per-range annotation not supported. Use explicit list: `2:fast,3:fast,...`"
- `<id>:<level>` → extract id + level; invalid level → parse error "Unknown level '<level>' — valid: fast, careful"
- Bare `<id>`/`<range>` → no annotation

After parsing: `mcp__proj__todo_get` each ID (error on missing).
Store `per_todo_quality: dict[str, str]`. ≥1 annotation → `auto_suggest_mode = false`; zero → `auto_suggest_mode = true`.
Tag-immune upgrade: `security`/`breaking-change`/`migration` annotated `fast` → silently upgrade to `careful` + warn.

All flags (`--steps`, `--from`, `--iter`, `--no-interactive`, `--no-verify`, `--resume`, `--fast`/`--careful`, `--max-parallel`, `--with-adversarial-review`) parsed per `_shared/flags.md`.

## Phase A.0 — Quality Level Resolution (batch only)

`TaskCreate(title="Phase A.0: Quality Level Resolution", metadata={"phase": "A.0"})` → `TaskUpdate(status="in_progress")`

`effective_quality(todo_id) = per_todo_quality.get(todo_id, quality_level)` — per-todo annotation if present, else batch-level.

> All quality-level gates MUST use `effective_quality(todo_id)`, never bare `quality_level`.

**If `auto_suggest_mode` true** (zero annotations):

Each todo: `mcp__proj__todo_get` → compute suggested quality:
1. **Tag signals (highest wins)**: `security`/`breaking-change`/`migration` → `careful`; `needs-review` → `careful`; `auto-execute` → `fast`
2. **Complexity score** (dims 3-7 only — file-count + dir-spread default 0, no plans yet): 4-14 → `careful`; 0-3 → `fast`
3. **Title complexity floor** (skip if requirements.md exists): parse title for low/high signals (see run/SKILL.md §Phase A.0 for full heuristic). Net ≤ -2 → no floor; -1 to +1 → `fast` min; ≥ +2 → `careful` min
4. **Notes risk keyword floor**: `auth`/`secret`/`migration`/`breaking` in notes → `careful` min
5. **Tag-immune upgrade**: suggested `fast` + immune tag → `careful`

**Reason fmt**: `"tag:<tag>"` / `"score:<N>/14 (pre-plan estimate)"` + `"+ floor: title-complexity:<net>"` or `"+ floor: keyword:<word>"` when applied.

```
### Auto-suggest quality levels

| Todo | Title | Suggested | Reason |
|------|-------|-----------|--------|
| <id> | <title> | <level> | <reason> |
```

3 options via `AskUserQuestion`: **Accept all** / **Tweak** / **Override batch**.

Tweak flow: ask which IDs to change → per-ID `AskUserQuestion` (fast/careful/Keep) → re-display table. Override batch after tweaks → confirm "This will discard N individual tweaks. Confirm?"

**If `auto_suggest_mode` false**: skip auto-suggest. `per_todo_quality` from parse. Unspecified → `effective_quality()` fallback.

**Derive batch-level exec params** (after `per_todo_quality` confirmed):
- `batch_max_parallel_execute`: most conservative quality (careful→10, fast→30). Override via `--max-parallel`. Phase C exec only; Phase B uses orig batch-level `max_parallel`.
- `batch_worktree_enabled`: `max_parallel == 1` → false. Else use config `worktree_enabled`.

`--no-interactive`: auto-accept all; log via `notes_append` tag `auto-suggest:accepted` w/ markdown table + timestamp.
`--resume` checkpoint: `per_todo_quality` map + orig annotation string included, restored before Phase A.0.

After quality resolution: `TaskUpdate(status="completed")`.

## Iteration Loop (repeat up to `--iter N`, default 5)

N > 1 → `Iteration <i>/<N>`

**Phase A — Define** (if `run_define_interactive`):
`TaskCreate(title="Phase A: Define — batch", metadata={"phase": "A"})` → `TaskUpdate(status="in_progress")`
Each todo in dep order: `Define: <id> — <title>` → interactive define. Iteration > 1 → `--skip-bg-prep`.
Quality gate check: confidence ≤ 2 → flagged. Non-empty flagged → Continue/Re-define/Stop prompt. Re-define → interactive on flagged, resume from decompose.
After: `TaskUpdate(status="completed")`.

**Phase A.5 — Preflight:**
`TaskCreate(title="Phase A.5: Preflight — batch", metadata={"phase": "A.5"})` → `TaskUpdate(status="in_progress")`
`effective_quality(todo_id) == fast` → skip that todo.
Each todo: structural checks (10 if v2, else 5 — same table/rules as run/SKILL.md §"If preflight", incl grandfather rule, fix-loop cap, `--no-interactive` demotion).
Failures AND NOT `--no-interactive` (attempts < 3) → Fix/Continue/Stop. 4th attempt → auto-demote. `--no-interactive` → demote, log, auto-continue.
After: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

> Adversarial review (A.5b, C0.5b) off by default. Re-enable via `--with-adversarial-review`. See run/SKILL.md Preflight Agents Reference.

**Phase B — Decompose + Refine (parallel agents):**
`TaskCreate(title="Phase B: Decompose — batch", metadata={"phase": "B"})` → `TaskUpdate(status="in_progress")`
Each batch in dep order:
- If child IDs already known, write TodoWrite to track progress before spawning:
  ```
  TodoWrite([
    {content: "<child-id>: <title>", status: "pending"},
    ...
  ])
  ```
  (Skip pre-spawn TodoWrite if no children known yet.)
- One Agent per todo w/ `run_in_background=true`. Runs `agent_steps` autonomously. Decompose agents append result via `todo_notes_append(parent_id, 'decompose_result: {"created_ids": [...]}')`. Plan gap → escalation (see `_shared/errors.md`). Wait per batch, report failures → `failed-agents.yaml`.

After agents complete — collect created IDs per todo (replaces `todo_tree` refresh):
1. `mcp__proj__todo_get(parent_id)` → read `.notes` → find last line matching `decompose_result:` → parse JSON → extract `created_ids` → store as `decomposed_ids[todo_id]`.
2. Fallback (no `decompose_result` found): `mcp__proj__todo_list(status="pending")` → filter by `group:<parent_id>` tag → store as `decomposed_ids[todo_id]`.

Update TodoWrite: mark each `decomposed_ids[todo_id]` entry as `in_progress` when its execute agent launches; mark `completed` when merged.

`TaskUpdate(status="completed")`.

**Phase B.75 — Refine** (if `effective_quality(todo_id) == careful` AND `refine` in steps AND NOT `--no-interactive`):
fast → skip. careful → auto-enable. (No TaskCreate when skipped.)
`TaskCreate(title="Phase B.75: Refine — batch", metadata={"phase": "B.75"})` → `TaskUpdate(status="in_progress")`
Each todo: `skill: "proj:refine", args: "<id>"`. Subject to `max_parallel` throttle. Apply → reqs/research updated, preflight re-runs.
After: `TaskUpdate(status="completed")`.

## Phase C — Execute (after iteration loop)

`has_execute` false → skip to summary.

NOT `--no-interactive`:
```
### Prep complete — Execute?

1. **Execute all** — Plan and execute all todos
2. **Stop** — Exit (prep saved)
```

All fast → display: "⚡ --fast mode. Auto-executing low-complexity. Tag-immune get full review."

**Phase C1 — Plan (sequential, main):**
`--no-interactive` → skip to C2 w/ exec instructions.
`TaskCreate(title="Phase C1: Plan — batch", metadata={"phase": "C1"})` → `TaskUpdate(status="in_progress")`
Each todo in dep order: `todo_check_executable` → manual → skip. `proj_get_todo_context`, `proj_search_knowledge`. Smart gate scoring per run/SKILL.md §5ii-T. Plan creation, approval, store. File-overlap detection per execute/SKILL.md §Shared.
After: `TaskUpdate(status="completed")`.

**Phase C0.5 — Pre-execute Preflight** (after C1, before C2; skip if `effective_quality == fast`):
`TaskCreate(title="Phase C0.5: Pre-execute Preflight — batch", metadata={"phase": "C0.5"})` → `TaskUpdate(status="in_progress")`
Each todo (excl `manual_skipped_ids` + AUTO-EXECUTE w/o plan): 6 structural checks per run/SKILL.md Phase 1.25 table. Failure UX same as Phase A.5 (Fix/Continue/Stop, demote on `--no-interactive`, cap at 3 attempts).
All pass → silent. After: `TaskUpdate(status="completed")`. Failure → `failed`.

> Adversarial review (C0.5b) off by default. Re-enable via `--with-adversarial-review`. See run/SKILL.md Preflight Agents Reference.

**Phase C2 — Execute:**
`TaskCreate(title="Phase C2: Execute — batch", metadata={"phase": "C2"})` → `TaskUpdate(status="in_progress")`
Resume checkpoint (`--resume`): same 4-step logic as run/SKILL.md §5ii-T.
Task mapping (one-way): `TaskCreate` per todo, `addBlockedBy` rels. Only if tasks_enabled.
Children source: use `decomposed_ids[todo_id]` from Phase B if available; fallback to children from `todo_get` if `decomposed_ids` absent.
Each batch in dep order: one Agent per todo w/ `run_in_background=true`. Gets plan (or ctx/exec instructions) + reqs + research + parent ctx. Worktree → same instruction. Escalation on plan gap → see `_shared/errors.md`. Wait per batch, report failures. Write checkpoint per execute/SKILL.md §Shared. Failures → `failed-agents.yaml`.
Dirty main → warn merge conflicts.
After: `TaskUpdate(status="completed")`. Failure → `failed`.

**Phase C2.5 — Merge worktree branches** (if `worktree_enabled`):
`TaskCreate(title="Phase C2.5: Merge Worktree Branches — batch", metadata={"phase": "C2.5"})` → `TaskUpdate(status="in_progress")`
Same 3-tier cascade as run/SKILL.md Phase 2.5 (clean merge / auto-resolve / prompt manual). `-X theirs` + `git rerere` NOT used. Post-merge test: bisect logic. Re-exec queue: sequential on-main.
After: `TaskUpdate(status="completed")`. Conflict → `failed`.

**Phase C2.6 — Post-merge verification:**
`TaskCreate(title="Phase C2.6: Post-merge Verification — batch", metadata={"phase": "C2.6"})` → `TaskUpdate(status="in_progress")`
1. Full test run. Fail → `notes_append`, offer fix/proceed/abort.
2. Diff-vs-plan review agent — read-only, 60s, WARNING only.
3. Resource safeguards (pre-batch): disk ≥300MB × max_parallel, FDs ≥256 × max_parallel, ctx budget. Shortfall → cap `max_parallel`, `notes_append`.
After: `TaskUpdate(status="completed")`. Failure → `failed`.

**Phase C2a — Verification** (skip if `--no-verify`):
`TaskCreate(title="Phase C2a: Verification — batch", metadata={"phase": "C2a"})` → `TaskUpdate(status="in_progress")`
Verify each completed todo (excl `manual_skipped_ids` + failures). Checks A/B/C per execute/SKILL.md §4a. Combined table + persist per todo. Fix (parallel agents, max 2 retries) / Proceed / Skip.
After: `TaskUpdate(status="completed")`. Failure → `failed`.

**Satisfaction check:**
`TaskCreate(title="Phase SAT: Satisfaction Check — batch", metadata={"phase": "SAT"})` → `TaskUpdate(status="in_progress")`
Mode from `effective_quality(todo_id).satisfaction`: per-batch / per-todo / skip / per-todo+re-verify.
**Batch completion rule**: ≥2 → ALWAYS `todo_batch_complete`. Only `todo_complete` for single.
Recursive → `--careful`. Max depth 2.
All fast → post-run summary w/ `git diff HEAD~N`.
After: `TaskUpdate(status="completed")`.

**Phase C5 — Worktree cleanup** (if `worktree_enabled`):
`TaskCreate(title="Phase C5: Worktree Cleanup — batch", metadata={"phase": "C5"})` → `TaskUpdate(status="in_progress")`
Each worktree: `wt_unlock`, `wt_remove`, `sandbox_reconcile`, `wt_prune`. Display: "Cleaned up N worktrees."
After: `TaskUpdate(status="completed")`.

## Summary

Per-batch breakdown + overall count. `mcp__proj__notes_append`.

Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Run: {todo-id}")`.

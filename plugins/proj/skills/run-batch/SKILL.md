---
name: run-batch
description: Batch/range execution workflow for multiple todos. Extension of run skill.
allowed-tools: mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__proj_search_knowledge, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_batch_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__tracking_git_flush, Read, Task, TaskCreate, TaskList, EnterPlanMode, ExitPlanMode, TeamCreate, TeamDelete, SendMessage, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__worktree__wt_add_repo, mcp__proj__proj_session_context, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, mcp__proj__proj_decision_log, AskUserQuestion
argument-hint: "<id-range|comma-list> [--steps ...] [--fast|--careful] [--trust N] [--max-parallel N]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Batch/range execution workflow. Extension of `run/SKILL.md` — all flag parsing, quality param mapping, flag compat checks, preflight check tables, adversarial agent specs, and agent delegation protocols defined there. This file covers batch-specific orchestration only.

## Parse — Batch Input

Parse each token from $ARGUMENTS:
- `<range>:<level>` (e.g. `2-5:fast`) → parse error: "Per-range annotation not supported. Use explicit list: `2:fast,3:fast,...`"
- `<id>:<level>` → extract id + level; if level not `fast|careful` → parse error "Unknown level '<level>' — valid: fast, careful"
- Bare `<id>`/`<range>` → no annotation

After parsing: `mcp__proj__todo_get` on each ID to confirm existence; parse error for missing.
Store `per_todo_quality: dict[str, str]` (id → level for annotated only). If ≥1 annotation → `auto_suggest_mode = false`; zero → `auto_suggest_mode = true`.
Tag-immune upgrade: each ID in `per_todo_quality` w/ tags `security`/`breaking-change`/`migration`: if annotated `fast`, silently upgrade to `careful` + warn: "Todo N has tag X — annotation :fast upgraded to :careful (tag-immune safety rule)"

All flags (`--steps`, `--from`, `--iter`, `--no-interactive`, `--no-verify`, `--team`, `--no-team`, `--full-context`, `--trust`, `--resume`, `--no-pipeline`, `--refine`, `--fast`/`--careful`, `--force-plan`, `--batch-approve`, `--worktree`/`--no-worktree`, `--max-parallel`) parsed per run/SKILL.md Section 1. Quality param mapping + flag compat checks per run/SKILL.md tables.

## Batch mode

*(Range/comma list — all steps run autonomously)*

**a.** Setup
- Load steps, apply `--steps`/`--from`.
- `run_define_interactive` = `define` in steps (always interactive — define needs user input even in batch)
- `has_execute` = `execute` in steps
- `agent_steps` = steps excl `define` (if interactive) + `execute`

**b.** Dependency order
`mcp__proj__proj_identify_batches` w/ all IDs. Error on cycles.

**Phase A.0 — Quality Level Resolution (batch only):**

Helper: `effective_quality(todo_id) = per_todo_quality.get(todo_id, quality_level)` — per-todo annotation if present, else batch-level.

> ⚠ All quality-level gates in batch mode must use `effective_quality(todo_id)`, never bare `quality_level`. Same rule for any new control point.

**If `auto_suggest_mode` is true** (zero `:level` annotations):

Each todo in dep order, `mcp__proj__todo_get` + compute suggested quality:
1. **Tag signals (first, highest wins)**: `security`/`breaking-change`/`migration` → `careful`; `needs-review` → `careful`; `auto-execute` → `fast`
2. **Complexity score** (dims 3-7 only — file-count + dir-spread default 0, no plans yet): 4-14 → `careful`; 0-3 → `fast`.
3. **Title complexity floor** (replaces requirements floor): If requirements.md exists, skip. Else parse title:
 - Low-complexity (-1 each): short (<60 chars), targeted-fix (`fix\s+(line\s+\d+|off.by.one|typo|import|indent)`), single-rename (`rename\s+\S+\s+to\s+`), version-bump (`bump\s+version|update\s+version`), add-guard (`add\s+(try[/]except|try[/]finally|null check|type hint|assert)`), remove-unused (`remove\s+unused|delete\s+dead`), single-file ref (1 file-like token w/ `.` ext or `/` sep, excl URLs w/ `://`)
 - High-complexity (+1 each): long (>120 chars), multi-file (`\d+\s+files?` or 2+ file tokens), rewrite (`\b(rewrite|refactor|redesign|overhaul|rearchitect)\b`), cross-cutting (`\b(all\s+plugins?|across|everywhere|every\s+\w+|global)\b`), feature (`\b(new\s+feature|add\s+support\s+for|implement\s+\w+)\b`), scope (`\b(migrate|migration)\b`, only if not caught by tag #1)
 - Net: sum(high) - sum(low). <= -2 → no floor; -1 to +1 → `fast` min; >= +2 → `careful` min
4. **Notes risk keyword floor**: any of `auth`, `secret`, `migration`, `breaking` in notes → `careful` min
5. **Tag-immune upgrade**: suggested `fast` + `security`/`breaking-change`/`migration` tag → `careful`
6. **Precedence**: tags override score; highest tag level wins (careful > fast)

**Reason fmt**: `"tag:<tag>"` for tag-driven; `"score:<N>/14 (pre-plan estimate)"` for score; append `"+ floor: title-complexity:<net>"` or `"+ floor: keyword:<word>"` when applied. Only 2 levels: fast, careful.

```
### Auto-suggest quality levels

| Todo | Title | Suggested | Reason |
|------|-------|-----------|--------|
| <id> | <title> | <level> | <reason> |
```

3 options via `AskUserQuestion`:
- **Accept all** — populate `per_todo_quality` from suggestions
- **Tweak** — enter Tweak flow
- **Override batch** — ask for one level to apply to all

**Tweak flow**:
1. `AskUserQuestion`: "Which todo IDs to change? (comma-separated)"
2. Each ID: not in batch → warn inline, skip. Valid → `AskUserQuestion` w/ 2 levels (fast/careful) + "Keep suggested" — one call per ID.
3. Re-display table w/ resolved levels.
4. Override batch after tweaks → confirm "This will discard N individual tweaks. Confirm?"

**If `auto_suggest_mode` is false** (≥1 annotation):
Skip auto-suggest. `per_todo_quality` populated from parse. Unspecified → fallback via `effective_quality()`.

**Derive batch-level exec params** (after `per_todo_quality` confirmed):
- `batch_max_parallel_execute`: most conservative quality across `per_todo_quality` (careful→10, fast→30). Override via `--max-parallel`. Replaces table `max_parallel` for **Phase C exec only**. Phases B + C0 use orig batch-level `max_parallel`.
- `batch_worktree_enabled`: `max_parallel == 1` → false (whole batch). Else: use existing `worktree_enabled` derivation.

`--no-interactive`: skip AskUserQuestion; auto-accept all; log via `notes_append` tag `auto-suggest:accepted`; body = markdown table `| Todo | Title | Suggested | Reason |` w/ timestamp.

`--resume` checkpoint: `per_todo_quality` map + orig annotation string included in checkpoint YAML, restored on `--resume` before Phase A.0 (or skipped if populated).

**Iteration loop** (repeat up to `--iter N`, default 5):

N > 1 → `Iteration <i>/<N>`

**Phase A — Define (if `run_define_interactive`):**
Each todo in dep order:
- `Define: <id> — <title>`
- Execute define interactively in main
- Iteration > 1 → `--skip-bg-prep` (codebase unchanged, bg prep redundant).

**Quality gate check** (after define):
Agent-driven defines → read self-assessment. Confidence ≤ 2 → flagged.

flagged non-empty:

```
### Low-confidence definitions detected

| Todo | Low-confidence sections |
|------|------------------------|
| <id> | <section> (<score>/5) |

1. **Continue anyway** — proceed to decompose
2. **Re-define** — run interactive define on flagged todos
3. **Stop** — exit workflow
```

Re-define → interactive define on flagged, resume from decompose.

**Phase A.5 — Preflight:**

`effective_quality(todo_id) == fast` → skip preflight for that todo.

Each todo in dep order:
 Structural checks (10 if v2, else 5 — same table/rules as run/SKILL.md Section 2 "If preflight", incl grandfather, fix-loop cap, `--no-interactive` demotion).
 Collect failures.

Failures AND NOT `--no-interactive` (attempts < 3):

  ```
  ### Preflight Check — <N> issues across <M> todos (attempt <k>/3)

  | Todo | Check | Status |
  |------|-------|--------|
  | <id> | <check name> | FAIL — <message> |
  ...

  1. **Fix** — Re-run define on failing todos
  2. **Continue** — Proceed to decompose for all
  3. **Stop** — Exit workflow
  ```

 Fix → re-define failing, re-preflight (increment counter).
 Attempt 4 → auto-demote, `(1) Continue anyway (2) Stop`.

Failures AND `--no-interactive` → demote, log, auto-continue.
All pass → silent, Phase A.5b.

**Phase A.5b — Adversarial Review (Define) — Batch:**

Only when `effective_quality(todo_id) == careful`. NEVER `fast`.

**Batch sampling**: > 5 todos → only **5 highest-complexity** (7-dim score). Override: `--force-preflight-all`.

Spawn via `TeamCreate(name="preflight-adversarial-define-batch-{timestamp}", ...)`. One Agent per role per todo (never combine roles). After findings aggregated → `TeamDelete`.

Each sampled todo: 3 agents (Ambiguity, Completeness, Research Validation) in parallel. Same tools, timeout, JSON schema, severity as run/SKILL.md Phase A.5b. See run/SKILL.md Preflight Agents Reference appendix for prompts.

After return: aggregate into combined table. Same BLOCKING prompt flow. Timeouts/malformed JSON → WARNING. `TeamDelete`.

**Phase B — Remaining steps (parallel agents):**

**Mode selection:** `config_load()` → `team_mode.enabled`.
- `--team` OR (config enabled AND `--no-team` NOT passed) AND 2+ non-manual → **Team mode**.
- Else → **Task agent mode**.

**Team mode:**
1. `TeamCreate(name="run-decompose-{project}-{timestamp}", ...)`
2. Each batch in dep order: one Agent per todo w/ `team_name`. Each runs `agent_steps` autonomously. `--full-context` → include CLAUDE.md + NOTES.md. Plan gap → use ASK_USER protocol (see run/SKILL.md Agent Delegation Protocols appendix). Wait per batch. Report failures.
3. All done → `TeamDelete`.
4. Failures → log to `failed-teams.yaml`.

**Task agent mode (fallback):**
`TeamCreate(name="run-decompose-fallback-{project}-{timestamp}", ...)`. Each batch: one `general-purpose` Task per todo w/ `team_name`. Wait per batch. Report failures. All done → `TeamDelete`.

After Phase B: refresh descendants via `mcp__proj__todo_tree`.

**Phase B.75 — Refine (if `effective_quality(todo_id) == careful` AND `refine` in steps AND NOT `--no-interactive`):**

fast → skip. careful → auto-enable despite --refine.

Each todo in dep order: `skill: "proj:refine", args: "<id>"`. Subject to `max_parallel` throttle.
 Present reports sequentially. Apply → requirements/research updated, preflight re-runs.

**Phase B.5 — Convergence check** (skip if `--no-interactive`, only when N > 1)

Before iter 1: capture `snapshot_0` (requirements, research, tree structure per todo).
After each iter: `snapshot_<i>`.

Compare + display:

```
### Convergence Assessment (Iteration <i>) — Batch

| Todo | Requirements | Research | Structure |
|------|-------------|----------|-----------|
| <id> | Stable/Minor/Significant | ... | ... |

**Overall**: [Ready to execute | Continue iterating] — <reason>
```

Then between-iteration prompt (same 4 options as run/SKILL.md Section 4b).

**Phase C — Execute (after iteration loop):**

`has_execute` false → skip to summary.

NOT `--no-interactive`:
```
### Prep complete — Execute?

1. **Execute all** — Plan and execute all todos
2. **Stop** — Exit (prep saved)
```

All fast → display: "⚡ --fast mode. Auto-executing low-complexity. Tag-immune get full review."

**Phase C0 — Speculative planning** (if effective_quality == fast AND trust != 0 AND trust != 3):

`TeamCreate(name="run-spec-{project}-{timestamp}", ...)`. One read-only Task per todo w/ `team_name`. Each:
- Gets: todo ctx, requirements.md, research.md, parent ctx
- Read-only tools: `Read`, `Glob`, `Grep`, `proj_get_todo_context`, `proj_explore_codebase`, `content_get_requirements`, `content_get_research`
- Produces: `{prose: "<plan text>", actions: [{type: "create"|"modify"|"delete"|"test", file: "<path>"}]}`
- PLAN_ESCALATION: agents CANNOT call EnterPlanMode/ExitPlanMode. Agent drafts plan → SendMessage "PLAN_ESCALATION: <plan>" to team-lead → lead EnterPlanMode → ExitPlanMode → user approves/rejects → lead relays result → agent continues or revises.

Wait all. Failure → exclude, fall back to sequential planning. Store in `speculative_plans[todo_id]`. `TeamDelete`.

**Phase C1 — Plan (sequential, main):**

Trust 3 → skip to C2 w/ ctx only.
`--no-interactive` → skip to C2 w/ exec instructions.

Init `approved_plans = {}`, `executing_agents = {}`, `manual_skipped_ids = []`.

**Pipeline team setup** (if `pipeline_enabled` AND trust != 3): `TeamCreate(name="run-c1-pipeline-{project}-{timestamp}", ...)`. Torn down in C2.

Each todo in dep order:
1. `todo_check_executable` — manual → skip.
2. `proj_get_todo_context(include_parent=true)`.
3. `proj_search_knowledge(query=<title>, scope=all)` → "### Related Context" if snippets.

**Smart gate scoring** (skip if effective_quality == fast w/ auto-exec, or --force-plan):

Same 7-dimension complexity score (0-14), same eval order (tags → score → critical-path guard), same gate routing (AUTO-EXECUTE/LIGHT/FULL) as run/SKILL.md Section 5ii-T smart gate scoring.

`--force-plan` → FULL REVIEW all.

4. Plan creation (per gate level). Include Related Context.
5. Approval (per trust + gate).
6. Store.
7. Pipeline spawn (if enabled, trust != 3): respect `batch_max_parallel_execute` from Phase A.0. Spawn w/ `team_name="run-c1-pipeline-{project}-{timestamp}"`.

**Pattern detection** (skip if effective_quality == careful):

1. Normalize each plan: strip todo IDs, extract (action_type, file_pattern), replace unique segments w/ *.
2. Pairwise Jaccard: |A∩B| / |A∪B|.
3. Group plans >80% similarity. Min 2, max 10.
4. fast → auto-approve all groups.
5. Else → display groups as collapsible sections:

 **Pattern Group 1** (3 todos: 1.1, 1.2, 1.3) — 85% similar
 Common: modify `tests/test_*.py`, modify `server/tools/*.py`
 Deviations: todo 1.2 also creates `server/tools/new_helper.py`

 Per-group: Approve pattern / Edit pattern / Review individually

IF speculative_plans exist:
 **Phase C1a — Batch review:**

  ```
  ### Batch Plan Review — N todos

  **Todo <id>**: <1-line summary>
  Actions: create X, modify Y, test Z

  [repeat for each todo]

  ### File Overlap Table
  | File | Touched by |
  |------|-----------|
  | ... | ... |

  ### Pattern Groups (if any — see pattern detection)
  [collapsible pattern sections]

  1. **Approve all** — proceed to execution
  2. **Edit** — re-plan specific todos (enter IDs). After re-planning, re-run file-overlap detection on the updated plan set.
  3. **Reject** — remove specific todos (enter IDs)
  4. **Cancel** — abort batch
  ```

 `--batch-approve` OR trust 2 → auto-approve all.

**File-Overlap Detection** (after C1, before C2, skip if trust 3):
1-2: Same as run/SKILL.md Section 5ii-T file-overlap (extract file lists, build within-batch overlap matrix).
3. Quality behavior (pairwise — `max(effective_quality(A), effective_quality(B))`):
 - fast → auto-proceed.
 - careful → auto-serialize.
4. Overlaps found (when prompted via `--max-parallel` override):

```
### File Overlap Warning

| File | Touched by | Batch |
|------|-----------|-------|
| models.py | todo 1, todo 3 | 1 |
| config.py | todo 1, todo 3 | 1 |

Options:
1. **Serialize** — Move conflicting todos to a separate sequential batch (executed one at a time after parallel batch completes, using the same team)
2. **Proceed** — Execute in parallel anyway (risk of conflicts)
3. **Cancel** — Stop execution
```

5-8: Same serialize/proceed/cancel/silent logic.

**Phase C0.5 — Pre-execute Preflight**

After C1 plan approval, before C2 exec spawn (before C1.5 worktree setup). Per-todo, dep order, not batch-aggregated.

**Skip under trust 3**: no plan → checks N/A. Log: `Phase C0.5 skipped — trust 3 (no plan)`.
**Skip when `effective_quality(todo_id) == fast`**: consistent w/ `preflight: skip`.

Each todo (excl `manual_skipped_ids` + AUTO-EXECUTE w/o plan), 6 structural checks per run/SKILL.md Phase 1.25 table.

**On failure** (same UX as A.5):
- NOT `--no-interactive` AND attempts < 3 → Fix / Continue / Stop. Fix re-runs C1 plan (increment counter).
- `--no-interactive` → demote BLOCKING→WARNING, log, decision log, continue.
- 4th attempt → auto-demote, `(1) Continue anyway (2) Stop`.

All pass → silent, Phase C0.5b.

**Phase C0.5b — Adversarial Review (Pre-execute)**

Only `effective_quality(todo_id) == careful`. Never fast. Skip under trust 3.

**Batch sampling**: > 5 → 5 highest-complexity (same ranking as A.5b). Override: `--force-preflight-all`.

`TeamCreate(name="preflight-adversarial-execute-{timestamp}", ...)`. One Agent per role per todo. After aggregation → `TeamDelete`.

Each sampled todo, 3 read-only Agents in parallel (File Path Verifier, Spec-Plan Alignment, Impact Scanner). Same tools, timeout, JSON schema as run/SKILL.md Phase C0.5b. See run/SKILL.md Preflight Agents Reference appendix for prompts.

**Findings aggregation**: merge across 3 agents, combined table (same fmt as A.5b). Same severity semantics. Timeouts/malformed JSON → WARNING.

`worktree_enabled` → File Path Verifier checks worktree tree for todo's branch.

**Phase C1.5 — Worktree setup** (if `worktree_enabled`):

Same prereq check + dirty-tree handling + per-todo setup as run/SKILL.md Phase 1.5.

Pipeline → per-todo after plan approval. Non-pipeline → all batch todos before C2.

**Phase C2 — Execute:**

**Mode selection:** `config_load()` → `team_mode.enabled`. Same rules as Phase B mode selection.

**Resume checkpoint** (`--resume`): same 4-step logic as run/SKILL.md Section 5ii-T (find checkpoint, fresh/stale check, skip to batch_index or restart).

**Team mode:**

IF `pipeline_enabled`:
 Wait for agents. Report. `TeamDelete(team_name="run-c1-pipeline-{project}-{timestamp}")`.
 All failed → batch failure short-circuit.
ELSE:

1. `TeamCreate(name="run-exec-{project}-{timestamp}", ...)`
1a. Task Mapping (one-way): same as run/SKILL.md Section 5ii-T Phase 2 (TaskCreate per todo, addBlockedBy, pull model, one-way only).

2. Each batch in dep order (excl `manual_skipped_ids`):
 - Display batch. One Agent per todo w/ `team_name`. Gets: plan (or ctx/exec instructions) + requirements.md + research.md + parent ctx. `--full-context` → CLAUDE.md + NOTES.md.
 - Worktree → same instruction.
 - Agents exec plan, no `todo_complete`. Plan gap → use ASK_USER protocol (see run/SKILL.md Agent Delegation Protocols appendix).
 - Wait per batch. Report failures.
 - Write checkpoint:
     ```yaml
     team_name: run-exec-{project}-{timestamp}
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
3. All done → `TeamDelete`.
4. Failures → `failed-teams.yaml`.

**Task agent mode (fallback):**

IF `pipeline_enabled`: same wait/teardown/short-circuit.
ELSE:

`TeamCreate(name="run-fallback-{project}-{timestamp}", ...)`.

Each batch: one `general-purpose` Task per todo w/ `team_name`. Gets: todo details, requirements.md, research.md, parent ctx, plan (or ctx/exec instructions). No `todo_complete`. Worktree → same instruction. Wait. Report.

All done → `TeamDelete`.

Dirty main → warn merge conflicts.

**Phase C2.5 — Merge worktree branches** (if `worktree_enabled`):

Same 3-tier cascade as run/SKILL.md Phase 2.5:
- Tier 1: clean merge → add to `files_merged_this_batch`, notes, remove worktree + branch.
- Tier 2: auto-resolve (≤5 files, <50 lines, no critical-path). Decision: NOT in set → theirs; IN → ours.
- Tier 3: `--no-interactive` → abort, enqueue. Interactive → prompt manual/abort.

`-X theirs` + `git rerere` intentionally NOT used.

Post-merge test: same bisect logic.
Re-exec queue: same sequential on-main logic.

**Phase C2.6 — Post-merge verification** (after cascades + re-exec drain, before C2a):

1. Full test run w/o `-q`. Fail → `notes_append`, offer fix/proceed/abort.
2. Diff-vs-plan review agent — read-only, 60s, WARNING only, feeds Drift column.
3. Resource safeguards (pre-batch, gate before C1.5): disk ≥300MB × max_parallel, FDs ≥256 × max_parallel, ctx budget. Shortfall → cap `max_parallel`, `notes_append`.

**Phase C2a — Verification** (skip if `--no-verify`):

Each completed todo (excl `manual_skipped_ids` + failures), verification from execute step 4a:
- A. Automated (tests/lint)
- B. Spec validation (criteria vs diff)
- C. Diff review (plan vs actual)

Verify ALL first, combined report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| <id> | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| <id> | FAIL (2 failed) | 2/3 met | 1 extra file | FAIL |
```

Persist to `todos/<id>/verification-report.md` (timestamped, overwrite prev).

Failures → `N passed, M failed. Fix? (1) Fix (2) Proceed (3) Skip`
- Fix: N >= 2 → `TeamCreate(name="run-verify-fix-batch-{project}-{timestamp}", ...)`, spawn, `TeamDelete`. N == 1 → single Agent. Each gets: report + ctx + plan + fix instructions. Re-verify (max 2 retries). Re-prompt if still failing.
- Proceed/Skip: same as run/SKILL.md.

All pass → display, proceed.

**Satisfaction check** (sequential, main):

Mode from `effective_quality(todo_id).satisfaction`:
- per-batch → summary, "Satisfied?" once, `todo_batch_complete`.
- per-todo → individual loop, collect, `todo_batch_complete` at batch end.
- skip → auto-complete all via single `todo_batch_complete`.
- per-todo + re-verify → individual + re-verify + `todo_batch_complete`.

**Batch completion rule:** ≥2 → ALWAYS `todo_batch_complete`. Only `todo_complete` for single.

Per-todo/re-verify: `satisfied_ids = []`. Each completed todo (excl `manual_skipped_ids`):
 a. "Satisfied with todo <id>, or anything else needed?"
 1. Satisfied → append (no `todo_complete` yet).
 2. Not satisfied → ask what's missing. `proj_decision_log(...)`. Fix, re-ask.
 3. Redefine → interactive define, re-run.

 After: `len >= 2` → `todo_batch_complete`. `== 1` → `todo_complete`.

 Recursive → `--no-pipeline --careful --no-worktree`. Max depth 2. Depth >= 2 → refuse.

All fast → post-run summary w/ `git diff HEAD~N`.

Clear `executing_agents = {}`.

**Phase C5 — Worktree cleanup** (if `worktree_enabled`, always runs):

Each worktree: `wt_unlock`, `wt_remove`, `sandbox_reconcile`, `wt_prune`.
Display: "Cleaned up N worktrees."

**d.** Summary

Per-batch breakdown + overall count. `mcp__proj__notes_append`.

**e.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Run: {todo-id}")`.

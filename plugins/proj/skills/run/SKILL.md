---
name: run
description: Run the full workflow (define → decompose → execute) on a todo interactively, prompting between each step. Use when asked "run 1", "full workflow on 1", or "proj:run 1".
allowed-tools: mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__proj_search_knowledge, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__tracking_git_flush, Read, Task, TaskCreate, TaskList, EnterPlanMode, ExitPlanMode, TeamCreate, TeamDelete, SendMessage, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__worktree__wt_add_repo, mcp__proj__proj_session_context, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, mcp__proj__proj_decision_log, AskUserQuestion
argument-hint: "<todo-id> [--steps define,execute] [--from <step>] [--iter N] [--no-interactive] [--no-verify] [--team] [--no-team] [--full-context] [--trust 0-3] [--resume] [--no-pipeline] [--refine] [--fast|--balanced|--careful|--paranoid] [--force-plan] [--batch-approve] [--worktree] [--no-worktree] [1:fast,2:careful,3]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Run workflow for: $ARGUMENTS

**1.** Parse & validate

Extract from $ARGUMENTS:
- Input mode: single ID (`1`), range (`2-5`), comma list (`1,3,5`)
- `--steps <csv>`: explicit step list (reordered to workflow order)
- `--from <step>`: slice from that step onward (`--steps` takes precedence)
- `--iter N`: prep iteration count (default 5, positive int)
- `--no-interactive`: run autonomously, no user prompts
- `--no-verify`: skip verification in execute (passed through)
- `--team`: force team mode ON (overrides config)
- `--no-team`: force team mode OFF (overrides config)
- `--full-context`: include CLAUDE.md + NOTES.md in each agent's ctx
- `--trust N` (0-3): override trust level. If unset, use `team_mode.trust_level` from config (default 1).
 - Trust 0 (supervised): per-todo approval — each plan presented individually, user approves one at time
 - Trust 1 (guided): bulk approval + parallel exec — all plans presented sequentially, user approves each, bulk confirm before exec. Default.
 - Trust 2 (autonomous): auto-approve plans — skip `ExitPlanMode` user review
 - Trust 3 (full-auto): no plan phase — agents exec w/ ctx only (requirements + research + parent ctx)
- `--resume`: resume from most recent checkpoint. See Resume checkpoint sections.
- `--no-pipeline`: disable plan-while-executing pipeline (default: pipeline enabled)
- `--refine`: enable requirement refinement w/ review agents (default: off for `--balanced`, auto-enabled for `--careful`/`--paranoid`)
- `--fast`: minimize review gates, auto-exec low-complexity todos, skip verification. Tag immunity: `security`/`breaking-change`/`migration` still get FULL REVIEW.
- `--balanced`: smart-gate scoring determines review level.
- `--careful`: default. Full review all plans, auto-enable refine, enhanced verification.
- `--paranoid`: sequential exec (max_parallel=1), cross-review agents, full verification w/ independent review agent.
- Quality levels mutually exclusive (last wins, default: `--careful`).
- `--force-plan`: force FULL REVIEW on all todos despite complexity score.
- `--batch-approve`: auto-approve all speculative plans w/o review (subject to trust level).
- `--worktree`: (default) enable worktree isolation for parallel exec. No-op; kept for explicitness.
- `--no-worktree`: opt out of worktree isolation — run all agents on cur branch. Use when batch is small, fully sequential, or worktree setup costs outweigh benefits.

Derive `worktree_enabled` — **default: on**:
 1. `--no-worktree` explicitly passed → off.
 2. `quality_level == paranoid` → off (max_parallel=1 makes worktree unnecessary).
 3. Else → on (despite `config.worktree_isolation`; config flag retained for legacy callers, force-off via `--no-worktree`).

Derive `quality_level` from flags. If no quality flag, call `mcp__proj__config_load` and read `config.quality_level`, defaulting to `--careful` if unset/unrecognized.

**Quality Level Parameter Mapping:**

| Parameter | --fast | --balanced | --careful | --paranoid |
|-----------|--------|-----------|-----------|-----------|
| gate_override | auto-execute (tag-immune) | smart-gate | full-review | full-review |
| batch_approve | auto | smart-gate | disabled | disabled |
| speculative_planning | enabled | enabled | disabled | disabled |
| pattern_detection | auto-approve | enabled | disabled | disabled |
| verification_mode | skip | standard | enhanced | full |
| max_parallel | 30 | 30 | 10 | 1 |
| satisfaction | skip (auto-complete) | per-batch | per-todo | per-todo + re-verify |
| preflight | skip | enabled | enabled | enabled |
| preflight_structural | skip | enabled | enabled | enabled |
| preflight_adversarial_agents | skip | skip | enabled | enabled |
| pre_execute_preflight | skip | enabled | enabled | enabled |
| refine | skip | if --refine set | auto-enabled (per iteration) | auto-enabled (per iteration) |
| worktree | on (unless `--no-worktree`) | on (unless `--no-worktree`) | on (unless `--no-worktree`) | off (max_parallel=1) |
| overlap_action | auto-proceed | prompt user | auto-serialize | auto-serialize + warn |

**Recommended cap**: 10 for CPU-bound/API-rate-limited workloads (heavy test suites, rate-limited LLM calls, DB migrations). Raw `--fast`/`--balanced` ceiling of 30 tuned for I/O-bound work w/ isolated worktrees; override via `--max-parallel` or `config.team_mode.max_agents` when agent saturates shared resource.

Derive: `pipeline_enabled = not no_pipeline_flag`

**Flag compatibility check** (validate before proceeding):
- `--fast --force-plan` → ERROR: "Cannot combine --fast with --force-plan."
- `--fast --refine` → fast wins, refine skipped (warn).
- `--careful --batch-approve` → careful wins, batch approve disabled (warn).
- `--paranoid --batch-approve` → paranoid wins, batch approve disabled (warn).
- `--force-plan --batch-approve` → ERROR: "Cannot combine --force-plan with --batch-approve."
- `--no-verify --paranoid` → ERROR: "Cannot combine --no-verify with --paranoid."
- `--no-verify --careful` → WARNING: "--no-verify overrides --careful's enhanced verification." Verification skipped.
- `--fast --steps refine` → ERROR: "Cannot use --fast with --steps refine (fast skips refine)."
- `--batch-approve --no-pipeline` → Allowed (speculative planning independent of pipeline).
- `--paranoid --no-pipeline` → Redundant warn: "--paranoid already enforces max_parallel=1."
- `--careful --no-pipeline` → Allowed.
- `--fast --no-pipeline` → Redundant warn: "--fast with auto-execute makes pipeline moot."
- `--force-plan --careful` → Redundant warn: "--careful already forces full review."
- `--force-plan --paranoid` → Redundant warn: "--paranoid already forces full review."
- `--no-verify --balanced` → --no-verify wins, verification skipped.
- `--no-verify --fast` → Redundant: --fast already skips verification.
- `--refine --from execute` → Refine skipped (--from execute skips refine per step-order slicing).
- `--force-plan --trust 3` → ERROR: "Cannot combine --force-plan with --trust 3 (trust 3 skips planning)."
- `--paranoid --worktree` → paranoid wins, worktree disabled (warn: "max_parallel=1 makes worktree isolation unnecessary").
- `--worktree --no-interactive` → Allowed. Auto-resolve only for merge conflicts.
- Per-todo `:level` + `--no-verify` → annotation wins for that todo; `--no-verify` applies only to unannotated todos.
- Per-todo `:level` + `--force-plan` → annotation wins for that todo; `--force-plan` applies only to unannotated todos.
- Per-todo `:fast`/`:balanced` on `security`/`breaking-change`/`migration`-tagged todo → silently upgraded to `:careful` at parse time w/ user warn (tag-immune safety rule; mirrors global `--fast` tag-immunity in Phase C1).

No todo ID → stop: "Todo ID required. Usage: `/proj:run <id> [--steps define,execute] [--from <step>]`"

Default step order: `[define, preflight, decompose, refine, execute]`.
Apply `--steps`/`--from` to filter/slice. Error on invalid step name.

**Single ID**: `mcp__proj__todo_get` to confirm exists. If input has `:level` suffix (e.g. `1:fast`), parse error: "Cannot use `:level` annotation in single-ID mode. Use `--fast` (or appropriate quality flag) instead."
**Range/comma list**: parse each token:
- `<range>:<level>` (e.g. `2-5:fast`) → parse error: "Per-range annotation not supported. Use explicit list: `2:fast,3:fast,...`"
- `<id>:<level>` → extract id + level; if level not `fast|balanced|careful|paranoid` → parse error "Unknown level '<level>' — valid: fast, balanced, careful, paranoid"
- Bare `<id>`/`<range>` → no annotation

After parsing: `mcp__proj__todo_get` on each ID to confirm existence; parse error for missing.
Store `per_todo_quality: dict[str, str]` (id → level for annotated only). If ≥1 annotation → `auto_suggest_mode = false`; zero → `auto_suggest_mode = true`.
Tag-immune upgrade: each ID in `per_todo_quality` w/ tags `security`/`breaking-change`/`migration`: if annotated `fast`/`balanced`, silently upgrade to `careful` + warn: "Todo N has tag X — annotation :<old> upgraded to :careful (tag-immune safety rule)"
Skip to **Batch mode**.


## Single-ID mode

**2.** Display

```
Running workflow on todo **<id>** — <title>
Steps: <step1> → <step2> → ... (x<N> iterations)
```

Split: `prep_steps` = all except `execute`, `has_execute` = `execute` in steps.

**3.** Iteration loop (repeat up to N times)

N > 1 → announce: `Iteration <i>/<N>`

Build descendant list: `mcp__proj__todo_tree`, flatten depth-first.

**Each prep step:**

**If `define`** — sequential, interactive:
Each todo in descendant list (dependency order via `mcp__proj__proj_identify_batches`):
 - Announce: `Define: <id> — <title>`
 - `skill: "proj:define", args: "<id>"` (iteration > 1 → append `--skip-bg-prep`).

**Quality gate check** (after define):
Each agent-driven define → read self-assessment. Confidence ≤ 2 (speculative/inferred) → add to flagged_todos.

If flagged_todos non-empty:

```
### Low-confidence definitions detected

| Todo | Low-confidence sections |
|------|------------------------|
| <id> | <section> (<score>/5) |

1. **Continue anyway** — proceed to decompose
2. **Re-define** — run interactive define on flagged todos
3. **Stop** — exit workflow
```

Re-define → run interactive define on each flagged, resume from decompose.

**If `preflight`** — inline, main conversation:

fast quality → skip preflight entirely.

**Preflight versioning & grandfather rule**: each todo carries `preflight_version` meta. Unset (existing todos) → **legacy mode** w/ 5 checks (1-5). `preflight_version: 2` → expanded 10-check v2. New todos default v2. Manual upgrade: `todo update <id> preflight_version=2`. Bulk migration tracked separately.

**Fix-loop cap**: max 3 re-runs per todo per `/proj:run`. 4th attempt → auto-demote remaining BLOCKING to WARNING: "3 fix attempts exhausted — (1) Continue anyway (2) Stop".

**`--no-interactive` demotion**: BLOCKING auto-demoted to WARNING, logged via `notes_append` tag `preflight:auto-demoted`, decision log entry per demotion. Run auto-continues.

Each todo in descendant list:
1. Read requirements.md via `content_get_requirements`. Not found → hard fail "No requirements found. Run define first." (all checks fail).
2. Read research.md via `content_get_research`. Not found → mark research-dependent checks FAIL, continue others.
3. Structural checks. Legacy = checks 1-5; v2 = all 10:

   | # | Check | Data read | Pass condition | Version |
   |---|-------|-----------|---------------|---------|
   | 1 | Testable acceptance criteria | requirements.md, "Acceptance Criteria" | section exists w/ >= 1 item | v1+v2 |
   | 2 | Out-of-scope section | requirements.md, "Out of Scope" | section exists w/ >= 1 bullet | v1+v2 |
   | 3 | Research approach options | research.md, "Approach Options" or top-level headers | >= 2 options | v1+v2 |
   | 4 | Testing strategy coverage | requirements.md, "Testing Strategy" | mentions >= 2 of: unit, integration, e2e, manual | v1+v2 |
   | 5 | Edge cases documented | requirements.md, "Edge Cases" | >= 2 bullets/list items | v1+v2 |
   | 6 | Vague language (expanded) | requirements.md, "Goal" + "Acceptance Criteria" ONLY | no tokens from expanded vague-phrase list | v2 only |
   | 7 | Acceptance criterion verifiability | requirements.md, "Acceptance Criteria" | each criterion has >= 1 of: file path, fn/class name, CLI cmd, test name, numeric threshold, explicit observable outcome | v2 only |
   | 8 | Research file-path anchor | research.md, "Recommended Approach"/"Key Dependencies" + repo filesystem | >= 1 path ref resolving to existing file | v2 only |
   | 9 | Research option distinctness | research.md, "Approach Options" | when >= 2 options, differ by >= 1 of: library/tool, file/module placement, data-flow direction | v2 only |
   | 10 | Failure-mode coverage | requirements.md, "Edge Cases" | >= 1 explicit failure mode (err path, invalid input, network failure, missing file, permission err, concurrency, timeout) | v2 only |

 **Expanded vague-phrase list (v2, check 6)** — scoped ONLY to "Goal" + "Acceptance Criteria" of requirements.md. Excluded by policy (concrete engineering meanings): "reasonable", "simple", "efficient", "fast", "good", "clean", "lightweight", "proper", "correct", "elegant". List covers only unmeasurable marketing/handwave terms:

   ```
   robust, seamless, scalable, modern, state-of-the-art, best-in-class,
   user-friendly, intuitive, ideal, optimal, blazing, lightning-fast,
   enterprise-grade, world-class, next-generation, performant,
   cutting-edge, turnkey, revolutionary, game-changing, industry-leading,
   bulletproof, frictionless
   ```

 **23 phrases** (exceeds min 20). Self-validated against requirements.md of todos 487, 503-505, 507-510 w/ **zero false positives** in Goal/Acceptance Criteria (only hit: todo 503's own requirements.md where phrases appear as quoted examples — expected meta self-match, not defect).

 Match fails check 6: `Vague term "<token>" in <section> section — replace with a measurable criterion or remove`. Whole-word, case-insensitive.

 **Examples**:
 - FAIL (6): Goal "Build robust, scalable ingestion pipeline." — `robust` + `scalable` match.
 - PASS (6): Goal "Build ingestion pipeline that handles 10k events/sec with <1% drop rate." — measurable, no vague terms.
 - FAIL (7): "Users can log in smoothly" — no path, fn, CLI, test, threshold, or observable outcome.
 - PASS (7): "`POST /api/login` returns 200 with valid JWT in `token` field for valid credentials" — API endpoint + observable outcome.
 - FAIL (8): research.md "Recommended Approach" is pure prose, no file refs.
 - PASS (8): research.md refs `plugins/proj/server/server/tools/todo.py` in "Key Dependencies".

4. All pass → silent, next step.
5. Any fail AND NOT `--no-interactive` (fix-loop < 3):

   ```
   ### Preflight Check — <N> issue(s) found (attempt <k>/3)

   | # | Check | Status |
   |---|-------|--------|
   | 1 | Testable criteria | PASS |
   | 6 | Vague language | FAIL — "robust" in Goal section |
   ...

   1. **Fix** — Re-run define on this todo to address failures
   2. **Continue** — Proceed to decompose anyway
   3. **Stop** — Exit workflow
   ```

 Fix → re-run define on failing todo, re-run preflight (increment counter).
 Attempt 4 → auto-demote remaining BLOCKING to WARNING, prompt only `(1) Continue anyway (2) Stop`.

6. Any fail AND `--no-interactive` → demote BLOCKING to WARNING, log via `notes_append` tag `preflight:auto-demoted`, decision log per demotion, auto-continue.

**Phase A.5b — Adversarial Review (Define)**

Runs only when `quality_level` in `[careful, paranoid]`. NEVER under `--balanced`/`--fast`. Runs after structural checks pass, in parallel across 3 read-only agents.

**Batch sampling**: descendant list > 5 → agents run on **5 highest-complexity** todos (ranked by 7-dimension complexity score from Phase C1 smart gating). Others get structural checks only. Override: `--force-preflight-all`.

**Agents** — spawn via `TeamCreate`, one Agent per role per todo. Never combine roles. Call `TeamCreate(name="preflight-adversarial-define-{todo_id}", description="Adversarial review agents (Ambiguity, Completeness, Research Validation) for todo {todo_id}")`, spawn each w/ that `team_name`. After all return + findings aggregated → `TeamDelete(team_name="preflight-adversarial-define-{todo_id}")`.

| Agent | Reads | Checks |
|-------|-------|--------|
| Ambiguity | requirements.md + research.md | undefined domain terms, handwavey claims, unmeasurable goals |
| Completeness | requirements.md + research.md | missing failure modes, missing auth/security concerns, scope gaps |
| Research Validation | research.md + repo filesystem | each ref'd file exists, option distinctness, risk realism |

Each spawned as `general-purpose` Task:
- Tools (read-only): `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__content_get_research`, `mcp__proj__proj_explore_codebase`
- Timeout: 90s
- Output schema (strict JSON):

  ```json
  {
    "agent": "ambiguity|completeness|research_validation",
    "findings": [
      {
        "severity": "BLOCKING|WARNING|INFO",
        "title": "short description",
        "evidence": "direct quote or file:line reference",
        "suggested_fix": "optional"
      }
    ]
  }
  ```

See **Preflight Agents Reference** appendix for prompt templates.

**Findings aggregation**: merge across 3 agents, single table keyed by todo:

```
### Preflight Adversarial Review — todo <id>

| Severity | Agent | Finding | Evidence |
|----------|-------|---------|----------|
| BLOCKING | Completeness | Missing auth failure path | requirements.md L23 |
| WARNING  | Ambiguity | Undefined term "downstream" | requirements.md L12 |
```

**Severity semantics**:
- BLOCKING — triggers Fix / Continue / Stop. Subject to `--no-interactive` demotion + fix-loop cap.
- WARNING — shown, non-blocking, single OK. Under `--paranoid`, WARNINGs need explicit ack; "Acknowledge all WARNINGs" shortcut when >= 3.
- INFO — shown, non-blocking, no ack.

**Degraded mode**: agent timeouts/malformed JSON → demoted to WARNING (never BLOCKING). Raw output shown under finding.

**If `decompose`** — parallel Task agents:

Spawn via `TeamCreate` before per-batch loop: `TeamCreate(name="run-decompose-single-{timestamp}", description="Run: decomposing descendants of root todo")`. Each Task agent uses that `team_name`. After all batches → `TeamDelete`.

Each batch in dep order:
 - One `general-purpose` Task per todo w/ `team_name`. Each runs decompose autonomously.
 - Wait for batch. Report failures.
After: refresh descendant list via `mcp__proj__todo_tree`. `TeamDelete`.

**If `refine`** — after decompose, within iteration (if `quality_level in [careful, paranoid]` AND `refine` in steps AND NOT `--no-interactive`):

fast → skip refine. careful/paranoid → auto-enable despite --refine flag.

Each todo: `skill: "proj:refine", args: "<id>"`.
 Apply → requirements/research updated, preflight re-runs automatically.

**3a.** Capture iteration snapshots (only when N > 1)

**Before iteration 1** (after building initial descendant list, before any prep steps), capture pre-existing state as `snapshot_0`:
- Each todo: read `content_get_requirements` + `content_get_research`
- Record descendant list structure: child IDs, titles, blocked_by
- Descendant list > 15 → read content for root-level children only.

**After each iteration's prep steps**: capture as `snapshot_<i>` (same method).

**4.** Between-iteration prompt (skip if last iteration or `--no-interactive`)

**4a.** Convergence assessment

Compare `snapshot_<i>` w/ `snapshot_<i-1>` across 4 dimensions:

- Requirements: compare requirements.md text per todo. Ignore whitespace/fmt/minor rewording. Flag new acceptance criteria, changed goals/testing strategy.
- Research: compare research.md. Flag changed recommended approach, new options, significant findings.
- Structure: compare descendant lists. Flag new/removed children, title changes.
- Dependencies: compare blocked_by. Flag new/removed blocking edges.

```
### Convergence Assessment (Iteration <i>)

**Requirements**: [Stable | Minor changes | Significant changes] — <1-line summary>
**Research**: [Stable | Minor changes | Significant changes] — <1-line summary>
**Structure**: [Stable | Changed] — <summary>
**Dependencies**: [Stable | Changed] — <summary>

**Recommendation**: [Ready to execute — prep has converged] OR [Continue iterating — <reason>]
```

Recommend "Ready to execute" when ALL dimensions Stable/Minor w/ no new structural additions. Else "Continue iterating".

**4b.** Next action prompt

```
### Iteration <i>/<N> complete — Next Action?

1. **Continue** — Start iteration <i+1>
2. **Skip to execute** — Prep has converged, proceed to execute
3. **Redefine** — Re-run interactive define on specific todos (enter IDs)
4. **Stop** — Exit workflow now (completed steps are saved)
```

Option 2 → skip remaining iterations, jump to step 5 (Execute).
Option 3 → prompt for todo IDs, interactive define on each, resume from decompose.

**5.** Execute (only if `has_execute`)

Refresh todo via `mcp__proj__todo_get`. `has_children = len(children) > 0`.

NOT `--no-interactive` → prompt:

```
### Prep complete — Execute?

1. **Proceed** — Run execute
2. **Redefine** — Re-run interactive define on specific todos (enter IDs)
3. **Stop** — Exit (prep saved)
```

No children → exec parent only (5i).
Has children → exec all (parent + descendants) via 5ii.

**5i. Single execute:**

fast → display: "⚡ --fast mode. Auto-executing low-complexity. Tag-immune (security/breaking-change/migration) get full review."
 **Fast-mode safety guardrails**:
 - Minimal syntax check: verify modified files parseable (Python: `py_compile`, JS: basic syntax) even in fast mode.
 - Todos completed under --fast marked `fast_mode: true` via `todo_update`.
 - External sync (Todoist/Trello) deferred until workflow completes.
 - Security-tagged todos that got FULL REVIEW under --fast also get STANDARD verification before completion.

1. `mcp__proj__todo_check_executable` — manual-tagged → warn + stop.
2. `skill: "proj:execute", args: "<id>"`.

fast → after exec: display post-run summary w/ `git diff HEAD~N`.

**5ii. Execute-all (parent + descendants):**

Full list: `[todo_id] + all_descendants` (todo_tree, flattened depth-first).
`mcp__proj__proj_identify_batches` for dep order.

**Mode selection:** `mcp__proj__config_load` → `team_mode.enabled`. Determine:
- `--team` passed, OR (`config.team_mode.enabled` true AND `--no-team` NOT passed) AND 2+ non-manual descendants → **Team-based exec** (5ii-T).
- Else → **Task agent exec** (5ii-F).

**--- Team-based exec (5ii-T) ---**

fast → display: "⚡ --fast mode. Auto-executing low-complexity. Tag-immune get full review."

**Phase 1 — Plan (sequential, main):**

Trust 3 → skip Phase 1, go Phase 2 w/ ctx only.
`--no-interactive` → skip Phase 1, Phase 2 w/ exec instructions only.

Init `approved_plans = {}`, `executing_agents = {}`, `manual_skipped_ids = []`.

**Pipeline team setup** (if `pipeline_enabled` AND trust != 3): `TeamCreate(name="run-exec-pipeline-{project}-{timestamp}", ...)`. All pipeline agents use this `team_name`. Torn down in Phase 2 after collection.

**If `--batch-approve`:**

1. `EnterPlanMode` once.
2. Each todo in dep order (in plan mode):
 - `todo_check_executable` — manual → skip, add to `manual_skipped_ids`.
 - `proj_get_todo_context(include_parent=true)`.
 - `proj_search_knowledge(query=<title>, scope=all)` → include as "### Related Context" if snippets returned.
 - Smart gate scoring (same rules as default cycle) — AUTO-EXECUTE skip plan, create git tag; LIGHT REVIEW 1-line summary; FULL REVIEW full plan.
 - Create plan (FULL/LIGHT): read ctx, explore source. Cover files, changes, order, testing. Include Related Context. AUTO-EXECUTE: `git tag pre-auto-execute-{todo_id}`, skip plan.
 - Store in `approved_plans[todo_id]`.
3. `ExitPlanMode` once, presenting all plans combined.
4. Plan approval:
 - Trust 0-1: user reviews all plans. Can approve batch, reject individual (re-plan/skip rejected — don't abort whole batch), modify individual.
 - Trust 2 w/ `--batch-approve`: skip `ExitPlanMode` review (auto-approve). Display: `Batch auto-approved (trust 2): <N> plans`.
5. Store approved plans. Pipeline: spawn exec agents as approved (same rules as default step 7).

**Default per-todo cycle:**

Each todo in dep order:
1. `todo_check_executable` — manual → skip.
2. `proj_get_todo_context(include_parent=true)`.
3. `proj_search_knowledge(query=<title>, scope=all)` → "### Related Context" if snippets.

**Smart gate scoring** (skip if fast w/ auto-exec, or --force-plan):

Complexity score (0-14) from 7 dimensions:

| Dimension | 0 pts | 1 pt | 2 pts |
|-----------|-------|------|-------|
| File count | 1 | 2-4 | 5+ |
| Dir spread | 1 dir | 2-3 | 4+ |
| Requirements quality | detailed | basic | none/vague |
| Research quality | detailed | basic | none |
| Risk tags | none | general | security/breaking/migration |
| Children count | 0 (leaf) | 1-3 | 4+ |
| Blocked-by deps | 0 | 1 | 2+ |

**Eval order:**
1. Tag overrides (FIRST): `auto-execute` → AUTO-EXECUTE. `security`/`breaking-change`/`migration`/`needs-review` → FULL REVIEW.
2. Score: AUTO-EXECUTE (0-3), LIGHT REVIEW (4-7), FULL REVIEW (8-14).
3. Critical-path file guard (LAST, floor): touches `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json` → min LIGHT REVIEW.

**Gate routing:**
- AUTO-EXECUTE: `git tag pre-auto-execute-{todo_id}`, skip plan, exec w/ ctx only.
- LIGHT REVIEW: 1-line summary + `Proceed? [Y/n]` (default yes).
- FULL REVIEW: full `EnterPlanMode`/`ExitPlanMode`.

`--force-plan` → FULL REVIEW on all despite score.

4. `EnterPlanMode` (FULL REVIEW). Create plan: files, changes, order, testing, Related Context. LIGHT REVIEW: 1-line summary w/o EnterPlanMode. AUTO-EXECUTE: skip.
5. Plan approval (trust + gate):
 - Trust 0: `ExitPlanMode`, user approves before next plan.
 - Trust 1: `ExitPlanMode`, user approves, move to next. After all → bulk approval summary.
 - Trust 2: skip `ExitPlanMode`. Display: `Plan auto-approved (trust 2): <summary>`.
 - AUTO-EXECUTE: skip approval despite trust.
 - LIGHT REVIEW: 1-line + `Proceed? [Y/n]` despite trust (unless 2+).
6. Store in `approved_plans[todo_id]`.
7. IF `pipeline_enabled` AND trust != 3:
 `len(executing_agents) >= max_parallel` → wait for one to complete.
 Spawn background `general-purpose` Task w/ `team_name="run-exec-pipeline-{project}-{timestamp}"`: todo details, requirements.md, research.md, parent ctx, approved plan. Instruction: implement plan, do NOT `todo_complete`. Store in `executing_agents[todo_id]`.

After all plans stored (trust 0-1): bulk approval summary w/ all IDs + summaries.

**File-Overlap Detection** (after Phase 1, before Phase 2, skip if trust 3):
1. Extract "Files to modify/create" from each plan. Check overlaps **within each batch** (across-batch OK since sequential).
2. Build overlap matrix: pairwise within-batch file list intersection.
3. Quality-level behavior:
 - fast → auto-proceed.
 - careful/paranoid → auto-serialize conflicting.
 - balanced → prompt user.
4. Overlaps found (balanced):

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

5. Serialize → remove conflicting from parallel batch, add sequential batch at end.
6. Proceed → continue as-is.
7. Cancel → stop, "Execution cancelled. Plans are saved."
8. No overlaps → silent.

**Resume checkpoint** (`--resume`):
1. Find most recent `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. Found + not stale (<24h): read, display `Resuming from batch {batch_index}/{total_batches} — {len(completed_todos)} done`. Use stored `approved_plans`. Skip to `batch_index` in Phase 2.
3. Stale (>24h) or refs nonexistent todos: display stale notice, prompt (1) Restart (2) Use anyway.
4. Not found: `No checkpoint found — starting fresh`.

**Phase 1.25 — Pre-execute Preflight**

After plan approval + overlap detection, before worktree setup + exec spawn. Same semantics as **Phase C0.5**: 6 structural checks (plan has file list, paths valid, critical-path touches named, working tree clean, test runner detectable [WARNING], plan non-empty), per-todo. Skipped under trust 3, skipped under `--fast`. Adversarial agents (File Path Verifier, Spec-Plan Alignment, Impact Scanner) only under `careful`/`paranoid`. See Phase C0.5/C0.5b for full tables + rules.

**Phase 1.5 — Worktree setup** (if `worktree_enabled`):

**Prerequisite check**:
- `wt_list_repos` to verify plugin installed + ≥1 base repo registered.
- No repos registered:
 - Get repos from `proj_session_context`.
 - 0 repos → disable worktree, "No worktree repos registered and no project repos found. Falling back to main."
 - 1 repo (`<path>`) → prompt: "No worktree base registered. Add `<path>` as worktree base `<basename(path)>`? [Y/n]"
 - Yes → `wt_add_repo(label=basename(path), path=path, default_branch="main")`. Success → proceed. Failure → disable worktree, fallback.
 - No → disable worktree, fallback.
 - 2+ repos:
    ```
      1. <label>: <path>
      2. <label>: <path>
      (enter numbers comma-separated, or 0 to skip)
      ```
 Each selected: `wt_add_repo`. Report per repo. Any success → proceed. All fail/none selected → disable worktree, fallback.
 - `--no-interactive`: 1 repo → auto-register silently; 0/2+ repos → disable w/ warn.

Dirty main (`git status --porcelain`):
 (1) Stash (2) Commit (3) Abort worktree setup
 Stash: `git stash push -m "pre-worktree-{timestamp}"`.
 `--no-interactive` → auto-stash.

Each todo in batch:
1. `wt_create` w/ repo_label, branch `todo-{id}`. Fails → fallback to main for this todo.
2. `wt_lock`.
3. `sandbox_add_write_path` for worktree path.
4. Store `worktree_path` + `worktree_branch`.

Pipeline → setup per-todo after plan approval. Non-pipeline → setup all batch todos before Phase 2.

**Phase 2 — Execute (batches sequential, within-batch parallel w/ Team):**

IF `pipeline_enabled`:
 Wait for all `executing_agents` to complete. Report failures. `TeamDelete(team_name="run-exec-pipeline-{project}-{timestamp}")`.
 All agents failed → "All N agents failed. (1) Retry (2) Skip to next (3) Stop." Skip satisfaction loops.
ELSE:

1. `TeamCreate(name="run-exec-{project}-{timestamp}", ...)`
1a. **Task Mapping** (one-way — tasks mirror todos for coordination):
 Each todo across all batches:
 - `TaskCreate(title, description="Implement todo {id} — {title}", metadata={"proj_todo_id": "{todo.id}", "team_name": "{team_name}"})`
 - If `blocked_by` in same exec set → `addBlockedBy` w/ prev Task IDs.
 Agents discover tasks via `TaskList(metadata={"team_name": team_name})` (pull model).
 **One-way**: Task completion does NOT auto-complete proj todo. Satisfaction loop handles that.

2. Each batch in dep order (excl `manual_skipped_ids`):
 - Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
 - One Agent per todo w/ `team_name`. Each gets: approved plan (or ctx if trust 3) + requirements.md + research.md + parent ctx. `--full-context` → also CLAUDE.md + NOTES.md. Agents do NOT `todo_complete`. Plan gap → use ASK_USER protocol (see Agent Delegation Protocols appendix): send `ASK_USER: <issue>` via SendMessage to team-lead, wait for `ASK_USER_RESPONSE`. Do NOT improvise.
 - `worktree_enabled` + todo has `worktree_path` → include `worktree_path: <path>`, `worktree_branch: <branch>`. Instruction: "Execute all file ops in `<worktree_path>`. Prefix git commit msgs with `[todo-{id}]`."
 - Wait for batch. Report failures: `Agent for todo <id> failed: <error>`.
 - **Write checkpoint** after each batch:
     ```yaml
     team_name: run-exec-{project}-{timestamp}
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
3. All batches done → `TeamDelete(team_name)`
4. Agent failures → log to `tracking/{project}/.team-state/failed-teams.yaml`.

**--- Task agent exec (5ii-F, fallback) ---**

fast → display warning (same as 5ii-T).

**Phase 1 — Plan (sequential, main):**

Trust 3 → skip, Phase 2 w/ ctx only.
`--no-interactive` → skip, Phase 2 w/ exec instructions.

Init `approved_plans = {}`, `executing_agents = {}`, `manual_skipped_ids = []`.

**Pipeline team setup** (if `pipeline_enabled` AND trust != 3): `TeamCreate(name="run-exec-pipeline-fallback-{project}-{timestamp}", ...)`. Torn down in Phase 2.

Each todo in dep order:
1-7: Same as 5ii-T Phase 1 (check_executable, get_todo_context, search_knowledge, smart gate scoring, plan creation, approval, pipeline spawn) — only diff: pipeline team name uses `-fallback-`.

**Phase 1.25 — Pre-execute Preflight**

Same as 5ii-T Phase 1.25. See Phase C0.5/C0.5b.

**Phase 1.5 — Worktree setup** (if `worktree_enabled`):

Same as 5ii-T Phase 1.5 (prereq check, dirty-tree handling, per-todo wt_create/lock/sandbox).

**Phase 2 — Execute (parallel Task agents):**

IF `pipeline_enabled`:
 Wait for agents. Report failures. `TeamDelete(team_name="run-exec-pipeline-fallback-{project}-{timestamp}")`.
 All failed → batch failure short-circuit.
ELSE:

`TeamCreate(name="run-exec-fallback-{project}-{timestamp}", ...)`.

Each batch in dep order (excl `manual_skipped_ids`):
1. Display batch.
2. One `general-purpose` Task per todo w/ `team_name`. Each gets: todo details, requirements.md, research.md, parent ctx, approved plan (or ctx/exec instructions). No `todo_complete`.
 `worktree_enabled` → same worktree instruction as 5ii-T.
3. Wait. Report failures.

All batches → `TeamDelete`.

**--- Common post-execute (both modes) ---**

Dirty main → warn "Main has uncommitted changes after worktree exec. This may cause merge conflicts."

**Phase 2.5 — Merge worktree branches** (if `worktree_enabled`):

Init `files_merged_this_batch = set()`, `reexecution_queue = []`.

Each completed todo in batch order:
 `git tag pre-merge-{todo_id}`.

 Each todo's worktree:
 `wt_auto_commit(worktree_path=<path>, message="[todo-{id}] Auto-commit agent work")`
 Committed → display "Auto-committed {N} files for todo {id}". Error → log, proceed.

 `git merge --no-ff todo-{id}` → **3-tier resolution cascade**:

 ### Tier 1 — Clean merge
 Exit 0. Add modified files to `files_merged_this_batch`, `notes_append("Merge tier 1 (clean): todo-{id} — {N} files")`, `wt_remove`, `git branch -d todo-{id}`.

 ### Tier 2 — Expanded auto-resolve
 Eligibility: ≤5 conflicting files, all hunks <50 lines, no critical-path files.
 Decision rule: file NOT in `files_merged_this_batch` → theirs; file IN → ours.
 Stage, commit, add to set. `wt_remove`, `git branch -d todo-{id}`, `notes_append("Merge tier 2 (auto-resolve): ...")`.

 ### Tier 3 — Ask user
 Tier 2 ineligible or raised error.
 `--no-interactive` → abort: `git merge --abort`, `git reset --hard pre-merge-{todo_id}`, enqueue, `notes_append("Merge tier 3 (aborted, non-interactive): ...")`.
 Interactive → show conflict summary, prompt: (1) Manual resolve (2) Abort. `notes_append("Merge tier 3 (user): ...")`.

 > `-X theirs` + `git rerere` strategies intentionally NOT used. See Phase 2.5 note for rationale.

 **Post-merge test** (after each merge):
 Run test suite (`uv run pytest --tb=short -q` / `npm test`).
 Fail: 1 merge so far → revert, re-exec on main. Multiple merges → `git bisect` to find breaker. Offer: (1) Revert (2) Fix manually (3) Continue anyway.

**Serialized re-exec queue** (after all merges):
 Non-empty → "N todos need re-exec on main (merge conflicts aborted)."
 Each queued: re-exec sequentially on main (no worktree, `--no-pipeline --balanced`).

**Phase 2.6 — Post-merge verification** (after all cascades + re-exec drain, before Verification):

1. **Full test run** — w/o `-q`. Fail → surface output, `notes_append("Post-merge verification FAILED: {N} tests")`, offer (1) Spawn fix agents (2) Proceed (3) Abort batch.
2. **Diff-vs-plan review agent** — read-only `general-purpose` Task, 60s timeout. Compare `git diff {merge_base}..HEAD` vs each todo's plan. Per-todo mismatches as WARNING. Feeds **Drift** column into verification summary.
3. **Resource safeguards** (pre-batch, gate before Phase 1.5):
 - Disk: `df --output=avail .` — need ≥300 MB × max_parallel. Shortfall → cap `max_parallel`.
 - FDs: `ulimit -n` — need ≥256 × max_parallel. Shortfall → cap.
 - Context budget: estimated per-agent ctx × max_parallel ≤ trust-level budget. Shortfall → cap.
 Each cap → `notes_append("Pre-batch cap: max_parallel {old}→{new} due to {reason}")`.

**Verification** (skip if `--no-verify`):

Each completed todo (excl failures + `manual_skipped_ids`), run verification from execute step 4a:
- A. Automated checks (test runner, tests/lint)
- B. Spec validation (acceptance criteria vs git diff)
- C. Diff review (plan files vs actual changes)

Verify ALL first, then combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| <id> | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| <id> | FAIL (2 failed) | 2/3 met | 1 extra file | FAIL |
```

Persist each to `todos/<id>/verification-report.md` (w/ timestamp, overwrite prev).

Any failures → prompt: `N passed, M failed. Fix? (1) Fix (2) Proceed (3) Skip`
- Fix: N >= 2 → `TeamCreate(name="run-verify-fix-{project}-{timestamp}", ...)`, spawn per-todo, `TeamDelete` after. N == 1 → single Agent. Each gets: verification report, todo ctx, plan, fix instructions. After → re-verify (max 2 retries). Re-prompt if still failing.
- Proceed: continue despite failures.
- Skip: skip remaining verification.

All pass → display report, proceed w/o prompt.

**Satisfaction check** (sequential, main):

Mode from `quality_level.satisfaction`:
- per-batch: batch summary, "Satisfied?" once per batch. Yes → `todo_batch_complete` w/ all ids.
- per-todo: individual loop; collect satisfied ids, finalize w/ one `todo_batch_complete` at batch end.
- skip: auto-complete all via single `todo_batch_complete`.
- per-todo + re-verify: individual + re-verify after fixes, finalize w/ one `todo_batch_complete`.

**Batch completion rule:** ≥2 todos → ALWAYS `mcp__proj__todo_batch_complete(todo_ids=[...])`. Never loop `todo_complete`. Only `todo_complete` for single-todo.

Per-todo/re-verify modes, collect `satisfied_ids = []`:
 a. Ask: "Satisfied with todo <id>, or anything else needed?"
 1. Satisfied → append to `satisfied_ids` (do NOT `todo_complete` yet).
 2. Not satisfied → ask what's missing. `proj_decision_log(action="add", decision=<feedback>, context="run:satisfaction:<todo_id>", tags="correction,quality", todo_id=<todo_id>)`. Create new todo, run `/proj:run <new_id> --iter 5`, re-ask.
 3. Redefine → interactive define, re-run `/proj:run <id> --from decompose`.

 After loop: `len(satisfied_ids) >= 2` → `todo_batch_complete(todo_ids=satisfied_ids)`. `== 1` → `todo_complete`.

 Recursive run → enforce `--no-pipeline --balanced --no-worktree`. Max recursion: 2. Pass `--_recursion_depth N` internally. Depth >= 2 → refuse, "Maximum satisfaction recursion depth reached. Fix manually."

Auto-complete parent: `manual_skipped_ids` empty → satisfaction loop (3-option) for parent, then `todo_complete` on parent (single, not batch). Else warn.

fast → after exec: post-run summary w/ `git diff HEAD~N`.

Clear `executing_agents = {}` before next batch.

**Phase 5 — Worktree cleanup** (if `worktree_enabled`, always runs even on failure):

Each worktree created:
1. `wt_unlock`.
2. `wt_remove`.
3. `sandbox_reconcile` to remove sandbox entries.
4. `wt_prune` for stale admin entries.
Display: "Cleaned up N worktrees."

**6.** Complete

```
Full workflow complete for todo <id>: <title>
Steps completed: <step1>, <step2>, ...
```

`mcp__proj__notes_append` w/ brief summary.

**7.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Run: {todo-id}")`.

Suggested next: `1. /proj:status`


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
1. **Tag signals (first, highest wins)**: `security`/`breaking-change`/`migration` → `paranoid`; `needs-review` → `careful`; `auto-execute` → `fast`
2. **Complexity score** (dims 3-7 only — file-count + dir-spread default 0, no plans yet): 8-14 → `careful`; 4-7 → `balanced`; 0-3 → `fast`. `paranoid` only via tag signals.
3. **Title complexity floor** (replaces requirements floor): If requirements.md exists, skip. Else parse title:
 - Low-complexity (-1 each): short (<60 chars), targeted-fix (`fix\s+(line\s+\d+|off.by.one|typo|import|indent)`), single-rename (`rename\s+\S+\s+to\s+`), version-bump (`bump\s+version|update\s+version`), add-guard (`add\s+(try[/]except|try[/]finally|null check|type hint|assert)`), remove-unused (`remove\s+unused|delete\s+dead`), single-file ref (1 file-like token w/ `.` ext or `/` sep, excl URLs w/ `://`)
 - High-complexity (+1 each): long (>120 chars), multi-file (`\d+\s+files?` or 2+ file tokens), rewrite (`\b(rewrite|refactor|redesign|overhaul|rearchitect)\b`), cross-cutting (`\b(all\s+plugins?|across|everywhere|every\s+\w+|global)\b`), feature (`\b(new\s+feature|add\s+support\s+for|implement\s+\w+)\b`), scope (`\b(migrate|migration)\b`, only if not caught by tag #1)
 - Net: sum(high) - sum(low). <= -2 → no floor; -1 to +1 → `balanced` min; >= +2 → `careful` min
4. **Notes risk keyword floor**: any of `auth`, `secret`, `migration`, `breaking` in notes → `careful` min
5. **Tag-immune upgrade**: suggested fast/balanced + `security`/`breaking-change`/`migration` tag → `careful`
6. **Precedence**: tags override score; highest tag level wins (paranoid > careful > balanced > fast)

**Reason fmt**: `"tag:<tag>"` for tag-driven; `"score:<N>/14 (pre-plan estimate)"` for score; append `"+ floor: title-complexity:<net>"` or `"+ floor: keyword:<word>"` when applied.

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
2. Each ID: not in batch → warn inline, skip. Valid → `AskUserQuestion` w/ 4 levels + "Keep suggested" — one call per ID.
3. Re-display table w/ resolved levels.
4. Override batch after tweaks → confirm "This will discard N individual tweaks. Confirm?"

**If `auto_suggest_mode` is false** (≥1 annotation):
Skip auto-suggest. `per_todo_quality` populated from parse. Unspecified → fallback via `effective_quality()`.

**Derive batch-level exec params** (after `per_todo_quality` confirmed):
- `batch_max_parallel_execute`: most conservative quality across `per_todo_quality` (paranoid→1, careful→10, balanced/fast→30). Replaces table `max_parallel` for **Phase C exec only**. Phases B + C0 use orig batch-level `max_parallel`.
- `batch_worktree_enabled`: any `paranoid` → false (whole batch). Else: use existing `worktree_enabled` derivation.
- Notice if conservative rule triggered: "⚠ max_parallel set to 1 because todo N resolves to paranoid"

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
 Structural checks (10 if v2, else 5 — same table/rules as single-ID, incl grandfather, fix-loop cap, `--no-interactive` demotion).
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

Only when `effective_quality(todo_id)` in `[careful, paranoid]`. NEVER `balanced`/`fast`.

**Batch sampling**: > 5 todos → only **5 highest-complexity** (7-dim score). Override: `--force-preflight-all`.

Spawn via `TeamCreate(name="preflight-adversarial-define-batch-{timestamp}", ...)`. One Agent per role per todo (never combine roles). After findings aggregated → `TeamDelete`.

Each sampled todo: 3 agents (Ambiguity, Completeness, Research Validation) in parallel. Same tools, timeout, JSON schema, severity as single-ID A.5b. See appendix for prompts.

After return: aggregate into combined table. Same BLOCKING prompt flow. Timeouts/malformed JSON → WARNING. `TeamDelete`.

**Phase B — Remaining steps (parallel agents):**

**Mode selection:** `config_load()` → `team_mode.enabled`.
- `--team` OR (config enabled AND `--no-team` NOT passed) AND 2+ non-manual → **Team mode**.
- Else → **Task agent mode**.

**Team mode:**
1. `TeamCreate(name="run-decompose-{project}-{timestamp}", ...)`
2. Each batch in dep order: one Agent per todo w/ `team_name`. Each runs `agent_steps` autonomously. `--full-context` → include CLAUDE.md + NOTES.md. Plan gap → use ASK_USER protocol (see Agent Delegation Protocols appendix). Wait per batch. Report failures.
3. All done → `TeamDelete`.
4. Failures → log to `failed-teams.yaml`.

**Task agent mode (fallback):**
`TeamCreate(name="run-decompose-fallback-{project}-{timestamp}", ...)`. Each batch: one `general-purpose` Task per todo w/ `team_name`. Wait per batch. Report failures. All done → `TeamDelete`.

After Phase B: refresh descendants via `mcp__proj__todo_tree`.

**Phase B.75 — Refine (if `effective_quality(todo_id)` in `[careful, paranoid]` AND `refine` in steps AND NOT `--no-interactive`):**

fast → skip. careful/paranoid → auto-enable despite --refine.

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

Then between-iteration prompt (same 4 options as single-ID).

**Phase C — Execute (after iteration loop):**

`has_execute` false → skip to summary.

NOT `--no-interactive`:
```
### Prep complete — Execute?

1. **Execute all** — Plan and execute all todos
2. **Stop** — Exit (prep saved)
```

All fast → display: "⚡ --fast mode. Auto-executing low-complexity. Tag-immune get full review."

**Phase C0 — Speculative planning** (if effective_quality != careful/paranoid AND trust != 0 AND trust != 3):

`TeamCreate(name="run-spec-{project}-{timestamp}", ...)`. One read-only Task per todo w/ `team_name`. Each:
- Gets: todo ctx, requirements.md, research.md, parent ctx
- Read-only tools: `Read`, `Glob`, `Grep`, `proj_get_todo_context`, `proj_explore_codebase`, `content_get_requirements`, `content_get_research`
- Produces: `{prose: "<plan text>", actions: [{type: "create"|"modify"|"delete"|"test", file: "<path>"}]}`

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

Same 7-dimension complexity score (0-14), same eval order (tags → score → critical-path guard), same gate routing (AUTO-EXECUTE/LIGHT/FULL) as 5ii-T.

`--force-plan` → FULL REVIEW all.

4. Plan creation (per gate level). Include Related Context.
5. Approval (per trust + gate).
6. Store.
7. Pipeline spawn (if enabled, trust != 3): respect `batch_max_parallel_execute` from Phase A.0. Spawn w/ `team_name="run-c1-pipeline-{project}-{timestamp}"`.

**Pattern detection** (skip if effective_quality in [careful, paranoid]):

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
1-2: Same as 5ii-T (extract file lists, build within-batch overlap matrix).
3. Quality behavior (pairwise — `max(effective_quality(A), effective_quality(B))`):
 - fast → auto-proceed.
 - careful/paranoid → auto-serialize.
 - balanced → prompt.
4. Overlaps found (balanced):

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

Each todo (excl `manual_skipped_ids` + AUTO-EXECUTE w/o plan), 6 structural checks:

| # | Check | Data read | Pass condition | Severity |
|---|-------|-----------|---------------|----------|
| 1 | Plan has file list | `approved_plans[todo_id]` | "Files to modify/create" section w/ >= 1 entry | BLOCKING |
| 2 | Paths valid | each path vs filesystem (worktree/main) | existing file OR creatable (parent dir exists, inside repo root) | BLOCKING |
| 3 | Critical-path not silent | plan text | each critical-path file (`*.env*`, `*secret*`, `*credential*`, `*auth*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`, `proj.yaml`, `*.config.*`) explicitly named | BLOCKING |
| 4 | Working tree clean | `git status --porcelain` on relevant tree | empty OR prev confirmed | BLOCKING |
| 5 | Test runner detectable | repo root | `pyproject.toml` has `[tool.pytest]`, OR `package.json` has `"test"` script, OR documented test cmd | WARNING |
| 6 | Plan non-empty | `approved_plans[todo_id]` | >= 20 lines or >= 100 words | BLOCKING |

**Removed** (by design): "Plan acknowledges each criterion" → relocated to Spec-Plan Alignment Agent (C0.5b). "No touched file gitignored" → too many false positives.

**On failure** (same UX as A.5):
- NOT `--no-interactive` AND attempts < 3 → Fix / Continue / Stop. Fix re-runs C1 plan (increment counter).
- `--no-interactive` → demote BLOCKING→WARNING, log, decision log, continue.
- 4th attempt → auto-demote, `(1) Continue anyway (2) Stop`.

All pass → silent, Phase C0.5b.

**Phase C0.5b — Adversarial Review (Pre-execute)**

Only `effective_quality(todo_id)` in `[careful, paranoid]`. Never balanced/fast. Skip under trust 3.

**Batch sampling**: > 5 → 5 highest-complexity (same ranking as A.5b). Override: `--force-preflight-all`.

`TeamCreate(name="preflight-adversarial-execute-{timestamp}", ...)`. One Agent per role per todo. After aggregation → `TeamDelete`.

Each sampled todo, 3 read-only Agents in parallel:

| Agent | Reads | Checks |
|-------|-------|--------|
| File Path Verifier | plan + filesystem (worktree/main) | double-checks paths; catches normalization bugs, case-sensitivity missed by structural |
| Spec-Plan Alignment | requirements.md "Acceptance Criteria" + plan | each criterion addressed by plan; flags unacknowledged criteria (relocated check) |
| Impact Scanner | plan file list + repo grep | greps refs for each touched file; flags top-10-most-referenced as WARNING only |

Each spawned w/:
- Tools (read-only): `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__proj_explore_codebase`
- Timeout: 90s
- Output schema: same strict JSON as A.5b (see appendix)

See **Preflight Agents Reference** appendix for prompts.

**Findings aggregation**: merge across 3 agents, combined table (same fmt as A.5b). Same severity semantics. Timeouts/malformed JSON → WARNING.

`worktree_enabled` → File Path Verifier checks worktree tree for todo's branch.

**Phase C1.5 — Worktree setup** (if `worktree_enabled`):

Same prereq check + dirty-tree handling + per-todo setup as 5ii-T Phase 1.5.

Pipeline → per-todo after plan approval. Non-pipeline → all batch todos before C2.

**Phase C2 — Execute:**

**Mode selection:** `config_load()` → `team_mode.enabled`. Same rules as Phase B mode selection.

**Resume checkpoint** (`--resume`): same 4-step logic as 5ii-T (find checkpoint, fresh/stale check, skip to batch_index or restart).

**Team mode:**

IF `pipeline_enabled`:
 Wait for agents. Report. `TeamDelete(team_name="run-c1-pipeline-{project}-{timestamp}")`.
 All failed → batch failure short-circuit.
ELSE:

1. `TeamCreate(name="run-exec-{project}-{timestamp}", ...)`
1a. Task Mapping (one-way): same as 5ii-T Phase 2 (TaskCreate per todo, addBlockedBy, pull model, one-way only).

2. Each batch in dep order (excl `manual_skipped_ids`):
 - Display batch. One Agent per todo w/ `team_name`. Gets: plan (or ctx/exec instructions) + requirements.md + research.md + parent ctx. `--full-context` → CLAUDE.md + NOTES.md.
 - Worktree → same instruction.
 - Agents exec plan, no `todo_complete`. Plan gap → use ASK_USER protocol (see Agent Delegation Protocols appendix).
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

Same 3-tier cascade as Phase 2.5:
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
- Proceed/Skip: same as 5ii-T.

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

 Recursive → `--no-pipeline --balanced --no-worktree`. Max depth 2. Depth >= 2 → refuse.

All fast → post-run summary w/ `git diff HEAD~N`.

Clear `executing_agents = {}`.

**Phase C5 — Worktree cleanup** (if `worktree_enabled`, always runs):

Each worktree: `wt_unlock`, `wt_remove`, `sandbox_reconcile`, `wt_prune`.
Display: "Cleaned up N worktrees."

**d.** Summary

Per-batch breakdown + overall count. `mcp__proj__notes_append`.

**e.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Run: {todo-id}")`.

## Prerequisites

- Active project loaded.
- Valid todo ID, range, or comma list.

## Error Handling

- No todo ID → `Todo ID required.` + usage.
- Todo not found → err from `todo_get`.
- Invalid step name → err.
- Manual-tagged → skip w/ warn.
- Quality gate failure (define) → low-confidence display, Continue/Re-define/Stop.
- Verification failures (execute) → combined report, Fix/Proceed/Skip.
- Agent failures → report + log to `failed-teams.yaml`.
- Stale checkpoint → ask restart or use stale.

## Output

- Single-ID: workflow progress per step, convergence assessments, verification report, satisfaction loop, completion.
- Batch: per-todo define (interactive), parallel decompose, parallel exec w/ batched verification, satisfaction per completed todo, overall summary.

Suggested next: `1. /proj:status`


## Preflight Agents Reference

Full prompt templates in `plugins/proj/skills/run/agents/`. Load at runtime via `Read` when spawning.

All 6 preflight agents ref'd by Phase A.5b (define) + Phase C0.5b (pre-execute). Spawned as `general-purpose` Agents in TeamCreate group, read-only tools, 90s timeouts, strict JSON schema. Timeouts/malformed JSON → WARNING (never BLOCKING).

### Shared output schema

See: plugins/proj/skills/run/agents/shared_schema.md

### Phase A.5b — Define-phase agents

#### 1. Ambiguity Agent
Tools: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__content_get_research`
See: plugins/proj/skills/run/agents/ambiguity_agent.md

#### 2. Completeness Agent
Tools: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__content_get_research`
See: plugins/proj/skills/run/agents/completeness_agent.md

#### 3. Research Validation Agent
Tools: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_research`, `mcp__proj__proj_explore_codebase`
See: plugins/proj/skills/run/agents/research_validation_agent.md

### Phase C0.5b — Pre-execute agents

#### 4. File Path Verifier
Tools: `Read`, `Glob`, `Grep`
See: plugins/proj/skills/run/agents/file_path_verifier.md

#### 5. Spec-Plan Alignment Agent
Tools: `Read`, `mcp__proj__content_get_requirements`
See: plugins/proj/skills/run/agents/spec_plan_alignment_agent.md

#### 6. Impact Scanner
Tools: `Read`, `Glob`, `Grep`
See: plugins/proj/skills/run/agents/impact_scanner.md

### Spawning pattern

All agents via `TeamCreate` (never bare parallel Task calls). Example for A.5b:

```
# Pseudocode — TeamCreate first, then spawn Agents with team_name
TeamCreate(name="preflight-adversarial-define-<id>",
           description="Adversarial review agents for todo <id>")
Agent(subagent_type="general-purpose", description="Ambiguity review — todo <id>",
      team_name="preflight-adversarial-define-<id>", prompt=<ambiguity_prompt>)
Agent(subagent_type="general-purpose", description="Completeness review — todo <id>",
      team_name="preflight-adversarial-define-<id>", prompt=<completeness_prompt>)
Agent(subagent_type="general-purpose", description="Research validation — todo <id>",
      team_name="preflight-adversarial-define-<id>", prompt=<research_validation_prompt>)
# ... await all three ...
TeamDelete(name="preflight-adversarial-define-<id>")
```

Await all three, parse JSON, aggregate into per-todo review table. Apply severity (BLOCKING → prompt, WARNING → show, INFO → show). Repeat per sampled todo.


## Agent Delegation Protocols

Spawned agents lack user-facing tools. These protocols bridge gap via SendMessage to lead.

### Tool Availability (spawned agents)

| Tool | Available? |
|------|-----------|
| AskUserQuestion | NO |
| EnterPlanMode / ExitPlanMode | NO |
| SendMessage | YES |
| Read / Edit / Write / Bash / Glob / Grep | YES |
| Task tools (TaskCreate, TaskUpdate, etc.) | YES |
| MCP tools (proj, worktree, sandbox, router, etc.) | YES |

### ASK_USER Protocol

Agent needs user input → SendMessage to lead:

```
ASK_USER: <question or decision needed>
Context: <why this matters>
Options: <if enumerable, list them>
```

Lead receives → calls `AskUserQuestion` w/ options → relays answer:

```
ASK_USER_RESPONSE: <user's answer>
```

Use for: plan gaps, ambiguous requirements, architectural decisions, scope clarifications.

### PLAN_ESCALATION Protocol

Agent researched + drafted impl plan → SendMessage to lead:

```
PLAN_ESCALATION:
<full plan content — Context, Files, Changes, Verification>
```

Lead receives → `EnterPlanMode` → writes plan file → `ExitPlanMode` → relays:

```
PLAN_APPROVED
```
or
```
PLAN_REJECTED: <user feedback>
```

Agent continues impl (approved) or revises plan + re-escalates (rejected).

Use for: execution agents needing plan approval, speculative planners needing user sign-off.

### Agent Prompt Inclusion

All agent spawn instructions MUST include:

```
If you encounter work outside approved plan or need user input:
send "ASK_USER: <description>" via SendMessage to team-lead.
Do NOT improvise or auto-fix. Wait for ASK_USER_RESPONSE.

If you need plan approval:
send "PLAN_ESCALATION:\n<plan>" via SendMessage to team-lead.
Wait for PLAN_APPROVED or PLAN_REJECTED before proceeding.
```

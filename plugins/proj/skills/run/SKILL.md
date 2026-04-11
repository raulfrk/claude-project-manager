---
name: run
description: Run the full workflow (define → decompose → execute) on a todo interactively, prompting between each step. Use when asked "run 1", "full workflow on 1", or "proj:run 1".
allowed-tools: mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__proj_search_knowledge, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__tracking_git_flush, Read, Task, TaskCreate, TaskList, EnterPlanMode, ExitPlanMode, TeamCreate, TeamDelete, SendMessage, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__worktree__wt_add_repo, mcp__proj__proj_session_context, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, mcp__proj__proj_decision_log
argument-hint: "<todo-id> [--steps define,execute] [--from <step>] [--iter N] [--no-interactive] [--no-verify] [--team] [--no-team] [--full-context] [--trust 0-3] [--resume] [--no-pipeline] [--refine] [--fast|--balanced|--careful|--paranoid] [--force-plan] [--batch-approve] [--worktree] [--no-worktree]"
---

Run workflow for: $ARGUMENTS

**1.** Parse and validate

Extract from $ARGUMENTS:
- **Input mode**: single ID (`1`), range (`2-5`), or comma list (`1,3,5`)
- **`--steps <csv>`**: explicit step list (reordered to workflow order)
- **`--from <step>`**: slice from that step onward (`--steps` takes precedence)
- **`--iter N`**: prep iteration count (default 5, positive integer)
- **`--no-interactive`**: run autonomously with no user prompts
- **`--no-verify`**: skip verification step in execute (passed through to execute skill)
- **`--team`**: force team mode ON (overrides config)
- **`--no-team`**: force team mode OFF (overrides config)
- **`--full-context`**: when using team mode, include CLAUDE.md and NOTES.md in each agent's context
- **`--trust N`** (N = 0-3): override trust level for execution phases. If not specified, use `team_mode.trust_level` from config (default 1 if unset). Trust levels:
  - **Trust 0 (supervised)**: per-todo approval — each plan presented individually, user approves one at a time.
  - **Trust 1 (guided)**: bulk approval + parallel execution — all plans presented sequentially, user approves each, then bulk confirmation before execution. Default.
  - **Trust 2 (autonomous)**: auto-approve plans — skip `ExitPlanMode` user review. Plans created and automatically approved.
  - **Trust 3 (full-auto)**: no plan phase — skip planning entirely. Agents execute with context only (requirements + research + parent context).
- **`--resume`**: resume execution from the most recent checkpoint. See **Resume checkpoint** sections below.
- **`--no-pipeline`**: disable plan-while-executing pipeline (default: pipeline enabled)
- **`--refine`**: enable requirement refinement with review agents (default: off for `--balanced`, auto-enabled for `--careful`/`--paranoid`)
- **`--fast`**: minimize review gates, auto-execute low-complexity todos, skip verification. Tag immunity: `security`/`breaking-change`/`migration` still get FULL REVIEW.
- **`--balanced`**: Smart-gate scoring determines review level.
- **`--careful`**: default. Full review on all plans, auto-enable refine, enhanced verification.
- **`--paranoid`**: sequential execution (max_parallel=1), cross-review agents, full verification with independent review agent.
- Quality levels are mutually exclusive (last wins, default: `--careful`).
- **`--force-plan`**: force FULL REVIEW on all todos regardless of complexity score.
- **`--batch-approve`**: auto-approve all speculative plans without review (subject to trust level).
- **`--worktree`**: (default) enable worktree isolation for parallel execution. No-op since worktree is on by default; kept for explicitness.
- **`--no-worktree`**: opt out of worktree isolation — run all agents on the current branch. Use this when the batch is small, fully sequential, or when worktree setup costs outweigh isolation benefits.

Derive: `worktree_enabled` — **default: on**. Evaluated as:
  1. If `--no-worktree` was explicitly passed → off.
  2. Else if `quality_level == paranoid` → off (max_parallel=1 makes worktree isolation unnecessary).
  3. Else → on (regardless of `config.worktree_isolation`; the config flag is retained only for legacy callers and can force-off via `--no-worktree`).

Derive: `quality_level` from flags (fast/balanced/careful/paranoid). If no quality flag is passed, call `mcp__proj__config_load` and read `config.quality_level`, defaulting to `--careful` if not set or unrecognized.

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

**Recommended cap**: 10 for CPU-bound or API-rate-limited workloads (e.g., heavy test suites, rate-limited LLM calls, DB migrations). The raw `--fast`/`--balanced` ceiling of 30 is tuned for I/O-bound work with isolated worktrees; override via `--max-parallel` or `config.team_mode.max_agents` when an individual agent will saturate a shared resource.

Derive: `pipeline_enabled = not no_pipeline_flag`

**Flag compatibility check** (validate before proceeding):
- `--fast --force-plan` → ERROR: "Cannot combine --fast with --force-plan."
- `--fast --refine` → fast wins, refine skipped (warn).
- `--careful --batch-approve` → careful wins, batch approve disabled (warn).
- `--paranoid --batch-approve` → paranoid wins, batch approve disabled (warn).
- `--force-plan --batch-approve` → ERROR: "Cannot combine --force-plan with --batch-approve."
- `--no-verify --paranoid` → ERROR: "Cannot combine --no-verify with --paranoid."
- `--no-verify --careful` → WARNING: "--no-verify overrides --careful's enhanced verification." Verification is skipped.
- `--fast --steps refine` → ERROR: "Cannot use --fast with --steps refine (fast skips refine)."
- `--batch-approve --no-pipeline` → Allowed (speculative planning is independent of pipeline).
- `--paranoid --no-pipeline` → Redundant warning: "--paranoid already enforces max_parallel=1."
- `--careful --no-pipeline` → Allowed (no conflict).
- `--fast --no-pipeline` → Redundant warning: "--fast with auto-execute makes pipeline moot."
- `--force-plan --careful` → Redundant warning: "--careful already forces full review."
- `--force-plan --paranoid` → Redundant warning: "--paranoid already forces full review."
- `--no-verify --balanced` → --no-verify wins, verification skipped.
- `--no-verify --fast` → Redundant: --fast already skips verification.
- `--refine --from execute` → Refine skipped (--from execute skips refine per step-order slicing).
- `--force-plan --trust 3` → ERROR: "Cannot combine --force-plan with --trust 3 (trust 3 skips planning)."
- `--paranoid --worktree` → paranoid wins, worktree disabled (warn: "max_parallel=1 makes worktree isolation unnecessary").
- `--worktree --no-interactive` → Allowed. Auto-resolve only for merge conflicts.

If no todo ID, stop with: "Todo ID required. Usage: `/proj:run <id> [--steps define,execute] [--from <step>]`"

Default step order: `[define, preflight, decompose, refine, execute]`.
Apply `--steps` or `--from` to filter/slice. Error if any step name is invalid.

For **single ID**: call `mcp__proj__todo_get` to confirm it exists. Continue to step 2.
For **range or comma list**: parse into a deduplicated list. Skip to **"Batch mode"** below.

---

## Single-ID mode

**2.** Display

```
Running workflow on todo **<id>** — <title>
Steps: <step1> → <step2> → ... (x<N> iterations)
```

Split into: `prep_steps` = all except `execute`, `has_execute` = whether `execute` is in steps.

**3.** Iteration loop (repeat up to N times)

If N > 1, announce: `Iteration <i>/<N>`

Build descendant list: call `mcp__proj__todo_tree`, flatten depth-first.

**For each prep step:**

**If `define`** — sequential, interactive:
- For each todo in descendant list (in dependency order via `mcp__proj__proj_identify_batches`):
  - Announce: `Define: <id> — <title>`
  - Call the Skill tool: `skill: "proj:define", args: "<id>"` (if current iteration > 1, append `--skip-bg-prep`).

**Quality gate check** (after define phase):
For each todo defined non-interactively (agent-driven):
- Read the self-assessment from define output
- If any section has confidence ≤ 2 (speculative or inferred), add to flagged_todos

If flagged_todos is non-empty, display:

```
### Low-confidence definitions detected

| Todo | Low-confidence sections |
|------|------------------------|
| <id> | <section> (<score>/5) |

1. **Continue anyway** — proceed to decompose
2. **Re-define** — run interactive define on flagged todos
3. **Stop** — exit workflow
```

If Re-define: run interactive define on each flagged todo, then resume from decompose.

**If `preflight`** — inline, main conversation:

IF quality_level == fast: skip preflight entirely, proceed to next step.

**Preflight versioning and grandfather rule**: each todo carries a `preflight_version` meta field. When unset (existing todos created before this feature), preflight runs in **legacy mode** with only the original 5 checks (checks 1-5 below). Todos with `preflight_version: 2` run the expanded 10-check v2 suite. New todos default to v2. Users may upgrade a todo manually with `todo update <id> preflight_version=2`. Bulk migration is out of scope (tracked separately).

**Fix-loop cap**: max 3 preflight re-runs per todo per `/proj:run` invocation. On the 4th attempt, auto-demote remaining BLOCKING findings to WARNING and display: "3 fix attempts exhausted — (1) Continue anyway (2) Stop".

**`--no-interactive` demotion**: under `--no-interactive`, BLOCKING findings are auto-demoted to WARNING, logged via `notes_append` with the tag `preflight:auto-demoted`, and a decision log entry is recorded per demotion. The run auto-continues.

For each todo in descendant list:
1. Read requirements.md via `content_get_requirements`. If not found: hard fail with "No requirements found. Run define first." (counts as all checks failing).
2. Read research.md via `content_get_research`. If not found: mark research-dependent checks as FAIL, continue other checks.
3. Run structural checks. Legacy mode runs checks 1-5; v2 mode runs all 10:

   | # | Check | Data read | Pass condition | Version |
   |---|-------|-----------|---------------|---------|
   | 1 | Testable acceptance criteria | requirements.md, "Acceptance Criteria" section | section exists with >= 1 item | v1+v2 |
   | 2 | Out-of-scope section | requirements.md, "Out of Scope" section | section exists with >= 1 bullet | v1+v2 |
   | 3 | Research approach options | research.md, "Approach Options" or top-level headers | >= 2 approach options | v1+v2 |
   | 4 | Testing strategy coverage | requirements.md, "Testing Strategy" section | mentions >= 2 of: unit, integration, e2e, manual | v1+v2 |
   | 5 | Edge cases documented | requirements.md, "Edge Cases" section | >= 2 bullets or list items | v1+v2 |
   | 6 | Vague language (expanded) | requirements.md, "Goal" and "Acceptance Criteria" sections ONLY | no tokens from the expanded vague-phrase list (see below) | v2 only |
   | 7 | Acceptance criterion verifiability | requirements.md, "Acceptance Criteria" section | each criterion contains >= 1 of: file path, function/class name, CLI command, test name, numeric threshold, or explicit observable outcome | v2 only |
   | 8 | Research file-path anchor | research.md, "Recommended Approach" or "Key Dependencies" section + repo filesystem | >= 1 path reference that resolves to an existing file in the repo tree | v2 only |
   | 9 | Research option distinctness | research.md, "Approach Options" section | when >= 2 options present, options differ by >= 1 of: library/tool choice, file/module placement, or data-flow direction | v2 only |
   | 10 | Failure-mode coverage | requirements.md, "Edge Cases" section | >= 1 explicit failure mode (error path, invalid input, network failure, missing file, permission error, concurrency, timeout) | v2 only |

   **Expanded vague-phrase list (v2, check 6)** — scoped ONLY to the "Goal" and "Acceptance Criteria" sections of requirements.md. Phrases that break legitimate practical planning language ("reasonable", "simple", "efficient", "fast", "good", "clean", "lightweight", "proper", "correct", "elegant") are **excluded by policy**: these have concrete meanings in engineering prose (e.g. "lightweight entry", "correct name printed", "proper shutdown"). The list covers only unmeasurable marketing/handwave terms:

   ```
   robust, seamless, scalable, modern, state-of-the-art, best-in-class,
   user-friendly, intuitive, ideal, optimal, blazing, lightning-fast,
   enterprise-grade, world-class, next-generation, performant,
   cutting-edge, turnkey, revolutionary, game-changing, industry-leading,
   bulletproof, frictionless
   ```

   This list contains **23 phrases** (exceeds the required minimum of 20). It has been self-validated against the requirements.md of todos 487, 503, 504, 505, 507, 508, 509, 510 and produces **zero false positives** in the Goal/Acceptance Criteria sections (the only hit is in todo 503's own requirements.md where the phrases appear as quoted examples describing this feature — an expected meta self-match, not a defect).

   A match fails check 6 with message: `Vague term "<token>" in <section> section — replace with a measurable criterion or remove`. Token matching is whole-word, case-insensitive.

   **Examples (passing vs failing)**:
   - FAIL (check 6): Goal says "Build a robust, scalable ingestion pipeline." — both `robust` and `scalable` match.
   - PASS (check 6): Goal says "Build an ingestion pipeline that handles 10k events/sec with <1% drop rate." — measurable criteria, no vague terms.
   - FAIL (check 7): Acceptance criterion "Users can log in smoothly" — no file path, function, CLI, test, numeric threshold, or observable outcome.
   - PASS (check 7): Acceptance criterion "`POST /api/login` returns 200 with a valid JWT in the `token` field for valid credentials" — CLI/API endpoint + observable outcome.
   - FAIL (check 8): research.md "Recommended Approach" section is pure prose with no file references.
   - PASS (check 8): research.md references `plugins/proj/server/server/tools/todo.py` in "Key Dependencies".

4. If all pass: silent, proceed to next step.
5. If any fail AND NOT `--no-interactive` (and fix-loop attempts < 3): display table and prompt:

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

   Fix → re-run define on the failing todo, then re-run preflight (increment attempt counter).

   On attempt 4: auto-demote remaining BLOCKING findings to WARNING and prompt only `(1) Continue anyway (2) Stop`.

6. If any fail AND `--no-interactive`: demote BLOCKING to WARNING, log to notes via `notes_append` with tag `preflight:auto-demoted`, record a decision log entry per demotion, auto-continue to next step.

**Phase A.5b — Adversarial Review (Define)**

Runs only when `quality_level` in `[careful, paranoid]`. NEVER runs under `--balanced` or `--fast`. Runs **after** the structural checks pass for a given todo, **in parallel** across 3 read-only agents.

**Batch sampling rule**: when the descendant list has > 5 todos, adversarial agents run only on a sampled subset — the **5 highest-complexity** todos (ranked by the same 7-dimension complexity score used in Phase C1 smart gating). Other todos get structural checks only. Users can override with `--force-preflight-all`.

**Agents (spawn in parallel via `Task` tool, one Task call per agent per todo)**:

| Agent | Reads | Checks |
|-------|-------|--------|
| Ambiguity Agent | requirements.md + research.md | undefined domain terms, handwavey claims, unmeasurable goals |
| Completeness Agent | requirements.md + research.md | missing failure modes, missing auth/security concerns, stated-scope vs out-of-scope gaps |
| Research Validation Agent | research.md + repo filesystem | each referenced file exists, distinctness of options, realism of stated risks |

Each agent is spawned as a `general-purpose` Task with:
- **Tools (read-only)**: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__content_get_research`, `mcp__proj__proj_explore_codebase`
- **Timeout**: 90 seconds
- **Output schema (strict JSON)**:

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

See the **Preflight Agents Reference** appendix for full prompt templates.

**Findings aggregation**: merge findings across all 3 agents into a single table keyed by todo:

```
### Preflight Adversarial Review — todo <id>

| Severity | Agent | Finding | Evidence |
|----------|-------|---------|----------|
| BLOCKING | Completeness | Missing auth failure path | requirements.md L23 |
| WARNING  | Ambiguity | Undefined term "downstream" | requirements.md L12 |
```

**Severity semantics**:
- **BLOCKING** — triggers the Fix / Continue / Stop prompt (same UX as structural failures). Subject to `--no-interactive` demotion and the fix-loop cap.
- **WARNING** — shown, non-blocking, single OK acknowledgement. Under `--paranoid`, WARNINGs require explicit acknowledgement; an "Acknowledge all WARNINGs" shortcut is offered when >= 3 WARNINGs are present.
- **INFO** — shown, non-blocking, no acknowledgement required.

**Degraded-mode handling**: agent timeouts or malformed JSON are demoted to WARNING (never BLOCKING). Raw agent output is shown under the finding.

**If `decompose`** — parallel Task agents:
- For each batch in dependency order:
  - Spawn one `general-purpose` Task agent per todo. Each runs decompose autonomously.
  - Wait for batch completion. Report failures.
- After completion: refresh descendant list via `mcp__proj__todo_tree`.

**If `refine`** — after decompose, within iteration (if (`quality_level in [careful, paranoid]`) AND `refine` in steps AND NOT `--no-interactive`):

IF quality_level == fast: skip refine entirely, proceed to next step.
IF quality_level in [careful, paranoid]: auto-enable refine regardless of --refine flag.

For each todo in the descendant list, call the Skill tool: `skill: "proj:refine", args: "<id>"`.
  If Apply: requirements/research are updated and preflight re-runs automatically.

**3a.** Capture iteration snapshots (only when N > 1)

**Before iteration 1 starts** (after building the initial descendant list but before running any prep steps), capture the pre-existing state as `snapshot_0`:
- For each todo in the descendant list (including root): read `content_get_requirements` and `content_get_research`
- Record the descendant list structure: child IDs, titles, and blocked_by for each
- If descendant list exceeds 15 todos, read content for root-level children only.

**After each iteration's prep steps complete**, capture the current state as `snapshot_<i>` using the same method.

**4.** Between-iteration prompt (skip if last iteration or `--no-interactive`)

**4a.** Convergence assessment

Compare `snapshot_<i>` with `snapshot_<i-1>` across four dimensions:

- **Requirements**: Compare requirements.md text for each todo. Ignore whitespace/formatting/minor rewording. Flag new acceptance criteria, changed goals, or changed testing strategy.
- **Research**: Compare research.md text. Flag changed recommended approach, new options, or significant new findings.
- **Structure**: Compare descendant lists. Check for new/removed children or title changes.
- **Dependencies**: Compare blocked_by relationships. Check for new/removed blocking edges.

Display:

```
### Convergence Assessment (Iteration <i>)

**Requirements**: [Stable | Minor changes | Significant changes] — <1-line summary>
**Research**: [Stable | Minor changes | Significant changes] — <1-line summary>
**Structure**: [Stable | Changed] — <summary>
**Dependencies**: [Stable | Changed] — <summary>

**Recommendation**: [Ready to execute — prep has converged] OR [Continue iterating — <reason>]
```

Recommend "Ready to execute" when ALL dimensions are Stable or Minor changes with no new structural additions. Otherwise recommend "Continue iterating".

**4b.** Next action prompt

```
### Iteration <i>/<N> complete — Next Action?

1. **Continue** — Start iteration <i+1>
2. **Skip to execute** — Prep has converged, proceed to execute
3. **Redefine** — Re-run interactive define on specific todos (enter IDs)
4. **Stop** — Exit workflow now (completed steps are saved)
```

When the user picks option 2, skip all remaining iterations and jump directly to step 5 (Execute).
When the user picks option 3: prompt for todo IDs, run interactive define on each, then resume from decompose step.

**5.** Execute (only if `has_execute`)

Refresh todo via `mcp__proj__todo_get`. Determine `has_children = len(children) > 0`.

If NOT `--no-interactive`, prompt:

```
### Prep complete — Execute?

1. **Proceed** — Run execute
2. **Redefine** — Re-run interactive define on specific todos (enter IDs)
3. **Stop** — Exit (prep saved)
```

**If no children** — execute parent only (step 5i).
**If has children** — execute all (parent + descendants) via step 5ii.

**5i. Single execute:**

IF quality_level == fast:
  Display warning: "⚡ Running in --fast mode. Auto-executing low-complexity todos. Tag-immune todos (security/breaking-change/migration) will still get full review."
  **Fast-mode safety guardrails** (apply to all --fast execution):
  - Minimal syntax check: verify modified files are parseable (Python: `py_compile`, JS: basic syntax check) even in fast mode.
  - Todos completed under --fast are marked with metadata `fast_mode: true` via `todo_update`.
  - External sync (Todoist/Trello) is deferred until workflow completes (not per-todo).
  - Security-tagged todos (security/breaking-change/migration) that received FULL REVIEW under --fast also get STANDARD verification before completion.

1. Call `mcp__proj__todo_check_executable` — if manual-tagged: display warning and stop.
2. Call the Skill tool: `skill: "proj:execute", args: "<id>"`.

IF quality_level == fast:
  After execution completes: display post-run summary with `git diff HEAD~N` command.

**5ii. Execute-all (parent + descendants):**

Build full list: `[todo_id] + all_descendants` (from todo_tree, flattened depth-first).
Call `mcp__proj__proj_identify_batches` for dependency order.

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine execution mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 2+ total (non-manual) descendants: use **Team-based execution** below.
- Otherwise: use **Task agent execution** below.

**--- Team-based execution (5ii-T) ---**

IF quality_level == fast:
  Display warning: "⚡ Running in --fast mode. Auto-executing low-complexity todos. Tag-immune todos (security/breaking-change/migration) will still get full review."

**Phase 1 — Plan (sequential, main conversation):**

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

If `--no-interactive`: skip Phase 1, proceed directly to Phase 2 with execute instructions only.

Store `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

**If `--batch-approve` is set:**

1. `EnterPlanMode` once (single session for all todos).
2. For each todo in dependency order (inside plan mode):
   - Call `mcp__proj__todo_check_executable` — if manual: display `Todo <id> [manual] — skipped`, add to `manual_skipped_ids`, continue.
   - Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
   - Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan. If no snippets are returned, skip silently.
   - Smart gate scoring (same rules as default cycle below) — AUTO-EXECUTE todos skip plan creation; LIGHT REVIEW todos get a 1-line plan summary (no separate EnterPlanMode since already in plan mode); FULL REVIEW todos get a full implementation plan.
   - Create implementation plan (for FULL REVIEW and LIGHT REVIEW todos): read context and explore relevant source files. Cover files to modify/create, key changes, implementation order, testing approach. Include any Related Context. For AUTO-EXECUTE: create git tag `pre-auto-execute-{todo_id}`, skip plan creation entirely.
   - Store plan in `approved_plans[todo_id]`.
3. `ExitPlanMode` once, presenting all plans together as a combined summary.
4. Plan approval:
   - **Trust 0-1**: User reviews all plans in one pass. User can approve the batch, reject individual plans (offer re-plan or skip for rejected ones — don't abort the whole batch), or modify individual plans before approving the rest.
   - **Trust 2** with `--batch-approve`: single plan mode session, skip `ExitPlanMode` user review (auto-approve all). Display: `Batch auto-approved (trust 2): <N> plans`.
5. Store all approved plans in `approved_plans`. Pipeline: spawn execution agents as plans are approved (same spawning rules as default cycle step 7).

**Otherwise (default per-todo cycle):**

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: display `Todo <id> [manual] — skipped`, add to `manual_skipped_ids`, continue.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.

**Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

Compute complexity score (0-14) from 7 dimensions:

| Dimension | 0 points | 1 point | 2 points |
|-----------|----------|---------|----------|
| File count (from plan) | 1 file | 2-4 files | 5+ files |
| Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
| Requirements quality | detailed | basic | none/vague |
| Research quality | detailed | basic | none |
| Risk tags | none | general risk | security/breaking/migration |
| Children count | 0 (leaf) | 1-3 | 4+ |
| Blocked-by deps | 0 | 1 | 2+ |

**Evaluation order:**
1. Tag overrides (FIRST): `auto-execute` tag → AUTO-EXECUTE. `security`/`breaking-change`/`migration`/`needs-review` → FULL REVIEW.
2. Complexity score: AUTO-EXECUTE (0-3), LIGHT REVIEW (4-7), FULL REVIEW (8-14).
3. Critical-path file guard (LAST, floor): if plan touches critical-path files (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW.

**Gate routing:**
- AUTO-EXECUTE: Create git tag `pre-auto-execute-{todo_id}`. Skip plan mode, execute with context only.
- LIGHT REVIEW: Display 1-line plan summary + `Proceed? [Y/n]` (default yes).
- FULL REVIEW: Full EnterPlanMode/ExitPlanMode (current behavior).

IF --force-plan: force FULL REVIEW on all todos regardless of complexity score.

4. `EnterPlanMode` (for FULL REVIEW gate). Read context and explore relevant source files. Create an implementation plan covering files to modify/create, key changes, implementation order, testing approach. Include any Related Context from step 3. For LIGHT REVIEW: create a 1-line plan summary without EnterPlanMode. For AUTO-EXECUTE: skip plan creation entirely.
5. Plan approval (respects trust level AND gate routing):
   - **Trust 0**: `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: `ExitPlanMode` for user review. User approves this plan, then move to the next todo. After all plans: present a bulk approval summary for final confirmation.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
   - AUTO-EXECUTE gate: skip approval entirely regardless of trust level.
   - LIGHT REVIEW gate: display 1-line summary + `Proceed? [Y/n]` regardless of trust level (unless trust 2+).
6. Store approved plan in `approved_plans[todo_id]`.
7. IF `pipeline_enabled` AND trust level is NOT 3:
     Before spawning: if `len(executing_agents) >= max_parallel` (from quality_level), wait for at least one executing agent to complete before spawning another.
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

After all plans are stored (trust 0-1): present a bulk approval summary showing all todo IDs and their plan summaries.

**File-Overlap Detection** (after Phase 1, before Phase 2, skip if trust 3):
1. For each approved plan in `approved_plans`, extract the "Files to modify/create" list from the plan text. For dependency-batched execution, check overlaps **within each batch** (across-batch overlaps are acceptable since batches run sequentially).
2. Build an overlap matrix: for each pair of plans within the same batch, check if their file lists intersect.
3. Quality-level behavior for overlaps:
   - IF quality_level == fast: auto-proceed on overlap (no prompt).
   - IF quality_level in [careful, paranoid]: auto-serialize conflicting todos.
   - IF quality_level == balanced: prompt user (current behavior below).
4. If overlaps are found (and quality_level == balanced), display:

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

5. If user selects **Serialize**: remove conflicting todos from their parallel batch, add them to a new sequential batch at the end.
6. If user selects **Proceed**: continue as-is.
7. If user selects **Cancel**: stop, display "Execution cancelled. Plans are saved."
8. If no overlaps detected: skip silently.

**Resume checkpoint** (applies when `--resume` is passed):
1. Look for the most recent checkpoint file in `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. If found and not stale (created within the last 24 hours):
   - Read the checkpoint. Display: `Resuming from batch {batch_index}/{total_batches} — {len(completed_todos)} todos already completed`.
   - Use the stored `approved_plans` from the checkpoint.
   - Skip to the `batch_index` in Phase 2 (all prior batches are treated as complete).
3. If the checkpoint is stale (older than 24 hours) or references todos that no longer exist:
   - Display: `Checkpoint is stale (created {timestamp}). Restart from the beginning? (1) Restart (2) Use anyway`.
   - If Restart: ignore checkpoint and start from Phase 1.
   - If Use anyway: proceed with the stale checkpoint data.
4. If no checkpoint found: display `No checkpoint found — starting fresh` and proceed normally.

**Phase 1.25 — Pre-execute Preflight**

Runs after plan approval and file-overlap detection, before worktree setup and execute spawn. Follows the same semantics as **Phase C0.5 — Pre-execute Preflight** (and Phase C0.5b adversarial review) described later in this document: 6 structural checks (plan has file list, paths valid, critical-path touches named, working tree clean, test runner detectable [WARNING only], plan non-empty), per-todo, skipped under trust 3, skipped under `--fast`. Adversarial agents (File Path Verifier, Spec-Plan Alignment, Impact Scanner) run only under `careful`/`paranoid`. See Phase C0.5/C0.5b for full tables, severity rules, `--no-interactive` demotion, and fix-loop cap.

**Phase 1.5 — Worktree setup** (if `worktree_enabled`):

**Worktree prerequisite check**:
- Call `wt_list_repos` to verify the worktree plugin is installed and at least one base repo is registered.
- If no repos registered:
  - Get current project repos from `proj_session_context`.
  - If project has 0 repos: disable worktree for this run, display "No worktree repos registered and no project repos found. Falling back to main." Continue.
  - If project has exactly 1 repo (`<path>`):
    - Display: "No worktree base registered. Add `<path>` as worktree base `<basename(path)>`? [Y/n]"
    - If yes: call `wt_add_repo(label=basename(path), path=path, default_branch="main")`.
      - If success: display "Registered `<path>` as worktree base `<basename(path)>`. Continuing." Proceed with worktree setup as normal.
      - If failure: display error, disable worktree, fall back to main.
    - If no: disable worktree, display "Falling back to main." Continue.
  - If project has 2+ repos:
    - Display: "No worktree base registered. Select repo(s) to register as worktree base:"
      ```
      1. <label>: <path>
      2. <label>: <path>
      (enter numbers comma-separated, or 0 to skip)
      ```
    - For each selected repo: call `wt_add_repo(label=basename(path), path=path, default_branch="main")`.
      - Report success/failure per repo.
      - On any success: proceed with worktree setup as normal.
      - If all fail or none selected: disable worktree, fall back to main.
  - If `--no-interactive`: if exactly 1 project repo, auto-register silently and display notice; if 0 or 2+ repos, disable worktree with warning "No worktree repos registered. Falling back to main."

Check `git status --porcelain` on main. If dirty (uncommitted changes):
  Prompt: (1) Stash changes (2) Commit changes (3) Abort worktree setup
  Stash: run `git stash push -m "pre-worktree-{timestamp}"`, proceed.
  Commit: prompt for message, commit, proceed.
  Abort: disable worktree for this run, fall back to main.
  If `--no-interactive`: auto-stash.

For each todo in current batch:
1. Call `wt_create` with repo_label and branch name `todo-{id}`.
   If fails: fall back to main for this todo, display warning. Continue with remaining todos.
2. Call `wt_lock` on the created worktree.
3. Call `sandbox_add_write_path` to add the worktree path to sandbox write allowlist.
4. Store `worktree_path` and `worktree_branch` for this todo.

With pipeline: setup runs per-todo immediately after plan approval (before spawning execution agent).
Without pipeline: setup runs for all todos in batch before Phase 2 begins.

**Phase 2 — Execute (batches sequential, within-batch parallel with Team):**

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

1. `TeamCreate(name="run-exec-{project}-{timestamp}", description="Run: executing descendants of todo {parent_id} in {N} batches")`
1a. **Task Mapping** (one-way — tasks mirror todos for coordination only):
   For each todo across all batches:
   - Call `TaskCreate` with:
     - `title`: todo title
     - `description`: `"Implement todo {id} — {title}"`
     - `metadata`: `{"proj_todo_id": "{todo.id}", "team_name": "{team_name}"}`
   - If the todo has `blocked_by` relationships with other todos in the same execution set, use `addBlockedBy` to map the blocking relationships (using the Task IDs returned from previous `TaskCreate` calls).

   Agents discover their assigned tasks via `TaskList(metadata={"team_name": team_name})` (pull model — agents are not assigned tasks directly).

   **One-way only**: Task completion does NOT auto-complete the proj todo. The satisfaction loop handles proj todo completion.

2. For each batch in dependency order (excluding `manual_skipped_ids`):
   - Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
   - Spawn one Agent per todo in this batch with `team_name`. Each agent receives: the approved plan (or context only if trust 3) + requirements.md + research.md + parent context. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content. Each implements the approved plan. Agents do NOT call `todo_complete`. If they hit an issue not covered by the plan, they report via `SendMessage` to the team lead rather than improvising.
   - If `worktree_enabled` and todo has `worktree_path`:
     Include in agent context: `worktree_path: <path>`, `worktree_branch: <branch>`.
     Instruction: "Execute all file operations in the worktree directory at `<worktree_path>`. Prefix all git commit messages with `[todo-{id}]` when working in the worktree."
   - Wait for this batch to complete before starting the next batch. Report failures: `Agent for todo <id> failed: <error>`.
   - **Write checkpoint** after each batch to `<tracking_dir>/<project>/.team-state/<team-name>/checkpoint.yaml`:
     ```yaml
     team_name: run-exec-{project}-{timestamp}
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
3. After all batches complete: `TeamDelete(team_name)`
4. If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml` (create the directory if needed).

**--- Task agent execution (5ii-F, fallback) ---**

IF quality_level == fast:
  Display warning: "⚡ Running in --fast mode. Auto-executing low-complexity todos. Tag-immune todos (security/breaking-change/migration) will still get full review."

**Phase 1 — Plan (sequential, main conversation):**

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

If `--no-interactive`: skip Phase 1, proceed directly to Phase 2 with execute instructions only.

Store `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: display `Todo <id> [manual] — skipped`, add to `manual_skipped_ids`, continue.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.

**Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

Compute complexity score (0-14) from 7 dimensions:

| Dimension | 0 points | 1 point | 2 points |
|-----------|----------|---------|----------|
| File count (from plan) | 1 file | 2-4 files | 5+ files |
| Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
| Requirements quality | detailed | basic | none/vague |
| Research quality | detailed | basic | none |
| Risk tags | none | general risk | security/breaking/migration |
| Children count | 0 (leaf) | 1-3 | 4+ |
| Blocked-by deps | 0 | 1 | 2+ |

**Evaluation order:**
1. Tag overrides (FIRST): `auto-execute` tag → AUTO-EXECUTE. `security`/`breaking-change`/`migration`/`needs-review` → FULL REVIEW.
2. Complexity score: AUTO-EXECUTE (0-3), LIGHT REVIEW (4-7), FULL REVIEW (8-14).
3. Critical-path file guard (LAST, floor): if plan touches critical-path files (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW.

**Gate routing:**
- AUTO-EXECUTE: Create git tag `pre-auto-execute-{todo_id}`. Skip plan mode, execute with context only.
- LIGHT REVIEW: Display 1-line plan summary + `Proceed? [Y/n]` (default yes).
- FULL REVIEW: Full EnterPlanMode/ExitPlanMode (current behavior).

IF --force-plan: force FULL REVIEW on all todos regardless of complexity score.

4. `EnterPlanMode` (for FULL REVIEW gate). Read context and explore relevant source files. Create an implementation plan covering files to modify/create, key changes, implementation order, testing approach. Include any Related Context from step 3. For LIGHT REVIEW: create a 1-line plan summary without EnterPlanMode. For AUTO-EXECUTE: skip plan creation entirely.
5. Plan approval (respects trust level AND gate routing):
   - **Trust 0**: `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: `ExitPlanMode` for user review. User approves this plan, then move to the next todo.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
   - AUTO-EXECUTE gate: skip approval entirely regardless of trust level.
   - LIGHT REVIEW gate: display 1-line summary + `Proceed? [Y/n]` regardless of trust level (unless trust 2+).
6. Store approved plan in `approved_plans[todo_id]`.
7. IF `pipeline_enabled` AND trust level is NOT 3:
     Before spawning: if `len(executing_agents) >= max_parallel` (from quality_level), wait for at least one executing agent to complete before spawning another.
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

**Phase 1.25 — Pre-execute Preflight**

Runs after plan approval and file-overlap detection, before worktree setup and execute spawn. Follows the same semantics as **Phase C0.5 — Pre-execute Preflight** (and Phase C0.5b adversarial review) described later in this document: 6 structural checks (plan has file list, paths valid, critical-path touches named, working tree clean, test runner detectable [WARNING only], plan non-empty), per-todo, skipped under trust 3, skipped under `--fast`. Adversarial agents (File Path Verifier, Spec-Plan Alignment, Impact Scanner) run only under `careful`/`paranoid`. See Phase C0.5/C0.5b for full tables, severity rules, `--no-interactive` demotion, and fix-loop cap.

**Phase 1.5 — Worktree setup** (if `worktree_enabled`):

**Worktree prerequisite check**:
- Call `wt_list_repos` to verify the worktree plugin is installed and at least one base repo is registered.
- If no repos registered:
  - Get current project repos from `proj_session_context`.
  - If project has 0 repos: disable worktree for this run, display "No worktree repos registered and no project repos found. Falling back to main." Continue.
  - If project has exactly 1 repo (`<path>`):
    - Display: "No worktree base registered. Add `<path>` as worktree base `<basename(path)>`? [Y/n]"
    - If yes: call `wt_add_repo(label=basename(path), path=path, default_branch="main")`.
      - If success: display "Registered `<path>` as worktree base `<basename(path)>`. Continuing." Proceed with worktree setup as normal.
      - If failure: display error, disable worktree, fall back to main.
    - If no: disable worktree, display "Falling back to main." Continue.
  - If project has 2+ repos:
    - Display: "No worktree base registered. Select repo(s) to register as worktree base:"
      ```
      1. <label>: <path>
      2. <label>: <path>
      (enter numbers comma-separated, or 0 to skip)
      ```
    - For each selected repo: call `wt_add_repo(label=basename(path), path=path, default_branch="main")`.
      - Report success/failure per repo.
      - On any success: proceed with worktree setup as normal.
      - If all fail or none selected: disable worktree, fall back to main.
  - If `--no-interactive`: if exactly 1 project repo, auto-register silently and display notice; if 0 or 2+ repos, disable worktree with warning "No worktree repos registered. Falling back to main."

Check `git status --porcelain` on main. If dirty (uncommitted changes):
  Prompt: (1) Stash changes (2) Commit changes (3) Abort worktree setup
  Stash: run `git stash push -m "pre-worktree-{timestamp}"`, proceed.
  Commit: prompt for message, commit, proceed.
  Abort: disable worktree for this run, fall back to main.
  If `--no-interactive`: auto-stash.

For each todo in current batch:
1. Call `wt_create` with repo_label and branch name `todo-{id}`.
   If fails: fall back to main for this todo, display warning. Continue with remaining todos.
2. Call `wt_lock` on the created worktree.
3. Call `sandbox_add_write_path` to add the worktree path to sandbox write allowlist.
4. Store `worktree_path` and `worktree_branch` for this todo.

With pipeline: setup runs per-todo immediately after plan approval (before spawning execution agent).
Without pipeline: setup runs for all todos in batch before Phase 2 begins.

**Phase 2 — Execute (parallel Task agents):**

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

For each batch in dependency order (excluding `manual_skipped_ids`):
1. Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
2. Spawn one `general-purpose` Task agent per todo. Each receives: todo details, requirements.md, research.md, parent context, AND the approved plan (or context only if trust 3, or execute instructions if `--no-interactive`). Each implements the approved plan. Agents do NOT call `todo_complete`.
   If `worktree_enabled` and todo has `worktree_path`:
     Include in agent context: `worktree_path: <path>`, `worktree_branch: <branch>`.
     Instruction: "Execute all file operations in the worktree directory at `<worktree_path>`. Prefix all git commit messages with `[todo-{id}]` when working in the worktree."
3. Wait for batch completion. Report failures: `Agent for todo <id> failed: <error>`.

**--- Common post-execute (both modes) ---**

Check `git status --porcelain` on main. If dirty: display warning "Main has uncommitted changes after worktree execution. This may cause merge conflicts."

**Phase 2.5 — Merge worktree branches** (if `worktree_enabled`):

Initialize `files_merged_this_batch = set()` and `reexecution_queue = []`.

For each completed todo in batch order:
  Create pre-merge backup: `git tag pre-merge-{todo_id}`.

  For each completed todo's worktree:
    Call `wt_auto_commit(worktree_path=<path>, message="[todo-{id}] Auto-commit agent work")`
    If committed: display "Auto-committed {N} files in worktree for todo {id}"
    If error: log warning, proceed to merge attempt

  Run `git merge --no-ff todo-{id}` and apply the **3-tier resolution cascade** below.

  ---

  ### Tier 1 — Clean merge

  `git merge --no-ff todo-{id}` exits 0.

  - Add all modified files (from `git diff-tree --no-commit-id --name-only -r HEAD`) to `files_merged_this_batch`.
  - Call `mcp__proj__notes_append` with `note="Merge tier 1 (clean): todo-{id} — {N} files"`.
  - After successful merge and `wt_remove`: delete the branch with `git branch -d todo-{id}`.
  - Continue to the next todo.

  ### Tier 2 — Expanded auto-resolve

  Merge had conflicts. Evaluate eligibility (ALL conditions must hold):
  - Conflicting file count ≤ **5** (raised from previous cap of 2).
  - All conflict hunks < **50 lines** (raised from 20).
  - No conflicting file matches any critical-path pattern (e.g. `**/models.py`, `**/schema.*`, `**/migrations/**`, `**/security/**` — configurable list).

  If eligible, resolve each conflicting file using the `files_merged_this_batch` decision rule:
  - If file **NOT** in `files_merged_this_batch` → accept **theirs** (worktree version is the authoritative latest write).
  - If file **IN** `files_merged_this_batch` → accept **ours** (main already holds a merged version from an earlier todo in this batch; the worktree branched before that merge and its view is stale).

  Stage resolved files, commit, add files to `files_merged_this_batch`. After successful merge and `wt_remove`, delete branch with `git branch -d todo-{id}`.

  Call `mcp__proj__notes_append` with `note="Merge tier 2 (auto-resolve): todo-{id} — {N} files, strategy=[theirs×K, ours×M]"`.

  ### Tier 3 — Ask user

  Tier 2 ineligible (too many files, hunks too large, or critical-path file touched) OR Tier 2 auto-resolve raised a fresh error.

  **IF `--no-interactive`**:
    - Abort merge: `git merge --abort`, then `git reset --hard pre-merge-{todo_id}`.
    - Append todo to `reexecution_queue`.
    - Call `mcp__proj__notes_append` with `note="Merge tier 3 (aborted, non-interactive): todo-{id} — queued for re-execution"`.

  **ELSE** (interactive):
    Display conflict summary: conflicting files, hunk counts, critical-path matches (if any). Prompt:
    1. **Manual resolve** — user resolves in editor, then `git add` + `git commit` + continue
    2. **Abort this merge** — revert to `pre-merge-{todo_id}` tag, add to `reexecution_queue`

    Call `mcp__proj__notes_append` with `note="Merge tier 3 (user): todo-{id} — choice={manual|abort}"`.

  > **Note**: the previous Tier 3 `-X theirs` and `git rerere` strategies have been removed. `rerere` is a user-side local config (not a runtime-invocable command), and a blind `-X theirs` across an arbitrary conflict set is unsafe without a files-merged decision rule — which is exactly what Tier 2 already provides within its eligibility envelope.

  ---

  **Post-merge test** (after each merge):
    Run test suite (`uv run pytest --tb=short -q` or `npm test`).
    If tests fail:
    - If only 1 merge completed so far: revert that merge, re-execute todo on main.
    - If multiple merges: use `git bisect` on merge commits to identify the breaking merge. Offer: (1) Revert breaking merge (2) Fix manually (3) Continue anyway.

**Serialized re-execution queue** (after all batch merges):
  If `reexecution_queue` is non-empty:
    Display: "N todos need re-execution on main (merge conflicts aborted)."
    For each queued todo: re-execute sequentially on main (no worktree, `--no-pipeline --balanced`).

**Phase 2.6 — Post-merge verification** (after all tier-1/2/3 merges and any re-execution queue drain, before `Verification` step):

1. **Final full-suite test run** — run the project test suite **without** `-q` so that per-test output is visible. Detect runner via the same logic as execute step 4a (`uv run pytest --tb=short`, `npm test`, etc.). If the suite fails, surface the full failing output, append `notes_append("Post-merge verification FAILED: {N} tests")`, and offer: (1) Spawn fix agents (2) Proceed anyway (3) Abort batch.

2. **Diff-vs-plan review agent** — spawn a read-only `general-purpose` Task agent with a **60s timeout** to compare the combined batch diff (`git diff {merge_base}..HEAD`) against each todo's approved implementation plan (from the plans persisted earlier in Phase 1/2). The agent reports per-todo mismatches as `WARNING` entries — it does NOT modify files and does NOT block the batch. Its report is appended to the combined verification summary below as a new **Drift** column.

3. **Resource safeguards** (pre-batch, run these checks *before* Phase 1.5 worktree setup as a gate):
   - **Disk**: `df --output=avail .` — require at least `300 MB × max_parallel` free on the worktree root. On shortfall, warn and cap `max_parallel` to `floor(avail_mb / 300)`.
   - **File descriptors**: `ulimit -n` — require at least `256 × max_parallel` descriptors. On shortfall, warn and cap `max_parallel` accordingly.
   - **Context budget**: estimated aggregate context per agent × `max_parallel` must stay below the trust-level budget (see `context_injection_budget`). On shortfall, cap `max_parallel`.
   Each cap emits a `notes_append("Pre-batch cap: max_parallel {old}→{new} due to {reason}")` line.

**Verification** (skip entirely if `--no-verify` was passed):

For each completed todo across all batches (excluding failed agents and `manual_skipped_ids`), run the verification checks from execute step 4a:
- **A. Automated checks** (detect test runner, run tests/lint)
- **B. Spec validation** (check acceptance criteria against git diff)
- **C. Diff review** (compare approved plan files vs actual changes)

Verify ALL todos first, then display a combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| <id> | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| <id> | FAIL (2 failed) | 2/3 met | 1 extra file | FAIL |
```

Persist each todo's report to `todos/<id>/verification-report.md` in the tracking dir (with timestamp, overwrite previous).

If any todo has failures, prompt:
> N passed, M failed. Fix failed todos? (1) Fix (2) Proceed (3) Skip
- **Fix**: spawn one `general-purpose` Task agent per failed todo with: (1) the verification report, (2) todo details + requirements.md + research.md + parent context (via `proj_get_todo_context`), (3) the approved implementation plan, and (4) instructions to fix the failures. After agents complete, re-run verification on fixed todos only (max 2 retries). Update the combined report and re-prompt if still failing.
- **Proceed**: continue to satisfaction check despite failures.
- **Skip**: skip remaining verification for this session.

If all checks pass, display the report and proceed without prompting.

**Satisfaction check** (sequential, main conversation):

Satisfaction mode is determined by `quality_level.satisfaction`:
- IF satisfaction == "per-batch": After all todos in batch complete, display summary table, prompt "Satisfied with this batch?" once for the entire batch.
- IF satisfaction == "per-todo": Run individual satisfaction loop per todo (default behavior below).
- IF satisfaction == "skip": Auto-complete all todos without prompting (call `mcp__proj__todo_complete` on each).
- IF satisfaction == "per-todo + re-verify": Run individual satisfaction per todo, then re-run verification after any fixes.

For per-todo and per-todo + re-verify modes, for each completed todo in the batch, run the satisfaction loop:
   a. Ask: "Are you satisfied with the outcome of todo <id>, or is there anything else that needs to be done?"
      1. **Satisfied** — mark done: call `mcp__proj__todo_complete`
      2. **Not satisfied** — fix in scope: ask what's missing. Call `mcp__proj__proj_decision_log` with `action="add"`, `decision=<feedback text>`, `context="run:satisfaction:<todo_id>"`, `tags="correction,quality"`, `todo_id=<todo_id>`. Then create new todo (`todo_add`), run full workflow (`/proj:run <new_id> --iter 5`), then re-ask satisfaction on original todo
      3. **Redefine** — refine requirements and re-run workflow: run interactive define on the todo, then re-run `/proj:run <id> --from decompose`

   When spawning a satisfaction-driven recursive run: enforce `--no-pipeline --balanced --no-worktree`. Maximum recursion depth: 2. Pass `--_recursion_depth N` internally (not user-facing). If depth >= 2: refuse to recurse, display "Maximum satisfaction recursion depth reached. Fix manually."

Auto-complete parent: if `manual_skipped_ids` is empty, run the satisfaction loop (3-option: Satisfied / Not satisfied / Redefine) for the parent todo before calling `mcp__proj__todo_complete` on parent. Otherwise display warning.

IF quality_level == fast:
  After execution completes: display post-run summary with `git diff HEAD~N` command.

Clear `executing_agents = {}` before proceeding to the next batch.

**Phase 5 — Worktree cleanup** (if `worktree_enabled`, always runs even on failure):

For each worktree created during this execution:
1. Call `wt_unlock` on the worktree.
2. Call `wt_remove` to delete the worktree.
3. Call `sandbox_reconcile` to remove sandbox entries for deleted worktree paths.
4. Call `wt_prune` to clean any stale worktree admin entries.
Display: "Cleaned up N worktrees."

**6.** Complete

```
Full workflow complete for todo <id>: <title>
Steps completed: <step1>, <step2>, ...
```

Call `mcp__proj__notes_append` with brief summary.

**7.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Run: {todo-id}"`.

Suggested next: `1. /proj:status` -- see updated project overview

---

## Batch mode

*(Range or comma list input — all steps run autonomously)*

**a.** Setup
- Load step list, apply `--steps`/`--from` flags.
- `run_define_interactive` = `define` in steps (always interactive — define requires user input even in batch mode)
- `has_execute` = `execute` in steps
- `agent_steps` = steps excluding `define` (if interactive) and `execute`

**b.** Dependency order
Call `mcp__proj__proj_identify_batches` with all todo IDs. Error on cycles.

**Iteration loop** (repeat up to `--iter N` times, default 5):

If N > 1: announce `Iteration <i>/<N>`

**Phase A — Define (if `run_define_interactive`):**
For each todo in dependency order:
- Announce: `Define: <id> — <title>`
- Execute define interactively in main conversation
- If current iteration > 1, pass `--skip-bg-prep` to define (codebase hasn't changed between iterations, background prep would be redundant).

**Quality gate check** (after define phase):
For each todo defined non-interactively (agent-driven):
- Read the self-assessment from define output
- If any section has confidence ≤ 2 (speculative or inferred), add to flagged_todos

If flagged_todos is non-empty, display:

```
### Low-confidence definitions detected

| Todo | Low-confidence sections |
|------|------------------------|
| <id> | <section> (<score>/5) |

1. **Continue anyway** — proceed to decompose
2. **Re-define** — run interactive define on flagged todos
3. **Stop** — exit workflow
```

If Re-define: run interactive define on each flagged todo, then resume from decompose.

**Phase A.5 — Preflight checklist:**

IF quality_level == fast: skip preflight entirely, proceed to Phase B.

For each todo in dependency order:
  Run the preflight structural checks (10 checks if `preflight_version: 2`, else legacy 5 — same table and rules as single-ID mode above, including grandfather, fix-loop cap, and `--no-interactive` demotion).
  Collect all failures.

If any failures AND NOT `--no-interactive` (and fix-loop attempts < 3):
  Display combined table:

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

  Fix → re-run define on failing todos, then re-run preflight on those todos (increment attempt counter).

  On attempt 4: auto-demote remaining BLOCKING to WARNING, prompt `(1) Continue anyway (2) Stop`.

If any failures AND `--no-interactive`: demote BLOCKING to WARNING, log to notes with tag `preflight:auto-demoted`, auto-continue.
If all pass: silent, proceed to Phase A.5b.

**Phase A.5b — Adversarial Review (Define) — Batch:**

Runs only when `quality_level` in `[careful, paranoid]`. NEVER under `--balanced`/`--fast`.

**Batch sampling**: if the batch has > 5 todos, adversarial agents run only on the **5 highest-complexity todos** (ranked by the 7-dimension complexity score). Override with `--force-preflight-all`.

For each sampled todo, spawn the 3 review agents (Ambiguity, Completeness, Research Validation) **in parallel** (one Task call per agent per todo). Same tools, timeout, JSON schema, and severity semantics as the single-ID mode's Phase A.5b. See the Preflight Agents Reference appendix for prompt templates.

After all agents return: aggregate findings into a single combined table keyed by todo. Apply the same BLOCKING prompt flow as structural checks. Timeouts and malformed JSON demote to WARNING.

**Phase B — Remaining steps (parallel agents):**

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 2+ non-manual todos in the batch: use **Team mode** below.
- Otherwise: use **Task agent mode** below.

**Team mode:**
1. `TeamCreate(name="run-decompose-{project}-{timestamp}", description="Run: decomposing todos {id1}, {id2}, ...")`
2. For each batch in dependency order:
   - Spawn one Agent per todo in this batch with `team_name`. Each runs `agent_steps` autonomously. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content. If agents hit an issue, they report via `SendMessage` to the team lead rather than improvising.
   - Wait for this batch to complete before starting the next batch. Report failures.
3. After all batches complete: `TeamDelete(team_name)`
4. If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml`.

**Task agent mode (fallback):**
For each batch in dependency order:
- Spawn one `general-purpose` Task agent per todo. Each runs `agent_steps` autonomously.
- Wait for batch completion. Report failures.

After Phase B completes (either mode): refresh descendant lists via `mcp__proj__todo_tree`.

**Phase B.75 — Refine (if (`quality_level in [careful, paranoid]`) AND `refine` in steps AND NOT `--no-interactive`):**

IF quality_level == fast: skip refine entirely, proceed to convergence check.
IF quality_level in [careful, paranoid]: auto-enable refine regardless of --refine flag.

For each todo in dependency order, call the Skill tool: `skill: "proj:refine", args: "<id>"`. Subject to `max_parallel` throttling from quality_level.
  Present per-todo refinement reports sequentially.
  If Apply on any todo: requirements/research updated, preflight re-runs on that todo.

**Phase B.5 — Convergence check** (skip if `--no-interactive`, only when N > 1)

**Before iteration 1 starts** (after dependency order but before Phase A), capture pre-existing state as `snapshot_0` for each todo in the input list (requirements, research, tree structure).
**After each iteration**, capture current state as `snapshot_<i>`.

Compare `snapshot_<i>` with `snapshot_<i-1>` and display:

```
### Convergence Assessment (Iteration <i>) — Batch

| Todo | Requirements | Research | Structure |
|------|-------------|----------|-----------|
| <id> | Stable/Minor/Significant | ... | ... |

**Overall**: [Ready to execute | Continue iterating] — <reason>
```

Then show the between-iteration prompt (same 4 options as single-ID mode).

**Phase C — Execute (after iteration loop):**

If `has_execute` is false: skip to summary.

If NOT `--no-interactive`, prompt:
```
### Prep complete — Execute?

1. **Execute all** — Plan and execute all todos
2. **Stop** — Exit (prep saved)
```

IF quality_level == fast:
  Display warning: "⚡ Running in --fast mode. Auto-executing low-complexity todos. Tag-immune todos (security/breaking-change/migration) will still get full review."

**Phase C0 — Speculative planning (if quality_level != careful/paranoid AND trust level != 0 AND trust level != 3):**

Spawn one read-only Task agent per todo in this batch. Each agent:
- Receives: todo context, requirements.md, research.md, parent context
- Restricted to read-only tools: Read, Glob, Grep, proj_get_todo_context, proj_explore_codebase, content_get_requirements, content_get_research
- Produces structured plan: `{prose: "<plan text>", actions: [{type: "create"|"modify"|"delete"|"test", file: "<path>"}]}`

Wait for all agents. If an agent fails: exclude that todo, fall back to sequential planning for it.
Store plans in `speculative_plans[todo_id]`.

**Phase C1 — Plan (sequential, main conversation):**

Skip Phase C1 entirely if **trust level is 3** — go directly to Phase C2 with context only (no plans).

If `--no-interactive`: skip Phase C1, proceed directly to Phase C2 with execute instructions only.

Store `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: skip with warning.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.

**Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

Compute complexity score (0-14) from 7 dimensions:

| Dimension | 0 points | 1 point | 2 points |
|-----------|----------|---------|----------|
| File count (from plan) | 1 file | 2-4 files | 5+ files |
| Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
| Requirements quality | detailed | basic | none/vague |
| Research quality | detailed | basic | none |
| Risk tags | none | general risk | security/breaking/migration |
| Children count | 0 (leaf) | 1-3 | 4+ |
| Blocked-by deps | 0 | 1 | 2+ |

**Evaluation order:**
1. Tag overrides (FIRST): `auto-execute` tag → AUTO-EXECUTE. `security`/`breaking-change`/`migration`/`needs-review` → FULL REVIEW.
2. Complexity score: AUTO-EXECUTE (0-3), LIGHT REVIEW (4-7), FULL REVIEW (8-14).
3. Critical-path file guard (LAST, floor): if plan touches critical-path files (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW.

**Gate routing:**
- AUTO-EXECUTE: Create git tag `pre-auto-execute-{todo_id}`. Skip plan mode, execute with context only.
- LIGHT REVIEW: Display 1-line plan summary + `Proceed? [Y/n]` (default yes).
- FULL REVIEW: Full EnterPlanMode/ExitPlanMode (current behavior).

IF --force-plan: force FULL REVIEW on all todos regardless of complexity score.

4. `EnterPlanMode` (for FULL REVIEW gate) — create implementation plan. Include any Related Context from step 3. For LIGHT REVIEW: create a 1-line plan summary without EnterPlanMode. For AUTO-EXECUTE: skip plan creation entirely.
5. Plan approval (respects trust level AND gate routing):
   - **Trust 0**: `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: `ExitPlanMode` for user review. User approves this plan, then move to the next todo. After all plans: present a bulk approval summary for final confirmation.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
   - AUTO-EXECUTE gate: skip approval entirely regardless of trust level.
   - LIGHT REVIEW gate: display 1-line summary + `Proceed? [Y/n]` regardless of trust level (unless trust 2+).
6. Store approved plan.
7. IF `pipeline_enabled` AND trust level is NOT 3:
     Before spawning: if `len(executing_agents) >= max_parallel` (from quality_level), wait for at least one executing agent to complete before spawning another.
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

**Pattern detection** (skip if quality_level in [careful, paranoid]):

1. Normalize each plan: strip todo-specific IDs, extract (action_type, file_pattern) tuples, replace unique path segments with *.
2. Compute pairwise Jaccard similarity: |A∩B| / |A∪B|.
3. Group plans with >80% similarity. Min group size: 2, max: 10.
4. IF quality_level == fast: auto-approve all pattern groups.
5. ELSE: display pattern groups as collapsible sections in batch review:

   **Pattern Group 1** (3 todos: 1.1, 1.2, 1.3) — 85% similar
   Common pattern: modify `tests/test_*.py`, modify `server/tools/*.py`
   Deviations: todo 1.2 also creates `server/tools/new_helper.py`

   Per-group actions: Approve pattern / Edit pattern / Review individually

IF speculative_plans exist:
  **Phase C1a — Batch review:**

  Display batch review document:
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

  IF `--batch-approve` OR trust level 2: auto-approve all, display "Batch auto-approved."

**File-Overlap Detection** (after Phase C1, before Phase C2, skip if trust 3):
1. For each approved plan in `approved_plans`, extract the "Files to modify/create" list from the plan text. For dependency-batched execution, check overlaps **within each batch** (across-batch overlaps are acceptable since batches run sequentially).
2. Build an overlap matrix: for each pair of plans within the same batch, check if their file lists intersect.
3. Quality-level behavior for overlaps:
   - IF quality_level == fast: auto-proceed on overlap (no prompt).
   - IF quality_level in [careful, paranoid]: auto-serialize conflicting todos.
   - IF quality_level == balanced: prompt user (current behavior below).
4. If overlaps are found (and quality_level == balanced), display:

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

5. If user selects **Serialize**: remove conflicting todos from their parallel batch, add them to a new sequential batch at the end.
6. If user selects **Proceed**: continue as-is.
7. If user selects **Cancel**: stop, display "Execution cancelled. Plans are saved."
8. If no overlaps detected: skip silently.

**Phase C0.5 — Pre-execute Preflight**

Runs **after** Phase C1 plan approval (including after the single `ExitPlanMode` under `--batch-approve`) and **before** Phase C2 execute spawn (and before Phase C1.5 worktree setup). Runs **per-todo** in dependency order, not batch-aggregated.

**Skipped entirely under trust 3**: trust 3 has no plan, so plan-based checks are not applicable. Log a single line: `Phase C0.5 skipped — trust 3 (no plan)`. Proceed to Phase C2.

**Skipped under `quality_level == fast`**: consistent with `preflight: skip` in the quality-level table.

For each todo in dependency order (excluding `manual_skipped_ids` and todos that fell back to AUTO-EXECUTE without a plan), run 6 structural checks:

| # | Check | Data read | Pass condition | Severity if fail |
|---|-------|-----------|---------------|------------------|
| 1 | Plan has file list | `approved_plans[todo_id]` text | contains a "Files to modify" or "Files to create" section with >= 1 entry | BLOCKING |
| 2 | File paths are valid | each path in plan vs filesystem (worktree tree if `worktree_enabled`, else main) | every path is an existing file OR creatable (parent dir exists, path is inside repo root) | BLOCKING |
| 3 | No critical-path file touched silently | plan text | each touched critical-path file (`*.env*`, `*secret*`, `*credential*`, `*auth*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`, `proj.yaml`, `*.config.*`) is named explicitly in the plan | BLOCKING |
| 4 | Git working tree clean | `git status --porcelain` on the relevant tree (main or worktree branch) | empty output OR user previously confirmed "proceed with dirty tree" | BLOCKING |
| 5 | Test runner detectable | repo root | `pyproject.toml` has `[tool.pytest]`, OR `package.json` has `"test"` script, OR a documented test command in a known location | WARNING (not BLOCKING — docs-only todos may have no tests) |
| 6 | Plan is non-empty | `approved_plans[todo_id]` text | >= 20 lines or >= 100 words | BLOCKING |

**Removed from this phase** (by design, documented for clarity):
- "Plan acknowledges each acceptance criterion" — LLM judgment, relocated to the Spec-Plan Alignment Agent in Phase C0.5b.
- "No touched file is gitignored" — too many false positives for legitimate build-artifact regeneration.

**On failure** (same UX pattern as Phase A.5):
- NOT `--no-interactive` AND attempts < 3: display per-todo table with Fix / Continue / Stop. Fix re-runs Phase C1 plan for that todo (incrementing the attempt counter).
- `--no-interactive`: demote BLOCKING to WARNING, log via `notes_append` tag `preflight:auto-demoted`, record decision log, continue.
- 4th attempt: auto-demote, prompt `(1) Continue anyway (2) Stop`.

If all pass: silent, proceed to Phase C0.5b.

**Phase C0.5b — Adversarial Review (Pre-execute)**

Runs only when `quality_level` in `[careful, paranoid]`. NEVER under `--balanced`/`--fast`. Also skipped under trust 3 (no plan to review).

**Batch sampling**: when the batch has > 5 todos, adversarial agents run only on the **5 highest-complexity todos** (same ranking as Phase A.5b). Override with `--force-preflight-all`.

For each sampled todo, spawn 3 read-only agents **in parallel** via the Task tool:

| Agent | Reads | Checks |
|-------|-------|--------|
| File Path Verifier | `approved_plans[todo_id]` + filesystem (worktree tree if `worktree_enabled`, else main) | double-checks each path against the filesystem; catches path-normalization bugs and case-sensitivity issues missed by the structural check |
| Spec-Plan Alignment Agent | requirements.md "Acceptance Criteria" + `approved_plans[todo_id]` | for each acceptance criterion, judges whether the plan addresses it; flags any criterion not acknowledged by the plan (this is the relocated "plan acknowledges criteria" check) |
| Impact Scanner | `approved_plans[todo_id]` file list + repo grep | for each touched file, greps for references elsewhere; flags top-10-most-referenced files as WARNING only (never BLOCKING — impact scanning is heuristic) |

Each agent is spawned with:
- **Tools (read-only)**: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__proj_explore_codebase`
- **Timeout**: 90 seconds
- **Output schema**: same strict JSON as Phase A.5b adversarial agents (see appendix)

See the **Preflight Agents Reference** appendix for full prompt templates.

**Findings aggregation**: merge across all 3 agents into a combined table keyed by todo (same format as Phase A.5b). Apply the same severity semantics: BLOCKING triggers Fix / Continue / Stop, WARNING is shown non-blocking (acknowledge-all shortcut under `--paranoid`), INFO is shown non-blocking. Timeouts and malformed JSON demote to WARNING.

If `worktree_enabled`, the File Path Verifier checks the worktree tree (not main) for the current todo's branch.

**Phase C1.5 — Worktree setup** (if `worktree_enabled`):

**Worktree prerequisite check**:
- Call `wt_list_repos` to verify the worktree plugin is installed and at least one base repo is registered.
- If no repos registered:
  - Get current project repos from `proj_session_context`.
  - If project has 0 repos: disable worktree for this run, display "No worktree repos registered and no project repos found. Falling back to main." Continue.
  - If project has exactly 1 repo (`<path>`):
    - Display: "No worktree base registered. Add `<path>` as worktree base `<basename(path)>`? [Y/n]"
    - If yes: call `wt_add_repo(label=basename(path), path=path, default_branch="main")`.
      - If success: display "Registered `<path>` as worktree base `<basename(path)>`. Continuing." Proceed with worktree setup as normal.
      - If failure: display error, disable worktree, fall back to main.
    - If no: disable worktree, display "Falling back to main." Continue.
  - If project has 2+ repos:
    - Display: "No worktree base registered. Select repo(s) to register as worktree base:"
      ```
      1. <label>: <path>
      2. <label>: <path>
      (enter numbers comma-separated, or 0 to skip)
      ```
    - For each selected repo: call `wt_add_repo(label=basename(path), path=path, default_branch="main")`.
      - Report success/failure per repo.
      - On any success: proceed with worktree setup as normal.
      - If all fail or none selected: disable worktree, fall back to main.
  - If `--no-interactive`: if exactly 1 project repo, auto-register silently and display notice; if 0 or 2+ repos, disable worktree with warning "No worktree repos registered. Falling back to main."

Check `git status --porcelain` on main. If dirty (uncommitted changes):
  Prompt: (1) Stash changes (2) Commit changes (3) Abort worktree setup
  Stash: run `git stash push -m "pre-worktree-{timestamp}"`, proceed.
  Commit: prompt for message, commit, proceed.
  Abort: disable worktree for this run, fall back to main.
  If `--no-interactive`: auto-stash.

For each todo in current batch:
1. Call `wt_create` with repo_label and branch name `todo-{id}`.
   If fails: fall back to main for this todo, display warning. Continue with remaining todos.
2. Call `wt_lock` on the created worktree.
3. Call `sandbox_add_write_path` to add the worktree path to sandbox write allowlist.
4. Store `worktree_path` and `worktree_branch` for this todo.

With pipeline: setup runs per-todo immediately after plan approval (before spawning execution agent).
Without pipeline: setup runs for all todos in batch before Phase C2 begins.

**Phase C2 — Execute:**

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 2+ non-manual todos: use **Team mode** below.
- Otherwise: use **Task agent mode** below.

**Resume checkpoint** (applies when `--resume` is passed):
1. Look for the most recent checkpoint file in `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. If found and not stale (created within the last 24 hours):
   - Read the checkpoint. Display: `Resuming from batch {batch_index}/{total_batches} — {len(completed_todos)} todos already completed`.
   - Use the stored `approved_plans` from the checkpoint.
   - Skip to the `batch_index` in Phase C2 (all prior batches are treated as complete).
3. If the checkpoint is stale (older than 24 hours) or references todos that no longer exist:
   - Display: `Checkpoint is stale (created {timestamp}). Restart from the beginning? (1) Restart (2) Use anyway`.
   - If Restart: ignore checkpoint and start from Phase C1.
   - If Use anyway: proceed with the stale checkpoint data.
4. If no checkpoint found: display `No checkpoint found — starting fresh` and proceed normally.

**Team mode:**

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

1. `TeamCreate(name="run-exec-{project}-{timestamp}", description="Run: executing todos {id1}, {id2}, ... in {N} batches")`
1a. **Task Mapping** (one-way — tasks mirror todos for coordination only):
   For each todo across all batches:
   - Call `TaskCreate` with:
     - `title`: todo title
     - `description`: `"Implement todo {id} — {title}"`
     - `metadata`: `{"proj_todo_id": "{todo.id}", "team_name": "{team_name}"}`
   - If the todo has `blocked_by` relationships with other todos in the same execution set, use `addBlockedBy` to map the blocking relationships (using the Task IDs returned from previous `TaskCreate` calls).

   Agents discover their assigned tasks via `TaskList(metadata={"team_name": team_name})` (pull model — agents are not assigned tasks directly).

   **One-way only**: Task completion does NOT auto-complete the proj todo. The satisfaction loop handles proj todo completion.

2. For each batch in dependency order (excluding `manual_skipped_ids`):
   - Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
   - Spawn one Agent per todo in this batch with `team_name`. Each agent receives: the approved plan (or context only if trust 3, or execute instructions if `--no-interactive`) + requirements.md + research.md + parent context. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content.
   - If `worktree_enabled` and todo has `worktree_path`:
     Include in agent context: `worktree_path: <path>`, `worktree_branch: <branch>`.
     Instruction: "Execute all file operations in the worktree directory at `<worktree_path>`. Prefix all git commit messages with `[todo-{id}]` when working in the worktree."
   - Agents execute the approved plan as-is. They do NOT call `todo_complete`. If they hit an issue not covered by the plan, they report via `SendMessage` to the team lead rather than improvising.
   - Wait for this batch to complete before starting the next batch. Report failures.
   - **Write checkpoint** after each batch to `<tracking_dir>/<project>/.team-state/<team-name>/checkpoint.yaml`:
     ```yaml
     team_name: run-exec-{project}-{timestamp}
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
3. After all batches complete: `TeamDelete(team_name)`
4. If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml` (create the directory if needed).

**Task agent mode (fallback):**

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

For each batch in dependency order (excluding `manual_skipped_ids`):
- Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
- Spawn one `general-purpose` Task agent per todo with approved plan (or context only if trust 3, or execute instructions if `--no-interactive`). Each receives: todo details, requirements.md, research.md, parent context. Agents do NOT call `todo_complete`.
  If `worktree_enabled` and todo has `worktree_path`:
    Include in agent context: `worktree_path: <path>`, `worktree_branch: <branch>`.
    Instruction: "Execute all file operations in the worktree directory at `<worktree_path>`. Prefix all git commit messages with `[todo-{id}]` when working in the worktree."
- Wait for completion. Report failures.

Check `git status --porcelain` on main. If dirty: display warning "Main has uncommitted changes after worktree execution. This may cause merge conflicts."

**Phase C2.5 — Merge worktree branches** (if `worktree_enabled`):

Initialize `files_merged_this_batch = set()` and `reexecution_queue = []`.

For each completed todo in batch order:
  Create pre-merge backup: `git tag pre-merge-{todo_id}`.

  For each completed todo's worktree:
    Call `wt_auto_commit(worktree_path=<path>, message="[todo-{id}] Auto-commit agent work")`
    If committed: display "Auto-committed {N} files in worktree for todo {id}"
    If error: log warning, proceed to merge attempt

  Run `git merge --no-ff todo-{id}` and apply the **3-tier resolution cascade** (see Phase 2.5 for the full definition — the batch cascade is identical):

  ### Tier 1 — Clean merge
  Exit 0. Add modified files to `files_merged_this_batch`, `notes_append("Merge tier 1 (clean): todo-{id} — {N} files")`, `wt_remove`, `git branch -d todo-{id}`.

  ### Tier 2 — Expanded auto-resolve
  Eligibility: ≤5 conflicting files, all hunks <50 lines, no critical-path files. Decision rule: file NOT in `files_merged_this_batch` → theirs; file IN → ours. Stage, commit, `notes_append("Merge tier 2 (auto-resolve): todo-{id} — {N} files, strategy=[theirs×K, ours×M]")`.

  ### Tier 3 — Ask user
  **IF `--no-interactive`**: abort, revert to `pre-merge-{todo_id}`, enqueue, `notes_append("Merge tier 3 (aborted, non-interactive): todo-{id} — queued for re-execution")`.
  **ELSE**: display conflict summary, prompt (1) Manual resolve (2) Abort, `notes_append("Merge tier 3 (user): todo-{id} — choice={manual|abort}")`.

  > `-X theirs` and `git rerere` Tier-3 strategies are intentionally NOT used. See Phase 2.5 note for rationale.

  **Post-merge test** (after each merge):
    Run test suite (`uv run pytest --tb=short -q` or `npm test`).
    If tests fail:
    - If only 1 merge completed so far: revert that merge, re-execute todo on main.
    - If multiple merges: use `git bisect` on merge commits to identify the breaking merge. Offer: (1) Revert breaking merge (2) Fix manually (3) Continue anyway.

**Serialized re-execution queue** (after all batch merges):
  If `reexecution_queue` is non-empty:
    Display: "N todos need re-execution on main (merge conflicts aborted)."
    For each queued todo: re-execute sequentially on main (no worktree, `--no-pipeline --balanced`).

**Phase C2.6 — Post-merge verification** (after all cascades and re-execution drain, before Phase C2a):

1. **Final full-suite test run** — run project test suite **without** `-q`. On failure: surface full output, `notes_append("Post-merge verification FAILED: {N} tests")`, offer (1) Spawn fix agents (2) Proceed anyway (3) Abort batch.
2. **Diff-vs-plan review agent** — spawn a read-only `general-purpose` Task agent (60s timeout) to compare `git diff {merge_base}..HEAD` against each todo's approved plan. Reports per-todo mismatches as `WARNING` only; does NOT block or modify files. Feeds a **Drift** column into the combined verification summary.
3. **Resource safeguards** (pre-batch, gate before Phase C1.5): disk (≥300 MB × max_parallel), FDs (≥256 × max_parallel), context budget. Any shortfall caps `max_parallel` downward with a `notes_append("Pre-batch cap: max_parallel {old}→{new} due to {reason}")` line.

**Phase C2a — Verification** (skip entirely if `--no-verify` was passed):

For each completed todo across all batches (excluding `manual_skipped_ids` and failed agents), run the verification checks from execute step 4a:
- **A. Automated checks** (detect test runner, run tests/lint)
- **B. Spec validation** (check acceptance criteria against git diff)
- **C. Diff review** (compare approved plan files vs actual changes)

Verify ALL todos first, then display a combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| <id> | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| <id> | FAIL (2 failed) | 2/3 met | 1 extra file | FAIL |
```

Persist each todo's report to `todos/<id>/verification-report.md` in the tracking dir (with timestamp, overwrite previous).

If any todo has failures, prompt:
> N passed, M failed. Fix failed todos? (1) Fix (2) Proceed (3) Skip
- **Fix**: spawn one `general-purpose` Task agent per failed todo with: (1) the verification report, (2) todo details + requirements.md + research.md + parent context (via `proj_get_todo_context`), (3) the approved implementation plan, and (4) instructions to fix the failures. After agents complete, re-run verification on fixed todos only (max 2 retries). Update the combined report and re-prompt if still failing.
- **Proceed**: continue to summary despite failures.
- **Skip**: skip remaining verification for this session.

If all checks pass, display the report and proceed without prompting.

**Satisfaction check** (sequential, main conversation):

Satisfaction mode is determined by `quality_level.satisfaction`:
- IF satisfaction == "per-batch": After all todos in batch complete, display summary table, prompt "Satisfied with this batch?" once for the entire batch.
- IF satisfaction == "per-todo": Run individual satisfaction loop per todo (default behavior below).
- IF satisfaction == "skip": Auto-complete all todos without prompting (call `mcp__proj__todo_complete` on each).
- IF satisfaction == "per-todo + re-verify": Run individual satisfaction per todo, then re-run verification after any fixes.

For per-todo and per-todo + re-verify modes, for each completed todo (excluding `manual_skipped_ids`), run the satisfaction loop:
   a. Ask: "Are you satisfied with the outcome of todo <id>, or is there anything else that needs to be done?"
      1. **Satisfied** — mark done: call `mcp__proj__todo_complete`
      2. **Not satisfied** — fix in scope: ask what's missing. Call `mcp__proj__proj_decision_log` with `action="add"`, `decision=<feedback text>`, `context="run:satisfaction:<todo_id>"`, `tags="correction,quality"`, `todo_id=<todo_id>`. Then fix, re-ask
      3. **Redefine** — refine requirements and re-run workflow

   When spawning a satisfaction-driven recursive run: enforce `--no-pipeline --balanced --no-worktree`. Maximum recursion depth: 2. Pass `--_recursion_depth N` internally (not user-facing). If depth >= 2: refuse to recurse, display "Maximum satisfaction recursion depth reached. Fix manually."

IF quality_level == fast:
  After execution completes: display post-run summary with `git diff HEAD~N` command.

Clear `executing_agents = {}` before proceeding to the next batch.

**Phase C5 — Worktree cleanup** (if `worktree_enabled`, always runs even on failure):

For each worktree created during this execution:
1. Call `wt_unlock` on the worktree.
2. Call `wt_remove` to delete the worktree.
3. Call `sandbox_reconcile` to remove sandbox entries for deleted worktree paths.
4. Call `wt_prune` to clean any stale worktree admin entries.
Display: "Cleaned up N worktrees."

**d.** Summary

Display per-batch breakdown and overall count. Call `mcp__proj__notes_append`.

**e.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Run: {todo-id}"`.

## Prerequisites

- An active project must be loaded.
- A valid todo ID, range, or comma list must be provided.

## Error Handling

- **No todo ID**: displays `Todo ID required.` with usage and stops.
- **Todo not found**: displays error from `todo_get` and stops.
- **Invalid step name**: displays error and stops.
- **Manual-tagged todo**: skips with warning `Todo <id> [manual] — skipped`.
- **Quality gate failure (define phase)**: presents low-confidence definitions and offers Continue/Re-define/Stop.
- **Verification failures (execute phase)**: presents combined report with Fix/Proceed/Skip options.
- **Agent failures (team/task mode)**: reports failed agents. Logged to `failed-teams.yaml`.
- **Stale checkpoint (--resume)**: asks user whether to restart or use stale data.

## Output

- **Single-ID**: Workflow progress through each step (define, decompose, execute), convergence assessments between iterations, verification report, satisfaction loop, completion confirmation.
- **Batch mode**: Per-todo define (interactive), parallel decompose, parallel execute with batched verification, satisfaction loop for each completed todo, overall summary.

Suggested next: `1. /proj:status` -- see updated project overview

---

## Preflight Agents Reference

This appendix contains the prompt templates and output schemas for all 6 preflight review agents referenced by Phase A.5b (define-phase adversarial review) and Phase C0.5b (pre-execute adversarial review). All agents are spawned via the `Task` tool as `general-purpose` agents with read-only sub-tools, 90-second timeouts, and a strict JSON output schema. Timeouts and malformed JSON output are demoted to WARNING (never BLOCKING).

### Shared output schema

All 6 agents return the same JSON envelope:

```json
{
  "agent": "<agent_name>",
  "findings": [
    {
      "severity": "BLOCKING|WARNING|INFO",
      "title": "<short description>",
      "evidence": "<direct quote, file:line reference, or path list>",
      "suggested_fix": "<optional remediation>"
    }
  ]
}
```

Agents must emit valid JSON with no preamble or postamble. If no findings, return `{"agent": "<name>", "findings": []}`.

### Phase A.5b — Define-phase agents

#### 1. Ambiguity Agent

**Tools**: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__content_get_research`

**Prompt template**:

```
You are the Ambiguity Agent for preflight review. Your job is to flag UNMEASURABLE
or HANDWAVEY language in the todo's requirements and research.

Read:
- mcp__proj__content_get_requirements(todo_id="<id>")
- mcp__proj__content_get_research(todo_id="<id>")

For each finding, check:
1. Undefined domain terms used without definition (e.g., "downstream", "upstream",
   "the system", "the pipeline" — when it's unclear which system).
2. Handwavey claims without measurable criteria (e.g., "handles load well",
   "supports scale").
3. Unmeasurable goals in the Goal or Acceptance Criteria sections.

Severity rules:
- BLOCKING: undefined term used >= 3 times, or any unmeasurable goal in
  Acceptance Criteria.
- WARNING: 1-2 uses of an undefined term, or handwavey claim in research
  Recommended Approach.
- INFO: stylistic suggestions.

Output EXACTLY this JSON shape (no preamble):
{"agent": "ambiguity", "findings": [...]}
```

#### 2. Completeness Agent

**Tools**: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_requirements`, `mcp__proj__content_get_research`

**Prompt template**:

```
You are the Completeness Agent for preflight review. Your job is to flag
MISSING elements that should be present in a well-formed requirements document.

Read:
- mcp__proj__content_get_requirements(todo_id="<id>")
- mcp__proj__content_get_research(todo_id="<id>")

For each finding, check:
1. Missing failure modes: the "Edge Cases" section omits an obvious error path
   (network failure, permission error, missing file, concurrency, timeout).
2. Missing auth/security concerns: the todo touches authentication, authorization,
   tokens, credentials, or user data without a security consideration.
3. Stated-scope vs Out-of-Scope gaps: items in the Goal are not reflected in
   Acceptance Criteria, OR items in Out of Scope contradict the Goal.

Severity rules:
- BLOCKING: missing failure mode for an error-prone area, OR security concern
  not acknowledged when auth is touched.
- WARNING: partial coverage, or gaps between Goal and Acceptance Criteria.
- INFO: nice-to-have additions.

Output EXACTLY this JSON shape (no preamble):
{"agent": "completeness", "findings": [...]}
```

#### 3. Research Validation Agent

**Tools**: `Read`, `Glob`, `Grep`, `mcp__proj__content_get_research`, `mcp__proj__proj_explore_codebase`

**Prompt template**:

```
You are the Research Validation Agent for preflight review. Your job is to verify
that research.md is grounded in the actual repo.

Read:
- mcp__proj__content_get_research(todo_id="<id>")
- For each file path mentioned in research.md, verify with Read or Glob.

For each finding, check:
1. File existence: every path referenced in research.md resolves to an existing
   file in the repo tree.
2. Option distinctness: when research lists multiple approach options, each
   differs by library/tool choice, file/module placement, or data-flow direction.
3. Realism of stated risks: risks are concrete and tied to the code, not
   generic boilerplate.

Severity rules:
- BLOCKING: a referenced file does not exist.
- WARNING: options are near-identical, or risks are generic.
- INFO: additional research directions.

Output EXACTLY this JSON shape (no preamble):
{"agent": "research_validation", "findings": [...]}
```

### Phase C0.5b — Pre-execute agents

#### 4. File Path Verifier

**Tools**: `Read`, `Glob`, `Grep`

**Prompt template**:

```
You are the File Path Verifier for pre-execute preflight. Your job is to
double-check every file path named in the approved implementation plan.

Input:
- Plan text (passed in the prompt below): <PLAN_TEXT>
- Repo root: <REPO_ROOT> (use this as the filesystem root; if worktree_enabled,
  this is the worktree tree, not main)

For each path in the plan's "Files to modify" and "Files to create" sections:
1. Use Read or Glob to verify the path.
2. For "modify" entries: file must exist.
3. For "create" entries: parent directory must exist, path must be inside the
   repo root, file must NOT already exist.
4. Detect case-sensitivity drift (e.g., plan says `Foo.py` but file is `foo.py`).
5. Detect path-normalization bugs (`./` prefix, trailing slash, absolute vs relative).

Severity rules:
- BLOCKING: "modify" path does not exist, or "create" path already exists, or
  path escapes the repo root.
- WARNING: case mismatch, or path-normalization issue.
- INFO: suggested normalization.

Output EXACTLY this JSON shape (no preamble):
{"agent": "file_path_verifier", "findings": [...]}
```

#### 5. Spec-Plan Alignment Agent

**Tools**: `Read`, `mcp__proj__content_get_requirements`

**Prompt template**:

```
You are the Spec-Plan Alignment Agent for pre-execute preflight. Your job is to
verify that the approved plan addresses every acceptance criterion.

Read:
- mcp__proj__content_get_requirements(todo_id="<id>")
- Plan text (passed in the prompt below): <PLAN_TEXT>

For each bullet in the requirements "Acceptance Criteria" section:
1. Judge whether the plan addresses this criterion (directly via a concrete step,
   or indirectly via a file/change that would satisfy it).
2. Flag any criterion that the plan does NOT acknowledge.

Severity rules:
- BLOCKING: >= 1 acceptance criterion has no corresponding plan step or file change.
- WARNING: criterion is partially addressed but lacks explicit implementation detail.
- INFO: plan exceeds requirements (unplanned scope).

Output EXACTLY this JSON shape (no preamble):
{"agent": "spec_plan_alignment", "findings": [...]}
```

#### 6. Impact Scanner

**Tools**: `Read`, `Glob`, `Grep`

**Prompt template**:

```
You are the Impact Scanner for pre-execute preflight. Your job is to flag
HIGH-IMPACT files that the plan touches (files referenced heavily elsewhere).

Input:
- Plan text: <PLAN_TEXT>
- Repo root: <REPO_ROOT>

For each file in the plan's file list:
1. Use Grep to count references to the file's module/class/function name across
   the repo.
2. Rank files by reference count. The top 10 most-referenced are "high-impact".
3. Flag any planned file that lands in the top 10.

Severity rules:
- WARNING ONLY: high-impact file touched. Never BLOCKING — impact scanning is
  heuristic, not authoritative.
- INFO: reference counts for all touched files.

Output EXACTLY this JSON shape (no preamble):
{"agent": "impact_scanner", "findings": [...]}
```

### Spawning pattern

All agents are spawned in parallel via the `Task` tool. Example for Phase A.5b:

```
# Pseudocode — run as a single tool-call block with 3 parallel Task invocations
Task(subagent_type="general-purpose", description="Ambiguity review — todo <id>",
     prompt=<ambiguity_prompt>)
Task(subagent_type="general-purpose", description="Completeness review — todo <id>",
     prompt=<completeness_prompt>)
Task(subagent_type="general-purpose", description="Research validation — todo <id>",
     prompt=<research_validation_prompt>)
```

Await all three, parse JSON, aggregate findings into the per-todo review table. Apply severity semantics (BLOCKING → prompt, WARNING → show, INFO → show). Repeat for each sampled todo in the batch.

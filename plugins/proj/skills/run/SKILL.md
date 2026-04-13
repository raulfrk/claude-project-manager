---
name: run
description: Run the full workflow (define → decompose → execute) on a todo interactively, prompting between each step. Use when asked "run 1", "full workflow on 1", or "proj:run 1".
allowed-tools: mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__proj_search_knowledge, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__tracking_git_flush, Read, Task, TaskCreate, TaskList, EnterPlanMode, ExitPlanMode, TeamCreate, TeamDelete, SendMessage, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__worktree__wt_add_repo, mcp__proj__proj_session_context, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, mcp__proj__proj_decision_log, AskUserQuestion
argument-hint: "<todo-id> [--steps define,execute] [--from <step>] [--iter N] [--no-interactive] [--no-verify] [--team] [--no-team] [--full-context] [--trust 0-3] [--resume] [--no-pipeline] [--refine] [--fast|--careful] [--force-plan] [--worktree] [--no-worktree] [--max-parallel N]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Run workflow for: $ARGUMENTS

**1.** Parse & validate

Extract from $ARGUMENTS:
- Input: single ID (`1`). Range/comma list → dispatched to `/proj:run-batch`.
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
- `--refine`: enable requirement refinement w/ review agents (default: off for `--fast`, auto-enabled for `--careful`)
- `--fast`: minimize review gates, auto-exec low-complexity todos, skip verification. Tag immunity: `security`/`breaking-change`/`migration` still get FULL REVIEW.
- `--careful`: default. Full review all plans, auto-enable refine, enhanced verification. For sequential exec, combine w/ `--max-parallel 1`.
- `--max-parallel N`: override max_parallel (e.g. `--careful --max-parallel 1` for former `--paranoid` behavior).
- Quality levels mutually exclusive (last wins, default: `--careful`).
- `--force-plan`: force FULL REVIEW on all todos despite complexity score.
- `--batch-approve`: (batch mode only — passed through to `/proj:run-batch`).
- `--worktree`: (default) enable worktree isolation for parallel exec. No-op; kept for explicitness.
- `--no-worktree`: opt out of worktree isolation — run all agents on cur branch. Use when batch is small, fully sequential, or worktree setup costs outweigh benefits.

Derive `worktree_enabled` — **default: on**:
 1. `--no-worktree` explicitly passed → off.
 2. `max_parallel == 1` → off (sequential exec makes worktree unnecessary).
 3. Else → on (despite `config.worktree_isolation`; config flag retained for legacy callers, force-off via `--no-worktree`).

Derive `quality_level` from flags. If no quality flag, call `mcp__proj__config_load` and read `config.quality_level`, defaulting to `--careful` if unset/unrecognized.

**Quality Level Parameter Mapping:**

| Parameter | --fast | --careful (default) |
|-----------|--------|---------------------|
| gate_override | auto-execute (tag-immune) | full-review |
| batch_approve | auto | disabled |
| speculative_planning | enabled | disabled |
| pattern_detection | auto-approve | disabled |
| verification_mode | skip | enhanced |
| max_parallel | 30 | 10 |
| satisfaction | skip (auto-complete) | per-todo |
| preflight | skip | enabled |
| preflight_structural | skip | enabled |
| preflight_adversarial_agents | skip | enabled |
| pre_execute_preflight | skip | enabled |
| refine | skip | auto-enabled (per iteration) |
| worktree | on (unless `--no-worktree`) | on (unless `--no-worktree` or max_parallel=1) |
| overlap_action | auto-proceed | auto-serialize |

**Former `--paranoid` behavior**: `--careful --max-parallel 1` (sequential exec, worktree auto-off).

**Recommended cap**: 10 for CPU-bound/API-rate-limited workloads (heavy test suites, rate-limited LLM calls, DB migrations). `--fast` ceiling of 30 tuned for I/O-bound work w/ isolated worktrees; override via `--max-parallel` or `config.team_mode.max_agents` when agent saturates shared resource.

Derive: `pipeline_enabled = not no_pipeline_flag`

**Flag compatibility check** (validate before proceeding):
- `--fast --force-plan` → ERROR: "Cannot combine --fast with --force-plan."
- `--fast --refine` → fast wins, refine skipped (warn).
- `--no-verify --careful` → WARNING: "--no-verify overrides --careful's enhanced verification." Verification skipped.
- `--fast --steps refine` → ERROR: "Cannot use --fast with --steps refine (fast skips refine)."
- `--careful --no-pipeline` → Allowed.
- `--fast --no-pipeline` → Redundant warn: "--fast with auto-execute makes pipeline moot."
- `--force-plan --careful` → Redundant warn: "--careful already forces full review."
- `--no-verify --fast` → Redundant: --fast already skips verification.
- `--refine --from execute` → Refine skipped (--from execute skips refine per step-order slicing).
- `--force-plan --trust 3` → ERROR: "Cannot combine --force-plan with --trust 3 (trust 3 skips planning)."
- `--max-parallel 1 --worktree` → max_parallel wins, worktree disabled (warn: "max_parallel=1 makes worktree isolation unnecessary").
- `--worktree --no-interactive` → Allowed. Auto-resolve only for merge conflicts.

No todo ID → stop: "Todo ID required. Usage: `/proj:run <id> [--steps define,execute] [--from <step>]`"

Default step order: `[define, preflight, decompose, refine, execute]`.
Apply `--steps`/`--from` to filter/slice. Error on invalid step name.

**Single ID**: `mcp__proj__todo_get` to confirm exists. If input has `:level` suffix (e.g. `1:fast`), parse error: "Cannot use `:level` annotation in single-ID mode. Use `--fast` (or appropriate quality flag) instead."
**Range/comma list** → invoke `skill: "proj:run-batch"` w/ same $ARGUMENTS.

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

Runs only when `quality_level == careful`. NEVER under `--fast`. Runs after structural checks pass, in parallel across 3 read-only agents.

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
- WARNING — shown, non-blocking, single OK. Under `--careful --max-parallel 1`, WARNINGs need explicit ack; "Acknowledge all WARNINGs" shortcut when >= 3.
- INFO — shown, non-blocking, no ack.

**Degraded mode**: agent timeouts/malformed JSON → demoted to WARNING (never BLOCKING). Raw output shown under finding.

**If `decompose`** — parallel Task agents:

Spawn via `TeamCreate` before per-batch loop: `TeamCreate(name="run-decompose-single-{timestamp}", description="Run: decomposing descendants of root todo")`. Each Task agent uses that `team_name`. After all batches → `TeamDelete`.

Each batch in dep order:
 - One `general-purpose` Task per todo w/ `team_name`. Each runs decompose autonomously.
 - Wait for batch. Report failures.
After: refresh descendant list via `mcp__proj__todo_tree`. `TeamDelete`.

**If `refine`** — after decompose, within iteration (if `quality_level == careful` AND `refine` in steps AND NOT `--no-interactive`):

fast → skip refine. careful → auto-enable despite --refine flag.

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

No children → exec parent directly.
Has children → invoke `skill: "proj:run-batch"` w/ parent + descendant IDs + same flags.

**5a. Execute (single, no children):**

fast → display: "⚡ --fast mode. Auto-executing low-complexity. Tag-immune (security/breaking-change/migration) get full review."
 **Fast-mode safety guardrails**:
 - Minimal syntax check: verify modified files parseable (Python: `py_compile`, JS: basic syntax) even in fast mode.
 - Todos completed under --fast marked `fast_mode: true` via `todo_update`.
 - External sync (Todoist/Trello) deferred until workflow completes.
 - Security-tagged todos that got FULL REVIEW under --fast also get STANDARD verification before completion.

1. `mcp__proj__todo_check_executable` — manual-tagged → warn + stop.
2. `skill: "proj:execute", args: "<id>"`.

fast → after exec: display post-run summary w/ `git diff HEAD~N`.

**6.** Complete

```
Full workflow complete for todo <id>: <title>
Steps completed: <step1>, <step2>, ...
```

`mcp__proj__notes_append` w/ brief summary.

**7.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Run: {todo-id}")`.

Suggested next: `1. /proj:status`


## Prerequisites

- Active project loaded.
- Valid todo ID. Range/comma list dispatched to `/proj:run-batch`.

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

- Workflow progress per step, convergence assessments, verification report, satisfaction loop, completion.

Suggested next: `1. /proj:status`


## Preflight Agents Reference

Agent defs in `plugins/proj/agents/`. Each agent file includes frontmatter (name, tools, model) + output schema inline. Load at runtime via `Read` when spawning.

All 6 preflight agents ref'd by Phase A.5b (define) + Phase C0.5b (pre-execute). Spawned as `general-purpose` Agents in TeamCreate group, read-only tools, 90s timeouts, strict JSON schema. Timeouts/malformed JSON → WARNING (never BLOCKING).

### Phase A.5b — Define-phase agents

#### 1. Ambiguity Reviewer
See: plugins/proj/agents/ambiguity-reviewer.md

#### 2. Completeness Reviewer
See: plugins/proj/agents/completeness-reviewer.md

#### 3. Research Validator
See: plugins/proj/agents/research-validator.md

### Phase C0.5b — Pre-execute agents

#### 4. File Path Verifier
See: plugins/proj/agents/file-path-verifier.md

#### 5. Spec-Plan Alignment
See: plugins/proj/agents/spec-plan-alignment.md

#### 6. Impact Scanner
See: plugins/proj/agents/impact-scanner.md

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


## Agent Fallback

If `subagent_type="<name>"` not found (agent .md file missing/renamed):
1. Log warning via `notes_append`: "Agent definition '<name>' not found, falling back to general-purpose"
2. Use `Agent(subagent_type="general-purpose", prompt=<inline_fallback>)` w/ minimal role desc
3. Fallback prompts (one-line per agent):
   - `ambiguity-reviewer`: "Review requirements.md + research.md for undefined terms, handwavey claims, unmeasurable goals. Return JSON {agent, findings}."
   - `completeness-reviewer`: "Review requirements.md + research.md for missing failure modes, auth/security gaps, scope holes. Return JSON {agent, findings}."
   - `research-validator`: "Validate research.md file refs exist, option distinctness, risk realism. Return JSON {agent, findings}."
   - `file-path-verifier`: "Verify all file paths in plan resolve to existing files. Return JSON {agent, findings}."
   - `spec-plan-alignment`: "Compare plan against requirements.md acceptance criteria. Flag unaddressed criteria. Return JSON {agent, findings}."
   - `impact-scanner`: "Scan codebase for callers/consumers of files in plan. Flag potential breakage. Return JSON {agent, findings}."


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

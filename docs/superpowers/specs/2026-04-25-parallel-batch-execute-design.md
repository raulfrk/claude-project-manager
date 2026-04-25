# Parallel Batch Execute — Design Spec

**Date**: 2026-04-25
**Todo**: 736 — "Investigate how to ensure superpowers parallel-orchestration approach matches one-todo-at-a-time quality"
**Author**: brainstorming session (Raul + Claude Opus 4.7)
**Status**: design approved; awaiting user spec review → writing-plans

---

## Problem statement

Single-todo and sequential-multi-todo execution under the standard superpowers workflow (brainstorming → writing-plans → subagent-driven-development → finishing-a-development-branch) work well. Quality is high; user-in-the-loop interactions, reviewer chains, and end-to-end smoke fall out of the workflow naturally.

Parallel execution (cpm `parallel-impl-orchestration` recipe — concurrent worktrees + parallel implementers) trades several gates for speed. The 2026-04-25 retro on the D+E + Batch A clusters confirmed that parallel orchestration **scales within-layer quality** (test rigor, style, spec fidelity per artifact) but **degrades on cross-layer integration checks** — boundary issues at the seam between MCP-tool / SKILL-orchestrator / dispatched-agent layers slip through. Two concrete misses:

1. `/wiki:lint` SKILL `allowed-tools` lacked `Glob`/`Bash` for runtime path discovery → orchestrator silently failed at runtime.
2. `check_section_map_drift` Python helper drifted from the parallel subagent prose impl with no sync contract — two implementations of the same logic, no reviewer compared them.

Both are exactly the class of issue a single-implementer's natural end-to-end smoke catches for free.

## Goal

Make parallel execution preserve **every gate** of the standard superpowers workflow. Parallelism applies only where (a) no user-in-the-loop interaction is needed and (b) state is genuinely disjoint. The deliverable is **a generic method** — language/framework-agnostic, project-agnostic for the execution layer, cpm-bound only for orchestration mechanics (worktree plugin, proj plugin).

**Core constraint**: superpowers skills are the building blocks. The new skill **calls** them — never replaces them.

## Non-goals

- Brainstorm/plan parallelism. Phase 1 is strictly sequential per-todo.
- Cross-batch deduplication.
- Auto-revert on CI failure.
- Generalization beyond cpm (revisit after 2-3 successful batches).
- Replacing `superpowers:subagent-driven-development`. We wrap it per worker; never reimplement per-task flow.
- Resolving 737 (Python vs prose tier-2 lint architecture). 736 is detection axis only.
- Resolving 735 (worktree-rebase-artifact root cause). Skill references the workaround; root-cause fix is 735's job.

## Architecture

Single cpm SKILL `proj:parallel-batch-execute`. One entry point. Drives a 5-phase parallel-aware execution of the standard superpowers workflow.

| Phase | Parallelism | Superpowers skills invoked |
|---|---|---|
| 1. Per-todo design | sequential | `superpowers:brainstorming` × N → `superpowers:writing-plans` × N |
| 2. Worktree setup | parallel | `superpowers:using-git-worktrees` × N + post-wt-create-remote-sync |
| 3. Parallel execution | **parallel** | `superpowers:subagent-driven-development` × N (one per worktree); each implementer applies `superpowers:test-driven-development`, `superpowers:verification-before-completion`; reviewer chains use `superpowers:requesting-code-review` / `superpowers:code-reviewer` / `superpowers:receiving-code-review` |
| 4. Integration gates | sequential | `superpowers:requesting-code-review` (whole-batch); new e2e smoke role (no upstream equivalent) |
| 5. Merge + finish | sequential | `superpowers:finishing-a-development-branch` (batch-level) |

**Threshold**: invoke when N ≥ 2 disjoint todos. Below threshold, use standard sequential superpowers workflow.

**State surface**: orchestrator maintains in-session state via `TaskCreate` hierarchy (one parent task per phase, subtasks per todo). Persistent state via proj todos. No new YAML files.

## Phase 1 — Per-todo design (sequential, fully interactive)

Strictly per-todo. No shortcuts. No batch-brainstorm escape hatch (dropped as a non-goal — full brainstorm per todo is the locked decision).

```
for each todo in batch:
  1. invoke superpowers:brainstorming
       → interactive Q&A with user → design sections → user approval
       → produces docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
       → spec self-review + revdiff-routed user review (per managed rule 12)
  2. invoke superpowers:writing-plans
       → produces docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md
       → user approval before continuing
```

**Why sequential**: brainstorming is fundamentally interactive Q&A; cannot parallelize without losing user attention quality. writing-plans is mostly automated but its output gets user review — also a serial gate.

**Failure modes**: if user kills the brainstorm for any todo (e.g. "not now"), that todo drops from the batch. Skill continues with remaining N-1.

**Outputs**: N spec docs + N plan docs in `docs/superpowers/`. All committed before Phase 2 starts.

## Phase 2 — Worktree setup (parallel, no user)

```
1. wt_create × N (parallel via mcp__plugin_worktree_worktree__wt_create)
   - one branch per todo, forked from current dev
2. post-wt-create-remote-sync per worktree (parallel; single Bash loop)
   - per managed rule 13
```

That's it. Environment setup (deps, lockfiles, language-specific tooling) is the implementer's responsibility in Phase 3. Orchestrator stays project-agnostic.

**Abort-on-failure**: if any wt_create fails, abort batch, leave Phase 1 artifacts intact, surface failed todo to user.

## Phase 3 — Parallel execution (parallel impl + reviewers per worktree)

Each implementer's per-task flow IS `superpowers:subagent-driven-development`. Orchestrator parallelizes across worktrees + routes implementer questions.

### 3.1 Implementer dispatch

**Note on superpowers:subagent-driven-development "no parallel implementers" red flag**: that rule applies to **shared-state** conflicts. With per-todo isolated worktrees (Phase 2) + verified disjoint file lists (Phase 1 design contract), parallel implementers cannot interfere. CLAUDE.md rule 1 (parallel `Agent()` calls + `run_in_background=true`) supersedes the skill default per skill priority order. The wiki [[parallel-impl-orchestration]] recipe documents the same override. The skill invokes the **per-task flow** of `subagent-driven-development` (implementer → spec compliance reviewer → code quality reviewer → re-review loop → DONE) per worker — that flow itself is unchanged.

```
N × Agent(...) calls in single message, run_in_background=true
  - model: sonnet (orchestrator may upgrade per-todo to opus on user request)
  - prompt: full per-todo plan inline (NEVER make subagent read plan file
    — per superpowers:subagent-driven-development red flag)
  - "ALL file edits and git ops MUST happen in worktree path: <path>"
    (per managed rule 6 — Agent isolation:worktree does NOT work)
  - implementer applies superpowers:test-driven-development inside its task
  - implementer treats superpowers:verification-before-completion as gate
    before reporting DONE
```

Implementer reports one of: `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`. Status handling mirrors superpowers:subagent-driven-development exactly.

### 3.2 Q-routing — match superpowers behavior

**Locked decision**: orchestrator Claude answers implementer questions from its own context (spec, plan, conversation). Only escalates to human user when orchestrator itself doesn't know. This matches single-todo `superpowers:subagent-driven-development` behavior.

```
on implementer Q:
  implementer pauses (waits for orchestrator response)
  orchestrator attempts to answer from spec/plan/conversation context
    - if confident answer available: reply directly, implementer unblocks
    - if ambiguous OR contradicts user-stated preferences:
        collect Q into pending buffer
        flush trigger: buffer hits 4 OR all active implementers blocked
                       OR 30s elapsed since first pending Q
        flush: single AskUserQuestion call (max 4 Qs per managed rule 4)
        relay user answers back to each blocked implementer
```

Implementers never proceed past a Q without an answer. Same invariant as sequential.

### 3.3 Per-implementer reviewer chain

When an implementer reports DONE:

```
1. invoke superpowers:requesting-code-review (spec compliance, haiku)
   → if ❌ → re-dispatch implementer with findings
   → if ✅ → continue
2. invoke superpowers:requesting-code-review (code quality, opus)
   → if ❌ → re-dispatch implementer with findings
   → if ✅ → mark this worker REVIEW_PASSED
```

Reviewer chains for different workers run concurrently — each operates on a different worktree, no shared state. Re-review loops are per-worker.

### 3.4 Phase 3 exit condition

All N workers reach REVIEW_PASSED. Orchestrator records git SHAs per branch + transitions to Phase 4. REVIEW_PASSED workers wait for slowest worker (no useful work to dispatch in the meantime).

If any worker is permanently BLOCKED → AskUserQuestion: continue with N-1 / abort batch / let user investigate.

## Phase 4 — Pre-merge integration gates (sequential, codified)

**Goal**: catch the cross-layer boundary issues per-worker reviewers miss. Run after all N workers REVIEW_PASSED, before any merge to dev.

### 4a. Final whole-impl reviewer

```
dispatch one reviewer subagent (opus model)
  - input: ALL N branches' diffs concatenated against current dev
  - role: superpowers:requesting-code-review semantics, but cross-batch
  - explicit checks:
    * shared types / config keys touched by 2+ todos → consistent?
    * dual-impls (Python helper + subagent prose, two scripts implementing
      same algo) → sync contract present?
    * SKILL.md frontmatter changes (allowed-tools, context, agent) →
      reviewed against sibling SKILLs in same plugin?
    * cross-cutting user-facing flows touched by 2+ todos →
      end-to-end consistency?
  - output: APPROVE / FINDINGS list per worker affected
```

Re-review loop on findings: orchestrator routes each finding back to the relevant worker's implementer (same subagent that did the work, per `superpowers:receiving-code-review`). Implementer fixes → final reviewer re-runs against updated diffs. Loop until APPROVE.

### 4b. End-to-end smoke

```
dispatch one smoke subagent (sonnet — cheaper, mechanical)
  - input: list of features touched across the batch
    (orchestrator extracts from per-todo plans)
  - role: exercise integrated feature against a real fixture
    - prefer sandboxed fixture (tmpdir-based, synthetic, isolated from user state)
    - fall back to live ~/.claude/ ONLY when explicitly safe
      (e.g. read-only feature, no state mutation)
  - explicit check: invoke each touched SKILL/MCP tool/script end-to-end at least once
    catches: allowed-tools gaps, missing dispatcher wiring,
             runtime tool-permission chain breaks
  - output: SMOKE_OK / SMOKE_FAILED <details> / NO_SMOKE_AVAILABLE
```

On SMOKE_FAILED → route finding to relevant worker's implementer → re-smoke. Loop until SMOKE_OK or NO_SMOKE_AVAILABLE.

NO_SMOKE_AVAILABLE is **not** a blocker — it's a flag. Skill surfaces via AskUserQuestion: "Smoke fixture missing for [features]. Proceed anyway / add fixtures first / abort?"

### 4c. Cross-todo integration sweep

**Collapsed into 4a** — already covered by "shared types/config keys" + "cross-cutting user-facing flows" checks in the final reviewer prompt. Avoids redundancy.

### Phase 4 exit condition

4a APPROVE + 4b SMOKE_OK (or NO_SMOKE_AVAILABLE acknowledged by user). All implementer branches contain integrated fixes. Transition to Phase 5.

## Phase 5 — Merge + finish (sequential)

Largely preserves the current cpm parallel-impl-orchestration recipe.

```
1. Sequential rebase + FF-merge (per [[worktree-merge-uses-rebase]])
   - First branch: FF-merge directly to dev
   - Each subsequent branch: rebase onto current dev → FF-merge
   - Per-todo file lists are disjoint (verified at design time) → conflict-free in practice
   - On rebase artifact: git restore . → retry rebase

2. Single git push origin dev (per [[ff-merge-convention]])
   - One CI run for the batch

3. invoke superpowers:finishing-a-development-branch (batch-level)
   - Operates on merged dev branch — verifies CI green, cleans up
   - This is the explicit gate the current wiki recipe MISSES — restored.

4. Cleanup parallel
   - wt_remove × N (parallel, force=true if needed per [[worktree-rebase-artifact]])
   - git branch -d × N after verifying merged
   - mcp__plugin_proj_proj__todo_complete(todo_ids=[<id-1>, ..., <id-N>]) — single batch call
     (todo_batch_complete tool was removed; todo_complete now accepts a list — see todo 738)

5. Append-only log entry per managed rule 20
   - notes_append heading: "## [YYYY-MM-DD HH:MM] checkpoint | Batch N completed: <todo-ids>"
```

**Failure modes**:
- Rebase conflict: pause, AskUserQuestion: resolve manually / abort batch / investigate
- CI fails after push: surface via AskUserQuestion; never auto-revert (managed rule 8)
- `superpowers:finishing-a-development-branch` flags issue: implementer re-dispatched per skill flow

## Validation strategy

### Field test — primary

Ship skill v1; run on next 2 parallel batches drawn from current backlog. For each batch capture:

- Did Phase 4a / 4b catch any boundary issue per-worker reviewers missed? Class of issue.
- False positives flagged by gates that turned out non-actionable. Ratio.
- Phase 1 sequential cost (wall-clock) vs. Phase 3 parallelism gain.
- Q-routing fired how many times? User satisfied with batching cadence?

**Adoption criteria** (codified):
- Phase 4a: ≥1 real boundary issue caught across 2 batches → keep. <1 → demote to opt-in.
- Phase 4b: same threshold. NO_SMOKE_AVAILABLE rate logged but not adoption criterion.
- Q-routing: if user reports >50% of escalations are "obvious context the orchestrator could have answered" → tighten escalation threshold.

### Synthetic regression test — deferred

Build a fake batch reproducing the 2026-04-25 defects (lint allowed-tools gap + dual-impl drift). Each gate proves it catches each defect class. CI-friendly. Add to skill's own test suite once skill is stable. **Not blocking v1 ship.**

## Risks

| Risk | Mitigation |
|---|---|
| Phase 1 wall-clock cost dominates parallelism gain for medium batches (N=3-5) | Field test will show. Future iteration may add opt-in batch-brainstorm if cost intolerable. |
| Phase 4b smoke fixture coverage low in cpm (most features lack synthetic fixtures) | Skill surfaces NO_SMOKE_AVAILABLE clearly; user adds fixtures incrementally. |
| Q-routing user fatigue (orchestrator escalates too aggressively) | Match superpowers default (parent-absorbs from context, escalate-ambiguity). If field test shows >50% of escalations are "obvious context the orchestrator could have answered," tighten escalation threshold via skill-side rubric updates — not by changing the default model. |
| Skill drift from upstream superpowers | Cross-ref managed CLAUDE.md + wiki recipe; revisit on superpowers version bump. |
| Threshold N≥2 too eager when todos are tiny | Skill prompts at start: "N=2; sure?" with fallback to sequential. |

## Skill structure

```
plugins/proj/skills/parallel-batch-execute/
  SKILL.md                           # caveman ultra; orchestrator prose + phase walkthrough
  references/
    final-reviewer-prompt.md         # Phase 4a reviewer prompt template
    smoke-prompt.md                  # Phase 4b smoke prompt template
    implementer-q-routing.md         # Q-buffer flush trigger semantics + escalation rubric
```

Skill SKILL.md uses the cpm caveman-ultra convention (per CLAUDE.md project rule). Output directive after frontmatter:
`> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.`

## Wiki + managed CLAUDE.md updates

**Wiki**: update existing `parallel-impl-orchestration` page. Becomes canonical human-readable doc; refs the skill for execution. Add cross-refs to `parallel-orchestration-boundary-issues` page (the diagnosis) and the new skill (the fix).

**Managed CLAUDE.md**: add one bullet (estimated location: after rule 25, the research-synthesis bullet):

> **Parallel batch execution** — When implementing ≥2 todos with disjoint file scopes, prefer `proj:parallel-batch-execute`. Skill orchestrates standard superpowers workflow (brainstorming → writing-plans → subagent-driven-development → finishing-a-development-branch) with parallelism only in the execution stage. Below threshold (N=1 or coupled work), use standard sequential superpowers flow. *Source: 2026-04-25 boundary-issue retro on parallel-impl-orchestration recipe.*

## Open questions (deferred — non-blocking for plan)

1. Phase 4b smoke — how to detect "feature is read-only safe to run against live ~/.claude/" vs. "must use sandboxed fixture"? Heuristic vs. annotation in plan? Default sandbox; user opts in to live.
2. Phase 1 escape hatch (batch-brainstorm covering N todos in one session) — currently dropped. Revisit only if field test shows Phase 1 cost dominates.
3. Generalization to non-cpm projects — revisit after 2-3 successful batches with cpm-internal usage.

## Cross-references

- Wiki: [[parallel-impl-orchestration]] (current recipe, will be updated)
- Wiki: [[parallel-orchestration-boundary-issues]] (the diagnosis this spec resolves)
- Wiki: [[worktree-rebase-artifact]], [[parallel-git-races]], [[stale-worktree-vs-advancing-dev]] (sibling pitfalls referenced in Phase 5)
- Todo 736 (this spec's parent): notes section lists 5 hypothesis-tests; this spec adopts 4 of them (drops self-test as overlapping with cross-batch reviewer)
- Todo 735: worktree rebase artifact root-cause investigation (separate)
- Todo 737: wiki tier-2 lint architecture (separate; resolution axis vs detection axis)
- Commit 14f90dd: process-level mitigation that motivated this spec
- Superpowers skills: `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:subagent-driven-development`, `superpowers:test-driven-development`, `superpowers:verification-before-completion`, `superpowers:requesting-code-review`, `superpowers:receiving-code-review`, `superpowers:code-reviewer`, `superpowers:using-git-worktrees`, `superpowers:finishing-a-development-branch`
- Managed CLAUDE.md rules invoked: 1 (parallel agents), 2 (plan mode), 3 (auto-capture), 4 (batched Q&A), 6 (worktree isolation), 8 (destructive ops consent), 12 (revdiff review), 13 (post-wt-create-remote-sync), 20 (append-only log), and the new bullet to be added

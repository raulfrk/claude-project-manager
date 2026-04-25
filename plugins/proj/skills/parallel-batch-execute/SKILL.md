---
name: parallel-batch-execute
description: Orchestrate parallel impl of >=2 disjoint todos w/ full superpowers gate fidelity. Use when user requests parallel batch impl OR says "parallel batch", "/proj:parallel-batch-execute", "execute these N todos in parallel". Wraps standard superpowers workflow (brainstorming -> writing-plans -> subagent-driven-development -> finishing-a-development-branch); parallelism only in execution stage.
allowed-tools: mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__todo_get, mcp__plugin_proj_proj__todo_complete, mcp__plugin_proj_proj__notes_append, mcp__plugin_worktree_worktree__wt_create, mcp__plugin_worktree_worktree__wt_remove, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent, Bash, Skill, Read, Edit
argument-hint: "<todo-id> <todo-id> [<todo-id>...]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Orchestrate parallel impl of >=2 disjoint todos. Wrap superpowers workflow; parallelize Phase 3 only.

**Threshold**: N >= 2 disjoint todos. N=1 OR coupled work -> standard sequential superpowers flow.

## Phases

### Phase 0 — Setup

1. `mcp__plugin_proj_proj__proj_session_context` -> active proj name + tracking_dir.
2. Parse `$ARGUMENTS` -> N todo IDs. N < 2 -> err: "use sequential superpowers workflow".
3. Each todo: `mcp__plugin_proj_proj__todo_get` -> verify exists + open. Missing/done -> err.
4. Disjointness intent gate: prompt user via `AskUserQuestion` to confirm batch is intended as parallel disjoint todos (vs coupled). Coupled intent -> abort. Concrete file-overlap check happens at Phase 2 entry (after plans exist).
5. `TaskCreate` 1 parent task per phase + subtasks per todo for Phases 1+3.

### Phase 1 — Per-todo design (sequential, fully interactive)

Strict per-todo. No batch-brainstorm shortcut.

```
for each todo in batch:
  1. invoke `superpowers:brainstorming` w/ todo context
       -> docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
       -> spec self-review + revdiff-routed user review (per managed rule 12)
  2. invoke `superpowers:writing-plans` w/ spec
       -> docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md
       -> user approval gate
  3. user kills brainstorm/plan -> drop todo from batch; continue w/ N-1
```

Outputs: N spec docs + N plan docs committed before Phase 2.

### Phase 2 — Worktree setup (parallel)

```
0. File-overlap entry gate: orchestrator extracts "Files:" table / files-touched lists from each Phase 1 plan. Computes pairwise overlap across all N plans. Any overlap -> AskUserQuestion: abort batch / let user split or reorder / continue anyway (override).
1. wt_create x N parallel via mcp__plugin_worktree_worktree__wt_create
   - one branch per todo, forked from current dev
2. post-wt-create-remote-sync per worktree (parallel; single Bash loop)
   - per managed rule 13 (git fetch origin + reset based on local-ahead check)
3. wt_create fails -> abort batch; leave Phase 1 artifacts intact; surface failed todo
```

No language/framework setup (deps, lockfiles) -> implementer handles in Phase 3. Skill stays project-agnostic.

### Phase 3 — Parallel execution

Each impl applies `superpowers:subagent-driven-development` per-task flow. Orchestrator parallelizes across worktrees.

**Override note**: subagent-driven-development "no parallel impl" red flag applies to shared-state conflicts. Per-todo isolated worktrees + verified disjoint files -> safe (per CLAUDE.md rule 1; per [[parallel-impl-orchestration]] wiki recipe).

#### 3.1 Implementer dispatch

```
N x Agent(...) calls in single message, run_in_background=true
  - model: sonnet (orchestrator may upgrade per-todo to opus on user request)
  - prompt: full per-todo plan inline (NEVER make subagent read plan file
    — per superpowers:subagent-driven-development red flag)
  - "ALL file edits + git ops MUST happen in worktree path: <path>"
    (per managed rule 6)
  - impl applies superpowers:test-driven-development inside task
  - impl treats superpowers:verification-before-completion as DONE-gate
```

Status: `DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`. Handle per superpowers:subagent-driven-development "Handling Implementer Status" section.

#### 3.2 Q-routing — match superpowers (parent absorbs, escalate ambiguity)

Full rubric: `references/implementer-q-routing.md`. Summary:

- Impl Q -> impl pauses.
- Orchestrator answers from spec/plan/ctx if confident.
- Ambiguous OR contradicts user prefs -> queue into pending buffer.
- Flush: buffer hits 4 OR all active impls blocked OR 30s since first Q.
- Flush call: single `AskUserQuestion` (max 4 Qs per managed rule 4).
- Relay user answers back to each blocked impl.

Impls never proceed past Q without an answer.

#### 3.3 Per-impl reviewer chain (parallel across workers)

On `DONE`:

1. invoke `superpowers:requesting-code-review` (spec compliance, haiku) -> ❌ -> re-dispatch impl; ✅ -> step 2.
2. invoke `superpowers:requesting-code-review` (code quality, opus) -> ❌ -> re-dispatch impl; ✅ -> mark worker `REVIEW_PASSED`.

Reviewer chains parallel across workers (disjoint worktrees -> no shared state). Re-review loops per-worker.

#### 3.4 Phase 3 exit

All N `REVIEW_PASSED` -> record SHAs per branch -> Phase 4. `REVIEW_PASSED` workers wait for slowest. Permanent `BLOCKED` -> `AskUserQuestion`: continue N-1 / abort batch / let user investigate.

### Phase 4 — Pre-merge integration gates (sequential)

Run after all N workers `REVIEW_PASSED`, before any merge to dev. Catches cross-layer boundary issues per-worker reviewers miss.

#### 4a. Final whole-impl reviewer

Full template: `references/final-reviewer-prompt.md`. Mechanic:

```
dispatch one reviewer subagent (opus)
  - input: ALL N branches' diffs vs current dev
  - role: superpowers:requesting-code-review semantics, cross-batch
  - explicit checks (4 categories): shared types/config, dual-impls,
    SKILL.md frontmatter, cross-cutting user-facing flows
  - output: APPROVE / FINDINGS list per worker affected
```

Re-review loop on findings: route each finding -> relevant worker's impl (per `superpowers:receiving-code-review`). Loop until `APPROVE`.

#### 4b. End-to-end smoke

Full template: `references/smoke-prompt.md`. Mechanic:

```
dispatch one smoke subagent (sonnet)
  - input: features touched (orchestrator extracts from per-todo plans)
  - prefer sandboxed fixture (tmpdir-based, isolated from user state)
  - fall back to live ~/.claude/ ONLY when explicitly safe
  - check: invoke each touched SKILL/MCP tool/script end-to-end >=1x
  - output: SMOKE_OK / SMOKE_FAILED <details> / NO_SMOKE_AVAILABLE
```

`SMOKE_FAILED` -> route -> impl -> re-smoke. `NO_SMOKE_AVAILABLE` not blocker; `AskUserQuestion`: proceed / add fixtures first / abort batch.

#### 4c. Cross-todo integration sweep

Collapsed into 4a (subset of "shared types/config keys" + "cross-cutting user-facing flows" checks).

#### Phase 4 exit

4a `APPROVE` + 4b `SMOKE_OK` (or `NO_SMOKE_AVAILABLE` acknowledged by user). Transition to Phase 5.

### Phase 5 — Merge + finish (sequential)

```
1. Sequential rebase + FF-merge (per [[worktree-merge-uses-rebase]])
   - First branch: FF-merge to dev directly
   - Each subsequent: rebase onto current dev -> FF-merge
   - Disjoint files -> conflict-free in practice
   - On rebase artifact (per [[worktree-rebase-artifact]]): git restore . -> retry rebase

2. Single git push origin dev (per [[ff-merge-convention]]) — one CI run for batch

3. invoke `superpowers:finishing-a-development-branch` (batch-level)
   - operates on merged dev branch — verifies CI green, cleans up

4. Cleanup parallel:
   - wt_remove x N parallel (force=true if needed per [[worktree-rebase-artifact]])
   - git branch -d x N after verifying merged
   - mcp__plugin_proj_proj__todo_complete(todo_ids=[<id-1>, ..., <id-N>]) — single batch call

5. notes_append heading: "## [YYYY-MM-DD HH:MM] checkpoint | Batch N completed: <todo-ids>"
```

**Failure modes**:

- Rebase conflict -> `AskUserQuestion`: resolve manually / abort batch / investigate.
- CI fails post-push -> surface; never auto-revert (managed rule 8).
- `superpowers:finishing-a-development-branch` flags issue -> impl re-dispatched per skill flow.
- Partial cleanup failure (`wt_remove` / `git branch -d` / `todo_complete` for one of N) -> log per-worker err; do not block batch completion; surface to user post-Phase-5.

## Cross-refs

- Spec: `docs/superpowers/specs/2026-04-25-parallel-batch-execute-design.md`
- Wiki recipe: [[parallel-impl-orchestration]]
- Boundary issues diagnosis: [[parallel-orchestration-boundary-issues]]
- Sibling pitfalls: [[worktree-rebase-artifact]], [[parallel-git-races]], [[stale-worktree-vs-advancing-dev]]
- Reviewer prompts: `references/final-reviewer-prompt.md`, `references/smoke-prompt.md`
- Q-routing rubric: `references/implementer-q-routing.md`
- Superpowers skills invoked: `brainstorming`, `writing-plans`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review`, `finishing-a-development-branch`
- Superpowers patterns followed (not invoked directly): `using-git-worktrees` (Phase 2 calls cpm `wt_create` MCP tool + post-wt-create-remote-sync per managed rule 13)
- Superpowers agent dispatched: `code-reviewer` (used by `requesting-code-review` for per-impl + final review chains)
- Managed CLAUDE.md rules invoked: 1 (parallel agents), 4 (batched Q&A), 6 (worktree isolation), 8 (destructive ops consent), 12 (revdiff review), 13 (post-wt-create-remote-sync), 20 (append-only log)

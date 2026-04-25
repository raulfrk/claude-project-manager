# Parallel Batch Execute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the cpm SKILL `proj:parallel-batch-execute` (orchestrates the standard superpowers workflow with parallelism only in the execution stage), update the canonical wiki recipe, and add a managed-CLAUDE.md bullet pointing at the skill.

**Architecture:** Single skill at `plugins/proj/skills/parallel-batch-execute/` (SKILL.md + 3 reference prompt templates under `references/`). Skill prose follows cpm caveman-ultra convention. Wiki page `parallel-impl-orchestration` becomes the canonical human-readable description; managed-block adds one bullet for discoverability. `_shared` version bumps because managed_section.md changes.

**Tech Stack:** Markdown skill prose + reference templates only. No Python code, no new MCP tools, no new config keys. Verification is via existing pre-commit hooks (caveman lint, schema, _shared version-bump check) + manual visual review of skill prose.

**Spec:** `docs/superpowers/specs/2026-04-25-parallel-batch-execute-design.md`

---

## File Structure

| File | Responsibility | Created/modified by task |
|---|---|---|
| `plugins/proj/skills/parallel-batch-execute/SKILL.md` | Main skill prose — frontmatter + phase walkthrough | Tasks 1-7 (incremental) |
| `plugins/proj/skills/parallel-batch-execute/references/implementer-q-routing.md` | Phase 3.2 Q-routing rubric (parent absorbs, escalate ambiguity) | Task 5 |
| `plugins/proj/skills/parallel-batch-execute/references/final-reviewer-prompt.md` | Phase 4a final whole-impl reviewer prompt template | Task 6 |
| `plugins/proj/skills/parallel-batch-execute/references/smoke-prompt.md` | Phase 4b end-to-end smoke prompt template | Task 6 |
| `~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md` | Wiki canonical recipe — update to reflect new skill | Task 8 (via `mcp__plugin_wiki_wiki__wiki_page_write`) |
| `plugins/_shared/claudemd/managed_section.md` | Managed-block bullet — points at the new skill | Task 9 |
| `plugins/_shared/pyproject.toml` | Bump `claude-hook-transport` version (per project convention when `_shared` changes) | Task 9 |
| `README.md` | Skill reference list — add `proj:parallel-batch-execute` row | Task 10 |
| `docs/plugins.md` | Detailed skill reference — add entry | Task 10 |

Tasks 11+ cover pre-commit verification + branch finishing.

---

## Pre-Task Setup

Before starting any task, create an isolated worktree per project rules.

- [ ] **Step 1: Create worktree from dev**

```
mcp__plugin_worktree_worktree__wt_create(
  repo_label="cpm",
  branch="feat/736-parallel-batch-execute",
  new_branch=true
)
```

Expected: returns `worktree_path` like `/home/raul/worktrees/cpm/feat-736-parallel-batch-execute`.

- [ ] **Step 2: Sync worktree to remote per managed rule 13**

```bash
cd <worktree_path>
git fetch origin
git rev-list origin/dev..dev
# If output is empty (local dev not ahead of origin):
git reset --hard origin/dev
# Else (local dev has unpushed commits):
git reset --hard dev
```

Expected: HEAD at the most recent dev commit.

- [ ] **Step 3: Verify clean working tree**

```bash
cd <worktree_path>
git status
```

Expected: "nothing to commit, working tree clean".

---

## Task 1: Create skill directory + SKILL.md skeleton (frontmatter + caveman header)

**Files:**
- Create: `plugins/proj/skills/parallel-batch-execute/SKILL.md`

- [ ] **Step 1: Create skill directory**

```bash
cd <worktree_path>
mkdir -p plugins/proj/skills/parallel-batch-execute/references
```

- [ ] **Step 2: Write SKILL.md skeleton (frontmatter + caveman header + section anchors)**

Write to `plugins/proj/skills/parallel-batch-execute/SKILL.md`:

```markdown
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

<!-- Sections filled in subsequent tasks: Phase 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, Cross-refs -->
```

- [ ] **Step 3: Verify file exists + frontmatter parses**

```bash
test -f plugins/proj/skills/parallel-batch-execute/SKILL.md && echo OK
head -5 plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: `OK` + frontmatter starting with `---` + `name: parallel-batch-execute`.

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md
git commit -m "feat(proj/736): scaffold parallel-batch-execute skill"
```

---

## Task 2: Phase 0 — Setup section

**Files:**
- Modify: `plugins/proj/skills/parallel-batch-execute/SKILL.md`

- [ ] **Step 1: Replace the `<!-- Sections filled... -->` placeholder with the Phase 0 section + leave subsequent placeholders intact**

Use Edit tool to replace:

```
<!-- Sections filled in subsequent tasks: Phase 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, Cross-refs -->
```

with:

````
### Phase 0 — Setup

1. `mcp__plugin_proj_proj__proj_session_context` -> active proj name + tracking_dir.
2. Parse `$ARGUMENTS` -> N todo IDs. N < 2 -> err: "use sequential superpowers workflow".
3. Each todo: `mcp__plugin_proj_proj__todo_get` -> verify exists + open. Missing/done -> err.
4. Disjointness: prompt user via `AskUserQuestion` to confirm per-todo file scopes disjoint. Coupled -> abort.
5. `TaskCreate` 1 parent task per phase + subtasks per todo for Phases 1+3.

<!-- Sections to fill: Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, Cross-refs -->
````

- [ ] **Step 2: Verify section parses + structure intact**

```bash
grep -c '^### Phase' plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: `1` (only Phase 0 so far).

- [ ] **Step 3: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md
git commit -m "feat(proj/736): SKILL.md Phase 0 — setup + disjointness check"
```

---

## Task 3: Phase 1 — Per-todo design section

**Files:**
- Modify: `plugins/proj/skills/parallel-batch-execute/SKILL.md`

- [ ] **Step 1: Insert Phase 1 section before the placeholder**

Replace:

```
<!-- Sections to fill: Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, Cross-refs -->
```

with:

````
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

<!-- Sections to fill: Phase 2, Phase 3, Phase 4, Phase 5, Cross-refs -->
````

- [ ] **Step 2: Verify**

```bash
grep -c '^### Phase' plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: `2` (Phase 0 + Phase 1).

- [ ] **Step 3: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md
git commit -m "feat(proj/736): SKILL.md Phase 1 — per-todo design (sequential)"
```

---

## Task 4: Phase 2 — Worktree setup section

**Files:**
- Modify: `plugins/proj/skills/parallel-batch-execute/SKILL.md`

- [ ] **Step 1: Insert Phase 2 section before placeholder**

Replace:

```
<!-- Sections to fill: Phase 2, Phase 3, Phase 4, Phase 5, Cross-refs -->
```

with:

````
### Phase 2 — Worktree setup (parallel)

```
1. wt_create x N parallel via mcp__plugin_worktree_worktree__wt_create
   - one branch per todo, forked from current dev
2. post-wt-create-remote-sync per worktree (parallel; single Bash loop)
   - per managed rule 13 (git fetch origin + reset based on local-ahead check)
3. wt_create fails -> abort batch; leave Phase 1 artifacts intact; surface failed todo
```

No language/framework setup (deps, lockfiles) -> implementer handles in Phase 3. Skill stays project-agnostic.

<!-- Sections to fill: Phase 3, Phase 4, Phase 5, Cross-refs -->
````

- [ ] **Step 2: Verify**

```bash
grep -c '^### Phase' plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: `3`.

- [ ] **Step 3: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md
git commit -m "feat(proj/736): SKILL.md Phase 2 — worktree setup (parallel)"
```

---

## Task 5: Phase 3 — Parallel execution + Q-routing reference

**Files:**
- Modify: `plugins/proj/skills/parallel-batch-execute/SKILL.md`
- Create: `plugins/proj/skills/parallel-batch-execute/references/implementer-q-routing.md`

- [ ] **Step 1: Create `references/implementer-q-routing.md`**

Write to `plugins/proj/skills/parallel-batch-execute/references/implementer-q-routing.md`:

```markdown
# Implementer Q-Routing Rubric

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Q-routing model: parent absorbs, escalate ambiguity. Matches superpowers:subagent-driven-development behavior.

## Decision tree

Implementer Q arrives:

1. Q answerable from spec/plan/conversation ctx -> orchestrator answers; impl unblocks.
2. Q contradicts user-stated pref (e.g. user said "no abstractions"; impl asks "should I add base class") -> orchestrator answers "no" + reason; impl unblocks.
3. Genuinely ambiguous (multiple valid choices, no spec/plan signal) -> queue Q for batch flush.
4. Decision changes spec scope -> queue + flag as `scope-question` (will require user attention).

## Flush triggers (whichever first)

a) Pending buffer hits 4 Qs (AskUserQuestion max per managed rule 4).
b) All currently-active impls blocked on a Q (deadlock-avoid).
c) 30s elapsed since first Q hit pending buffer.

## Flush mechanic

Single `AskUserQuestion` call:

- Max 4 Qs per managed rule 4.
- Per-Q: rich context (which impl/todo asked, why ambiguous).
- Multi-choice when answer enumerable; "Other" for free-form.
- Relay each answer back to originating impl. Impl unblocks + continues.

## Anti-patterns

- Escalating Qs answerable from ctx (creates user fatigue).
- Allowing impl to proceed without an answer (breaks superpowers gate parity).
- Batching > 4 Qs into one ask (violates managed rule 4).
- Auto-answering ambiguous Qs from training priors (always escalate when unsure).
```

- [ ] **Step 2: Insert Phase 3 section into SKILL.md**

Replace:

```
<!-- Sections to fill: Phase 3, Phase 4, Phase 5, Cross-refs -->
```

with:

````
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

<!-- Sections to fill: Phase 4, Phase 5, Cross-refs -->
````

- [ ] **Step 3: Verify**

```bash
test -f plugins/proj/skills/parallel-batch-execute/references/implementer-q-routing.md && echo OK
grep -c '^### Phase' plugins/proj/skills/parallel-batch-execute/SKILL.md
grep -c '^#### 3' plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: `OK` + `4` Phases + `4` subsections (3.1, 3.2, 3.3, 3.4).

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md \
        plugins/proj/skills/parallel-batch-execute/references/implementer-q-routing.md
git commit -m "feat(proj/736): SKILL.md Phase 3 + Q-routing reference rubric"
```

---

## Task 6: Phase 4 — Integration gates + final-reviewer + smoke prompts

**Files:**
- Modify: `plugins/proj/skills/parallel-batch-execute/SKILL.md`
- Create: `plugins/proj/skills/parallel-batch-execute/references/final-reviewer-prompt.md`
- Create: `plugins/proj/skills/parallel-batch-execute/references/smoke-prompt.md`

- [ ] **Step 1: Create `references/final-reviewer-prompt.md`**

Write to `plugins/proj/skills/parallel-batch-execute/references/final-reviewer-prompt.md`:

```markdown
# Phase 4a — Final Whole-Impl Reviewer Prompt Template

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

## Role

Cross-batch reviewer for `proj:parallel-batch-execute`. N parallel impls each shipped per-todo branch off `dev`. Each branch passed per-impl spec + code-quality review. Job: catch boundary issues per-impl reviewers missed.

## Input (passed inline by orchestrator)

- N branch names: `<branch-1>`, `<branch-2>`, ...
- Each branch's diff vs current `dev`
- Per-todo plans (as ctx)

## Explicit checks

For each pair of branches in batch:

1. **Shared types / config keys**: any 2+ todos touch same type, config schema, key namespace? -> verify consistent (no drift, no double-define).
2. **Dual-impls**: any pair implements same logic in different forms (Python helper + subagent prose, two scripts implementing same algo)? -> verify sync contract (cross-ref comments) present.
3. **SKILL.md frontmatter**: any todo touches SKILL.md frontmatter (allowed-tools, context, agent)? -> diff against >=1 sibling SKILL.md in same plugin; flag missing tools or non-standard fields.
4. **Cross-cutting user-facing flows**: any 2+ todos touch same user-facing flow (e.g. `/proj:save`, `/wiki:lint`)? -> verify end-to-end consistency.

## Output

```
APPROVE
```

OR

```
FINDINGS:
1. [worker-id] <finding w/ file:line citation>
2. [worker-id] <finding>
...
```

Each finding tagged w/ worker-id whose branch needs fix.

## Style

- Be specific; cite `file:line`.
- Don't repeat per-impl reviewer findings (those passed).
- Surgical: flag only cross-batch / cross-layer issues.
```

- [ ] **Step 2: Create `references/smoke-prompt.md`**

Write to `plugins/proj/skills/parallel-batch-execute/references/smoke-prompt.md`:

```markdown
# Phase 4b — End-to-End Smoke Prompt Template

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

## Role

Integration smoke subagent for `proj:parallel-batch-execute`. All N branches integrated (rebased + ready to merge). Job: invoke touched features end-to-end + verify they work together.

## Input (passed inline by orchestrator)

- List of features touched across batch (each: SKILL/MCP-tool/script + entry point).
- Integrated working tree state (orchestrator has done temp merge for testing).

## Test environment

**Prefer sandboxed**: tmpdir-based, isolated from user's `~/.claude/` state. Examples:

- Wiki feature -> `WIKI_DIR=$tmpdir/wiki` env var; populate w/ minimal fixtures.
- Proj feature -> tmpdir w/ minimal `proj.yaml` + `tracking_dir`; export `PROJ_HOME=$tmpdir`.
- settings.json feature -> tmpdir w/ test settings.json; pass via env var.

**Fall back to live `~/.claude/` ONLY when**:

- Feature is read-only (no state mutation).
- Orchestrator confirms safe via explicit allow-flag.

## Smoke checks

For each touched feature:

1. Invoke entry point end-to-end (real CLI call, real MCP tool call, real SKILL invocation).
2. Verify exit code / return value matches plan expectations.
3. Verify side effects (file writes, state changes) match plan expectations.
4. Note runtime tool-permission errors (allowed-tools gaps), missing-binary errors, schema violations.

## Output

```
SMOKE_OK
```

OR

```
SMOKE_FAILED:
1. [feature] <error + steps to reproduce>
2. [feature] <error>
```

OR

```
NO_SMOKE_AVAILABLE:
features without fixtures: [list]
reason: <why no fixture is feasible>
```

## Style

- Real invocations, not mocked.
- Cite exact CLI cmd / MCP tool / SKILL call.
- Include err output verbatim.
```

- [ ] **Step 3: Insert Phase 4 section into SKILL.md**

Replace:

```
<!-- Sections to fill: Phase 4, Phase 5, Cross-refs -->
```

with:

````
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

<!-- Sections to fill: Phase 5, Cross-refs -->
````

- [ ] **Step 4: Verify**

```bash
ls plugins/proj/skills/parallel-batch-execute/references/
grep -c '^### Phase' plugins/proj/skills/parallel-batch-execute/SKILL.md
grep -c '^#### 4' plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: 3 reference files (`final-reviewer-prompt.md`, `implementer-q-routing.md`, `smoke-prompt.md`); `5` Phases; `4` subsections (4a, 4b, 4c, exit).

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md \
        plugins/proj/skills/parallel-batch-execute/references/final-reviewer-prompt.md \
        plugins/proj/skills/parallel-batch-execute/references/smoke-prompt.md
git commit -m "feat(proj/736): SKILL.md Phase 4 + final-reviewer + smoke prompts"
```

---

## Task 7: Phase 5 — Merge + finish + cross-refs section

**Files:**
- Modify: `plugins/proj/skills/parallel-batch-execute/SKILL.md`

- [ ] **Step 1: Insert Phase 5 + cross-refs sections, removing the placeholder**

Replace:

```
<!-- Sections to fill: Phase 5, Cross-refs -->
```

with:

````
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
     (todo_batch_complete was removed; todo_complete accepts a list — see todo 738)

5. notes_append heading: "## [YYYY-MM-DD HH:MM] checkpoint | Batch N completed: <todo-ids>"
```

**Failure modes**:

- Rebase conflict -> `AskUserQuestion`: resolve manually / abort batch / investigate.
- CI fails post-push -> surface; never auto-revert (managed rule 8).
- `superpowers:finishing-a-development-branch` flags issue -> impl re-dispatched per skill flow.

## Cross-refs

- Spec: `docs/superpowers/specs/2026-04-25-parallel-batch-execute-design.md`
- Wiki recipe: [[parallel-impl-orchestration]]
- Boundary issues diagnosis: [[parallel-orchestration-boundary-issues]]
- Sibling pitfalls: [[worktree-rebase-artifact]], [[parallel-git-races]], [[stale-worktree-vs-advancing-dev]]
- Reviewer prompts: `references/final-reviewer-prompt.md`, `references/smoke-prompt.md`
- Q-routing rubric: `references/implementer-q-routing.md`
- Superpowers skills wrapped: `brainstorming`, `writing-plans`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review`, `code-reviewer`, `using-git-worktrees`, `finishing-a-development-branch`
- Managed CLAUDE.md rules invoked: 1 (parallel agents), 4 (batched Q&A), 6 (worktree isolation), 8 (destructive ops consent), 12 (revdiff review), 13 (post-wt-create-remote-sync), 20 (append-only log)
````

- [ ] **Step 2: Verify final SKILL.md structure**

```bash
grep -c '^### Phase' plugins/proj/skills/parallel-batch-execute/SKILL.md
grep -c '^## Cross-refs' plugins/proj/skills/parallel-batch-execute/SKILL.md
wc -l plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: `6` Phases (0-5); `1` Cross-refs section; total ~140-180 lines.

- [ ] **Step 3: Visually proofread final SKILL.md**

```bash
cat plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Check: no leftover `<!-- placeholder -->` markers; phases ordered 0-5; caveman compression consistent (no articles, fragments, arrows).

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md
git commit -m "feat(proj/736): SKILL.md Phase 5 + cross-refs (skill complete)"
```

---

## Task 8: Update wiki `parallel-impl-orchestration` page

The current wiki page documents the recipe in text form. Update it to (a) link to the new skill, (b) note the boundary-issue gates as resolved by the skill, (c) keep the page as the human-readable canonical doc.

**Files:**
- Modify: `~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md` (via wiki MCP tool)

- [ ] **Step 1: Read current page content**

```
mcp__plugin_wiki_wiki__wiki_page_get(slug="parallel-impl-orchestration", category="concepts")
```

Save output for reference.

- [ ] **Step 2: Edit body — add a "Skill" section near top + update "Known limitations" section**

Use `mcp__plugin_wiki_wiki__wiki_page_write` with the existing frontmatter (preserving `tags`, `links_to`, `scope`, `sources`, `aliases`) and a new body that:

(a) Inserts a new section right after the opening paragraph:

```markdown
## Skill

Codified as `proj:parallel-batch-execute` (cpm SKILL). Skill orchestrates the full superpowers workflow with parallelism only in Phase 3 (execution). See: `plugins/proj/skills/parallel-batch-execute/SKILL.md`. Threshold: invoke when N >= 2 disjoint todos. Below threshold, use standard sequential superpowers flow.
```

(b) Replaces the existing "Known limitations" section's first paragraph (which currently says recipe excels at within-layer quality but degrades on cross-layer integration checks) with:

```markdown
## Known limitations

Recipe original form (pre-skill) excels at **within-layer quality** (per-artifact test rigor, style, spec fidelity) but degrades on **cross-layer integration checks**. Per-todo reviewer chains see one layer in isolation; boundary issues at the seam between MCP-tool / SKILL-orchestrator / dispatched-agent layers slip through.

**Resolution**: `proj:parallel-batch-execute` skill restores the lost gates (final whole-impl reviewer + e2e smoke + cross-batch reviewer) in Phase 4. See [[parallel-orchestration-boundary-issues]] for the diagnosis.

- [[worktree-rebase-artifact]] — recurred 2/2 batches; sibling orchestration-polish gap (todo 735, separate).
```

(c) Add `parallel-batch-execute-skill` to `links_to` if you want the wiki to track the cross-ref. Optional.

- [ ] **Step 3: Verify wiki page renders + lint clean**

```
mcp__plugin_wiki_wiki__wiki_lint_schema(category="concepts")
mcp__plugin_wiki_wiki__wiki_lint_broken_links(category="concepts")
```

Expected: no errors against the updated page.

- [ ] **Step 4: Commit (wiki lives outside repo; nothing to commit in working tree). Note via notes_append**

```
mcp__plugin_proj_proj__notes_append(
  heading="## [YYYY-MM-DD HH:MM] note | Wiki parallel-impl-orchestration page updated for skill 736",
  text="Added Skill section pointing at proj:parallel-batch-execute. Updated Known limitations to flag the new skill as resolution mechanism."
)
```

(Wiki page changes don't appear in `git status` — they live in `~/.claude/wiki/`.)

---

## Task 9: Update managed CLAUDE.md (add bullet) + bump _shared version

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md`
- Modify: `plugins/_shared/pyproject.toml`

- [ ] **Step 1: Read current managed_section.md to confirm insertion point**

```bash
cat plugins/_shared/claudemd/managed_section.md
```

Note the position of rule 25 (research synthesis bullet — last rule currently).

- [ ] **Step 2: Add new bullet after rule 25**

Use Edit tool. Find the last bullet (rule 25, starts `- **Research synthesis for brainstorm/spec/plan work**`). Append a new bullet on the line below it:

```markdown
- **Parallel batch execution** — When implementing >=2 todos with disjoint file scopes, prefer `proj:parallel-batch-execute`. Skill orchestrates standard superpowers workflow (brainstorming -> writing-plans -> subagent-driven-development -> finishing-a-development-branch) with parallelism only in the execution stage. Below threshold (N=1 or coupled work), use standard sequential superpowers flow. *Source: 2026-04-25 boundary-issue retro on parallel-impl-orchestration recipe.*
```

- [ ] **Step 3: Bump `claude-hook-transport` version in `plugins/_shared/pyproject.toml`**

Current version: read from file. Bump patch level (e.g. `0.4.26` → `0.4.27`).

```bash
# Read current
grep '^version' plugins/_shared/pyproject.toml
# Edit via Edit tool — bump last digit
```

- [ ] **Step 4: Verify pre-commit `Check _shared version bump` passes**

```bash
cd <worktree_path>
git add plugins/_shared/claudemd/managed_section.md plugins/_shared/pyproject.toml
pre-commit run check-shared-version --files plugins/_shared/claudemd/managed_section.md plugins/_shared/pyproject.toml
```

Expected: `Passed`.

- [ ] **Step 5: Refresh installed managed block to verify the new bullet renders correctly**

```
mcp__plugin_proj_proj__claudemd_refresh_managed
```

Then visually inspect `~/.claude/CLAUDE.md` to confirm new rule 26 appears.

- [ ] **Step 6: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(claudemd/736): managed-block bullet for parallel-batch-execute

Adds rule 26 — points users at proj:parallel-batch-execute when N >= 2
disjoint todos. Bumps _shared version to invalidate cache.
EOF
)"
```

---

## Task 10: Update README + docs/plugins.md

**Files:**
- Modify: `README.md`
- Modify: `docs/plugins.md`

- [ ] **Step 1: Update `README.md` skill listing**

Locate the section listing `/proj:*` skills (around line 74-94 per project layout). Add a new line:

```
/proj:parallel-batch-execute  # Orchestrate >=2 disjoint todos in parallel w/ full superpowers gate fidelity
```

Insert alphabetically (or after `/proj:save` for visibility — consistent with neighboring entries). Use Edit tool.

- [ ] **Step 2: Update `docs/plugins.md`**

Locate the proj plugin's skills list. Add a new entry following the same format as other skills (skill name, one-line description, optional notes about argument-hint or sub-skill nature).

- [ ] **Step 3: Verify both files**

```bash
grep -n 'parallel-batch-execute' README.md docs/plugins.md
```

Expected: 1 match per file.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/plugins.md
git commit -m "docs(736): README + plugins.md — list parallel-batch-execute skill"
```

---

## Task 11: Pre-commit + final verification

- [ ] **Step 1: Run full pre-commit on the changeset**

```bash
cd <worktree_path>
pre-commit run --all-files
```

Expected: all hooks pass. Common pass list: `ruff (legacy alias)`, `ruff format`, `basedpyright`, `Auto-update README`, `Check _shared version bump`. (basedpyright skipped if no Python files changed — fine.)

- [ ] **Step 2: Verify skill loads in Claude Code**

```bash
# Skill content is auto-discovered from plugins/proj/skills/. Restart Claude Code OR
# verify the skill's metadata is parseable:
python3 -c "
import yaml, sys
with open('plugins/proj/skills/parallel-batch-execute/SKILL.md') as f:
    content = f.read()
parts = content.split('---', 2)
fm = yaml.safe_load(parts[1])
print('name:', fm.get('name'))
print('allowed-tools count:', len(fm.get('allowed-tools', '').split(',')))
print('description starts:', fm.get('description')[:80])
"
```

Expected: `name: parallel-batch-execute`; allowed-tools count >=10; description starts with `Orchestrate parallel impl`.

- [ ] **Step 3: Verify cross-refs resolve**

```bash
# Check references files exist + named in SKILL.md correctly
grep -E 'references/(implementer-q-routing|final-reviewer-prompt|smoke-prompt)\.md' \
  plugins/proj/skills/parallel-batch-execute/SKILL.md
ls plugins/proj/skills/parallel-batch-execute/references/
```

Expected: 3 grep matches (one per reference file); 3 files in `references/`.

- [ ] **Step 4: Verify managed-block reads + 26-rule count**

```bash
grep -c '^- \*\*' plugins/_shared/claudemd/managed_section.md
```

Expected: `26` (was 25; +1 for new bullet).

- [ ] **Step 5: Note completion via notes_append**

```
mcp__plugin_proj_proj__notes_append(
  heading="## [YYYY-MM-DD HH:MM] checkpoint | 736 parallel-batch-execute skill shipped",
  text="Skill at plugins/proj/skills/parallel-batch-execute/. Wiki page updated. Managed CLAUDE.md rule 26 added. Field test pending: next 2 parallel batches per spec validation strategy."
)
```

---

## Task 12: Branch finishing

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Per managed rule 11 — superpowers:finishing-a-development-branch is the terminal step for any dev branch.

```
Skill(skill="superpowers:finishing-a-development-branch")
```

Expected: skill walks through merge / PR / cleanup options. Per CLAUDE.md project memory: "Branch completion: FF-merge to dev, no PR" — pick FF-merge option.

- [ ] **Step 2: Per the skill's guidance — rebase + FF-merge to dev**

```bash
cd <worktree_path>
git fetch origin
git rebase origin/dev
cd /home/raul/projects/claude-project-manager
git merge --ff-only feat/736-parallel-batch-execute
git push origin dev
```

Expected: clean rebase (no conflicts), FF merge succeeds, push lands.

- [ ] **Step 3: Watch CI on `dev`**

```bash
gh run watch
```

Expected: green.

- [ ] **Step 4: Cleanup worktree**

```
mcp__plugin_worktree_worktree__wt_remove(worktree_path="<worktree_path>")
```

```bash
git branch -d feat/736-parallel-batch-execute
```

- [ ] **Step 5: Mark todo 736 done**

```
mcp__plugin_proj_proj__todo_complete(todo_id="736")
```

(Single todo → `todo_complete(todo_id="736")`. For batch closure, `todo_complete(todo_ids=[...])` accepts a list — see todo 738.)

---

## Self-Review (run before handing off)

**Spec coverage check** — every section of the spec maps to a task:

| Spec section | Task(s) |
|---|---|
| Architecture (5-phase model + skill-to-phase mapping) | Tasks 1, 2, 3, 4, 5, 6, 7 (incremental SKILL.md build) |
| Phase 1 — Per-todo design | Task 3 |
| Phase 2 — Worktree setup | Task 4 |
| Phase 3 — Parallel execution + Q-routing | Tasks 5 (incl. references/implementer-q-routing.md) |
| Phase 4 — Integration gates (4a final reviewer, 4b smoke, 4c collapsed into 4a) | Task 6 (incl. references/final-reviewer-prompt.md, references/smoke-prompt.md) |
| Phase 5 — Merge + finish | Task 7 |
| Validation strategy (field test) | Documented in spec; not implemented as code (field test is post-ship activity) |
| Skill structure (SKILL.md + references/) | Tasks 1-7 collectively |
| Wiki + managed CLAUDE.md updates | Tasks 8 + 9 |
| README/docs updates | Task 10 |
| Risks (Phase 1 cost, smoke fixture coverage, Q-routing fatigue, drift, threshold) | Documented in spec; not implemented as code |
| Open questions | Documented in spec; not blocking v1 |

No spec section is left unmapped.

**Placeholder scan** — Search this plan for: `TBD`, `TODO`, `Add appropriate`, `Similar to Task`, `Write tests for the above`. No matches expected. Each task contains the exact prose to write.

**Type/name consistency** — `proj:parallel-batch-execute` used consistently. `feat/736-parallel-batch-execute` branch name used consistently. Reference files named consistently between SKILL.md cross-refs and Task 5/6 file creation.

---

## Notes for the implementer

- **Strict sequencing**: Tasks 1-7 build SKILL.md incrementally. Each task's Edit replaces a `<!-- Sections to fill -->` placeholder with the next section + an updated placeholder marker. Don't skip ahead; the placeholder threads guarantee no orphaned content.
- **Wiki page edit (Task 8)**: lives in `~/.claude/wiki/`, not the repo. Use `mcp__plugin_wiki_wiki__wiki_page_write`. Won't show up in `git status`. Note via `notes_append` for traceability.
- **Caveman ultra discipline**: every prose block in SKILL.md + references must drop articles, abbreviate, use fragments + arrows. Code blocks, file paths, MCP tool names, URLs preserved exactly. Reference: project CLAUDE.md "SKILL.md Compression (Caveman Ultra)" section.
- **Pre-commit `Check _shared version bump`**: triggered by any change under `plugins/_shared/`. Task 9 bumps `claude-hook-transport` version explicitly to keep this hook green.
- **No revdiff for this session**: per session-scoped user preference; for any user-review step, ask the user to read files directly.

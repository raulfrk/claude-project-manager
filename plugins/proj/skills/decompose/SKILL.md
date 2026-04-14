---
name: decompose
description: Break a large todo into smaller sub-todos based on its requirements and research. Use when asked "decompose 1", "break down 1", or "split 1 into subtasks".
allowed-tools: mcp__proj__todo_get, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__proj_search_knowledge, mcp__proj__proj_decision_log, mcp__proj__config_load, mcp__proj__todo_add_child, mcp__proj__todo_tree, mcp__proj__todo_block, mcp__proj__todo_update, mcp__proj__todo_batch_add_children, mcp__proj__todo_notes_patch, mcp__proj__todo_notes_append, mcp__proj__tracking_git_flush, Skill, Task
argument-hint: "<todo-id>"
---


<!-- n-distinct-agents-rule: not applicable — decompose does not spawn review/check agents -->

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Decompose todo $ARGUMENTS into sub-todos.

**1.** `mcp__proj__todo_get` — get todo.
**2.** `mcp__proj__content_get_requirements` — read requirements.md (if available).
**3.** `mcp__proj__content_get_research` — read research.md (if available).

**4.** Assess atomicity — before proposing breakdown, evaluate if todo already atomic:
 - Title/notes — single focused operation or spans multiple concerns?
 - requirements.md — separable phases or multiple unrelated systems?
 - research.md — independent sub-problems?

 Todo is **atomic** if ALL hold:
 - Single focused operation (edit one file, add one fn, write one docs section)
 - Fits one coding session, no multi-day scope
 - No distinct separable phases touching unrelated systems

 Borderline → proceed step 4, let user decide via confirmation prompt.

 Atomic → print `↩ Skipping decompose for <id> — already atomic.` and stop.

**4b.** Search prior decisions: `mcp__proj__proj_decision_log(action="search", decision=<todo title>)`. Results found → include as ctx when proposing breakdown.

**5.** Analyze todo, propose **multi-level** breakdown:
 - Identify sub-tasks from natural problem structure — no hard cap.
 - Each sub-task: assess **large** vs **leaf**:
 - Large — 3+ distinct impl phases or 2+ unrelated systems/files
 - Leaf — single focused operation
 - Large sub-tasks → propose nested children inline. Recurse same assessment — nest as deep as needed.
 - Consider deps at all levels (ordering). Assign priorities to all tasks.
 - Each leaf implementable in focused coding session.

**6.** Shared-file conflict analysis: predict files each subtodo writes. Shared write target → add `blocked_by` from dependent to simpler subtodo. When in doubt, add dep — false positives cheaper than parallel write conflicts.

 **Step D — Worktree-aware conflict resolution** (if worktree available):

 Check: `mcp__proj__config_load` — `worktree_isolation` enabled or `--worktree` flag passed?

 Shared-file conflict detected:
 1. Assess conflict granularity:
 - Low risk: diff fns/sections, non-overlapping → `worktree_candidate`
 - High risk: same fn, overlapping lines, schema/migration → `blocked_by`
 2. Low risk AND worktree available → `worktree_candidate` instead of `blocked_by`.
 - Mutual exclusivity: pair is EITHER `blocked_by` OR `worktree_candidate`, never both.
 - Store in todo notes: `wt-candidate: [<paired_todo_id>] (shared: <filename>)`
 3. High risk OR no worktree → `blocked_by` (Step C).

 `proj_identify_batches` ignores `worktree_candidate` — only uses `blocked_by`. wt-candidate pairs treated as independent, can run parallel w/ worktree isolation.

 No worktree mode → skip Step D entirely; all shared-file conflicts use `blocked_by`.

**7.** Clarity check — EVERY proposed sub-todo:
 - Clear: dev understands exactly what to do w/o further ctx.
 - Vague: ambiguous terms ("handle", "improve", "set up stuff"), no specific target, multiple interpretations.
 - Flag vague titles w/ brief explanation.
 - Offer `skill: "proj:define", args: "<sub-todo-id>"` for each vague sub-todo after creation.

**8.** Present breakdown as **indented bullet points**:
 - Root tasks level 0; each nesting +2 spaces.
 - Format: `- **ID** — title _(priority)_ [manual] [blocks X, blocked by Y]`
 - `manual` tag → append `[manual]` after priority.
 - Shared-file blocks (step 6) → append filename: `[blocks X (shared: filename.py)]`.
 - `worktree_candidate` → append `[wt-candidate: X (shared: filename.py)]`.
 - Children indented under parent.
 - Vague titles get `[vague]` tag w/ reason on next line.

 Example:
   ```
   Proposed sub-todos for 1:
   - **1.1** — Add rate-limit middleware to auth router _(high)_ [blocks 1.3 (shared: auth.py)]
   - **1.2** — Write unit tests for rate-limit logic _(medium)_
   - **1.3** — Another task _(medium)_ [wt-candidate: 1.2 (shared: models.py)]
   - **1.4** — Update OpenAPI schema with rate-limit headers _(low)_ [blocked by 1.1 (shared: auth.py)]
   - **1.5** — Handle edge cases _(medium)_ [vague]
     → Vague: "handle edge cases" doesn't specify which cases or where. Consider: "Add timeout handling for upstream auth failures"
   ```

**9.** Ask: "Does this breakdown look good? Any changes?" User can add, remove, rename, restructure at any level.

**10.** Create confirmed todos via `mcp__proj__todo_batch_add_children`:
 - Call once per parent w/ `children` (list of `{title, priority, tags, notes}`) and `blocking_pairs` (list of `[blocker_index, blocked_index]`).
 - Multi-level: call root-level children first, then each parent w/ nested children (via returned IDs).

**11.** Show final tree via `mcp__proj__todo_tree`.

**12.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Decompose: {todo-id}")`.

## Prerequisites

- Active project loaded.
- Valid todo ID provided.

## Error Handling

- No todo ID → show usage msg, stop.
- Todo not found → show err from `todo_get`, stop.
- Already atomic → `Skipping decompose for <id> — already atomic.`, stop.
- Batch add failure → show err from `todo_batch_add_children`, stop.

## Output

Proposed multi-level breakdown as indented bullets w/ IDs, titles, priorities, blocking relationships, vague-title flags. After confirmation: final todo tree. Git tracking flush confirmation.

## Agent Fallback

Decompose currently runs inline (no agent spawns). Agent def exists at `plugins/proj/agents/decomposer.md` for future use.

If `subagent_type="decomposer"` wired in future + .md file missing/renamed:
1. Log warning via `notes_append`: "Agent definition 'decomposer' not found, falling back to general-purpose"
2. Use `Agent(subagent_type="general-purpose", prompt=<inline_fallback>)` w/ minimal role desc
3. Fallback prompt:
   - `decomposer`: "Break todo into sub-todos. Read requirements + research, propose multi-level breakdown w/ deps + priorities. Return structured breakdown."

Suggested next: `1. /proj:execute X.1` -- start w/ first sub-todo | `2. /proj:run X` -- run full workflow

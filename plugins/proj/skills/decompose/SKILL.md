---
name: decompose
description: Break a large todo into smaller sub-todos based on its requirements and research. Use when asked "decompose 1", "break down 1", or "split 1 into subtasks".
allowed-tools: mcp__proj__todo_get, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__proj_search_knowledge, mcp__proj__config_load, mcp__proj__todo_add_child, mcp__proj__todo_tree, mcp__proj__todo_block, mcp__proj__todo_update, mcp__proj__todo_batch_add_children, mcp__proj__tracking_git_flush, Skill, Task
argument-hint: "<todo-id>"
---

Decompose todo $ARGUMENTS into sub-todos.

**1.** Call `mcp__proj__todo_get` to get the todo.
**2.** Call `mcp__proj__content_get_requirements` to read requirements.md (if available).
**3.** Call `mcp__proj__content_get_research` to read research.md (if available).

**4.** Assess atomicity — before proposing any breakdown, evaluate whether this todo is already atomic (not meaningfully decomposable) using qualitative judgment based on:
   - **Title and notes** — is it a single focused operation, or does it span multiple distinct concerns?
   - **requirements.md** (if loaded) — does it specify separable phases or multiple unrelated systems?
   - **research.md** (if loaded) — does the research outline independent sub-problems?

   A todo is **atomic** if ALL of the following hold:
   - Single focused operation (e.g. edit one file, add one function, write one docs section)
   - Fits in one coding session with no multi-day scope
   - No distinct phases that are separable concerns (design + implement + test counted as one unless they touch unrelated systems)

   **When in doubt, do not auto-skip.** If borderline, proceed to step 4 and let the user decide via the normal confirmation prompt.

   If atomic: print `↩ Skipping decompose for <id> — already atomic.` and stop — do not proceed to steps 5–13.

**5.** Analyze the todo and propose a **multi-level** breakdown:
   - Identify sub-tasks based on the natural problem structure — no hard cap on count.
   - For each sub-task, assess if it is **large** (warrants nested children) or a **leaf** (single focused operation):
     - **Large** — contains 3+ distinct implementation phases or touches 2+ unrelated systems/files
     - **Leaf** — single focused operation: edit one file, add one function, write one docs section
   - For large sub-tasks, propose nested children inline. Apply the same large/leaf assessment recursively — nest as deep as needed.
   - Consider dependencies at all levels (which must come first?). Assign priorities to all tasks.
   - Each leaf sub-task should be implementable in a focused coding session.

**6.** Shared-file conflict analysis: Predict which files each subtodo will write. For any pair sharing a write target, add `blocked_by` from the dependent to the simpler/shallower subtodo. When in doubt, add the dependency — false positives are cheaper than parallel write conflicts.

   **Step D — Worktree-aware conflict resolution** (if worktree mode available):

   Check worktree availability: call `mcp__proj__config_load` and check if `execution.worktree_isolation` is enabled or `--worktree` flag was passed to the parent run/execute.

   When a shared-file conflict is detected between two subtodos:
   1. Assess conflict granularity (LLM judgment):
      - **Low risk**: different functions/sections in same file, non-overlapping changes → `worktree_candidate`
      - **High risk**: same function, overlapping lines, schema/migration changes → `blocked_by`
   2. If low risk AND worktree available: annotate as `worktree_candidate` instead of `blocked_by`.
      - **Mutual exclusivity**: a pair is EITHER `blocked_by` OR `worktree_candidate`, never both.
      - Store in todo notes field: `wt-candidate: [<paired_todo_id>] (shared: <filename>)`
   3. If high risk OR worktree not available: use `blocked_by` as before (Step C).

   **Note**: `proj_identify_batches` ignores `worktree_candidate` annotations — it only uses `blocked_by`. This means worktree_candidate pairs are treated as independent and can run in parallel when worktree isolation is enabled.

   If worktree mode is not available, skip Step D entirely — all shared-file conflicts use `blocked_by` from Step C.

**7.** Clarity check — for EVERY proposed sub-todo, assess whether the title is clear and actionable:
   - A title is **clear** if a developer can understand exactly what to do without further context.
   - A title is **vague** if it uses ambiguous terms ("handle", "improve", "set up stuff"), lacks a specific target, or could mean multiple things.
   - Flag each vague title with a brief explanation of why it is vague.
   - Offer to run the full interactive define flow via the `Skill` tool (invoke skill `proj:define` with the sub-todo ID) for each vague one, after creation.

**8.** Present the proposed multi-level breakdown as **indented bullet points**:
   - Root tasks at level 0; each nesting level adds two spaces of indentation.
   - Format per line: `- **ID** — title _(priority)_ [manual] [blocks X, blocked by Y]`
   - If a sub-todo is tagged `manual`, append `[manual]` after the priority.
   - For blocks added due to shared files (step 6), append the filename: `[blocks X (shared: filename.py)]`.
   - If a sub-todo has `worktree_candidate` annotations, append `[wt-candidate: X (shared: filename.py)]` after any existing badges.
   - Children shown indented under their parent.
   - Vague titles get a `[vague]` tag with the reason on the next line.

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

**9.** Ask: "Does this breakdown look good? Any changes?" Allow the user to add, remove, rename, or restructure sub-todos at any level.

**10.** Create the confirmed todos using `mcp__proj__todo_batch_add_children`:
   - Call once per parent with `children` (list of `{title, priority, tags, notes}`) and `blocking_pairs` (list of `[blocker_index, blocked_index]` pairs).
   - For multi-level nesting: call for root-level children first, then call again for each parent that has nested children (using the IDs returned from the first call).

**11.** Show the final tree via `mcp__proj__todo_tree`.

**12.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Decompose: {todo-id}"`.

## Prerequisites

- An active project must be loaded.
- A valid todo ID must be provided.

## Error Handling

- **No todo ID**: displays usage message and stops.
- **Todo not found**: displays error from `todo_get` and stops.
- **Already atomic**: displays `Skipping decompose for <id> — already atomic.` and stops.
- **Batch add failure**: displays error from `todo_batch_add_children` and stops.

## Output

Proposed multi-level breakdown as indented bullet points with IDs, titles, priorities, blocking relationships, and vague-title flags. After confirmation: final todo tree. Git tracking flush confirmation.

Suggested next: `1. /proj:execute X.1` -- start with the first sub-todo | `2. /proj:run X` -- run the full workflow

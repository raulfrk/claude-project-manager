---
name: full-workflow
description: Run the full workflow (define → research → decompose → execute) on a todo interactively, prompting between each step. Use when asked "full workflow on 1", "run workflow for 2", or "proj:full-workflow 1".
disable-model-invocation: "true"
allowed-tools: mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__claude_ai_Todoist__complete-tasks, Read, Task
argument-hint: "<todo-id> [--iter N | --iter-as-needed[=N]] [--steps define,execute] [--from <step>] [--no-interactive]"
---

Run full-workflow for: $ARGUMENTS

**1. Parse and validate**

Inspect $ARGUMENTS to determine the input mode and extract flags:

- **Input mode** — check the first non-flag token:
  - **Single ID**: a plain todo ID with no range syntax (e.g. `1`, `3.2`).
  - **Range**: two integers separated by a hyphen (e.g. `2-5`) — expands to all IDs in that inclusive range.
  - **Comma list**: multiple IDs separated by commas (e.g. `1,3,5`).
- **`--steps <csv>`**: if present, extract the comma-separated step names. Used as the explicit step list (validated and reordered in step 2).
- **`--from <step>`**: if present, extract the single step name. Slices the workflow step list from that step onward (inclusive).
- If both `--steps` and `--from` are given, `--steps` takes precedence; ignore `--from`.
- **`--iter N`**: if present, extract N as the number of prep iterations (default 1). N must be a positive integer. Ignored for range/comma-list input.
- **`--iter-as-needed[=N]`**: if present, use adaptive iteration mode — iterate prep steps until convergence, up to N iterations max (default 5 if N omitted). N must be a positive integer. If both `--iter` and `--iter-as-needed` are given, stop with: `Cannot use both --iter and --iter-as-needed. Choose one.`
- **`--no-interactive`**: if present, run all steps autonomously with no user prompts — define runs inside agents (or non-interactively for single-ID), convergence prompts are suppressed. For single-ID input: auto-proceed through convergence prompts (step 4c) and execute prompts (step 5) based on convergence state.
- If no todo ID is present, stop with: `Todo ID required. Usage: /proj:full-workflow <id> [--steps define,execute] [--from <step>]`

For **single ID**: call `mcp__proj__todo_get` to confirm it exists. If not found, stop with a clear error. Then continue to step 2.

For **range or comma list**: parse into a flat deduplicated list of todo ID strings (e.g. `"2-5"` → `["2","3","4","5"]`). Then skip to **"For a range of todos"** below.

**2. Load the workflow step list**

- This skill's base directory ends in `.../skills/full-workflow`. The sibling skill directories are at `.../skills/<step>/`.
- Read the workflow YAML: `<parent-of-this-skill's-base-dir>/workflows/full-workflow.yaml`
  - Parse the `steps` list. If the file cannot be read, fall back to the default: `[define, research, decompose, execute]`.
- Apply flag filters to produce the active step list:
  - If `--steps` was given: filter to only those steps, reordered to match workflow YAML order. Error if any step name is invalid (list valid names).
  - If `--from` was given (and no `--steps`): slice from that step to the end. Error if step name not found.
  - If neither flag: use the full step list.
- If the active step list is empty, stop with: `No steps to execute after applying filters.`
- Display: `Running full-workflow on todo **<id>** — <title>`
- Display: `Steps: <step1> → <step2> → ... (×<N> iterations)` (omit `×<N>` if N=1; for `--iter-as-needed`: display `(iter-as-needed, max N)` instead)

> **Read failure policy**: Any `Read` call on a sibling SKILL.md file (e.g. `define/SKILL.md`, `execute/SKILL.md`) that fails (file not found, permission error, or empty result) must be treated as a hard stop: display `Error: cannot read <path> — aborting workflow.` and exit without executing further steps. Completed steps up to that point are already saved.

**assess_convergence(todo_id)**

A shared sub-procedure used by step 4c and step 5 to evaluate whether a todo (and its full descendant subtree) are ready for execute.

1. Call `mcp__proj__proj_get_todo_context` for `todo_id` to load requirements.md and research.md. Evaluate quality across three dimensions:
   - **define**: are acceptance criteria specific and testable? No open questions or vague "TBD" goals?
   - **research**: is the recommended approach chosen (not "TBD")? No major unknowns blocking implementation?
   - **decompose**: if subtodos exist, are they concrete and implementable?
   Record `parent_converged: bool` and `parent_reason: str` (brief reason if parent fails, else empty).
2. Initialise a traversal queue with the `children` list from the `proj_get_todo_context` response (the `todo` object inside the response contains `children`). Also record the direct children IDs separately as `direct_children`.
3. While the queue is non-empty:
   a. Pop the next `node_id` from the queue.
   b. Call `mcp__proj__proj_get_todo_context` for `node_id`.
   c. Evaluate the same three dimensions; record `{node_id, converged: bool, reason: str}`.
   d. Push the node's `children` (from the context response) onto the queue so their descendants are also visited.
4. Collect all non-converged nodes (from step 3) into `failing_descendants: list[{node_id, reason}]`. (Empty list when all descendants pass or there are no descendants.)
5. Determine the overall verdict:
   - `parent_converged` = all three dimensions pass for the todo itself (from step 1)
   - `children_converged` = `parent_converged AND all(node.converged for node in direct_children)` (trivially true when there are no direct children; same depth-1 semantics used by step 5 branching)
   - `overall_converged` = `parent_converged AND failing_descendants is empty`
6. Return:
   - `overall_converged: bool` — true only when parent and every node in the full subtree pass all three dimensions
   - `children_converged: bool` — true when parent_converged AND all direct children (depth-1 only) pass (used by step 5)
   - `failing_descendants: list[{node_id, reason}]` — all failing nodes anywhere in the subtree (empty when all pass)
   - `parent_reason: str` — brief reason if parent fails, else empty string

Leaf-node safety: when `todo.children` is empty the traversal queue starts empty; steps 3-4 are no-ops. Result is identical to current behaviour: `overall_converged = parent_converged`, `children_converged = true`, `failing_descendants = []` (if parent passes) or containing the parent's reason (if parent fails).

**3. Separate prep steps from execute**

- Split the active step list: `prep_steps` = all steps except `execute`; `has_execute` = whether `execute` is in the active step list.
- If `prep_steps` is empty and `has_execute` is true: skip directly to step 4 (execute).

**4. Iteration loop**

Repeat the following up to N times (tracked as iteration i, from 1 to N). For `--iter-as-needed` mode, N = the max cap (default 5).

**a. Announce the iteration (only if N > 1)**

Display:
```
════════════════════════════
Iteration <i>/<N>
Running on: <id1>, <id2>, <id3>, ...
════════════════════════════
```

The `Running on:` line lists all IDs in `descendant_list` for that iteration (comma-separated). For the first iteration, `descendant_list` is built in step a-refresh below. For subsequent iterations, `descendant_list` was refreshed at the end of the previous iteration's decompose step (or at the start of this step a-refresh if decompose was not in prep_steps).

When N = 1 (single iteration, no header shown), the `Running on:` line is also omitted.

**a-refresh. Build full descendant list**

At the start of each iteration body (before announcing any step):

- Call `mcp__proj__todo_tree` with `<todo-id>` as the root.
- Flatten the returned nested structure depth-first to produce `descendant_list`:
  - Walk recursively: add the current node's ID first, then recurse into each child before moving to the next sibling.
  - Algorithm: `flatten(node) = [node.id] + flatten(child_1) + flatten(child_2) + ...`
  - Result example for a 3-level tree: `["1", "1.1", "1.1.1", "1.2"]`
- If the tree has no children (leaf node): `descendant_list = [<todo-id>]`. All subsequent steps behave identically to the current single-ID implementation — no new MCP calls, no behaviour change.

**b. For each step in prep_steps:**

i. Announce the step with the count of todos in scope:
```
━━━━━━━━━━━━━━━━━━━━━━━━
Step <step-index>/<total-prep-steps>: <step-name> (<len(descendant_list)> todos)
━━━━━━━━━━━━━━━━━━━━━━━━
```

ii. Read the step's SKILL.md:
- Construct the path: `<parent-of-this-skill's-base-dir>/<step>/SKILL.md`
- Call `Read` on that path to load the skill file.
- Extract the Markdown instructions — everything after the second `---` frontmatter delimiter.

iii. Order todos by dependencies:
- Call `mcp__proj__proj_identify_batches` with `descendant_list`.
- Returns `batches`: a list of lists, where each inner list contains todo IDs that can be processed in parallel.
- If `cycles` is non-empty: stop with an error listing the circular dependencies.

iv. Execute the step on all todos in `descendant_list`, in batch order:

**If step is `define`** — sequential and interactive:
- For each batch in order, for each todo ID in the batch:
  - Call `mcp__proj__todo_get` to get the todo title.
  - Announce: `━━━ Define: <id> — <title> ━━━`
  - Execute the define skill interactively for that todo ID (same as the current parent-only define execution, but repeated for each descendant in turn). Each iteration builds on the previous — the define skill already handles existing requirements.md by refining it.
- After all todos in `descendant_list` have been defined, show the step summary using `## Step: define — Complete`:
  - Call `mcp__proj__content_get_requirements` for `<todo-id>` (parent only). Display the full `## Acceptance Criteria` section.

**If step is `research`** — parallel Task agents, one per batch:
- For each batch in order:
  - Spawn one parallel `general-purpose` Task agent per todo ID in the batch. Each agent runs the research skill for its assigned todo ID autonomously (no user prompts).
  - Wait for all agents in the batch to complete before starting the next batch. If any agent terminates with an error or exception (non-success result), capture the error message and display `⚠️ Agent for todo <id> failed: <error>`. Continue processing remaining todos in `descendant_list` (degraded mode). Do not re-run failed agents automatically.
- After all todos are done, show the step summary using `## Step: research — Complete`:
  - Call `mcp__proj__content_get_research` for `<todo-id>` (parent only). Display the full `## Recommended Approach` section.

**If step is `decompose`** — parallel Task agents, one per batch:
- For each batch in order:
  - Spawn one parallel `general-purpose` Task agent per todo ID in the batch. Each agent runs the decompose skill for its assigned todo ID autonomously (no user prompts).
  - Wait for all agents in the batch to complete before starting the next batch. If any agent terminates with an error or exception (non-success result), capture the error message and display `⚠️ Agent for todo <id> failed: <error>`. Continue processing remaining todos in `descendant_list` (degraded mode). Do not re-run failed agents automatically.
- After all todos are done:
  - **Refresh `descendant_list`**: call `mcp__proj__todo_tree` again with `<todo-id>` and re-flatten depth-first. This picks up any grandchildren created by decompose during this iteration. The refreshed list is used for any subsequent steps within the same iteration and is available for the next iteration. If the count changed (new todos were added by decompose), display: `Descendant list refreshed: now <N> todos in scope.`
  - Show the step summary using `## Step: decompose — Complete`:
    - Call `mcp__proj__todo_tree` for `<todo-id>`. Render as a nested bullet list showing each subtodo's ID, title, status. For any todo with `"manual" in tags`, append `[manual]` after the priority (e.g. `- 🔲 **1.1** — title _(medium)_ [manual]`).

**c. Prompt between iterations** (skip after the last iteration, i.e. when i = N)

For **`--iter-as-needed` mode only**: before showing the prompt, call `assess_convergence(todo_id)` (defined above). This evaluates both the parent todo and all its children.

If `overall_converged` is true: display the following, where the parenthetical lists all IDs in `descendant_list` — if more than 6 IDs, truncate with `...` after the 6th:
```
🟢 Convergence check: full tree (<id1>, <id2>, ...) — all converged.
Recommending stop (proceed to execute).
```

If `overall_converged` is false:
- If `failing_descendants` is non-empty: display each failing item on its own bullet line using the item's full dotted ID. If `parent_reason` is non-empty and the parent todo is not already in `failing_descendants`, prepend a bullet for the parent todo ID with the parent reason:
```
🔄 Convergence check:
   - <node_id>: <step> — <reason>
   - <node_id>: <step> — <reason>
Recommend another iteration.
```
- Otherwise (parent fails but no descendant failures and no explicit reason): `🔄 Convergence check: [brief reason why another iteration would help]`

Store `children_converged` from the result for use in step 5.

Display this assessment line immediately before the prompt options.

**Automatic progression with `--no-interactive`** (single-ID path):
- If `--no-interactive` is true AND `overall_converged` is true: display the convergence assessment, then display `Auto-proceeding to execute (--no-interactive mode)` and skip remaining iterations — jump directly to step 5.
- If `--no-interactive` is true AND `overall_converged` is false: display the convergence assessment, then display `Auto-continuing to iteration <i+1> (--no-interactive mode)` and continue to the next iteration.
- If `--no-interactive` is false (interactive mode): proceed to show the user prompt as documented below.

When convergence is 🟢 AND `has_execute` is true AND NOT `--no-interactive`, show a 4-option prompt (execute is the natural next step):
```
### Iteration <i>/<N> complete — Next Action?

🟢 Convergence check: ... — recommending stop.

1. **Proceed to execute** → Skip remaining iterations, run execute now
2. **Continue** → Start iteration <i+1>/<N> anyway
3. **Edit** → Modify this iteration's output (describe changes)
4. **Stop** → Exit workflow now (completed steps are saved, no execute)

Enter 1, 2, 3, or 4:
```

When convergence is 🔄 OR `has_execute` is false, AND NOT `--no-interactive`, show the standard 3-option prompt:
```
### Iteration <i>/<N> complete — Next Action?

[🟢/🔄 convergence assessment — only shown in --iter-as-needed mode]

1. **Continue** → Start iteration <i+1>/<N>
2. **Edit** → Modify this iteration's output (describe changes)
3. **Stop** → Exit workflow now (completed steps are saved)

Enter 1, 2, or 3 (or "continue" / "edit" / "stop"):
```

Handle responses:
- **Proceed to execute** (1 when 🟢 prompt): exit iteration loop and jump directly to step 5 (execute).
- **Continue** (1 on 🔄 prompt, 2 on 🟢 prompt, "continue", "c"): advance to next iteration. The next iteration will refresh `descendant_list` via `todo_tree` at step a-refresh — any children created by decompose in this iteration will be included.
- **Edit** (2 on 🔄, 3 on 🟢, "edit", "e"): ask what to change. Then: "(a) re-run the last step with this input, or (b) apply as direct update and continue?" Act accordingly, then return to prompting.
- **Stop** (3 on 🔄, 4 on 🟢, "stop", "s"): display a summary of completed iterations and exit cleanly.

**5. Execute step** (only if `has_execute` is true)

First, call `mcp__proj__todo_get` with the todo ID to refresh the todo (it may have gained children during decompose). Store `has_children = len(todo.children) > 0`.

**Determine `children_converged`:**
- If `children_converged` was already set by step 4c (i.e. the `--iter-as-needed` path ran and stored it): use that value directly.
- Otherwise (fixed-iteration path or `--iter-as-needed` not used): if `has_children` is true, call `assess_convergence(todo_id)` now and store `children_converged` from the result. If `has_children` is false, set `children_converged = true` (irrelevant, but keeps branching consistent).

**Store `execute_all_path = false`** (will be set to true if the execute-all path is taken; used by step 7).

If **`has_children` is false**:

When `--no-interactive` is true: display `Auto-proceeding to execute (--no-interactive mode)` and jump directly to step 5i (parent execute) — do not show the prompt.

Otherwise, present the standard prompt:

```
### Prep complete (<N> iteration(s)) — Next Action?

1. **Proceed** → Run execute
2. **Edit** → Modify prep output (describe changes)
3. **Stop** → Exit workflow now (prep steps are saved)

Enter 1, 2, or 3 (or "proceed" / "edit" / "stop"):
```

Handle responses:
- **Proceed** (1, "proceed", "p", "continue"): continue to parent execute (step 5i below).
- **Edit** (2, "edit", "e"): ask what to change, apply as direct update, then return to this prompt.
- **Stop** (3, "stop", "s"): display summary and exit cleanly.

If **`has_children` is true AND `children_converged` is true**:

When `--no-interactive` is true: display `Auto-proceeding to execute all — parent + children (--no-interactive mode)`, set `execute_all_path = true`, and jump directly to step 5ii (execute-all) — do not show the prompt.

Otherwise, present the execute-all prompt:

```
### Prep complete — todo has <N> children (all converged). Next Action?

1. **Execute all (parent + children)** → Run execute on parent and all children in dependency order
2. **Edit** → Modify prep output (describe changes)
3. **Stop** → Exit workflow now (prep steps are saved)

Enter 1, 2, or 3:
```

Handle responses:
- **Execute all** (1, "execute", "proceed"): set `execute_all_path = true`. Run batch execute (Phase C style) on `[todo_id] + all_descendants` in dependency order (step 5ii-execute-all below). Then skip step 6.
- **Edit** (2, "edit", "e"): ask what to change, apply as direct update, then return to this prompt.
- **Stop** (3, "stop", "s"): display summary and exit cleanly.

If **`has_children` is true AND `children_converged` is false**:

When `--no-interactive` is true: display `Auto-proceeding to execute parent, then children workflow (--no-interactive mode)` and jump to step 5i (parent execute), then continue to step 6 (children workflow) — do not show the prompt.

Otherwise, present the children-aware prompt:

> **Note (edge-case fallback):** This prompt is only reached when `--steps` excluded the research/decompose steps, leaving children without prep. In the normal full-workflow path, step 4 handles all descendants (prep) and step 5ii handles execute-all; this branch is not taken. The children workflow below (step 6) will define/research/decompose/execute each child now.

```
### Prep complete — todo has <N> children (not fully prepared).

Note: children were not prepared because prep steps were limited via --steps.
Running the children workflow will define/research/decompose/execute each child now.

1. **Execute parent, then children** → Run execute on parent, then proceed to children workflow
2. **Skip to children** → Skip parent execute, go directly to children workflow
3. **Edit** → Modify prep output (describe changes)
4. **Stop** → Exit workflow now (prep steps are saved)

Enter 1, 2, 3, or 4:
```

Handle responses:
- **Execute parent, then children** (1): execute parent (step 5i below), then after completion continue to **step 6** (children workflow — edge-case fallback).
- **Skip to children** (2): skip parent execute entirely, go directly to **step 6** (children workflow — edge-case fallback).
- **Edit** (3, "edit", "e"): ask what to change, apply as direct update, then return to this prompt.
- **Stop** (4, "stop", "s"): display summary and exit cleanly.

**5i. Parent execute** (used when `has_children` is false, or `has_children AND NOT children_converged` and option 1 was chosen):

i. Announce:
```
━━━━━━━━━━━━━━━━━━━━━━━━
Execute
━━━━━━━━━━━━━━━━━━━━━━━━
```

ii. Call `mcp__proj__todo_check_executable` with the todo ID.
   - If the result starts with "⚠️" (manual-tagged): display the warning and **stop** — do not run execute. Show: "Prep steps saved. Execute this todo yourself when ready."
   - If the result is JSON: continue.

iii. Read `<parent-of-this-skill's-base-dir>/execute/SKILL.md` and extract the Markdown instructions.

iv. Execute the step.

v. Show summary: Call `mcp__proj__todo_get`. If status is `done`, display "✅ Todo <id> marked done." Otherwise display current status. If `has_children` is true AND `children_converged` is false AND `execute_all_path` is false, continue to **step 6** (children workflow — edge-case fallback). If `execute_all_path` is true, step 6 is skipped entirely.

**5ii. Execute-all** (used when `execute_all_path = true`, i.e. `has_children AND children_converged` and option 1 was chosen):

Read `<parent-of-this-skill's-base-dir>/execute/SKILL.md` instructions once.

Build the full descendant list:
1. Call `mcp__proj__todo_tree` with `todo_id` to get the full tree structure.
2. Walk the tree recursively to collect every descendant ID (children, grandchildren, and deeper). The parent `todo_id` itself is NOT a descendant — it is the root. Algorithm: `flatten(node) = [node.id] + flatten(child_1) + flatten(child_2) + ...` applied to each child of the root.
3. Construct `all_descendants` = the complete flat list of every descendant ID at any depth.
4. Construct the full batch list: `[todo_id] + all_descendants`.
5. Store `execute_all_total = len(all_descendants) + 1` (parent plus all descendants).

Call `mcp__proj__proj_identify_batches` with `[todo_id] + all_descendants` to get dependency-ordered batches.

For each batch in dependency order:
1. Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
2. Spawn one parallel `general-purpose` Task agent per todo in the batch. Each agent:
   - Calls `mcp__proj__todo_check_executable` — if ⚠️ (manual-tagged): skip, record warning.
   - Otherwise: executes using execute instructions, calls `todo_complete`.
3. Wait for batch to complete. Collect results including any manual-skips. If any agent terminates with an error or exception (non-success result), capture the error message and display `⚠️ Agent for todo <id> failed: <error>`. Mark that todo as failed (`❌`) in the final summary. Continue remaining batches. Do not re-run failed agents automatically.

After all batches complete:
- Count `manual_skipped` = number of todos where execute was skipped (⚠️ manual-tagged).
- If `manual_skipped == 0`: display `✅ All todos executed successfully.`
- If `manual_skipped > 0`: display `⚠️ <manual_skipped> todo(s) were manual-tagged and skipped.`
- Auto-complete parent logic: if `manual_skipped == 0`, call `mcp__proj__todo_complete` with the parent todo ID; if the parent has a `todoist_task_id`, call `mcp__claude_ai_Todoist__complete-tasks` with that ID; display `✅ Parent todo <id> auto-completed.`. If `manual_skipped > 0`: display `⚠️ Parent not auto-completed (<manual_skipped> manual-tagged todo(s) — complete manually when ready).`

Store `execute_all_manual_skipped = manual_skipped` and `execute_all_completed = (execute_all_total - manual_skipped)` for step 7.

**For a range of todos**

Execute this path when $ARGUMENTS is a range (e.g. `2-5`) or comma list (e.g. `1,3,5`). Interactive review and confirm prompts are **skipped** — all steps run autonomously.

**a. Load the workflow step list and step instructions**

- Determine the base step list: read `<parent-of-this-skill's-base-dir>/workflows/full-workflow.yaml` and parse `steps`. Fall back to `[define, research, decompose, execute]` if unreadable.
- Apply any `--steps` / `--from` flags as in step 2 above.
- Determine iteration mode:
  - If `--iter-as-needed[=N]` was given: set `iter_mode = "as-needed"`, `iter_max = N` (or 5 if N omitted)
  - If `--iter N` was given: set `iter_mode = "fixed"`, `iter_max = N`
  - Otherwise: set `iter_mode = "fixed"`, `iter_max = 1`
- All agents will run with `--iter 1` (single pass per iteration of the batch loop)
- Determine interactive mode:
  - `no_interactive` = `--no-interactive` flag was given
  - `run_define_interactive` = `"define" in active_step_list AND NOT no_interactive`
  - `has_execute_in_batch` = `"execute" in active_step_list`
  - `agent_steps` = active_step_list excluding "define" AND "execute" (if `run_define_interactive`), else active_step_list excluding "execute"
  - `define_only` = (`run_define_interactive` AND `agent_steps` is empty)
- For each step in `agent_steps`, read `<parent-of-this-skill's-base-dir>/<step>/SKILL.md` and extract the Markdown instructions. Store as `step_instructions[<step>]`.
- If `run_define_interactive`: also read `<parent-of-this-skill's-base-dir>/define/SKILL.md` once and store as `define_instructions` (reused for all todos in Phase A).

**b. Identify dependency-ordered batches**

- Call `mcp__proj__proj_identify_batches` with the full list of todo ID strings.
- Returns: `{"batches": [["1","2"],["3"]], "order": [...], "cycles": [...], "missing": [...]}`.
- If `cycles` is non-empty: stop with an error listing the circular dependencies.
- If `missing` is non-empty: display a warning for those IDs, then continue with the remaining todos.

**Initialize iteration state**:
- `remaining_todos = list of all deduplicated todo IDs`
- `converged_todos = {}` # id → True/False
- `show_iteration_header = (iter_mode == "as-needed" and iter_max > 1)`

**Iteration loop**:

For each iteration `i` from 1 to `iter_max`:

If `show_iteration_header`, display:
```
════════════════════════════
Iteration <i>/<iter_max>
════════════════════════════
```

**c. Execute each batch in sequence**

**If `run_define_interactive` is true:**

**Phase A — Define (sequential, interactive)**

Read `define_instructions` (already loaded above). For each batch in dependency order (using only `remaining_todos`), for each todo in the batch (in ID order):

Display:
```
━━━━━━━━━━━━━━━━━━━━━━━━
Define: <todo-id> — <todo-title>
━━━━━━━━━━━━━━━━━━━━━━━━
```
Execute define for this todo interactively in the main conversation (full Q&A with user), using `define_instructions` with `$ARGUMENTS` replaced by the todo ID.

**If `define_only` is true** (`agent_steps` is empty): skip Phase B. Set `converged_todos[id] = True` for all todos. Proceed to convergence prompts / early exit check.

**Phase B — Remaining steps (parallel agents)**

For each batch in the dependency order (using only `remaining_todos`):

1. Display: `Batch <N>/<total> — <agent_steps joined "→">: todos <id1>, <id2>, ...`
2. Spawn one parallel `general-purpose` Task agent per todo in `remaining_todos`. Each agent receives: the todo ID, `agent_steps` as the step list, the step instructions for those steps (with `$ARGUMENTS` replaced by the todo ID), `--iter 1` (single pass), and instructions to run autonomously without prompting the user. Each agent must compute convergence assessment for the steps it ran and include it in the result as `{converged: bool, reason: str}`.
3. Wait for all agents in the batch to complete before proceeding to the next batch. If any agent terminates with an error or exception (non-success result), capture the error message and display `⚠️ Agent for todo <id> failed: <error>`. Mark that todo as failed (`❌`) in the aggregated summary. Continue remaining batches. Do not re-run failed agents automatically.
4. Collect each agent's result: todo ID, final status, any errors, **and convergence status**.

**If `run_define_interactive` is false** (either `--no-interactive` or `define` not in active_step_list):

For each batch in the dependency order (using only `remaining_todos`):

1. Display: `Batch <N>/<total>: todos <id1>, <id2>, ...`
2. Spawn one parallel `general-purpose` Task agent per todo in `remaining_todos`. Each agent receives: the todo ID, `agent_steps` as the step list, the step instructions for those steps (with `$ARGUMENTS` replaced by `<todo-id> --no-interactive` for the define step when `no_interactive=True`, otherwise `<todo-id>`), `--iter 1` (single pass), and instructions to run all steps without prompting the user. Each agent must compute convergence assessment and include it in the result as `{converged: bool, reason: str}`.
3. Wait for all agents in the batch to complete before proceeding to the next batch. If any agent terminates with an error or exception (non-success result), capture the error message and display `⚠️ Agent for todo <id> failed: <error>`. Mark that todo as failed (`❌`) in the aggregated summary. Continue remaining batches. Do not re-run failed agents automatically.
4. Collect each agent's result: todo ID, final status, any errors, **and convergence status**.

**Convergence-based prompts** (only if `iter_mode == "as-needed" and iter_max > 1 and i < iter_max and NOT no_interactive`):

For each todo in `remaining_todos`:
- Update `converged_todos[todo_id]` from agent result
- If `converged_todos[todo_id] == True`: skip prompt (no user interaction)
- Else: display convergence reason and prompt:
  ```
  Todo <id>: <reason from agent>
  1. Continue iteration <i+1>
  2. Stop (mark converged)

  Enter 1 or 2:
  ```
- If user selects "Stop": remove `todo_id` from `remaining_todos`

**Early exit check** (after convergence prompts):
- If `remaining_todos` is empty OR all todos in `remaining_todos` have `converged_todos[id] == True`: break from iteration loop immediately (skip remaining iterations and proceed to Phase C)

**Phase C — Execute (runs once, after loop exits)**

If `has_execute_in_batch` is false or `remaining_todos` is empty: skip to section d.

If NOT `no_interactive`, prompt:
```
### Prep complete (<i> iteration(s)) — Execute?

1. **Execute all** → Run execute on all todos in parallel
2. **Stop** → Exit workflow now (prep steps are saved)

Enter 1 or 2:
```
- **Execute all** (1, "execute", "proceed"): continue.
- **Stop** (2, "stop", "s"): display summary and exit cleanly.

If `no_interactive`: proceed directly without prompt.

Read `<parent-of-this-skill's-base-dir>/execute/SKILL.md` instructions once.

For each batch in dependency order (using `remaining_todos`):
1. Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
2. Spawn one parallel `general-purpose` agent per todo. Each agent:
   - Calls `mcp__proj__todo_check_executable` — if ⚠️ (manual-tagged): skip, record warning.
   - Otherwise: executes using execute instructions, calls `todo_complete`.
3. Wait for batch to complete. Collect results including any manual-skips. If any agent terminates with an error or exception (non-success result), capture the error message and display `⚠️ Agent for todo <id> failed: <error>`. Mark that todo as failed (`❌`) in the aggregated summary (section d). Continue remaining batches. Do not re-run failed agents automatically.

**d. Aggregated summary**

Display a per-batch breakdown and overall count. If `iter_mode == "as-needed"`, also show:
- Total iterations completed
- Count of todos that converged
- Count of todos that stopped early by user selection
- Count of todos that ran to `iter_max` without converging

Phase C results:
- Count of todos executed successfully
- Count of manual-skipped todos (show `⚠️ Todo <id> [manual] — skipped execute` for each)

Call `mcp__proj__notes_append` with a one-line summary. Then stop — do not fall through to step 6 below.

**6. Children workflow (edge-case fallback — not used in normal full-workflow)** (only if `has_children` is true, `children_converged` is false due to `--steps` limiting prep, `execute_all_path` is false, and user did not stop)

> **When this path applies:** This section is only reached when `--steps` excluded the research/decompose steps, leaving children without prep. In normal full-workflow runs, step 4 handles all descendants (define → research → decompose) and step 5ii executes parent + all children together. When that path runs, step 6 is skipped entirely. Step 6 exists solely as a fallback so children are not left unprocessed when the caller limited prep steps via `--steps`.

**a.** Call `mcp__proj__todo_get` with the parent ID — read the fresh `todo.children` list (includes any subtodos created during decompose).

**b. Define phase (sequential, interactive)** — for each child in ID order:

i. Announce:
```
════════════════════════════
Child <N>/<total>: <child-id> — <child-title>
════════════════════════════
```
ii. Read `<parent-of-this-skill's-base-dir>/define/SKILL.md` and extract the Markdown instructions.
iii. Execute define for this child interactively (full Q&A with user). Apply `--iter`/`--iter-as-needed` flags if given.

**c. Research phase (parallel, autonomous)** — after all children have completed define:

i. Announce: `Running research for all children in parallel...`
ii. Read `<parent-of-this-skill's-base-dir>/research/SKILL.md` and extract the instructions.
iii. Spawn one background `general-purpose` Task agent per child. Each agent receives: the child's ID, its requirements, and the research instructions. Each agent runs research autonomously and writes research.md.
iv. Wait for all research agents to complete.

**d. Decompose phase (sequential confirmation)** — for each child in order (skip if `decompose` not in active step list):

i. Announce:
```
━━━━━━━━━━━━━━━━━━━━━━━━
Decompose: <child-id> — <child-title>
━━━━━━━━━━━━━━━━━━━━━━━━
```
ii. Read `<parent-of-this-skill's-base-dir>/decompose/SKILL.md` and extract the instructions.
iii. Execute decompose for this child — propose the breakdown and ask the user to confirm, edit, or skip. Only create subtodos after user confirmation.

**e. Execute phase (parallel, autonomous)** — after all decompositions confirmed (skip if `execute` not in active step list):

i. Prompt:
```
### All children prepared — Execute?

1. **Execute all children** → Run execute on all in parallel
2. **Edit** → Re-run a specific child's last step (specify which)
3. **Stop** → Exit workflow now (all prep steps saved)

Enter 1, 2, or 3:
```
Handle responses:
- **Execute all children** (1, "execute", "proceed"): continue.
- **Edit** (2): ask which child and which step to re-run. Run it, then return to this prompt.
- **Stop** (3, "stop", "s"): exit cleanly.

ii. Spawn one `general-purpose` Task agent per child. Each agent:
   - Calls `mcp__proj__todo_check_executable` — if ⚠️ (manual-tagged): skip, record warning.
   - Otherwise: reads execute/SKILL.md, executes, calls `todo_complete`.
iii. Collect results. For any `manual`-tagged children: show `⚠️ Child <id> [manual] — skipped execute`.
iv. **Auto-complete parent** (only if `execute` is in the active step list):
   - Count `manual_skipped` = number of children where execute was skipped (⚠️ manual-tagged).
   - If `manual_skipped == 0` (all children executed successfully):
     - Call `mcp__proj__todo_complete` with the parent todo ID.
     - If the parent has a `todoist_task_id`: call `mcp__claude_ai_Todoist__complete-tasks` with that ID.
     - Display: `✅ Parent todo <id> auto-completed.`
   - If `manual_skipped > 0`:
     - Display: `⚠️ <manual_skipped> child(ren) were manual-tagged — parent not auto-completed. Complete manually when ready.`
v. Call `mcp__proj__notes_append` with one-line summary of children execution (include parent auto-complete result).

**7. Workflow complete**

Display:
```
✅ Full workflow complete for todo <id>: <title>

Steps completed: <step1>, <step2>, ...
```

If `execute_all_path` is true (step 5ii ran — execute-all path), display:
```
Todos: <execute_all_total> processed via execute-all (<execute_all_completed> completed, <execute_all_manual_skipped> manual-skipped)
```
If `execute_all_manual_skipped == 0`: `✅ Parent auto-completed.`
If `execute_all_manual_skipped > 0`: `⚠️ Parent not auto-completed (<execute_all_manual_skipped> manual-tagged todo(s) — complete manually).`

If step 6 ran (children workflow path), display:
```
Children: <N> processed via children workflow (<completed> completed, <manual-skipped> manual-skipped)
```
If `manual_skipped == 0`: `✅ Parent auto-completed.`
If `manual_skipped > 0`: `⚠️ Parent not auto-completed (<manual_skipped> manual-tagged children — complete manually).`

If neither `execute_all_path` nor step 6 ran (no children, or children were skipped): omit the children line entirely.

Call `mcp__proj__notes_append` with a brief summary of the workflow run.

💡 Suggested next: /proj:status — see updated project overview

---
name: prep-workflow
description: Run the prep workflow (define → research → decompose) on a todo interactively, with optional --iter N to repeat the cycle N times. Each iteration builds on the previous. Use when asked "prep workflow on 1", "run prep for 2", or "proj:prep-workflow 1".
disable-model-invocation: "true"
allowed-tools: mcp__proj__claudemd_write, mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_active, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__claude_ai_Todoist__complete-tasks, Read, Task
argument-hint: "<todo-id> [--iter N | --iter-as-needed[=N]] [--steps define,research] [--from <step>] [--no-interactive]"
---

Run prep-workflow for: $ARGUMENTS

**1. Parse and validate**

Inspect $ARGUMENTS to determine the input mode and extract flags:

- **Input mode** — check the first non-flag token:
  - **Single ID**: a plain todo ID with no range syntax (e.g. `1`, `3.2`).
  - **Range**: two integers separated by a hyphen (e.g. `2-5`) — expands to all IDs in that inclusive range.
  - **Comma list**: multiple IDs separated by commas (e.g. `1,3,5`).
- **`--iter N`**: if present, extract N as the number of prep iterations (default 1). N must be a positive integer.
- **`--steps <csv>`**: if present, extract the comma-separated step names. Used as the explicit step list (validated and reordered in step 2).
- **`--from <step>`**: if present, extract the single step name. Slices the workflow step list from that step onward (inclusive).
- **`--iter-as-needed[=N]`**: if present, use adaptive iteration mode in batch mode — iterate until convergence, up to N iterations max (default 5 if N omitted). N must be a positive integer. Only applies to range/comma-list input.
- **`--no-interactive`**: if present, run all batch steps autonomously with no user prompts — define runs inside agents, convergence prompts are suppressed. Restores original batch behaviour. (Ignored for single-ID input.)
- If both `--steps` and `--from` are given, `--steps` takes precedence; ignore `--from`.
- If no todo ID is present, stop with: `Todo ID required. Usage: /proj:prep-workflow <id> [--iter N] [--steps define,research] [--from <step>]`

For **single ID**: call `mcp__proj__todo_get` to confirm it exists. If not found, stop with a clear error. Then continue to step 2.

For **range or comma list**: parse into a flat deduplicated list of todo ID strings (e.g. `"2-5"` → `["2","3","4","5"]`). Then skip to **"For a range of todos"** below.

**2. Load the workflow step list**

- This skill's base directory ends in `.../skills/prep-workflow`. The sibling skill directories are at `.../skills/<step>/`.
- Read the workflow YAML: `<parent-of-this-skill's-base-dir>/workflows/prep-workflow.yaml`
  - Parse the `steps` list. If the file cannot be read, fall back to the default: `[define, research, decompose]`.
- Apply flag filters to produce the active step list:
  - If `--steps` was given: filter to only those steps, reordered to match workflow YAML order. Error if any step name is invalid (list valid names).
  - If `--from` was given (and no `--steps`): slice from that step to the end. Error if step name not found.
  - If neither flag: use the full step list.
- If the active step list is empty, stop with: `No steps to execute after applying filters.`
- Display: `Running prep-workflow on todo **<id>** — <title>`
- Display: `Steps: <step1> → <step2> → ... (×<N> iterations)` (omit `×<N>` if N=1)

**3. Iteration loop**

Repeat the following N times (tracked as iteration i, from 1 to N):

**a. Announce the iteration (only if N > 1)**

Display:
```
════════════════════════════
Iteration <i>/<N>
════════════════════════════
```

**b. For each step in the active step list:**

i. Announce the step:
```
━━━━━━━━━━━━━━━━━━━━━━━━
Step <step-index>/<total-steps>: <step-name>
━━━━━━━━━━━━━━━━━━━━━━━━
```

ii. Read the step's SKILL.md:
- Construct the path: `<parent-of-this-skill's-base-dir>/<step>/SKILL.md`
- Call `Read` on that path to load the skill file.
- Extract the Markdown instructions — everything after the second `---` frontmatter delimiter.

iii. Execute the step: follow the extracted step instructions exactly, using `<todo-id>` as the argument. Each iteration builds on the previous — define/research skills already handle existing requirements.md and research.md by refining them.

iv. Show a step summary using `## Step: <step-name> — Complete`:
- **define** → Call `mcp__proj__content_get_requirements`. Display the full `## Acceptance Criteria` section.
- **research** → Call `mcp__proj__content_get_research`. Display the full `## Recommended Approach` section.
- **decompose** → Call `mcp__proj__todo_tree`. Render as a nested bullet list showing each subtodo's ID, title, status.

**c. Prompt between iterations** (skip after the last iteration)

```
### Iteration <i>/<N> complete — Next Action?

1. **Continue** → Start iteration <i+1>/<N>
2. **Edit** → Modify this iteration's output (describe changes)
3. **Stop** → Exit workflow now (completed steps are saved)

Enter 1, 2, or 3 (or "continue" / "edit" / "stop"):
```

Handle responses:
- **Continue** (1, "continue", "c", "proceed"): advance to the next iteration.
- **Edit** (2, "edit", "e"): ask what to change. Then ask: "(a) re-run the last step with this input, or (b) apply as a direct update and continue?" Act accordingly.
- **Stop** (3, "stop", "s"): display a summary of completed iterations and exit cleanly.

**4. Workflow complete** (single-todo path only)

Display:
```
✅ Prep workflow complete for todo <id>: <title>

Iterations completed: <N>
Steps per iteration: <step1>, <step2>, ...
```

Call `mcp__proj__notes_append` with a brief summary of the workflow run.

💡 Suggested next: /proj:execute <id> — implement using the refined requirements and research

---

**For a range of todos**

Execute this path when $ARGUMENTS is a range (e.g. `2-5`) or comma list (e.g. `1,3,5`). Interactive review and confirm prompts are **skipped** — all steps run autonomously in batch mode, except for convergence checks if `--iter-as-needed` is used.

**a. Load the workflow step list and step instructions**

- Determine the base step list: read `<parent-of-this-skill's-base-dir>/workflows/prep-workflow.yaml` and parse `steps`. Fall back to `[define, research, decompose]` if unreadable.
- Apply any `--steps` / `--from` flags as in step 2 above.
- Determine interactive mode:
  - `no_interactive` = `--no-interactive` flag was given
  - `run_define_interactive` = `"define" in active_step_list AND NOT no_interactive`
  - `agent_steps` = active_step_list excluding "define" (if `run_define_interactive`) else full active_step_list
  - `define_only` = (`run_define_interactive` AND `agent_steps` is empty)
- For each step in `agent_steps`, read `<parent-of-this-skill's-base-dir>/<step>/SKILL.md` and extract the Markdown instructions. Store as `step_instructions[<step>]`.
- If `run_define_interactive`: also read `<parent-of-this-skill's-base-dir>/define/SKILL.md` once and store as `define_instructions` (reused for all todos in Phase A).

**b. Identify dependency-ordered batches**

- Call `mcp__proj__proj_identify_batches` with the full list of todo ID strings.
- Returns: `{"batches": [["1","2"],["3"]], "order": [...], "cycles": [...], "missing": [...]}`.
- If `cycles` is non-empty: stop with an error listing the circular dependencies.
- If `missing` is non-empty: display a warning for those IDs, then continue with the remaining todos.

**Determine iteration mode**:
- If `--iter-as-needed[=N]` was given: set `iter_mode = "as-needed"`, `iter_max = N` (or 5 if N omitted)
- Otherwise: set `iter_mode = "fixed"`, `iter_max = N` (or 1 if no `--iter` flag)
- All agents will run with `--iter 1` per iteration (single pass; iteration loop is controlled here, not in agents)

**Initialize iteration state**:
- `remaining_todos = list of all deduplicated todo IDs`
- `converged_todos = {}` # id → True/False convergence status
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
3. Wait for all agents in the batch to complete before proceeding to the next batch.
4. Collect each agent's result: todo ID, final status, any errors, **and convergence status**.

**If `run_define_interactive` is false** (either `--no-interactive` or `define` not in active_step_list):

For each batch in the dependency order (using only `remaining_todos`):

1. Display: `Batch <N>/<total>: todos <id1>, <id2>, ...`
2. Spawn one parallel `general-purpose` Task agent per todo in `remaining_todos`. Each agent receives: the todo ID, the active step list, the step instructions (with `$ARGUMENTS` replaced by the todo ID), `--iter 1` (single pass), and instructions to run without prompting the user. Each agent must compute and return convergence assessment as `{converged: bool, reason: str}`. Include this in the result: `{todo_id, final_status, errors, convergence: {converged, reason}}`.
3. Wait for all agents in the batch to complete before proceeding to the next batch.
4. Collect each agent's result: todo ID, final status, any errors, **and convergence status**.

**Convergence-based prompts** (only if `iter_mode == "as-needed" and iter_max > 1 and i < iter_max and NOT no_interactive`):

For each todo in `remaining_todos`:
- Update `converged_todos[todo_id]` from agent result
- If `converged_todos[todo_id] == True`: skip prompt (no user interaction)
- Else: display convergence reason and prompt:
  ```
  Todo <id>: <reason from agent>
  1. Continue iteration <i+1>
  2. Stop (exit prep workflow)

  Enter 1 or 2:
  ```
- If user selects "Stop": remove `todo_id` from `remaining_todos`

**Early exit check** (after convergence prompts):
- If `remaining_todos` is empty OR all todos in `remaining_todos` have `converged_todos[id] == True`: break from iteration loop immediately (skip remaining iterations and proceed to aggregated summary)

*End of iteration loop*

**d. Aggregated summary**

Display a per-batch breakdown and overall count. If `iter_mode == "as-needed"`, also include:
- Total iterations completed (≤ iter_max)
- Count of todos that converged before iteration iter_max
- Count of todos that stopped early (user selection)
- Count of todos that ran to `iter_max` without converging

For each stopped-early todo, note: "Todo <id> — stopped at iteration <N>"

Call `mcp__proj__notes_append` with a one-line summary. Then stop.

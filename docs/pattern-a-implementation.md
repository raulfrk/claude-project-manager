# Pattern A Implementation Specification

## Overview

Implement the Sequential Plan, Parallel Execute pattern in the execute/SKILL.md.

**Key changes:**
1. Phase 1 collects all approved plans before Phase 2 starts (explicit approval gate)
2. Phase 2 passes approved plans to Task agents
3. Phase 3 runs satisfaction loops with iteration support

---

## Phase 1: Sequential Planning with Approval Gate

### Input
- Todo range (e.g., `2-4`)
- All todos checked for executability

### Algorithm

```
approved_plans = []
skipped_todos = []

for todo_id in range:
  1. if todo_check_executable(todo_id) starts with "⚠️":
       skip(todo_id, reason="manual")
       continue

  2. context = proj_get_todo_context(todo_id, include_parent=true)

  3. EnterPlanMode
     - Read requirements.md, research.md, parent context
     - Explore relevant source files
     - Create implementation plan:
       * Files to modify/create
       * Key changes per file
       * Implementation order
       * Testing approach

  4. ExitPlanMode → presents plan to user

  5. **APPROVAL GATE**: Wait for user feedback
     - If user says "go ahead" / no objection:
         approved_plans.append({todo_id, plan, context})
     - If user says "change X" / "modify":
         re-plan (go to step 3)
     - If user says "skip" / "next":
         skipped_todos.append(todo_id)

after Phase 1:
  - approved_plans is ordered list of (todo_id, plan, context) tuples
  - skipped_todos is list of manually skipped todos
  - output summary: "Ready to execute N todos in Phase 2"
```

### User Interaction Model

**Implicit Approval:** User sees plan from ExitPlanMode, does not object → approved

**Explicit Approval:** User can say:
- "looks good" / "go ahead" / "approved" → proceed
- "change X to Y" → re-plan with feedback
- "skip this" / "next" → skip and move to next todo
- "stop" → exit Phase 1 early

### Output to User

After each plan exits:
```
[Todo 2] Implementation Plan
Files to modify:
  - src/cli.py (add --force flag, update argument parser)
  - tests/test_cli.py (add test for --force)

Key changes:
  1. Parser: add --force to argparse (line 45-48)
  2. Handler: update handle_delete() to check force flag
  3. Tests: parametrized test for force={True,False}

Order:
  1. Modify parser
  2. Update handler
  3. Write tests
  4. Manual test: python cli.py delete --force

Ready to execute? (go ahead / change / skip)
```

---

## Phase 2: Parallel Execution with Approved Plans

### Input
- `approved_plans`: list of (todo_id, plan, context) from Phase 1
- `skipped_todos`: list of manual-tagged todos (noted in Phase 3 summary)

### Algorithm

```
agents = []

for (todo_id, plan, context) in approved_plans:
  agent = spawn_task_agent(
    name=f"executor-{todo_id}",
    todo_id=todo_id,
    todo_details=context.todo,
    parent_context=context.parent,
    requirements=context.requirements,
    research=context.research,
    approved_plan=plan,  # <-- KEY: pass the approved plan

    # Instructions to agent:
    # 1. Mark todo status="in_progress"
    # 2. Implement per approved_plan strictly (no deviations)
    # 3. Do NOT mark todo complete
    # 4. Return: {status, code_changes, test_results, errors}
  )
  agents.append(agent)

# All agents run in parallel
# Main thread waits for all agents to complete
results = wait_for_all(agents)

phase_2_output = {
  completed: {todo_id: result for result in results if result.status == "success"},
  failed: {todo_id: result for result in results if result.status == "error"},
  skipped: skipped_todos
}

return phase_2_output
```

### Task Agent Instructions

Each executor agent receives:
```
You are executing todo {todo_id}.

**Approved Plan (from Phase 1):**
{approved_plan}

**Your Tasks:**
1. Mark todo status="in_progress" immediately
2. Implement according to the approved plan EXACTLY
   - Do not deviate from the plan without explicit user input
   - If implementation reveals the plan is wrong, STOP and report in return value
3. Follow the implementation order specified in the plan
4. Use test approach from the plan
5. Do NOT mark todo complete (Phase 3 handles satisfaction + completion)

**Return Value:**
{
  "status": "success|error",
  "code_changes": ["file1", "file2", ...],
  "test_results": "...",
  "satisfaction_ready": true,
  "errors": "...",
  "messages": "..."
}
```

### Parallelism

- All agents run concurrently
- Phase 2 time = max(agent execution times)
- No dependencies between agents (if there are, execute sequentially)

---

## Phase 3: Sequential Satisfaction Checks with Iteration

### Input
- `phase_2_output`: results from all agents

### Algorithm

```
for todo_id in approved_plans:
  if todo_id in phase_2_output.failed:
    - Report error to user
    - Ask: "Continue to next todo?" / "Retry?" / "Create fix todo?"
    - Handle accordingly
    - Continue to next todo

  if todo_id in phase_2_output.completed:
    result = phase_2_output.completed[todo_id]

    # Review agent's work
    - Display code changes, test results
    - Summarize what was done

    # SATISFACTION LOOP
    ask_user: "Are you satisfied with this outcome?"

    while not satisfied:
      capture_missing_work()
      new_todo = create_todo_from_feedback()
      execute(new_todo)  # Re-run this skill on the new todo
      ask_user: "Satisfied now?"

    # COMPLETION
    mark_todo_complete(todo_id)
    sync_to_todoist_if_enabled(todo_id)
    sync_to_trello_if_enabled(todo_id)

# Summary for Phase 3
report_summary:
  - Completed: [N todos]
  - Failed: [M todos with errors]
  - New todos created via satisfaction: [K todos]
  - Skipped (manual): [L todos]

# Final git flush
git_flush(message=f"Execute: batch of {len(approved_plans)} todos")
```

### Satisfaction Loop Detail

```python
satisfied = false
iteration = 0
max_iterations = 5

while not satisfied and iteration < max_iterations:
  iteration += 1

  ask_user: "Are you satisfied with {todo_id}?"
  response = get_user_input()

  if response == "yes" / "satisfied":
    satisfied = true
    break

  elif response == "no" / "not satisfied":
    prompt_user: "What's missing or needs to be fixed?"
    missing_work = get_user_description()

    # Create new child todo
    new_todo = todo_add_child(
      parent_id=todo_id,
      title="Fix: {missing_work}",
      description=missing_work
    )

    # Execute the new todo
    execute_todo(new_todo)

    ask_user: "Try again with {original_todo}?"
    if user_wants_to_try_again:
      # Ask satisfaction again (loop continues)
      continue
    else:
      satisfied = true  # Accept partial completion
      break

  elif response == "skip":
    # Mark as done without full satisfaction
    satisfied = true
    break

if iteration >= max_iterations:
  # Too many iterations, ask user
  ask_user: "Hit iteration limit. Mark as done?"
  if user_agrees:
    satisfied = true
```

### Output to User (Phase 3 Summary)

```
Phase 3: Satisfaction Checks & Completion
=========================================

✅ Todo 2: Added --force flag
   - Reviewed: 3 files changed, 12 tests passing
   - Satisfied? yes

✅ Todo 3: Refactored argument parser
   - Reviewed: 1 file changed, 5 tests passing
   - Satisfied? yes → (1 new todo created for "add --verbose", completed and satisfied)

⚠️  Todo 4: Update docs
   - Agent error: docs file not found
   - Status: FAILED
   - Action: Create fix todo?

⏭️  Skipped: Todo 5 (manual tag)

Summary:
- Completed: 2 todos
- With iterations: 1 todo (1 new child todo created)
- Failed: 1 todo
- Skipped: 1 todo

Next steps:
1. (optional) /proj:execute 4 to handle failed todo
2. /proj:status to see updated project
3. /proj:save to persist changes
```

---

## Data Flow Diagram

```
Phase 1 (Sequential)
====================
Main Conversation
  ├─ Todo 2: check executable
  │  ├─ get context
  │  ├─ EnterPlanMode → plan → ExitPlanMode
  │  └─ [User approves] → approved_plans.append({2, plan, context})
  │
  ├─ Todo 3: ... [same] → approved_plans.append({3, plan, context})
  │
  └─ Todo 4: ... [same] → approved_plans.append({4, plan, context})

Phase 2 (Parallel)
==================
  ├─ Agent-2: implement todo 2 per approved plan
  ├─ Agent-3: implement todo 3 per approved plan (concurrent)
  └─ Agent-4: implement todo 4 per approved plan (concurrent)

Phase 3 (Sequential)
====================
Main Conversation
  ├─ Todo 2: review result → satisfaction loop → mark complete
  ├─ Todo 3: review result → satisfaction loop → mark complete
  └─ Todo 4: review result → satisfaction loop → mark complete
```

---

## Changes to execute/SKILL.md

### For Single Todo (No Changes)
- Already implements Phase 1+3 in sequence
- Keep as-is

### For Range with Independent Todos
Replace Phase 1/2/3 section with:

```markdown
**Phase 1 — Plan (sequential, in main conversation):**

For each todo in the range:
1. Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with
   `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
2. Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
3. Call `EnterPlanMode`. Create an implementation plan covering:
   - Files to modify/create
   - Key changes per file
   - Implementation order
   - Testing approach
4. Call `ExitPlanMode` to present the plan for user review.
5. **Wait for user approval** (implicit: user doesn't object, or explicit: "go ahead"):
   - If user says "change X" / "modify": re-plan (go to step 3)
   - If user says "skip" / "next": skip to next todo
   - Otherwise: store approved plan + context for Phase 2

After all plans are reviewed and approved, proceed to Phase 2.

**Phase 2 — Execute (parallel Task agents):**

Spawn one `general-purpose` Task agent per todo (excluding manual-skipped ones).
Each agent receives:
- The todo details
- Its requirements.md and research.md
- Parent context
- **The approved implementation plan from Phase 1**

Each agent:
1. Marks todo status="in_progress"
2. Implements according to the approved plan exactly
3. Returns: {status, code_changes, test_results, errors}
4. Does NOT call `todo_complete`

All agents run in parallel. Phase 2 completes when all agents finish.

**Phase 3 — Satisfaction check (sequential, main conversation):**

For each todo (in order, excluding manual-skipped):
1. Review the agent's output (code changes, test results, etc.)
2. Run the satisfaction loop:
   a. Ask: "Are you satisfied with the outcome?"
      - **Satisfied**: proceed to step 2c
      - **Not satisfied**: describe what's missing
   b. If not satisfied:
      - Create a new todo from the user's description
      - Execute the new todo with `/proj:execute <new_id>`
      - Ask satisfaction again (loop)
   c. Call `mcp__proj__todo_complete`
      - If Todoist enabled: sync completion
      - If Trello auto-sync enabled: sync checklist item
3. After all todos: append progress note with `mcp__proj__notes_append`

Report Phase 3 summary: completed, with-iterations, failed, skipped counts.
```

### For Range with Dependencies
Replace Phase 1/2/3 section with:

```markdown
**Phase 1 — Plan (sequential, in dependency order):**

Execute in topological order (respect blocked_by chains). For each todo:
1. Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with
   `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
2. Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
3. Call `EnterPlanMode`. Create an implementation plan.
4. Call `ExitPlanMode` for user review.
5. **Wait for user approval** (implicit or explicit as above):
   - If user says "change X" / "modify": re-plan
   - If user says "skip": skip to next todo
   - Otherwise: store approved plan + context

After all plans reviewed, proceed to Phase 2.

**Phase 2 — Execute (sequential, in dependency order):**

Execute each todo according to its approved plan, one at a time (respecting blocked_by chains).
For each todo:
1. Mark status="in_progress"
2. Implement per approved plan
3. Return results (does NOT mark complete)

**Phase 3 — Satisfaction check (sequential, main conversation):**

Same as Phase 3 for independent todos.
```

---

## Migration & Rollout

1. **Update execute/SKILL.md** with new Phase 1/2/3 flow (this spec)
2. **Test with single todo** — ensure ExitPlanMode approval works
3. **Test with 2-3 independent todos** — verify Phase 1→2→3 flow
4. **Test with dependencies** — verify topological ordering in Phase 2
5. **Document approval interaction** — make it clear to users how to approve plans

---

## Success Criteria

- ✅ Phase 1 blocks until user approves all plans
- ✅ Phase 2 executes all approved todos in parallel (or sequential for dependencies)
- ✅ Phase 3 satisfaction loop creates new todos as needed
- ✅ Code changes are minimal (reuse existing SKILL.md patterns)
- ✅ User can reject/modify any plan before Phase 2 starts
- ✅ All todos marked complete only after satisfaction check

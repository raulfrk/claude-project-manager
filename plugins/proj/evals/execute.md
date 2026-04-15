# E2E Eval: execute

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/execute/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `proj_init` with `name="eval-test-execute"`, `path="/tmp/claude-1000/eval-execute"`
- Call `proj_load_session`
- Call `todo_add` with `title="Test todo for eval"`, `priority="medium"` — store returned ID as `TODO_ID`
- Pre-populate requirements via `content_set_requirements` with:
  ```
  # Requirements: Test todo for eval
  ## Goal
  Create a Python utility function that validates email addresses using regex.
  ## Acceptance Criteria
  - [ ] Function `validate_email(email: str) -> bool` in `utils/validation.py`
  - [ ] Returns True for valid emails, False for invalid
  - [ ] Handles edge cases: empty string, missing @, missing domain
  - [ ] Unit tests in `tests/test_validation.py`
  ## Out of Scope
  - DNS validation of domain
  ## Testing Strategy
  Unit tests covering valid emails, invalid emails, and edge cases
  ```
- Pre-populate research via `content_set_research` with:
  ```
  # Research: Test todo for eval
  ## Approach Options
  ### Option 1: Simple regex
  Use a basic regex pattern. Pros: fast, no dependencies. Cons: may miss edge cases.
  ### Option 2: email-validator library
  Use third-party library. Pros: thorough. Cons: adds dependency.
  ## Recommended Approach
  Option 1 — simple regex is sufficient for the acceptance criteria.
  ## Key Dependencies
  - re (stdlib)
  ## Risks
  - Regex edge cases for international domains
  ```
- Call `todo_set_content_flag` with `todo_id=<TODO_ID>`, `has_requirements=True`, `has_research=True`

## Test Scenarios

### Scenario 1: Single todo execute with plan approval
- **Prompt**: Follow the skill instructions as if user said `/proj:execute <TODO_ID>`. Simulate user approval at plan review (step 3) and satisfaction at step 5.
- **Expected**: Per SKILL.md single-todo flow:
  - Step 1: Calls `todo_check_executable(todo_id=<TODO_ID>)` — returns JSON (not manual-tagged)
  - Step 2: Calls `proj_get_todo_context(todo_id=<TODO_ID>, include_parent=true)`
  - Step 3: Calls `EnterPlanMode` to create implementation plan, then `ExitPlanMode` to present for review (simulated approval)
  - Step 4: Calls `todo_update(todo_id=<TODO_ID>, status="in_progress")`, then implements the task: creates `utils/validation.py` with `validate_email` function and `tests/test_validation.py` with test cases
  - Step 5: Satisfaction loop (simulated: "Satisfied"), calls `todo_complete(todo_id=<TODO_ID>)`, calls `notes_append` with brief progress note
  - Step 6: Calls `tracking_git_flush` with `commit_message="Execute: <TODO_ID>"`
- **Assert**:
  - `todo_get(todo_id=<TODO_ID>)` shows `status="done"`
  - File `/tmp/claude-1000/eval-execute/utils/validation.py` exists and contains `def validate_email`
  - File `/tmp/claude-1000/eval-execute/tests/test_validation.py` exists

### Scenario 2: Manual-tagged todo is rejected
- **Prompt**: First create a manual todo: `todo_add` with `title="Manual task"`, `priority="low"`, `tags=["manual"]` — store as `MANUAL_ID`. Then follow the skill instructions as if user said `/proj:execute <MANUAL_ID>`.
- **Expected**: Per SKILL.md step 1:
  - Calls `todo_check_executable(todo_id=<MANUAL_ID>)`
  - Result starts with a warning indicating manual tag
  - Displays the warning as-is and stops — does NOT proceed to step 2 or implement anything
- **Assert**:
  - `todo_get(todo_id=<MANUAL_ID>)` shows `status` is NOT `"done"` and NOT `"in_progress"`

### Scenario 3: Empty arguments finds ready todo
- **Prompt**: Follow the skill instructions as if user said `/proj:execute` (no arguments, with `TODO_ID` in ready status)
- **Expected**: Per SKILL.md scope determination:
  - Empty arguments: calls `todo_list(status="in_progress")` — returns empty
  - Then calls `todo_list(status="ready")` — returns list including `TODO_ID`
  - Displays available todos and proceeds with the first one
- **Assert**:
  - The execute flow begins for the first ready todo

### Scenario 4: Range execute with independent todos runs parallel agents
- **Prompt**: First decompose `TODO_ID` into sub-todos (or manually create 2 independent children via `todo_add(parent=TODO_ID)`). Store child IDs as `CHILD_1` and `CHILD_2`. Pre-populate requirements and research for each. Then follow the skill instructions as if user said `/proj:execute <CHILD_1>-<CHILD_2>` (range syntax). Simulate plan approval and satisfaction for each.
- **Expected**: Per SKILL.md range-with-independent-todos flow:
  - Phase 1 (Plan): For each todo, calls `todo_check_executable`, `proj_get_todo_context`, `EnterPlanMode`, `ExitPlanMode` sequentially
  - Phase 2 (Execute): Spawns parallel Task agents for independent todos
  - Phase 3 (Satisfaction): Runs satisfaction loop sequentially for each completed todo, calls `todo_complete` for each
- **Assert**:
  - Both `todo_get(todo_id=<CHILD_1>)` and `todo_get(todo_id=<CHILD_2>)` show `status="done"`

## Cleanup
- Call `proj_archive` with the project ID for `eval-test-execute`
- Run `rm -rf /tmp/claude-1000/eval-execute`

# E2E Eval: decompose

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/decompose/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `proj_init` with `name="eval-test-decompose"`, `path="/tmp/claude-1000/eval-decompose"`
- Call `proj_load_session`
- Call `todo_add` with `title="Test todo for eval"`, `priority="high"` — store returned ID as `TODO_ID`
- Pre-populate requirements via `content_set_requirements` with:
  ```
  # Requirements: Test todo for eval
  ## Goal
  Build a REST API with authentication, database models, and test coverage.
  ## Acceptance Criteria
  - [ ] User model with email/password
  - [ ] JWT auth endpoints (login, register, refresh)
  - [ ] Integration tests for auth flow
  - [ ] API documentation
  ## Out of Scope
  - OAuth/social login
  ## Testing Strategy
  Unit tests for models, integration tests for endpoints
  ```
- Pre-populate research via `content_set_research` with:
  ```
  # Research: Test todo for eval
  ## Approach Options
  ### Option 1: FastAPI + SQLAlchemy
  Lightweight, async-native. Pros: fast, good docs. Cons: less mature ecosystem.
  ### Option 2: Django REST Framework
  Batteries-included. Pros: mature, ORM built-in. Cons: heavier, sync by default.
  ## Recommended Approach
  Option 1 — FastAPI + SQLAlchemy for async performance.
  ## Key Dependencies
  - fastapi, sqlalchemy, pyjwt
  ## Risks
  - Token refresh logic complexity
  ```
- Call `todo_set_content_flag` with `todo_id=<TODO_ID>`, `has_requirements=True`, `has_research=True`

## Test Scenarios

### Scenario 1: Decompose creates multi-level sub-todos
- **Prompt**: Follow the skill instructions as if user said `/proj:decompose <TODO_ID>`. Simulate user confirmation when the skill asks "Does this breakdown look good?" (step 6) by answering "yes".
- **Expected**: Per SKILL.md:
  - Step 1: Calls `todo_get(todo_id=<TODO_ID>)`
  - Step 2: Calls `content_get_requirements(todo_id=<TODO_ID>)`
  - Step 3: Calls `content_get_research(todo_id=<TODO_ID>)`
  - Step 3.5: Assesses atomicity — this todo has multiple separable concerns (models, auth endpoints, tests, docs), so it should NOT be skipped as atomic
  - Step 4: Proposes 3-8 sub-todos covering at least: database models, auth endpoints, tests, documentation
  - Step 4.5: Analyzes shared-file conflicts and adds `blocked_by` relationships
  - Step 5: Presents proposed breakdown as indented bullet points
  - Step 6: Asks for confirmation (simulated: "yes")
  - Step 7: Calls `todo_add` (with `parent=` param) for each sub-todo (parents before children), calls `todo_update(blocked_by_set=)` for dependency relationships
  - Step 8: Calls `todo_tree` to display final structure
  - Step 9: Calls `tracking_git_flush` with `commit_message="Decompose: <TODO_ID>"`
- **Assert**:
  - `todo_tree(todo_id=<TODO_ID>)` shows at least 3 children
  - At least one `blocked_by` relationship exists among the children
  - Each child has a non-empty title and a valid priority

### Scenario 2: Atomic todo is skipped
- **Prompt**: First create an atomic todo: `todo_add` with `title="Fix typo in README line 42"`, `priority="low"` — store as `ATOMIC_ID`. Then follow the skill instructions as if user said `/proj:decompose <ATOMIC_ID>`.
- **Expected**: Per SKILL.md:
  - Step 1: Calls `todo_get(todo_id=<ATOMIC_ID>)`
  - Steps 2-3: Calls `content_get_requirements` and `content_get_research` (if available)
  - Step 3.5: Assesses atomicity — single focused operation (edit one file), so it IS atomic
  - Output contains `Skipping decompose for <ATOMIC_ID> — already atomic`
  - Does NOT proceed to steps 4-9, does NOT call `todo_add` with `parent=`
- **Assert**:
  - `todo_get(todo_id=<ATOMIC_ID>)` has no children

### Scenario 3: Shared-file conflicts produce blocking relationships
- **Prompt**: Follow the skill instructions as if user said `/proj:decompose <TODO_ID>` (using the pre-populated todo with REST API requirements). Simulate user confirmation at step 6.
- **Expected**: Per SKILL.md step 4.5, the agent identifies that implementation and test sub-todos likely share files (e.g., conftest.py, test fixtures). Calls `todo_update(blocked_by_set=)` with shared-file reasoning for at least one pair of sub-todos.
- **Assert**:
  - `todo_tree(todo_id=<TODO_ID>)` shows at least one blocking relationship
  - The blocking relationship corresponds to sub-todos that would modify overlapping files

## Cleanup
- Call `proj_archive` with the project ID for `eval-test-decompose`
- Run `rm -rf /tmp/claude-1000/eval-decompose`

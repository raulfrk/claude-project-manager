# E2E Eval: run

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/run/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

Note: The run skill reads sibling SKILL.md files (define/SKILL.md, decompose/SKILL.md, execute/SKILL.md) and follows their instructions as sub-steps. This eval verifies the full chain.

## Setup
- Call `proj_init` with `name="eval-test-run"`, `path="/tmp/claude-1000/eval-run"`
- Call `proj_load_session`
- Call `todo_add` with `title="Test todo for eval"`, `priority="medium"` — store returned ID as `TODO_ID`

## Test Scenarios

### Scenario 1: Full workflow non-interactive (define, decompose, execute)
- **Prompt**: Follow the skill instructions as if user said `/proj:run <TODO_ID> --no-interactive`
- **Expected**: Per SKILL.md:
  - Step 1: Parses arguments — single ID, steps `[define, decompose, execute]`, `no_interactive=true`
  - Step 1 (validate): Calls `todo_get(todo_id=<TODO_ID>)` to confirm existence
  - Step 2: Displays: `Running workflow on todo <TODO_ID> — Test todo for eval`
  - Step 3 (iteration loop): Builds descendant list via `todo_tree`
  - **Define step**: Reads `define/SKILL.md`, follows its non-interactive path (calls `proj_get_todo_context`, explores codebase, writes requirements and research via `content_set_requirements`/`content_set_research`, calls `todo_set_content_flag`)
  - **Decompose step**: Reads `decompose/SKILL.md`, spawns Task agent to decompose autonomously, refreshes descendant list via `todo_tree`
  - Step 5 (execute): Reads `execute/SKILL.md`, calls `todo_check_executable` for each descendant, spawns parallel Task agents per batch (dependency order via `proj_identify_batches`), agents implement and do NOT call `todo_complete`
  - Calls `todo_complete` for completed todos
  - Step 6: Calls `notes_append` with summary
  - Step 7: Calls `tracking_git_flush` with `commit_message="Run: <TODO_ID>"`
- **Assert**:
  - `content_get_requirements(todo_id=<TODO_ID>)` returns non-empty content
  - `content_get_research(todo_id=<TODO_ID>)` returns non-empty content
  - `todo_tree(todo_id=<TODO_ID>)` shows children were created during decompose
  - `todo_get(todo_id=<TODO_ID>)` shows `status="done"`

### Scenario 2: Partial workflow with --steps flag
- **Prompt**: Follow the skill instructions as if user said `/proj:run <TODO_ID> --steps define,decompose --no-interactive`
- **Expected**: Per SKILL.md:
  - Step 1: Steps filtered to `[define, decompose]` — `has_execute=false`
  - Define and decompose run normally following their respective SKILL.md instructions
  - Execute is skipped entirely
  - Output ends with workflow summary, no implementation occurs
- **Assert**:
  - `content_get_requirements(todo_id=<TODO_ID>)` returns non-empty content
  - `todo_tree(todo_id=<TODO_ID>)` shows children (from decompose)
  - `todo_get(todo_id=<TODO_ID>)` shows `status` is NOT `"done"` (execute was skipped)

### Scenario 3: Workflow with --from flag starts mid-workflow
- **Prompt**: First follow the skill instructions as if user said `/proj:run <TODO_ID> --steps define --no-interactive` to complete define. Then follow the skill instructions as if user said `/proj:run <TODO_ID> --from decompose --no-interactive`.
- **Expected**: Per SKILL.md:
  - `--from decompose` slices steps to `[decompose, execute]`
  - Skips define entirely (requirements already exist)
  - Reads `decompose/SKILL.md` and `execute/SKILL.md`, follows their instructions
  - Runs decompose then execute
- **Assert**:
  - `todo_tree(todo_id=<TODO_ID>)` shows children
  - `todo_get(todo_id=<TODO_ID>)` shows `status="done"` after execute completes

### Scenario 4: Missing todo ID returns usage error
- **Prompt**: Follow the skill instructions as if user said `/proj:run` (no arguments)
- **Expected**: Per SKILL.md step 1, when no todo ID provided: stop with `Todo ID required. Usage: /proj:run <id> [--steps define,execute] [--from <step>]`
- **Assert**: No calls to `todo_get`, `content_set_requirements`, or `todo_complete`

## Cleanup
- Call `proj_archive` with the project ID for `eval-test-run`
- Run `rm -rf /tmp/claude-1000/eval-run`

# E2E Eval: quick

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/quick/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

Note: The quick skill invokes the run skill via the Skill tool (`skill: "proj:run"`). The eval should verify that the Skill tool call is made — the run skill itself is tested separately in run.md.

## Setup
- No pre-existing project — the quick skill creates one in Project mode
- For Todo mode tests: call `proj_init` with `name="eval-test-quick"`, `path="/tmp/claude-1000/eval-quick"` and `proj_load_session` first

## Test Scenarios

### Scenario 1: Project mode — no active project creates new project and runs workflow
- **Prompt**: Follow the skill instructions as if user said `/proj:quick "eval-quick-project"` (with no active project). Simulate user answers: confirm project name, provide todo title "Build a hello world CLI", select project location option.
- **Expected**: Per SKILL.md:
  - Step 1: Calls `proj_get_active` — returns null (no active project), enters Project mode
  - P1: Uses "eval-quick-project" as project name, asks for confirmation
  - P2: Asks for todo title (simulated: "Build a hello world CLI")
  - P3: Calls `config_load` for `projects_base_dir`, presents location options
  - P4: Calls `proj_init` with `name="eval-quick-project"`, `path=<chosen_path>`, `description="Build a hello world CLI"`. Calls `proj_load_session`
  - P5: If `perms_integration: true`: calls `proj_setup_permissions`
  - P6: Calls `claudemd_write` with project overview template
  - P7: Calls `todo_add` with `title="Build a hello world CLI"`, `priority=<default_priority>`
  - P8: Calls the Skill tool with `skill="proj:run"`, `args="<new_id> --iter 3"`
- **Assert**:
  - `proj_get_active` returns project with name `"eval-quick-project"`
  - `todo_list` shows at least one todo with title `"Build a hello world CLI"`
  - `claudemd_read` returns non-empty content

### Scenario 2: Todo mode — active project creates todo and runs workflow
- **Prompt**: Follow the skill instructions as if user said `/proj:quick "Add input validation" --no-interactive` (with `eval-test-quick` as active project)
- **Expected**: Per SKILL.md:
  - Step 1: Calls `proj_get_active` — returns active project, enters Todo mode
  - T1: Parses description "Add input validation" and flag `--no-interactive`
  - T2: Calls `config_load`, calls `todo_add` with `title="Add input validation"`, `priority=<default_priority>` — stores returned ID as `new_id`
  - T4: Displays: `Created todo <new_id>: Add input validation. Running workflow...`
  - T4: Calls the Skill tool with `skill="proj:run"`, `args="<new_id> --no-interactive"`
- **Assert**:
  - `todo_get(todo_id=<new_id>)` exists with title `"Add input validation"`
  - The run skill is invoked (requirements, research, and execution proceed)

### Scenario 3: Todo mode with --steps flag forwards flags to run
- **Prompt**: Follow the skill instructions as if user said `/proj:quick "Write unit tests" --steps define,decompose --no-interactive` (with active project)
- **Expected**: Per SKILL.md:
  - Enters Todo mode
  - T2: Calls `todo_add` with `title="Write unit tests"`
  - T4: Calls the Skill tool with `skill="proj:run"`, `args="<new_id> --steps define,decompose --no-interactive"`
  - Execute phase is NOT triggered (only define and decompose via forwarded flags)
- **Assert**:
  - `todo_get(todo_id=<new_id>)` exists with title `"Write unit tests"`
  - `todo_get(todo_id=<new_id>)` shows `status` is NOT `"done"` (execute was not run)
  - `content_get_requirements(todo_id=<new_id>)` returns non-empty content (define ran)

### Scenario 4: Empty description in Todo mode prompts for input
- **Prompt**: Follow the skill instructions as if user said `/proj:quick` (no arguments, with active project)
- **Expected**: Per SKILL.md:
  - Step 1: Calls `proj_get_active` — returns active project (Todo mode)
  - T1: Description is empty
  - Asks: `What would you like to work on?`
  - Waits for user input before proceeding
- **Assert**: No calls to `todo_add` before user provides a description

## Cleanup
- Call `proj_archive` with the project ID for `eval-test-quick` (if created in setup)
- Call `proj_archive` with the project ID for `eval-quick-project` (if created in Scenario 1)
- Run `rm -rf /tmp/claude-1000/eval-quick`

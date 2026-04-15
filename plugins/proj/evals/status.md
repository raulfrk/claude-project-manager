# E2E Eval: status

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/status/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `mcp__plugin_proj_proj__proj_init` with `name="eval-test-status"`, `path="/tmp/claude-1000/eval-status"`, `git_enabled=false`
- Call `mcp__plugin_proj_proj__todo_add` with `project_name="eval-test-status"`, `title="Design API schema"`, `priority="high"`
- Call `mcp__plugin_proj_proj__todo_add` with `project_name="eval-test-status"`, `title="Implement endpoints"`, `priority="medium"`
- Call `mcp__plugin_proj_proj__todo_add` with `project_name="eval-test-status"`, `title="Write integration tests"`, `priority="low"`
- Call `mcp__plugin_proj_proj__todo_update` with `project_name="eval-test-status"`, `todo_id="2"`, `blocked_by_set=["1"]` (todo 2 is blocked by todo 1)
- Call `mcp__plugin_proj_proj__todo_update` with `project_name="eval-test-status"`, `todo_id="1"`, `status="in_progress"`

## Test Scenarios

### Scenario 1: Basic status report with active project
- **Invocation**: Follow the skill instructions as if user said `/proj:status`
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__proj_get_active` (returns `eval-test-status`), then `mcp__plugin_proj_proj__config_load`, then `mcp__plugin_proj_proj__todo_list` and `mcp__plugin_proj_proj__todo_ready`. Output includes structured sections: "In Progress" listing todo 1, "Ready to Start" listing todo 3, "Blocked" listing todo 2 with `[blocked by 1]`.
- **Assert**:
  - Output contains `eval-test-status` as the project name
  - Output contains todo 1 under "In Progress" with title "Design API schema"
  - Output contains todo 3 under "Ready to Start" with title "Write integration tests"
  - Output contains todo 2 under "Blocked" with `blocked by 1`
  - Output contains suggested next actions

### Scenario 2: Status with no active project
- **Invocation**: Archive `eval-test-status` first via `mcp__plugin_proj_proj__proj_archive(name="eval-test-status")`, then follow the skill instructions as if user said `/proj:status`
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__proj_get_active` which returns no active project. Skill outputs "No active project. Run /proj:load first." and stops.
- **Assert**:
  - Output contains "No active project"
  - No calls to `todo_list` or `todo_ready` are made after the error

### Scenario 3: Status with all todos completed
- **Invocation**: Complete all three todos first, then follow the skill instructions as if user said `/proj:status`
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__todo_list` which returns an empty list. "Ready to Start", "In Progress", and "Blocked" sections are either absent or empty. Output still shows the project header and suggests adding new todos.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_list` with `project_name="eval-test-status"`, `status="active"` — returns empty list
  - Output does not list any todos under action sections
  - Suggested next actions include adding a new task

### Scenario 4: Status skips git activity when git is disabled
- **Invocation**: Follow the skill instructions as if user said `/proj:status` (project was initialized with `git_enabled=false`)
- **Expected**: The skill flow does NOT call `mcp__plugin_proj_proj__git_detect_work`. No "Recent Git Activity" section appears in output.
- **Assert**:
  - No invocation of `git_detect_work`
  - Output does not contain "Recent Git Activity"

## Cleanup
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-status"`
- Run `rm -rf /tmp/claude-1000/eval-status`

# E2E Eval: archive

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/archive/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `mcp__plugin_proj_proj__proj_init` with `name="eval-test-archive"`, `path="/tmp/claude-1000/eval-archive"`, `git_enabled=false`
- Call `mcp__plugin_proj_proj__todo_add` with `project_name="eval-test-archive"`, `title="Unfinished task"`, `priority="medium"`
- Ensure `/tmp/claude-1000/eval-archive` directory exists with at least one file

## Test Scenarios

### Scenario 1: Archive project with open todos shows warning
- **Invocation**: Follow the skill instructions as if user said `/proj:archive eval-test-archive` (accept defaults when prompted)
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__todo_list` and finds 1 open todo. Displays a warning listing the open todo with status icon, bold ID, title, and priority. Asks for confirmation before proceeding.
- **Assert**:
  - Output contains "This project has 1 open todo"
  - Output contains todo 1 title "Unfinished task"
  - After confirmation, `mcp__plugin_proj_proj__proj_archive` is called
  - Call `mcp__plugin_proj_proj__proj_get` with `name="eval-test-archive"` returns project with `status="archived"`

### Scenario 2: Archive project with no open todos skips warning
- **Invocation**: Complete todo 1 first via `mcp__plugin_proj_proj__todo_complete(project_name="eval-test-archive", todo_id="1")`, then follow the skill instructions as if user said `/proj:archive eval-test-archive`
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__todo_list` which returns empty. No warning about open todos. Proceeds directly to the consolidated cleanup prompt.
- **Assert**:
  - Output does NOT contain "open todo"
  - Output shows the consolidated cleanup prompt with Repos and Tracking Directory sections

### Scenario 3: Archive with purgeable=false
- **Invocation**: Follow the skill instructions as if user said `/proj:archive eval-test-archive` (when asked "Should this project be purgeable?", answer "no")
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__proj_archive` with `purgeable=false`.
- **Assert**:
  - Call `mcp__plugin_proj_proj__proj_get` with `name="eval-test-archive"` returns project with `purgeable=false` (or equivalent field)
  - Project will NOT appear in future `mcp__plugin_proj_proj__proj_purge_archive` candidates

### Scenario 4: Archive clears active project
- **Invocation**: Ensure `eval-test-archive` is the active project, then follow the skill instructions as if user said `/proj:archive`
- **Expected**: After archiving, `mcp__plugin_proj_proj__proj_get_active` returns no active project. Output includes "No active project now. Use /proj:switch to set a new one."
- **Assert**:
  - Call `mcp__plugin_proj_proj__proj_get_active` — returns null/empty (no active project)
  - Output contains "No active project now"

## Cleanup
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-archive"` (if not already archived)
- Run `rm -rf /tmp/claude-1000/eval-archive`

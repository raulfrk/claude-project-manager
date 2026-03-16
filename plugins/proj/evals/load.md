# E2E Eval: load

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/load/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Ensure `~/.claude/proj.yaml` exists.
- `mkdir -p /tmp/claude-1000/eval-load`
- Create a test project:
  - `mcp__proj__proj_init(name="eval-test-load", dirs=[{"path": "/tmp/claude-1000/eval-load", "label": "code"}], description="Load test project")`

## Test Scenarios

### Scenario 1: Load by exact name
- **Invocation**: Follow the skill instructions as if user said `/proj:load eval-test-load`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_load_session` called with `name="eval-test-load"`.
  - `mcp__proj__ctx_session_start` called.
  - `mcp__proj__config_load` called to get `tracking_dir`.
  - `mcp__proj__proj_get_active` called to get project name.
  - Last session file check via `Bash: ls <tracking_dir>/eval-test-load/sessions/session-*.md 2>/dev/null | sort | tail -1`.
  - Output contains "Loaded project 'eval-test-load' for this session."
- **Assert**:
  - `mcp__proj__proj_get_active` returns project with name `eval-test-load`.
  - Output includes project context (todos, notes section from `ctx_session_start`).

### Scenario 2: Load with interactive selection (no argument)
- **Invocation**: Follow the skill instructions as if user said `/proj:load` with no arguments
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_list` called first.
  - A numbered list of projects is presented.
  - After user selects a project (pick the eval-test-load entry), `mcp__proj__proj_load_session` is called.
  - `mcp__proj__ctx_session_start` called.
- **Assert**:
  - Output includes a numbered list containing `eval-test-load`.
  - After selection, `mcp__proj__proj_get_active` returns the selected project.

### Scenario 3: Load non-existent project
- **Invocation**: Follow the skill instructions as if user said `/proj:load nonexistent-project-xyz`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_load_session` called with `name="nonexistent-project-xyz"`.
  - Tool returns a not-found error.
  - Output contains error message and suggestion: "Check the project name or use /proj:init to add it."
- **Assert**:
  - `mcp__proj__proj_get_active` does NOT return `nonexistent-project-xyz`.
  - No call to `ctx_session_start`.

### Scenario 4: Load with fuzzy/ambiguous match
- **Invocation**: Create a second project `mcp__proj__proj_init(name="eval-test-load-extra", dirs=[{"path": "/tmp/claude-1000/eval-load/extra", "label": "code"}])`. Then follow the skill instructions as if user said `/proj:load eval-test-load`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_load_session` called with `name="eval-test-load"`.
  - If ambiguous match returned (both `eval-test-load` and `eval-test-load-extra`), the options are presented and user is asked to confirm.
  - If exact match succeeds directly, load proceeds normally.
- **Assert**:
  - After resolution, `mcp__proj__proj_get_active` returns the user-confirmed project.

## Cleanup
- `mcp__proj__proj_archive(name="eval-test-load")`
- `mcp__proj__proj_archive(name="eval-test-load-extra")` (if created)
- `Bash: rm -rf /tmp/claude-1000/eval-load`

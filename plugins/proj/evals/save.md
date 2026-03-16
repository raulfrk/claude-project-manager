# E2E Eval: save

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/save/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `mcp__plugin_proj_proj__proj_init` with `name="eval-test-save"`, `path="/tmp/claude-1000/eval-save"`, `git_enabled=false`
- Call `mcp__plugin_proj_proj__todo_add` with `project_name="eval-test-save"`, `title="Implement feature X"`, `priority="high"`
- Call `mcp__plugin_proj_proj__todo_update` with `project_name="eval-test-save"`, `todo_id="1"`, `status="in_progress"`

## Test Scenarios

### Scenario 1: Save session creates session file
- **Invocation**: Follow the skill instructions as if user said `/proj:save` (when prompted for session summary, respond with "Worked on feature X, decided to use REST over GraphQL")
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__proj_get_active` and `mcp__plugin_proj_proj__config_load` to get tracking dir. Creates a session file at `<tracking_dir>/eval-test-save/sessions/session-2026-03-16.md`. Calls `mcp__plugin_proj_proj__notes_append` with a one-line summary. Output confirms "Session saved to sessions/session-2026-03-16.md".
- **Assert**:
  - File exists: `<tracking_dir>/eval-test-save/sessions/session-2026-03-16.md`
  - Session file contains `# Session: 2026-03-16`
  - Session file contains `## User Note` section with the provided text
  - Session file contains `## Key Decisions`, `## Todos Worked On`, `## Insights Discovered`, `## Open Questions` sections
  - Call `mcp__plugin_proj_proj__notes_append` was invoked with a non-empty `text` parameter

### Scenario 2: Second save on same day increments filename
- **Invocation**: Follow the skill instructions as if user said `/proj:save` again (skip the user note by pressing Enter)
- **Expected**: The skill flow detects one existing `session-2026-03-16.md` and creates `session-2026-03-16-2.md`.
- **Assert**:
  - File exists: `<tracking_dir>/eval-test-save/sessions/session-2026-03-16-2.md`
  - Original `session-2026-03-16.md` is unchanged
  - New file contains `# Session: 2026-03-16`
  - New file does NOT contain `## User Note` section (user skipped)

### Scenario 3: Save with no active project fails gracefully
- **Invocation**: Archive the project first via `mcp__plugin_proj_proj__proj_archive(name="eval-test-save")`, then follow the skill instructions as if user said `/proj:save`
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__proj_get_active` which returns no project. Skill stops with an error message.
- **Assert**:
  - No session file is created
  - Output indicates no active project

### Scenario 4: Save skips git reconciliation when git is disabled
- **Invocation**: Follow the skill instructions as if user said `/proj:save` (project initialized with `git_enabled=false`)
- **Expected**: The skill flow does NOT call `mcp__plugin_proj_proj__proj_git_reconcile_todos`. Session file is still created normally without git-related content.
- **Assert**:
  - No invocation of `proj_git_reconcile_todos`
  - Session file exists and is well-formed

## Cleanup
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-save"`
- Run `rm -rf /tmp/claude-1000/eval-save`

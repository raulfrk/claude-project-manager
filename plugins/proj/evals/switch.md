# E2E Eval: switch

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/switch/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Ensure `~/.claude/proj.yaml` exists.
- `mkdir -p /tmp/claude-1000/eval-switch/proj-a /tmp/claude-1000/eval-switch/proj-b`
- Create two test projects:
  - `mcp__proj__proj_init(name="eval-test-switch-a", dirs=[{"path": "/tmp/claude-1000/eval-switch/proj-a", "label": "code"}])`
  - `mcp__proj__proj_init(name="eval-test-switch-b", dirs=[{"path": "/tmp/claude-1000/eval-switch/proj-b", "label": "code"}])`
- Load the first project: `mcp__proj__proj_load_session(name="eval-test-switch-a")`

## Test Scenarios

### Scenario 1: Switch to another project by name
- **Invocation**: Follow the skill instructions as if user said `/proj:switch eval-test-switch-b`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_list` called.
  - `mcp__proj__proj_load_session` called with `name="eval-test-switch-b"`.
  - `mcp__proj__ctx_session_start` called.
  - Output shows the new project's context (status, todos, notes).
- **Assert**:
  - `mcp__proj__proj_get_active` returns project with name `eval-test-switch-b`.
  - Output contains project context for `eval-test-switch-b`.

### Scenario 2: Switch with interactive selection (no argument)
- **Invocation**: Follow the skill instructions as if user said `/proj:switch` with no arguments
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_list` called.
  - A numbered list of projects is presented including both `eval-test-switch-a` and `eval-test-switch-b`.
  - User selects one; `mcp__proj__proj_load_session` called with the selected name.
  - `mcp__proj__ctx_session_start` called.
- **Assert**:
  - Output includes a numbered list with both test projects.
  - After selection, `mcp__proj__proj_get_active` returns the chosen project.

### Scenario 3: Switch to non-existent project
- **Invocation**: Follow the skill instructions as if user said `/proj:switch nonexistent-xyz`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_list` called.
  - No match found for `nonexistent-xyz`.
  - Output: "Project 'nonexistent-xyz' not found. Use /proj:list to see available projects."
- **Assert**:
  - No call to `mcp__proj__proj_load_session`.
  - `mcp__proj__proj_get_active` still returns the previously active project (unchanged).

### Scenario 4: Switch with prefix match (multiple matches)
- **Invocation**: Follow the skill instructions as if user said `/proj:switch eval-test-switch`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_list` called.
  - Both `eval-test-switch-a` and `eval-test-switch-b` match the prefix.
  - User is asked to confirm which one.
  - After confirmation, `mcp__proj__proj_load_session` called with the confirmed name.
- **Assert**:
  - Output lists both matching projects for disambiguation.
  - After user picks one, `mcp__proj__proj_get_active` returns that project.

## Cleanup
- `mcp__proj__proj_archive(name="eval-test-switch-a")`
- `mcp__proj__proj_archive(name="eval-test-switch-b")`
- `Bash: rm -rf /tmp/claude-1000/eval-switch`

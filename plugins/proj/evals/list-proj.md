# E2E Eval: list-proj

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/list-proj/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Ensure `~/.claude/proj.yaml` exists.
- `mkdir -p /tmp/claude-1000/eval-list-proj`
- Create two test projects:
  - `mcp__proj__proj_init(name="eval-test-list-a", dirs=[{"path": "/tmp/claude-1000/eval-list-proj/a", "label": "code"}])`
  - `mcp__proj__proj_init(name="eval-test-list-b", dirs=[{"path": "/tmp/claude-1000/eval-list-proj/b", "label": "code"}])`

## Test Scenarios

### Scenario 1: List shows all active projects
- **Invocation**: Follow the skill instructions as if user said `/proj:list-proj`
- **Expected**: The skill flow calls `mcp__proj__proj_list` with no arguments. Output includes both `eval-test-list-a` and `eval-test-list-b`.
- **Assert**:
  - Output contains `eval-test-list-a`.
  - Output contains `eval-test-list-b`.
  - Output does NOT contain any archived projects (if any exist in the system).

### Scenario 2: List after archiving one project
- **Invocation**: Archive project `eval-test-list-a` via `mcp__proj__proj_archive(name="eval-test-list-a")`. Then follow the skill instructions as if user said `/proj:list-proj`
- **Expected**: The skill flow calls `mcp__proj__proj_list` which returns list that includes `eval-test-list-b` but NOT `eval-test-list-a`.
- **Assert**:
  - Output contains `eval-test-list-b`.
  - Output does NOT contain `eval-test-list-a`.

### Scenario 3: List when no projects exist
- **Invocation**: Archive all remaining test projects. Follow the skill instructions as if user said `/proj:list-proj`
- **Expected**: The skill flow calls `mcp__proj__proj_list` which returns an empty list (or a list with no eval-test projects). Output is displayed as-is (may be empty or show non-test projects).
- **Assert**:
  - Output does NOT contain `eval-test-list-a` or `eval-test-list-b`.

## Cleanup
- `mcp__proj__proj_archive(name="eval-test-list-a")` (if not already archived).
- `mcp__proj__proj_archive(name="eval-test-list-b")` (if not already archived).
- `Bash: rm -rf /tmp/claude-1000/eval-list-proj`

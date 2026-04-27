# E2E Eval: save writes handoff section

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/save/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

This eval covers the new step 7b (handoff synthesis) + the extended step 7 template (`## Next Session Resumes Here` 6th section).

## Setup
- Call `mcp__plugin_proj_proj__proj_init` with `name="eval-test-save-handoff"`, `path="/tmp/claude-1000/eval-save-handoff"`, `git_enabled=false`
- Call `mcp__plugin_proj_proj__todo_add` with `project_name="eval-test-save-handoff"`, `title="Implement coordinator handoff"`, `priority="high"`
- Call `mcp__plugin_proj_proj__todo_update` with `project_name="eval-test-save-handoff"`, `todo_id="1"`, `status="in_progress"`

## Test Scenarios

### Scenario 1: Save writes handoff section with all 4 subsections
- **Invocation**: Follow the skill instructions as if user said `/proj:save Worked on coordinator handoff feature, decided ## Next Session Resumes Here heading is the right pattern, blocker: needs user review`
- **Expected**: The skill flow follows step 7's template (now 6 sections including handoff) + step 7b discipline. Session file written to `<tracking_dir>/eval-test-save-handoff/sessions/session-<date>.md`.
- **Assert**:
  - File exists: `<tracking_dir>/eval-test-save-handoff/sessions/session-<date>.md`
  - Session file contains `## Next Session Resumes Here` heading
  - Session file contains `### Attempted` subsection (non-empty)
  - Session file contains `### Blocked` subsection (either bullets OR `_(none)_` placeholder)
  - Session file contains `### Next Action` subsection (single concrete bullet OR `_(no concrete next action — review session or ask user)_`)
  - Session file contains `### Files / Todos` subsection (todo IDs/files OR `_(none specified)_`)
  - All 4 subsections appear in this exact order: Attempted → Blocked → Next Action → Files / Todos

### Scenario 2: Save with no clear next action uses placeholder
- **Invocation**: Follow the skill instructions as if user said `/proj:save General exploratory thinking session — no specific next step` (an explicitly directionless session)
- **Expected**: The skill flow detects no concrete next action + uses the `_(no concrete next action — review session or ask user)_` placeholder.
- **Assert**:
  - Session file contains `## Next Session Resumes Here`
  - `### Next Action` subsection contains `_(no concrete next action — review session or ask user)_`
  - `### Attempted` subsection still has at least one bullet (session WAS active)

### Scenario 3: Save with no blockers uses placeholder
- **Invocation**: Follow the skill instructions as if user said `/proj:save Smooth productive session — completed feature X end to end`
- **Expected**: The skill flow detects no explicit blockers + uses the `_(none)_` placeholder for Blocked.
- **Assert**:
  - Session file contains `## Next Session Resumes Here`
  - `### Blocked` subsection contains `_(none)_`

### Scenario 4: Save with no specific files touched uses placeholder
- **Invocation**: Follow the skill instructions as if user said `/proj:save Discussion-only session — reviewed designs, no code touched`
- **Expected**: The skill flow detects no specific file paths + uses the `_(none specified)_` placeholder for Files / Todos.
- **Assert**:
  - Session file contains `## Next Session Resumes Here`
  - `### Files / Todos` subsection contains `_(none specified)_` for files (todos may still list IDs touched)

## Cleanup
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-save-handoff"`
- Run `rm -rf /tmp/claude-1000/eval-save-handoff`

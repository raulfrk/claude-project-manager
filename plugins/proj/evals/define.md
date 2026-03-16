# E2E Eval: define

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/define/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `proj_init` with `name="eval-test-define"`, `path="/tmp/claude-1000/eval-define"`
- Call `proj_load_session`
- Call `todo_add` with `title="Test todo for eval"`, `priority="medium"` — store returned ID as `TODO_ID`

## Test Scenarios

### Scenario 1: Non-interactive define sets requirements and research
- **Prompt**: Follow the skill instructions as if user said `/proj:define <TODO_ID> --no-interactive`
- **Expected**: Per SKILL.md:
  - Step 1 parses `todo_id` and `no_interactive=true`, skips to Non-interactive path
  - NI-1: Calls `proj_get_todo_context` with the todo ID
  - NI-2: Explores codebase via Read/Glob/Grep
  - NI-3: Writes requirements and research directly from context
  - Calls `content_set_requirements` with markdown containing `# Requirements:` header, `## Goal`, `## Acceptance Criteria`, `## Out of Scope`, `## Testing Strategy`
  - Calls `content_set_research` with markdown containing `# Research:` header, `## Approach Options`, `## Recommended Approach`, `## Key Dependencies`, `## Risks`
  - Calls `todo_set_content_flag` with `has_requirements=True`, `has_research=True`
  - Step 7: Calls `claudemd_write` to append requirements summary
  - Step 8: Calls `tracking_git_flush` with `commit_message="Define: <TODO_ID>"`
- **Assert**:
  - `content_get_requirements(todo_id=<TODO_ID>)` returns non-empty content with `## Goal` and `## Acceptance Criteria` sections
  - `content_get_research(todo_id=<TODO_ID>)` returns non-empty content with `## Recommended Approach` section
  - `todo_get(todo_id=<TODO_ID>)` shows `has_requirements=true` and `has_research=true`

### Scenario 2: Missing todo ID returns usage error
- **Prompt**: Follow the skill instructions as if user said `/proj:define` (no arguments)
- **Expected**: Per SKILL.md step 1, when `todo_id` is empty: stop and output "Todo ID required. Usage: /proj:define <todo-id>"
- **Assert**: No calls to `content_set_requirements` or `content_set_research` are made

### Scenario 3: Non-existent todo ID returns not-found error
- **Prompt**: Follow the skill instructions as if user said `/proj:define 999 --no-interactive`
- **Expected**: Per SKILL.md NI-1, calls `proj_get_todo_context` with `todo_id=999`. Result indicates todo not found. Output: "Todo 999 not found."
- **Assert**: No calls to `content_set_requirements` or `content_set_research` are made

### Scenario 4: Non-interactive define updates CLAUDE.md with requirements summary
- **Prompt**: Follow the skill instructions as if user said `/proj:define <TODO_ID> --no-interactive`
- **Expected**: Per SKILL.md step 7, after writing requirements and research, calls `claudemd_write` to append a `## Requirements: Test todo for eval` heading with a 1-3 sentence summary
- **Assert**:
  - `claudemd_read` returns content containing `## Requirements: Test todo for eval`

## Cleanup
- Call `proj_archive` with the project ID for `eval-test-define`
- Run `rm -rf /tmp/claude-1000/eval-define`

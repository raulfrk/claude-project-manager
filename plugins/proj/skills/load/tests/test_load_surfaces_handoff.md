# E2E Eval: load surfaces handoff block

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/load/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

This eval covers the new step 3a (handoff surface) + verifies the existing-3a-renamed-to-3b ordering.

## Setup
- Ensure `~/.claude/proj.yaml` exists.
- `mkdir -p /tmp/claude-1000/eval-load-handoff`
- Create test project:
  - `mcp__proj__proj_init(name="eval-test-load-handoff", dirs=[{"path": "/tmp/claude-1000/eval-load-handoff", "label": "code"}], description="Load handoff test project")`
- Create fixture session file at `<tracking_dir>/eval-test-load-handoff/sessions/session-2026-04-27.md` with content:
  ```markdown
  # Session: 2026-04-27

  ## Key Decisions
  - Picked path D over A

  ## Todos Worked On
  - 804: defined handoff section schema

  ## Insights Discovered
  - Coordinator-style handoff blocks compress resumption ctx 10x

  ## Open Questions
  - Should the handoff also include a confidence rating?

  ## Next Session Resumes Here

  ### Attempted
  - Defined HandoffBlock dataclass + parse_handoff() in lib/handoff.py
  - Wrote 8 unit tests covering placeholder detection + multi-heading edge case

  ### Blocked
  - _(none)_

  ### Next Action
  - Implement Task 3 of plan at /home/raul/projects/tracking/claude-project-manager/plans/2026-04-27-claude-progress-handoff-plan.md (extend /proj:save SKILL.md template + add step 7b)

  ### Files / Todos
  - Todos: 804
  - Files: plugins/proj/server/server/lib/handoff.py, plugins/proj/server/tests/test_handoff_parser.py
  ```

## Test Scenarios

### Scenario 1: Load surfaces handoff block before last-session block
- **Invocation**: Follow the skill instructions as if user said `/proj:load eval-test-load-handoff`
- **Expected**: The skill flow:
  - `mcp__proj__proj_load_session` called with `name="eval-test-load-handoff"`.
  - `mcp__proj__ctx_session_start` called.
  - Step 3a: latest session file located, `## Next Session Resumes Here` heading detected, content extracted + displayed under top-level `# Next Session Resumes Here` heading.
  - Step 3b: same session file displayed under `### Last Session` block AFTER handoff display.
- **Assert**:
  - Output begins with top-level `# Next Session Resumes Here` heading (handoff display, before any other ctx).
  - Handoff display contains all 4 subsections: `### Attempted`, `### Blocked`, `### Next Action`, `### Files / Todos`.
  - Handoff display contains the "Implement Task 3 of plan" Next Action verbatim.
  - The `### Last Session` block (step 3b) appears AFTER the handoff display — order is enforced.
  - Output includes project ctx (todos, notes from `ctx_session_start`) AFTER both the handoff and last-session blocks.

### Scenario 2: Load gracefully handles legacy session without handoff block
- **Invocation**:
  - First, overwrite the fixture file to remove the `## Next Session Resumes Here` section (legacy session simulation).
  - Then follow the skill instructions as if user said `/proj:load eval-test-load-handoff`.
- **Expected**: Step 3a detects absent heading → skips silently → step 3b still runs.
- **Assert**:
  - Output does NOT contain `# Next Session Resumes Here` heading (handoff display skipped).
  - Output still contains `### Last Session` block (step 3b runs unchanged).
  - No error displayed about the missing section.

### Scenario 3: Load surfaces handoff with placeholders
- **Invocation**:
  - Overwrite fixture file with all 4 subsections present but using placeholders: `### Attempted` has 1 bullet, `### Blocked` is `_(none)_`, `### Next Action` is `_(no concrete next action — review session or ask user)_`, `### Files / Todos` is `_(none specified)_`.
  - Then follow the skill instructions as if user said `/proj:load eval-test-load-handoff`.
- **Expected**: Step 3a surfaces the block verbatim, including placeholders.
- **Assert**:
  - Output contains `# Next Session Resumes Here` heading.
  - Output contains `_(no concrete next action — review session or ask user)_` (placeholder preserved).
  - Output contains `_(none)_` and `_(none specified)_` placeholders.

## Cleanup
- `mcp__proj__proj_archive(name="eval-test-load-handoff")`
- `Bash: rm -rf /tmp/claude-1000/eval-load-handoff`

# E2E Eval: todo

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/todo/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `mcp__plugin_proj_proj__proj_init` with `name="eval-test-todo"`, `path="/tmp/claude-1000/eval-todo"`, `git_enabled=false`

## Test Scenarios

### Scenario 1: Add todo and verify
- **Prompt**: Follow the skill instructions as if user said `/proj:todo add Build authentication module priority=high tags=backend,auth`
- **Expected**: Per SKILL.md, the agent first calls `proj_get_active` to get the project name. Then parses the arguments to extract title="Build authentication module", priority=high, tags=["backend","auth"]. Calls `todo_add` accordingly. Calls `tracking_git_flush`.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="1"` returns todo with:
    - `title` = "Build authentication module"
    - `priority` = "high"
    - `tags` contains "backend" and "auth"
    - `status` = "pending"

### Scenario 2: Add child todo with parent ID prefix
- **Prompt**: Follow the skill instructions as if user said `/proj:todo add 1 Add JWT token validation priority=medium`
- **Expected**: Per SKILL.md smart parent inference, the agent extracts leading `1`, calls `todo_get` to verify it exists, then passes `parent="1"` and `title="Add JWT token validation"` to `todo_add`.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="1.1"` returns todo with:
    - `title` = "Add JWT token validation"
    - `priority` = "medium"
    - Parent is todo `1`

### Scenario 3: Block and unblock
- **Prompt**: First follow the skill instructions as if user said `/proj:todo add Write API tests priority=low`. Then follow the skill instructions as if user said `/proj:todo block 1 blocks 2`.
- **Expected**: Per SKILL.md, calls `todo_block` with `todo_id="1"`, `blocks_ids=["2"]`. Todo 2 is now blocked by todo 1.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="2"` — `blocked_by` contains `"1"`
  - Call `mcp__plugin_proj_proj__todo_ready` with `project_name="eval-test-todo"` — todo 2 is NOT in the ready list
- **Prompt**: Follow the skill instructions as if user said `/proj:todo unblock 2`
- **Expected**: Per SKILL.md, calls `todo_unblock` with `todo_id="2"`. Blocking relationship removed.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="2"` — `blocked_by` is empty
  - Call `mcp__plugin_proj_proj__todo_ready` with `project_name="eval-test-todo"` — todo 2 IS in the ready list

### Scenario 4: Complete and list
- **Prompt**: Follow the skill instructions as if user said `/proj:todo done 1`
- **Expected**: Per SKILL.md, calls `todo_complete` with `project_name="eval-test-todo"`, `todo_id="1"`. Todo 1 status becomes "done". Suggests `/proj:status` for overview.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="1"` — `status` = "done"
- **Prompt**: Follow the skill instructions as if user said `/proj:todo list`
- **Expected**: Per SKILL.md, default list (no filter) calls `todo_tree`. Shows open tasks as hierarchy, filtering out done todos.
- **Assert**:
  - Output contains todo 2 with status icon (pending)
  - Output contains todo 1.1 (non-done child, so parent 1 may appear as a container)
  - Completed todos without non-done descendants are excluded

### Scenario 5: Tree view shows hierarchy
- **Prompt**: Follow the skill instructions as if user said `/proj:todo tree`
- **Expected**: Per SKILL.md, calls `todo_tree` with `project_name="eval-test-todo"`. Returns nested structure. Output uses 2-space indentation, status icons, bold IDs, and italic priorities as specified in the skill.
- **Assert**:
  - Output shows todo 1 at top level (kept as container for non-done child 1.1)
  - Output shows todo 1.1 indented under todo 1
  - Output shows todo 2 at top level
  - All todos display format: `<icon> **<id>** -- <title> _(<priority>)_`

### Scenario 6: Update todo fields
- **Prompt**: Follow the skill instructions as if user said `/proj:todo update 2 title=Write comprehensive API tests priority=high due_date=2026-04-01`
- **Expected**: Per SKILL.md, parses key=value pairs and calls `todo_update` with the provided fields.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="2"` returns:
    - `title` = "Write comprehensive API tests"
    - `priority` = "high"
    - `due_date` = "2026-04-01"

### Scenario 7: Delete todo cleans up references
- **Prompt**: First follow the skill instructions as if user said `/proj:todo block 2 blocks 1.1`. Then follow the skill instructions as if user said `/proj:todo delete 2`.
- **Expected**: Per SKILL.md, calls `todo_block` then `todo_delete`. Todo 2 is removed and blocking reference on 1.1 is cleaned up.
- **Assert**:
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="2"` returns error (not found)
  - Call `mcp__plugin_proj_proj__todo_get` with `project_name="eval-test-todo"`, `todo_id="1.1"` — `blocked_by` does NOT contain `"2"`

### Scenario 8: Empty arguments shows usage
- **Prompt**: Follow the skill instructions as if user said `/proj:todo` (no arguments)
- **Expected**: Per SKILL.md, when $ARGUMENTS is empty or ambiguous, output usage: "Usage: /proj:todo [add|update|done|list|tree|block|unblock|delete] [args]"
- **Assert**:
  - Output contains "Usage:"
  - Output lists available subcommands: add, update, done, list, tree, block, unblock, delete

## Cleanup
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-todo"`
- Run `rm -rf /tmp/claude-1000/eval-todo`

# E2E Eval: trello-sync

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/trello-sync/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly -- only call what the skill instructions tell you to call

> **API dependency**: All scenarios require a valid Trello API token/key and a reachable Trello MCP server. The MCP server name is read from `trello.mcp_server` in proj config. The MCP server must expose checklist-related tools: `get_card_checklists`, `create_checklist`, `create_checkitem`, `update_checkitem`, `delete_checkitem`, `get_board_labels`, `create_label`, `add_card_to_list` / `create_card`, `get_lists`.

## Setup

1. Call `mcp__proj__config_load` -- verify `trello.enabled` is `true`, note `trello.mcp_server`, `trello.default_board_id`, `trello.default_list`.
2. Call `mcp__proj__proj_init` with `name="eval-test-trello-sync"`, `path="/tmp/claude-1000/eval-trello-sync"`.
3. Ensure a Trello board exists for testing. Set `trello.board_id` on the eval project via `mcp__proj__proj_update_meta` (or rely on `trello.default_board_id` from global config).
4. Add local test todos:
   - `mcp__proj__todo_add` with title `"Feature Alpha"` (root with children).
   - `mcp__proj__todo_add` with title `"Alpha subtask 1"` as child of "Feature Alpha".
   - `mcp__proj__todo_add` with title `"Alpha subtask 2"` as child of "Feature Alpha".
   - `mcp__proj__todo_add` with title `"Standalone task A"` (root leaf).
   - `mcp__proj__todo_add` with title `"Standalone task B"` (root leaf).

## Test Scenarios

### Scenario 1: First sync -- card creation, label, checklists, and items

- **Prompt**: Follow the skill instructions as if user said `/proj:trello-sync`.
- **Expected**: Per SKILL.md:
  - Step 1: Calls `config_load` and `proj_get_active`. Checks prerequisites.
  - Step 2: Ensures `proj` label exists on the board.
  - Step 3: No `trello_card_id` on meta -- creates a new card on the default list with `proj` label. Links card ID via `proj_trello_apply`.
  - Step 4: Fetches card checklists (empty initially).
  - Step 5: Calls `proj_trello_diff` with auto_apply=true. Plan should have:
    - `push_create_checklist`: 1 (for "Feature Alpha") + 1 (for "Tasks")
    - `push_create_item`: 2 items in "Feature Alpha" checklist + 2 items in "Tasks" checklist
  - Step 6: Creates checklists and items via Trello MCP tools. Links IDs via `proj_trello_apply`.
  - Step 7: Calls `tracking_git_flush`.
  - Summary: reports created checklists and items.
- **Assert**:
  - Project meta has `trello_card_id` set.
  - Root todo "Feature Alpha" has `trello_checklist_id` set.
  - Child todos have `trello_checklist_item_id` set.
  - Root leaf todos "Standalone task A" and "B" have `trello_checklist_item_id` set.
  - Trello card has 2 checklists: "Feature Alpha" (2 items) and "Tasks" (2 items).

### Scenario 2: Pull -- new checklist item from Trello

- **Prompt**: Manually add a new check item "Alpha subtask 3" to the "Feature Alpha" checklist in Trello (via Trello MCP tool). Then follow the skill as if user said `/proj:trello-sync`.
- **Expected**:
  - `proj_trello_diff` returns `pull_create` with 1 entry (the new item).
  - auto_apply creates a new local child todo under "Feature Alpha".
  - Summary includes "1 created" in pull.
- **Assert**:
  - `todo_list` shows a new child under "Feature Alpha" with title "Alpha subtask 3" and `trello_checklist_item_id` set.

### Scenario 3: Pull -- rename from Trello

- **Prompt**: Rename "Standalone task A" in the Trello "Tasks" checklist to "Standalone task A RENAMED" (via Trello MCP tool). Then sync.
- **Expected**:
  - `proj_trello_diff` returns `pull_update` with 1 entry.
  - auto_apply updates the local todo title.
- **Assert**:
  - Local todo title is "Standalone task A RENAMED".

### Scenario 4: Pull -- complete from Trello

- **Prompt**: Check "Standalone task B" in the Trello "Tasks" checklist (mark complete). Then sync.
- **Expected**:
  - `proj_trello_diff` returns `pull_complete` with 1 entry.
  - auto_apply completes the local todo.
- **Assert**:
  - Local todo "Standalone task B" status is `done`.

### Scenario 5: Pull -- reopen from Trello

- **Prompt**: Uncheck "Standalone task B" in Trello (mark incomplete). Then sync.
- **Expected**:
  - `proj_trello_diff` returns `pull_reopen` with 1 entry.
  - auto_apply reopens the local todo.
- **Assert**:
  - Local todo "Standalone task B" status is `pending`.

### Scenario 6: Push -- new local todo to Trello

- **Prompt**: Add a new local todo `mcp__proj__todo_add` with title `"Standalone task C"`. Then sync.
- **Expected**:
  - `proj_trello_diff` returns `push_create_item` with 1 entry (for "Standalone task C" in "Tasks" checklist).
  - Step 6 creates the check item in Trello. Links the ID.
- **Assert**:
  - Trello "Tasks" checklist has 3 items (A renamed, B, C).
  - Local todo has `trello_checklist_item_id` set.

### Scenario 7: Push -- rename checklist (root todo title change)

- **Prompt**: Update "Feature Alpha" title to "Feature Alpha v2" locally via `todo_update`. Then sync.
- **Expected**:
  - `proj_trello_diff` returns `push_rename_checklist` with 1 entry.
  - Step 6 renames the checklist in Trello.
- **Assert**:
  - Trello checklist name is "Feature Alpha v2".

### Scenario 8: Push -- complete item locally

- **Prompt**: Complete "Alpha subtask 1" locally. Then sync.
- **Expected**:
  - `proj_trello_diff` returns `push_complete_item` with 1 entry.
  - Step 6 marks the item as complete in Trello.
- **Assert**:
  - Trello check item state is "complete".

### Scenario 9: Pull -- new checklist from Trello (new root todo)

- **Prompt**: Create a new checklist "Feature Beta" on the Trello card (via Trello MCP tool) with one item "Beta task 1". Then sync.
- **Expected**:
  - `proj_trello_diff` returns `pull_create_root` with 1 entry and `pull_create` with 1 entry.
  - auto_apply creates a new root todo "Feature Beta" with `trello_checklist_id`, and a child todo "Beta task 1" with `trello_checklist_item_id`.
- **Assert**:
  - `todo_list` shows "Feature Beta" as a root todo with 1 child.

### Scenario 10: Dynamic restructuring -- leaf gains children

- **Prompt**: Add a child to "Standalone task C" locally (`todo_add` as child). Then sync.
- **Expected**:
  - "Standalone task C" was a root leaf (in "Tasks" checklist). Now it has a child.
  - `proj_trello_diff` should create a new checklist "Standalone task C" and an item for the child.
  - The old item in "Tasks" should be handled (either deleted or the restructuring reflected).
- **Assert**:
  - Trello card now has a "Standalone task C" checklist with the child item.

### Scenario 11: Everything up to date

- **Prompt**: Sync immediately after a successful sync with no changes.
- **Expected**:
  - All counts are zero.
  - Output: "Trello sync complete. Everything up to date."
  - `tracking_git_flush` is still called.
- **Assert**:
  - No state changes.

### Scenario 12: Trello MCP server unavailable

- **Prompt**: Temporarily change `trello.mcp_server` to a nonexistent server name. Then sync.
- **Expected**:
  - Skill stops at step 1 or 2 with the "MCP server not available" error message.
- **Assert**:
  - Output contains the unavailable server error.
  - Restore the original mcp_server value.

## Cleanup

1. Delete the Trello card created during the eval (using the card ID stored on project meta).
2. Archive the eval project: `mcp__proj__proj_archive` with project name "eval-test-trello-sync".
3. Remove temp files: `rm -rf /tmp/claude-1000/eval-trello-sync`.

# E2E Eval: trello-sync

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/trello-sync/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

> **API dependency**: All scenarios require a valid Trello API token/key and a reachable Trello MCP server. The MCP server name is read from `trello.mcp_server` in proj config. The MCP server must expose: `get_lists`, `get_cards_by_list_id`, `add_card_to_list`, `update_card_details`, `move_card`.

## Setup

1. Call `mcp__proj__config_load` -- verify `trello.enabled` is `true`, note `trello.mcp_server`, `trello.list_mappings.created`, and `trello.list_mappings.done`.
2. Call `mcp__proj__proj_init` with `name="eval-test-trello-sync"`, `path="/tmp/claude-1000/eval-trello-sync"`.
3. Ensure a Trello board exists for testing. Set `trello.board_id` on the eval project via `mcp__proj__proj_update_meta` (or rely on `trello.default_board_id` from global config).
4. Verify list resolution: call `mcp__<trello_server>__get_lists` with the board ID and confirm the "created" and "done" list names from config exist on the board. Record their list IDs.
5. Add local test todos (root level only -- trello-sync ignores children):
   - `mcp__proj__todo_add` with title `"Trello push test A"`.
   - `mcp__proj__todo_add` with title `"Trello push test B"`.
   - `mcp__proj__todo_add` with title `"Trello push test C"` and `due_date="2026-04-01"`.
   - `mcp__proj__todo_add` with title `"Trello child test"` as a child of todo A (should be skipped by sync).

## Test Scenarios

### Scenario 1: Push new local todos to Trello

- **Prompt**: Follow the skill instructions as if user said `/proj:trello-sync`.
- **Expected**: Per SKILL.md:
  - Step 1 (Setup): Calls `config_load` and `proj_get_active`. Checks prerequisites (trello.enabled, board_id). Resolves list names to IDs via `get_lists`.
  - Step 2: Fetches cards from both "created" and "done" lists via `get_cards_by_list_id`. Calls `todo_list` for local root todos. Builds lookup maps.
  - Step 4 (push): For each unlinked root todo (A, B, C), calls `add_card_to_list` with `listId` = "created" list ID and the todo's title. Todo C also includes `due="2026-04-01"`. Calls `todo_update` for each to store the returned `trello_card_id`.
  - The child todo "Trello child test" is NOT pushed to Trello.
  - Step 8: Calls `tracking_git_flush` with `commit_message="Sync: Trello"`.
  - Summary: "Pushed to Trello: 3 created".
- **Assert**:
  - Call `mcp__proj__todo_list` -- todos A, B, C have `trello_card_id` set; child todo does not.
  - Call `mcp__<trello_server>__get_cards_by_list_id` with the "created" list ID -- 3 cards exist with matching titles.

### Scenario 2: Pull title and due date changes from Trello

- **Prompt**: Manually update card A's name on Trello (via `mcp__<trello_server>__update_card_details` changing name to `"Trello push test A RENAMED"`). Update card C's due date to `"2026-05-15"`. Then follow the skill instructions as if user said `/proj:trello-sync`.
- **Expected**: Per SKILL.md step 3 (pull):
  - During pull, the sync detects the name mismatch for A and the due date mismatch for C.
  - Calls `todo_update` to update local todo A's title to "Trello push test A RENAMED".
  - Calls `todo_update` to update local todo C's due_date to "2026-05-15".
  - Summary includes "Pulled from Trello: 2 updated".
- **Assert**:
  - Call `mcp__proj__todo_list` -- todo A's title is "Trello push test A RENAMED", todo C's due_date is "2026-05-15".

### Scenario 3: Pull completion from Trello (card moved to done list)

- **Prompt**: Move card B to the "done" list on Trello (via `mcp__<trello_server>__move_card`). Then follow the skill instructions as if user said `/proj:trello-sync`.
- **Expected**: Per SKILL.md step 3 (pull, done-list cards):
  - Card B appears in the "done" list fetch, matched to local todo B via `trello_card_id`.
  - Calls `todo_complete` for todo B.
  - Summary includes "Pulled from Trello: ... 1 closed".
- **Assert**:
  - Call `mcp__proj__todo_list` -- todo B's status is `done`.

### Scenario 4: Push local completion to Trello

- **Prompt**: Complete todo A locally via `mcp__proj__todo_complete`. Then follow the skill instructions as if user said `/proj:trello-sync`.
- **Expected**: Per SKILL.md step 4 (push):
  - Todo A is done locally but its card is still in the "created" list on Trello.
  - Calls `move_card` to move card A to the "done" list ID.
  - Summary includes "Pushed to Trello: ... 1 updated".
- **Assert**:
  - Call `mcp__<trello_server>__get_cards_by_list_id` with "done" list ID -- card A is present.

### Scenario 5: Deleted/archived card propagation (Trello card removed externally)

- **Prompt**: Archive card C on Trello (via `mcp__<trello_server>__update_card_details` with `closed=true`, or delete it). Then follow the skill instructions as if user said `/proj:trello-sync`.
- **Expected**: Per SKILL.md step 5:
  - Local todo C has `trello_card_id` set, but the card appears in neither the "created" nor "done" list.
  - The sync detects this and completes todo C locally.
  - Summary includes "Pulled from Trello: ... 1 closed".
- **Assert**:
  - Call `mcp__proj__todo_list` -- todo C's status is `done`.

### Scenario 6: Everything up to date

- **Prompt**: Follow the skill instructions as if user said `/proj:trello-sync` immediately after a successful sync with no intervening changes.
- **Expected**: Per SKILL.md step 7:
  - All counts are zero.
  - Output: "Trello sync complete. Everything up to date."
  - Step 8: `tracking_git_flush` is still called.
- **Assert**:
  - No state changes in local todos or Trello cards.

### Scenario 7: List name mismatch -- early exit

- **Prompt**: Temporarily change `trello.list_mappings.created` to a nonexistent list name (e.g., `"Nonexistent List"`) via `mcp__proj__config_update`. Then follow the skill instructions as if user said `/proj:trello-sync`.
- **Expected**: Per SKILL.md step 1 (list resolution failure):
  - After calling `get_lists`, the configured list name cannot be matched.
  - Skill stops with: "Trello list 'Nonexistent List' not found on board '<board_id>'. Check your `trello.list_mappings` config. Available lists: ..."
  - No cards are created or modified.
- **Assert**:
  - Output contains the expected error message with available list names.
  - Restore the original `list_mappings.created` value after the test.

## Cleanup

1. Delete all Trello cards created during the eval: call `mcp__<trello_server>__get_cards_by_list_id` for both "created" and "done" lists, identify eval cards by title prefix "Trello push test", and archive or delete them.
2. Archive the eval project: `mcp__proj__proj_archive` with project name "eval-test-trello-sync".
3. Remove temp files: `rm -rf /tmp/claude-1000/eval-trello-sync`.

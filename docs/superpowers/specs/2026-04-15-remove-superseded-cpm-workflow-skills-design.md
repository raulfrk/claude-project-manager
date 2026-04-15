# Remove Superseded CPM Workflow Skills — Design Spec

**Date:** 2026-04-15
**Todo:** 627

---

## Goal

Remove CPM workflow skills (`define`, `execute`, `run`, `run-batch`, `refine`, `decompose`, `quick`) and their associated Python code and documentation references, since these are now superseded by the Superpowers workflow (`brainstorming` → `writing-plans` → `subagent-driven-development`). CPM retains its todo management, sync, and utility skills.

## Architecture

3 commits, cleanly separated by concern:

1. **Skill directory deletion** — `git rm -r` on 8 dirs, no other changes
2. **Python tool removal** — remove `todo_check_executable` MCP tool + 4 tests
3. **Doc/config cleanup** — CLAUDE.md managed section, project CLAUDE.md, kept-skill cross-refs, README

## Commit 1: Delete Skill Directories

Remove entirely (git rm -r):

```
plugins/proj/skills/define/
plugins/proj/skills/execute/
plugins/proj/skills/run/
plugins/proj/skills/run-batch/
plugins/proj/skills/refine/
plugins/proj/skills/decompose/
plugins/proj/skills/quick/
plugins/proj/skills/_shared/       ← only used by run/run-batch/execute, safe to remove
```

**Skills retained** (not touched): `add-repo`, `archive`, `create-skill`, `explore`, `flatten-children`, `init`, `init-plugin`, `jira-apply`, `jira-map`, `jira-sync`, `jira-sync-trello`, `list-proj`, `load`, `migrate`, `prioritize`, `purge`, `remove-repo`, `sandbox`, `save`, `status`, `switch`, `team-status`, `todo`, `todoist-sync`, `trello-setup`, `trello-sync`

## Commit 2: Python Tool Removal

### `plugins/proj/server/server/tools/todos.py`

Remove `todo_check_executable` MCP tool:
- Remove function definition (`def todo_check_executable(...)`)
- Remove from export list in `register()` (line ~365: `todo_set_content_flag, todo_check_executable,`)

**Keep:** `todo_set_content_flag` — still used; `has_requirements`/`has_research` flags are set by the Superpowers+CPM integration flow and displayed in todo output.

### `plugins/proj/server/tests/test_mcp_tools.py`

Remove 4 tests:
- `test_todo_check_executable_returns_todo_when_not_manual`
- `test_todo_check_executable_blocks_manual_tagged_todo`
- `test_todo_check_executable_returns_todo_for_multi_tag_without_manual`
- `test_todo_check_executable_returns_error_for_missing_todo`

**Verify:** Run full server test suite after — must be green.

## Commit 3: Doc/Config Cleanup

### `installer/claudemd.py` — `MANAGED_SECTION`

Delete these 4 rules entirely (they reference deleted skills):

1. **"Define-phase question batching"** — mentions `/proj:define`
2. **"N distinct agents per N roles"** — mentions `/proj:refine`, `/proj:run`, `/proj:execute`, `/proj:decompose`
3. **"Escalation on plan gaps"** — mentions `/proj:run`, `/proj:execute`
4. **"TaskCreate during /proj:run and /proj:execute"** — mentions deleted skills by name

### `installer/tests/test_claudemd.py` — `TestManagedSectionContent`

Remove tests asserting the 4 deleted rules exist:
- `test_interactive_qa_mentions_ask_user_question` — keep (rule stays)
- `test_managed_section_contains_ask_user_question_batching_rule` — keep (rule stays)
- `test_managed_section_still_has_preexisting_rules` — **update**: remove `"/proj:define"`, `"Define-phase"`, `"N distinct agents"`, `"Escalation on plan gaps"` from assertions; keep remaining
- `test_n_distinct_agents_canonical_sentence_in_managed_section` — **delete** (rule removed)
- `test_escalation_rule_in_managed_section` — **delete** (rule removed)
- `test_taskcreate_during_run_and_execute` — **delete** (rule removed)

### `plugins/proj/CLAUDE.md`

Remove these sections entirely:
- **"Worktree Isolation"** section — references `/proj:run` workflow
- **"Verification"** section — references `/proj:execute`, `/proj:run` verification step
- **`manual` tag behaviour** block — references `/proj:execute`, `/proj:run` skip behaviour
- **"Default --iter 5 for /proj:run"** line in Key Conventions
- In **"Batch Completion Enforcement"**: trim "Skills that mark todos done in a loop (execute, run, quick) must collect ids first" sentence

### `plugins/proj/skills/status/SKILL.md`

Line ~64:
```
Suggested next: `1. /proj:execute 3` -- start work on ready task | ...
```
→
```
Suggested next: `1. /superpowers:brainstorming <id>` -- start work on ready task | ...
```

### `plugins/proj/skills/todo/SKILL.md`

Line ~115:
```
Suggested next: After add → `1. /proj:define <id>` | After done → `1. /proj:status`
```
→
```
Suggested next: After add → `1. /superpowers:brainstorming <id>` | After done → `1. /proj:status`
```

### `README.md`

Remove from workflow skill table:
- `/proj:define <id>` row
- `/proj:decompose <id>` row
- `/proj:execute <id>` row
- `/proj:run <id>` row
- `/proj:run-batch <ids>` row

Update plugin description paragraph (~line 108):
- Remove "The `run` skill chains define, decompose, and execute steps with parallel agent execution."
- Replace with: "Todos use dot-notation IDs (`1`, `1.1`, `1.1.1`) with blocking relationships."

## Out of Scope

- Removing `content_set_requirements`, `content_set_research`, `content_patch_*`, `content_get_*` tools — still used by Superpowers+CPM integration (todo 626)
- Removing `proj_decision_log` — still used by `save` skill
- Removing `proj_explore_codebase` — still used by `init` skill
- Removing `proj_identify_batches` — still used by `todo` and `prioritize` skills
- Removing `todo_set_content_flag` — still useful for the integration flow
- Updating installer wizard skill-selection UI — separate concern
- Removing refine-related agent subagent types — separate concern (605)

## Testing

- Commit 2: `uv run pytest plugins/proj/server/tests/ -q` — must be green
- Commit 3: `uv run pytest installer/tests/test_claudemd.py -q` — must be green after test updates
- Manual: confirm no `NameError` or missing import from `todo_check_executable` removal

## Q&A Transcript

**Q:** Should CLAUDE.md rules referencing deleted skills be deleted or updated to Superpowers equivalents?
**A:** Delete entirely (option A) — Superpowers has its own enforcement built in.

**Q:** Should `todo_set_content_flag` be removed?
**A:** Keep — still useful for the 626 integration and todo display.

**Q:** Commit strategy?
**A:** 3 logical commits: skill dirs → Python → docs.

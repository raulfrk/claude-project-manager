---
name: quick
description: Quick-start a project or todo and immediately run the full workflow. Use when the user says "quick project", "proj:quick", or wants to start something new fast.
argument-hint: "[description or project-name]"
allowed-tools: mcp__proj__config_load, mcp__proj__proj_init, mcp__proj__proj_load_session, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__proj__proj_setup_permissions, mcp__proj__claudemd_write, mcp__proj__todo_add, mcp__proj__todo_update, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_tree, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, Bash, Read, Task, EnterPlanMode, ExitPlanMode, Skill
---

Quick-start: $ARGUMENTS

**1. Detect mode**

Call `mcp__proj__proj_get_active` to check if there is an active project.

- If an active project exists: go to **Todo mode** (create a todo on the active project)
- If no active project: go to **Project mode** (create a new project)

---

## Todo mode (active project exists)

**T1. Parse $ARGUMENTS**

Split into a description and flags:
- Known flags: `--steps`, `--from`, `--iter`, `--no-interactive`
- Everything that is not a flag or flag-value is the **description**.

If description is empty, ask: `What would you like to work on?`

**T2. Create the todo**

Call `mcp__proj__config_load` for config.
Call `mcp__proj__todo_add` with `title` = description, `priority` = config `default_priority`.
Store returned ID as `new_id`.

**T3. Todoist sync (if enabled)**

If `todoist.enabled` and `todoist.auto_sync`:
- Get `todoist_project_id` from `mcp__proj__proj_get_active`.
- If null: call `mcp__{todoist.mcp_server}__find-projects`, ask user to pick, update meta.
- Call `mcp__{todoist.mcp_server}__add-tasks` with the todo. Store returned task ID.
- Call `mcp__proj__todo_update` with `todoist_task_id`.

**T3b. Trello sync (if enabled)**

If Trello auto-sync (trello.enabled=true via config_load, project has trello_card_id):
- Determine checklist: if parent todo has `trello_checklist_id`, use that. Otherwise call `mcp__trello__get_card_checklists(card_id)` to find existing "Tasks" checklist; if none, call `mcp__trello__create_checklist(card_id, name="Tasks")` and store `trello_checklist_id` on the root todo.
- Call `mcp__trello__add_checklist_item(checklist_id, name=title)`
- Store returned item ID: call `mcp__proj__todo_update` with `trello_checklist_item_id=<returned id>`

**T3c. Trello title update sync**

If `mcp__proj__todo_update` is called with a `title` change AND the todo has `trello_checklist_item_id`:
- Call `mcp__trello__rename_checklist_item(card_id, checklist_id, item_id, name=new_title)` where card_id comes from project's `trello_card_id`, checklist_id from todo's parent's `trello_checklist_id`

**T4. Launch workflow**

Display: `Created todo <new_id>: <title>. Running workflow...`

Call the Skill tool: `skill: "proj:run", args: "<new_id> <forwarded-flags>"`

The run skill handles the full define → decompose → execute workflow including plan mode.

**T5. Done/complete** (when the run skill completes and the todo is marked done)

- If Trello auto-sync AND todo has `trello_checklist_item_id`:
  - Call `mcp__trello__update_checklist_item(card_id, checklist_id, item_id, state="complete")` where card_id from project's `trello_card_id`

---

## Project mode (no active project)

**P1. Project name**

If `$ARGUMENTS` is non-empty, use it as project name. Otherwise ask.
Confirm: `Project name: <name> — correct?`

**P2. Todo title**

Ask: `What would you like to work on? (This becomes the first todo.)`
Store as `todo_title`.

**P3. Project location**

Call `mcp__proj__config_load` for config.

Present options:
- If `projects_base_dir` is set:
  1. Existing directory
  2. New directory — create `<projects_base_dir>/<name>/`
  3. Worktree
- If not set:
  1. Existing directory
  2. Worktree

Handle each option (validate path, mkdir, or wt_create). Store as `content_path`.

**P4. Initialize**

Call `mcp__proj__proj_init` with `name`, `path=content_path`, `description=todo_title`.
Call `mcp__proj__proj_load_session`.

**P5. Permissions**

If `perms_integration: true`:
- Build MCP server list: `["plugin_proj_proj", "plugin_perms_perms"]` + worktree if enabled + todoist server if enabled + `"jira"` if jira.enabled + `"trello"` if trello.enabled.
- Call `mcp__proj__proj_setup_permissions` silently.

**P6. CLAUDE.md**

Call `mcp__proj__claudemd_write` with project overview template.

**P7. Create todo and Todoist sync**

Call `mcp__proj__todo_add` with `title=todo_title`, `priority=default_priority`.
If Todoist enabled: sync as in Todo mode step T3.

**P8. Launch workflow**

Display: `Project '<name>' created. Todo <new_id>: <todo_title>. Running workflow...`

Call the Skill tool: `skill: "proj:run", args: "<new_id> --iter 3"`

The run skill handles the full define → decompose → execute workflow including plan mode.

Suggested next:
- `/proj:todo list` — review all todos
- `/proj:status` — see project overview

---
name: quick
description: Quick-start a project or todo and immediately run the full workflow. Use when the user says "quick project", "proj:quick", or wants to start something new fast.
disable-model-invocation: "true"
argument-hint: "[description or project-name]"
allowed-tools: mcp__proj__config_load, mcp__proj__proj_init, mcp__proj__proj_load_session, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__proj__proj_setup_permissions, mcp__proj__claudemd_write, mcp__proj__todo_add, mcp__proj__todo_update, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_tree, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, Bash, Read, Task, EnterPlanMode, ExitPlanMode
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

**T4. Launch workflow**

Display: `Created todo <new_id>: <title>. Running workflow...`

Read `<parent-of-this-skill's-base-dir>/run/SKILL.md`. Extract instructions after second `---`.
Execute with `$ARGUMENTS` = `<new_id> <forwarded-flags>`.

**Plan mode requirements:**
- For the **define** step: call `EnterPlanMode` / `ExitPlanMode` unless the task is trivial (single-line fix, obvious change).
- For the **execute** step: ALWAYS call `EnterPlanMode` before implementing, then `ExitPlanMode` for user approval. This is mandatory — never skip plan mode before executing.

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
- Build MCP server list: `["plugin_proj_proj", "plugin_perms_perms"]` + worktree if enabled + todoist server if enabled.
- Call `mcp__proj__proj_setup_permissions` silently.

**P6. CLAUDE.md**

Call `mcp__proj__claudemd_write` with project overview template.

**P7. Create todo and Todoist sync**

Call `mcp__proj__todo_add` with `title=todo_title`, `priority=default_priority`.
If Todoist enabled: sync as in Todo mode step T3.

**P8. Launch workflow**

Display: `Project '<name>' created. Todo <new_id>: <todo_title>. Running workflow...`

Read `<parent-of-this-skill's-base-dir>/run/SKILL.md`. Extract instructions after second `---`.
Execute with `$ARGUMENTS` = `<new_id> --iter 3`.

**Plan mode requirements:**
- For the **define** step: call `EnterPlanMode` / `ExitPlanMode` unless the task is trivial (single-line fix, obvious change).
- For the **execute** step: ALWAYS call `EnterPlanMode` before implementing, then `ExitPlanMode` for user approval. This is mandatory — never skip plan mode before executing.

Suggested next:
- `/proj:todo list` — review all todos
- `/proj:status` — see project overview

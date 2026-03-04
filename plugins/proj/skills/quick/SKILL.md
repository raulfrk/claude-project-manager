---
name: quick
description: Create a new project and immediately launch full-workflow on the first todo in one command. Use when the user says "quick project", "proj:quick", or wants to start a new project without the full interactive init process.
disable-model-invocation: "true"
argument-hint: "[project-name]"
allowed-tools: mcp__proj__config_load, mcp__proj__proj_init, mcp__proj__proj_set_active, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__proj__proj_setup_permissions, mcp__proj__claudemd_write, mcp__proj__todo_add, mcp__proj__todo_update, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_tree, mcp__worktree__wt_list_repos, mcp__worktree__wt_create, mcp__claude_ai_Todoist__add-tasks, mcp__claude_ai_Todoist__complete-tasks, mcp__sentry__find-projects, Bash, Read, Task
---

Create a new project and immediately launch full-workflow on the first todo: $ARGUMENTS

**Collect all interactive input before making any MCP tool calls for init or tracking.**

**Step 1 — Project name**

- If `$ARGUMENTS` is non-empty, use it as the project name.
- Otherwise ask: `What is the project name?`
- Confirm: `Project name: <name> — correct? [yes]`
  - If the user says no or provides a correction, update and re-confirm.

**Step 2 — Todo title**

Ask: `What would you like to work on? (This becomes the first todo.)`

Wait for input. Store as `todo_title`. Do not parse flags out of this input — treat it as plain text.

**Step 3 — Project location**

Call `mcp__proj__config_load` to read global config (`tracking_dir`, `projects_base_dir`, `todoist`, `perms_integration`, `worktree_integration`, `default_priority`). Store the full config for reuse — do not call config_load again later.

Check whether `projects_base_dir` is set (non-null and non-empty) in config.

Present the location options:

If `projects_base_dir` IS set:

```
Where should this project live?

1. Existing directory — I'll provide a path
2. New directory — create <projects_base_dir>/<name>/ automatically
3. Worktree — create a git worktree from a registered repo

Enter 1, 2, or 3:
```

If `projects_base_dir` is NOT set:

```
Where should this project live?

1. Existing directory — I'll provide a path
2. Worktree — create a git worktree from a registered repo

Enter 1 or 2:
```

**Option 1 — Existing directory:**
- Ask: `Path to the existing directory:`
- Validate: `Bash: test -d <path>`
  - If the path does not exist: show `Error: directory '<path>' does not exist. Please provide a valid path.` and re-prompt for the path.
  - Repeat until a valid path is provided.
- Store as `content_path`.

**Option 2 — New directory** (only available when `projects_base_dir` is set):
- Derive `content_path = <projects_base_dir>/<name>`.
- Run: `Bash: mkdir -p <content_path>`
- Confirm: `Created <content_path>.`

**Option 3 — Worktree** (shown as option 2 when `projects_base_dir` is not set):
- Call `mcp__worktree__wt_list_repos` to list available base repos.
  - If the list is empty: show `No registered repos found. Register a repo first with /worktree:add-repo, or choose a different location option.` Re-show the location prompt from the beginning of Step 3.
- Display the list of repo labels.
- Ask: `Which repo? (label from the list above)`
- Ask: `Branch name for the worktree:`
- Call `mcp__worktree__wt_create` with `repo_label=<chosen>`, `branch=<branch>`, `new_branch=true`.
- Store the returned worktree path as `content_path`.
- Confirm: `Worktree created at <content_path>.`

**Step 4 — Initialize project tracking**

Call `mcp__proj__proj_init` with:
- `name` = project name
- `path` = `content_path`
- `description` = `todo_title` (reused as description; user can refine later)
- `git_enabled` = global config default (do not ask the user)

Call `mcp__proj__proj_set_active` to set the new project as the active project for this session.

**Step 5 — Permissions**

If `perms_integration: true` in config (and project auto_grant is not explicitly false):

Build the MCP server list:
- Always include: `["plugin_proj_proj", "plugin_perms_perms"]`
- Add `"plugin_worktree_worktree"` if `worktree_integration: true` in config.
- Add the value of `todoist.mcp_server` (e.g. `"claude_ai_Todoist"`) if `todoist.enabled: true` in config.

Call `mcp__proj__proj_setup_permissions` with:
- `grant_path_access=true`
- `grant_investigation_tools=true`
- `mcp_servers=<built list>`

Do not prompt the user — apply silently.

If `perms_integration` is false or not set, skip this step entirely.

**Step 6 — CLAUDE.md**

Call `mcp__proj__claudemd_write` for `content_path` with this content (substituting `<name>` and `<todo_title>`):

```markdown
# <name>

**Status**: active | **Priority**: medium
**Tracking**: ~/projects/tracking/<name>

## Overview
<todo_title>

## Active Todos
None yet — full-workflow is running.
```

**Step 7 — Create the todo**

Call `mcp__proj__todo_add` with:
- `title` = `todo_title`
- `priority` = config `default_priority` (from the config loaded in Step 3)
- No tags, no parent, no blocked_by

Store the returned ID as `new_id`.

**Step 8 — Todoist sync**

If `todoist.enabled` is `true` AND `todoist.auto_sync` is `true`:

- Call `mcp__proj__proj_get_active` to read `todoist_project_id`.
- If `todoist_project_id` is null:
  - Call `mcp__sentry__find-projects` (replace `mcp__sentry__` with `mcp__{todoist.mcp_server}__` per config).
  - Present a numbered list of project names.
  - Ask: `Which Todoist project should tasks for '<name>' go to? (enter number)`
  - Call `mcp__proj__proj_update_meta` with the chosen `todoist_project_id`.
- Call `mcp__{todoist.mcp_server}__add-tasks` with:
  - `tasks`: `[{ "content": todo_title, "priority": <mapped>, "projectId": todoist_project_id }]`
  - Priority mapping: `high` → `p2`, `medium` → `p3`, `low` → `p4`
- Store the returned Todoist task ID.
- Call `mcp__proj__todo_update` with `todo_id=new_id` and `todoist_task_id=<returned ID>`.

If `todoist.enabled` is false or `todoist.auto_sync` is false, skip this step entirely.

**Step 9 — Announce and launch full-workflow**

Display:

```
Project '<name>' created. Todo <new_id>: <todo_title>.
Launching full-workflow with --iter-as-needed 5...
```

This skill's base directory ends in `.../skills/quick`. The full-workflow skill is at `.../skills/full-workflow/SKILL.md`.

- Construct the path: `<parent-of-this-skill's-base-dir>/full-workflow/SKILL.md`
- Call `Read` on that path to load the full-workflow skill file.
- Extract the Markdown instructions — everything after the second `---` frontmatter delimiter.
- Execute those instructions exactly, substituting `$ARGUMENTS` with:

```
<new_id> --iter-as-needed 5
```

This is identical to the user having run `/proj:full-workflow <new_id> --iter-as-needed 5` directly. All interactive prompts, convergence checks, and execute steps apply as documented in full-workflow/SKILL.md.

---
name: quick-workflow
description: Create a new todo and immediately run the full workflow on it in one command. Use when the user says "quick workflow", "proj:quick-workflow", or wants to start working on something new without a separate add step.
disable-model-invocation: "true"
allowed-tools: mcp__proj__todo_add, mcp__proj__todo_update, mcp__proj__config_load, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__proj__claudemd_write, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__claude_ai_Todoist__add-tasks, mcp__claude_ai_Todoist__complete-tasks, mcp__sentry__find-projects, Read, Task
argument-hint: "<description> [--steps define,execute] [--from <step>] [--iter N] [--iter-as-needed[=N]]"
---

Create a new todo and run full-workflow on it: $ARGUMENTS

**1. Parse $ARGUMENTS**

Split the raw `$ARGUMENTS` string into a description and flags:

- Known flags: `--steps`, `--from`, `--iter`, `--iter-as-needed`, `--no-interactive`
- Scan tokens from left to right. Collect all tokens that are not a known flag (and not a value immediately following `--steps`, `--from`, or `--iter`) as the **description tokens**. Join them with spaces to form the `description`.
- Extract each flag and its value exactly as-is (they will be forwarded to full-workflow unchanged).
- Example: `"Fix login bug --steps define,research --iter 2"` → description=`"Fix login bug"`, forwarded flags=`"--steps define,research --iter 2"`.

If `description` is empty after parsing, ask the user:

```
What would you like to work on?
```

Wait for their response and use it as the `description`. Do not apply any flag parsing to the user's reply — treat it as plain description text.

**2. Create the todo**

Call `mcp__proj__config_load` to get the config (needed for default_priority and Todoist settings).

Call `mcp__proj__todo_add` with:
- `title` = `description`
- `priority` = config `default_priority` (typically `medium`)
- No tags, no parent, no blocked_by

Store the returned todo ID as `new_id` and the title as `new_title`.

**3. Todoist sync (if enabled)**

If `todoist.enabled` is `true` AND `todoist.auto_sync` is `true`:

- Call `mcp__proj__proj_get_active` to read `todoist_project_id`.
- If `todoist_project_id` is null: call `mcp__sentry__find-projects`, present a numbered list of project names, ask "Which Todoist project should tasks for '<project name>' go to? (enter number)", then call `mcp__proj__proj_update_meta` with the chosen `todoist_project_id`. Use the chosen ID for this call.
- Call `mcp__claude_ai_Todoist__add-tasks` with:
  - `tasks`: `[{ "content": new_title, "priority": <mapped: high→p2, medium→p3, low→p4>, "projectId": todoist_project_id }]`
- Store the returned task ID as `todoist_task_id`.
- Call `mcp__proj__todo_update` with `todo_id=new_id` and `todoist_task_id=todoist_task_id`.

**4. Announce**

Display:

```
Created todo <new_id>: <new_title>. Running full-workflow...
```

**5. Delegate to full-workflow**

This skill's base directory ends in `.../skills/quick-workflow`. The full-workflow skill is at `.../skills/full-workflow/SKILL.md`.

- Construct the path: `<parent-of-this-skill's-base-dir>/full-workflow/SKILL.md`
- Call `Read` on that path to load the full-workflow skill file.
- Extract the Markdown instructions — everything after the second `---` frontmatter delimiter.
- Execute those instructions exactly, substituting `$ARGUMENTS` with: `<new_id> <forwarded-flags>` (the new todo ID followed by any flags extracted in step 1, in their original form).

The full-workflow execution is identical to the user having run `/proj:full-workflow <new_id> <forwarded-flags>` directly. All interactive prompts, step filters, iteration modes, and child-workflow behaviour apply exactly as documented in full-workflow/SKILL.md.

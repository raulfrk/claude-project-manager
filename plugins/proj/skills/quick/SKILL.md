---
name: quick
description: Quick-start a project or todo and immediately run the full workflow. Use when the user says "quick project", "proj:quick", or wants to start something new fast.
argument-hint: "[description or project-name]"
allowed-tools: mcp__proj__proj_session_context, mcp__proj__config_load, mcp__proj__proj_init, mcp__proj__proj_load_session, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__proj__proj_setup_permissions, mcp__proj__claudemd_write, mcp__proj__todo_add, mcp__proj__todo_update, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_tree, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, Bash, Read, Task, EnterPlanMode, ExitPlanMode, Skill
---

Quick-start: $ARGUMENTS

**1.** Detect mode

Call `mcp__proj__proj_session_context`.
> If proj_session_context returned "No active project" or "No config found", go to **Project Mode**.

- Active project returned -> **Todo Mode** (use the returned config and project data throughout)
- No active project -> **Project Mode**

---

## Todo Mode

**T1.** Parse arguments

Split $ARGUMENTS into description + flags.
Known flags: `--steps`, `--from`, `--iter`, `--no-interactive`.
Everything else is the **description**.
If description is empty, ask: `What would you like to work on?`

**T2.** Create local todo

Use the `proj_session_context` result from step 1 for config values (e.g., `config.default_priority`).

Call `mcp__proj__todo_add` with `title` = description, `priority` = config `default_priority`.
> If todo_add returned an error, go to **Error Recovery**.

Store returned ID as `new_id`.

**T3.** Launch workflow

Display: `Created todo <new_id>: <title>. Running workflow...`

Call the Skill tool: `skill: "proj:run", args: "<new_id> <forwarded-flags>"`

---

## Project Mode

**P1.** Project name

If $ARGUMENTS is non-empty, use as project name. Otherwise ask.
Confirm: `Project name: <name> -- correct?`

**P2.** Todo title

Ask: `What would you like to work on? (This becomes the first todo.)`
Store as `todo_title`.

**P3.** Project location

Call `mcp__proj__config_load`.
> If config_load returned an error, go to **Error Recovery**.

Present options:
- If `projects_base_dir` set: (1) Existing dir, (2) New dir at `<projects_base_dir>/<name>/`, (3) Worktree
- If not set: (1) Existing dir, (2) Worktree

Handle selection: validate path, mkdir, or wt_create. Store as `content_path`.
> If wt_create returned an error, go to **Error Recovery**.

**P4.** Initialize

Call `mcp__proj__proj_init` with `name`, `path=content_path`, `description=todo_title`.
> If proj_init returned an error, go to **Error Recovery**.

Call `mcp__proj__proj_load_session`.
> If proj_load_session returned an error, go to **Error Recovery**.

**P5.** Permissions

Skip unless `sandbox_integration: true` in config.

Call `mcp__proj__proj_setup_permissions` with `mcp_servers=[<list>]` — build list:
  always include `"plugin_proj_proj"`, `"plugin_sandbox_sandbox"`, `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`;
  add `"plugin_worktree_worktree"` if worktree_integration; add `"todoist"` if todoist.enabled; add `"trello"` if trello.enabled; add `"jira"` if jira.enabled.
> If proj_setup_permissions returned an error, go to **Error Recovery**.

**P6.** CLAUDE.md

Call `mcp__proj__claudemd_write` with project overview template.
> If claudemd_write returned an error, go to **Error Recovery**.

**P7.** Create todo and sync

Call `mcp__proj__todo_add` with `title=todo_title`, `priority=default_priority`.
> If todo_add returned an error, go to **Error Recovery**.

**P8.** Launch workflow

Display: `Project '<name>' created. Todo <new_id>: <todo_title>. Running workflow...`

Call the Skill tool: `skill: "proj:run", args: "<new_id> --iter 3"`

Suggested next: `1. /proj:todo list` -- review all todos | `2. /proj:status` -- see project overview

---

## Prerequisites

- Proj plugin must be configured (`~/.claude/proj.yaml` exists).
- **Todo mode**: an active project must be loaded.
- **Project mode**: no active project required (creates one).

## Error Handling

**Root cause of prior step-skipping**: The original SKILL.md had no explicit failure
paths after MCP tool calls. When a call failed, the model had no instructions for how to
handle it — leading to silent skips where entire steps were dropped without error messages.
The fix is structural: every MCP call now has an inline "> If ... error, go to Error Recovery"
guard, and this section classifies steps as required vs optional so the model knows when to
stop and when to continue.

When any MCP tool call fails, do the following:

1. Log which step failed and the error message.
2. List completed steps so far.
3. Display to user:
   ```
   Quick-start failed at step <step>: <error summary>
   Completed: <list of completed steps>
   Failed: <step that errored>
   ```
4. If the failure is in a required step (T2, P3, P4, P5, P6, or the todo_add in P7):
   - Stop and display the error. Do not proceed to the workflow launch.
6. Never silently swallow errors. Always surface what failed and what succeeded.

## Output

- **Todo mode**: `Created todo <id>: <title>. Running workflow...` followed by the full `/proj:run` output.
- **Project mode**: `Project '<name>' created. Todo <id>: <title>. Running workflow...` followed by the full `/proj:run` output.
- **On failure**: `Quick-start failed at step <step>: <error summary>` with list of completed and failed steps.

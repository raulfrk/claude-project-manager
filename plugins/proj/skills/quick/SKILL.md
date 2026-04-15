---
name: quick
description: Quick-start a project or todo and immediately run the full workflow. Use when the user says "quick project", "proj:quick", or wants to start something new fast.
argument-hint: "[description or project-name]"
allowed-tools: mcp__proj__proj_session_context, mcp__proj__config_load, mcp__proj__proj_init, mcp__proj__proj_load_session, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__proj__proj_setup_permissions, mcp__proj__claudemd_write, mcp__proj__todo_add, mcp__proj__todo_update, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__todo_notes_patch, mcp__proj__todo_notes_append, mcp__proj__proj_identify_batches, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_tree, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, Bash, Read, Task, EnterPlanMode, ExitPlanMode, Skill
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Quick-start: $ARGUMENTS

**1.** Detect mode

Call `mcp__proj__proj_session_context`.
> "No active project"/"No config found" → **Project Mode**.

- Active project → **Todo Mode** (use returned config/project data throughout)
- No active project → **Project Mode**


## Todo Mode

**T1.** Parse args

Split $ARGUMENTS into desc + flags.
Flags: `--steps`, `--from`, `--iter`, `--no-interactive`.
Rest = **desc**.
Empty desc → ask: `What would you like to work on?`

**T2.** Create local todo

Use `proj_session_context` result for config vals (e.g., `config.default_priority`).

`mcp__proj__todo_add(title=description, priority=config.default_priority)`.
> Error → **Error Recovery**.

Store returned ID as `new_id`.

**T3.** Launch workflow

Show: `Created todo <new_id>: <title>. Running workflow...`

`skill: "proj:run", args: "<new_id> <forwarded-flags>"`


## Project Mode

**P1.** Project name

$ARGUMENTS non-empty → use as name. Otherwise ask.
Confirm: `Project name: <name> -- correct?`

**P2.** Todo title

Ask: `What would you like to work on? (This becomes the first todo.)`
Store as `todo_title`.

**P3.** Project location

`mcp__proj__config_load`.
> Error → **Error Recovery**.

Options:
- `projects_base_dir` set: (1) Existing dir, (2) New dir at `<projects_base_dir>/<name>/`, (3) Worktree
- Not set: (1) Existing dir, (2) Worktree

Handle selection: validate path, mkdir, or `wt_create`. Store as `content_path`.
> `wt_create` error → **Error Recovery**.

**P4.** Init

`mcp__proj__proj_init(name, path=content_path, description=todo_title)`.
> Error → **Error Recovery**.

`mcp__proj__proj_load_session`.
> Error → **Error Recovery**.

**P5.** Permissions

Skip unless `sandbox_integration: true` in config.

`mcp__proj__proj_setup_permissions(mcp_servers=[<list>])` — build list:
 always: `"plugin_proj_proj"`, `"plugin_sandbox_sandbox"`, `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`;
 add `"plugin_worktree_worktree"` if worktree_integration; `"todoist"` if todoist.enabled; `"trello"` if trello.enabled; `"jira"` if jira.enabled.
> Error → **Error Recovery**.

**P6.** CLAUDE.md

`mcp__proj__claudemd_write` w/ project overview tpl.
> Error → **Error Recovery**.

**P7.** Create todo + sync

`mcp__proj__todo_add(title=todo_title, priority=default_priority)`.
> Error → **Error Recovery**.

**P8.** Launch workflow

Show: `Project '<name>' created. Todo <new_id>: <todo_title>. Running workflow...`

`skill: "proj:run", args: "<new_id> --iter 3"`

Suggested next: `1. /proj:todo list` -- review todos | `2. /proj:status` -- project overview


## Prerequisites

- Proj plugin configured (`~/.claude/proj.yaml` exists).
- Todo mode: active project loaded.
- Project mode: no active project required (creates one).

## Error Handling

Every MCP call has inline "> If error → Error Recovery" guard. Required vs optional steps classified so model knows when to stop vs continue.

On any MCP call failure:

1. Log failed step + err msg.
2. List completed steps.
3. Show:
   ```
   Quick-start failed at step <step>: <error summary>
   Completed: <list of completed steps>
   Failed: <step that errored>
   ```
4. Required step failure (T2, P3, P4, P5, P6, todo_add in P7) → stop, show err. No workflow launch.
6. Never swallow errors silently. Always surface what failed/succeeded.

## Output

- Todo mode: `Created todo <id>: <title>. Running workflow...` + full `/proj:run` output.
- Project mode: `Project '<name>' created. Todo <id>: <title>. Running workflow...` + full `/proj:run` output.
- Failure: `Quick-start failed at step <step>: <error summary>` w/ completed/failed step list.

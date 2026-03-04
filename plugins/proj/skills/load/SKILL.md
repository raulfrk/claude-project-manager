---
name: load
description: Load a specific project for this session, even if Claude was not started in that project's directory. Use when asked "load project", "switch to project", or "open project".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_list, mcp__proj__proj_load_session, mcp__proj__ctx_session_start, mcp__proj__config_load, mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__todo_add, mcp__proj__todo_delete, mcp__proj__proj_find_archived_by_title, Bash, Read
argument-hint: "[project-name]"
---

Load a project context for this session only (not persisted globally).

1. If $ARGUMENTS is empty:
   - Call `mcp__proj__proj_list` to get all tracked projects
   - Present a numbered list and ask the user to pick one
   - Use their response as the project name

2. If $ARGUMENTS is provided:
   - Call `mcp__proj__proj_load_session` with the name
   - The tool handles fuzzy matching automatically
   - If the tool returns an "Ambiguous match" message, present the options and ask the user to confirm

3. After successful load:
   - Call `mcp__proj__ctx_session_start` to get the full project context
   - Confirm: "Loaded project '<name>' for this session. This session is now working on <name>."

3.5. **Display last session context** (before todos):
   - Call `mcp__proj__config_load` to get `tracking_dir`. Call `mcp__proj__proj_get_active` to get the project `name`.
   - Use Bash: `ls <tracking_dir>/<name>/sessions/session-*.md 2>/dev/null | sort | tail -1`
   - If the result is non-empty: read that file with the Read tool and display it under the heading `### Last Session` — show this **before** the ctx_session_start context block (todos, notes).
   - If no session files exist: skip silently.
   - Then display the ctx_session_start context (project header, todos, recent notes).

4. **Auto-sync with Todoist** (if configured):
   - Call `mcp__proj__config_load` to read global config.
   - If `todoist.enabled: true` AND `todoist.auto_sync: true`: run the full bidirectional sync.
   - Follow the exact same algorithm as `/proj:sync` (steps 1–6 in that skill).
   - **Todoist tool names are dynamic**: use `mcp__{todoist.mcp_server}__<tool>` as the prefix
     for all Todoist calls (e.g. if `todoist.mcp_server` is `sentry`, call `mcp__sentry__find-tasks`).
   - Display the sync summary inline after the load confirmation.
   - If `todoist.enabled` is false or `todoist.auto_sync` is false: skip silently.

5. Note: This only affects this session. Other parallel Claude sessions are unaffected.

Suggested next: /proj:status — see full project status  /proj:todo list — see all todos

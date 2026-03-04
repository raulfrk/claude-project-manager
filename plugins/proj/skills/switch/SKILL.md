---
name: switch
description: Switch the active project context. Use when the user says "switch to <project>", "change project", or "work on <project>".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_list, mcp__proj__proj_set_active, mcp__proj__ctx_session_start, mcp__claude_ai_Todoist__find-tasks, mcp__proj__todo_update, mcp__proj__config_load
argument-hint: "[project-name]"
---

Switch the active project to $ARGUMENTS.

1. Call `mcp__proj__proj_list` to show available projects.

2. If $ARGUMENTS is empty, present the list and ask which to switch to.

3. Call `mcp__proj__proj_set_active` with the chosen name.

4. If Todoist `auto_sync: true`: pull current Todoist state for the new project.

5. Call `mcp__proj__ctx_session_start` and display the returned context so the user immediately sees the new project's status.

💡 Suggested next: (1) /proj:status — see the project status  (2) /proj:todo list — see all todos

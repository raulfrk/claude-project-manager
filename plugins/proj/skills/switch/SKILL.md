---
name: switch
description: Switch the active project context. Use when the user says "switch to <project>", "change project", or "work on <project>".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_list, mcp__proj__proj_set_active, mcp__proj__ctx_session_start
argument-hint: "[project-name]"
---

Switch the active project to $ARGUMENTS.

1. Call `mcp__proj__proj_list` to get all tracked projects.
   - If the list is empty: reply "No tracked projects. Use /proj:init to add one." and stop.

2. If $ARGUMENTS is empty, present the list and ask the user which project to switch to.
   If $ARGUMENTS is provided:
   - Find projects whose name matches $ARGUMENTS (case-insensitive, exact or prefix match).
   - If no match: reply "Project '<name>' not found. Use /proj:list to see available projects." and stop.
   - If more than one match: list the matching names and ask the user to confirm which one.

3. Call `mcp__proj__proj_set_active` with the confirmed project name.

4. Call `mcp__proj__ctx_session_start` and display the returned context so the user immediately sees the new project's status.

💡 Suggested next: (1) /proj:status — see the project status  (2) /proj:todo list — see all todos

---
name: switch
description: Switch the active project context. Use when the user says "switch to <project>", "change project", or "work on <project>".
allowed-tools: mcp__proj__proj_list, mcp__proj__proj_load_session, mcp__proj__ctx_session_start
argument-hint: "[project-name]"
---

Switch the active project to $ARGUMENTS.

**1.** Call `mcp__proj__proj_list` to get all tracked projects.
   - If the list is empty, stop with: "No tracked projects found. Run `/proj:init` to add one."

**2.** If $ARGUMENTS is empty, present the list and ask the user which project to switch to.
   If $ARGUMENTS is provided:
   - Find projects whose name matches $ARGUMENTS (case-insensitive, exact or prefix match).
   - If no match, stop with: "Project `<name>` not found. Run `/proj:list-proj` to see available projects."
   - If more than one match: list the matching names and ask the user to confirm which one.

**3.** Call `mcp__proj__proj_load_session` with the confirmed project name.

**4.** Call `mcp__proj__ctx_session_start` and display the returned context so the user immediately sees the new project's status.

## Prerequisites

- Proj plugin must be configured (`~/.claude/proj.yaml` exists).
- At least one project must exist.

## Error Handling

- **No tracked projects**: displays "No tracked projects found. Run `/proj:init` to add one." and stops.
- **Project not found**: displays "Project `<name>` not found. Run `/proj:list-proj` to see available projects." and stops.
- **Multiple matches**: lists matching names and asks the user to confirm.

## Output

Displays the new project's context (status, todos, recent activity) via `ctx_session_start`.

Suggested next: `1. /proj:status` -- see the project status | `2. /proj:todo list` -- see all todos

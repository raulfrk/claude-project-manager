---
name: switch
description: Switch the active project context. Use when the user says "switch to <project>", "change project", or "work on <project>".
allowed-tools: mcp__proj__proj_list, mcp__proj__proj_load_session, mcp__proj__ctx_session_start
argument-hint: "[project-name]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Switch active project to $ARGUMENTS.

**1.** `mcp__proj__proj_list` → get tracked projects.
 - Empty → stop: "No tracked projects found. Run `/proj:init` to add one."

**2.** $ARGUMENTS empty → present list, ask user which project.
 $ARGUMENTS provided:
 - Match name (case-insensitive, exact/prefix).
 - No match → stop: "Project `<name>` not found. Run `/proj:list-proj` to see available projects."
 - Multiple matches → list names, ask user to confirm.

**3.** `mcp__proj__proj_load_session` w/ confirmed project name.

**4.** `mcp__proj__ctx_session_start` → display returned ctx so user sees new project status.

## Prerequisites

- Proj plugin configured (`~/.claude/proj.yaml` exists).
- ≥1 project exists.

## Error Handling

- No tracked projects → "No tracked projects found. Run `/proj:init` to add one." Stop.
- Not found → "Project `<name>` not found. Run `/proj:list-proj` to see available projects." Stop.
- Multiple matches → list names, ask user to confirm.

## Output

New project ctx (status, todos, recent activity) via `ctx_session_start`.

Suggested next: `1. /proj:status` -- see project status | `2. /proj:todo list` -- see all todos

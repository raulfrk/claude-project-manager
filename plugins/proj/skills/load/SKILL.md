---
name: load
description: Load a specific project for this session, even if Claude was not started in that project's directory. Use when asked "load project", "switch to project", or "open project".
allowed-tools: mcp__proj__proj_list, mcp__proj__proj_load_session, mcp__proj__ctx_session_start, mcp__proj__proj_session_context, mcp__proj__proj_session_digest, mcp__proj__config_load, mcp__proj__proj_get_active, Bash, Read
argument-hint: "[project-name]"
---

Load a project context for this session only (not persisted globally).

**1.** If $ARGUMENTS is empty:
   - Call `mcp__proj__proj_list` to get all tracked projects
   - If the list is empty, stop with: "No tracked projects found. Run `/proj:init` to add one."
   - Present a numbered list and ask the user to pick one
   - Call `mcp__proj__proj_load_session` with the selected name
   - If the tool returns not-found, stop with: "Project not found. Run `/proj:init` to add it."

**2.** If $ARGUMENTS is provided:
   - Call `mcp__proj__proj_load_session` with the name
   - The tool handles fuzzy matching automatically
   - If the tool returns an "Ambiguous match" message, present the options and ask the user to confirm
   - If the tool returns not-found, stop with: "Project `<name>` not found. Run `/proj:init` to add it."

**3.** After successful load:
   - Call `mcp__proj__ctx_session_start` to get the full project context
   - Confirm: "Loaded project '<name>' for this session. This session is now working on <name>."

**3a.** Display last session context (before todos):
   - Call `mcp__proj__proj_session_context` to get `config.tracking_dir` and `project.name`.
   - Use Bash: `ls <tracking_dir>/<name>/sessions/session-*.md 2>/dev/null | sort | tail -1`
   - If the result is non-empty: read that file with the Read tool and display it under the heading `### Last Session` — show this **before** the ctx_session_start context block (todos, notes).
   - If no session files exist: skip silently.
   - Then display the ctx_session_start context (project header, todos, recent notes).

**4.** Note: This only affects this session. Other parallel Claude sessions are unaffected.

## Prerequisites

- Proj plugin must be configured (`~/.claude/proj.yaml` exists).
- At least one project must exist (run `/proj:init` first if none).

## Error Handling

- **No tracked projects**: displays "No tracked projects found. Run `/proj:init` to add one." and stops.
- **Project not found**: displays "Project `<name>` not found. Run `/proj:init` to add it." and stops.
- **Ambiguous match**: presents matching options and asks the user to confirm.
- **Load session error**: displays error from `proj_load_session` and stops.

## Output

Confirmation message: `Loaded project '<name>' for this session.` Followed by last session notes (if any) and full project context (todos, notes, recent activity).

Suggested next: `1. /proj:status` -- see full project status | `2. /proj:todo list` -- see all todos

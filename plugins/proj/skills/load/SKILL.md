---
name: load
description: Load a specific project for this session, even if Claude was not started in that project's directory. Use when asked "load project", "switch to project", or "open project".
allowed-tools: mcp__proj__proj_list, mcp__proj__proj_load_session, mcp__proj__ctx_session_start, mcp__proj__proj_session_context, mcp__proj__proj_session_digest, mcp__proj__config_load, mcp__proj__proj_get_active, Bash, Read
argument-hint: "[project-name]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Load project ctx for this session only (not persisted).

**1.** No $ARGUMENTS:
 - `mcp__proj__proj_list` → get tracked projects
 - Empty list → stop: "No tracked projects found. Run `/proj:init` to add one."
 - Show numbered list, ask user to pick
 - `mcp__proj__proj_load_session` w/ selected name
 - Not-found → stop: "Project not found. Run `/proj:init` to add it."

**2.** $ARGUMENTS provided:
 - `mcp__proj__proj_load_session` w/ name (handles fuzzy match)
 - "Ambiguous match" → present opts, ask user to confirm
 - Not-found → stop: "Project `<name>` not found. Run `/proj:init` to add it."

**3.** Successful load:
 - `mcp__proj__ctx_session_start` → get full project ctx
 - Confirm: "Loaded project '<name>' for this session. This session is now working on <name>."

**3a.** Surface handoff block from latest session — BEFORE other context:
 - `mcp__proj__proj_session_context` → get `config.tracking_dir` + `project.name`
 - Bash: `ls <tracking_dir>/<name>/sessions/session-*.md 2>/dev/null | sort | tail -1` → latest session file path
 - Empty → skip silently to step 3b
 - Read file, search for `## Next Session Resumes Here` heading
 - Heading absent (legacy session file) → skip silently to step 3b
 - Heading present → extract section + 4 subsections (Attempted / Blocked / Next Action / Files / Todos), display under top-level `# Next Session Resumes Here` heading verbatim, BEFORE step 3b output

**3b.** Show last session ctx (before todos):
 - `mcp__proj__proj_session_context` → get `config.tracking_dir` + `project.name`
 - Bash: `ls <tracking_dir>/<name>/sessions/session-*.md 2>/dev/null | sort | tail -1`
 - Non-empty → `Read` file, display under `### Last Session` **before** ctx_session_start block
 - No session files → skip silently
 - Then display ctx_session_start ctx (project header, todos, recent notes)

**4.** Session-only. Parallel Claude sessions unaffected.

## Prerequisites

- Proj plugin configured (`~/.claude/proj.yaml` exists)
- ≥1 project exists (`/proj:init` first if none)

## Err Handling

- No projects → "No tracked projects found. Run `/proj:init` to add one." Stop.
- Not found → "Project `<name>` not found. Run `/proj:init` to add it." Stop.
- Ambiguous → present matches, ask confirm.
- Load err → display err, stop.

## Output

Confirm msg: `Loaded project '<name>' for this session.` + last session notes (if any) + full project ctx (todos, notes, recent activity).

Suggested next: `1. /proj:status` -- full project status | `2. /proj:todo list` -- all todos

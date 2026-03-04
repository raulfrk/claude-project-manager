---
name: report
description: Generate a comprehensive project report — progress, completed work, git history, remaining todos. Use when asked "project report", "progress report", or "summarize the project".
disable-model-invocation: "true"
allowed-tools: Read, mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__todo_tree, mcp__proj__git_detect_work, mcp__proj__notes_append, Task
---

Generate a comprehensive project report for the active project.

Spawn three parallel Explore Task agents to gather data simultaneously:

1. **Agent 1 — Project & Todos**: Call `mcp__proj__proj_get_active` then `mcp__proj__todo_list` (status: all) and `mcp__proj__todo_tree`
2. **Agent 2 — Git History**: Call `mcp__proj__git_detect_work` (days: 30)
3. **Agent 3 — Notes**: Call `mcp__proj__proj_get_active` to get project path, then `Read` the NOTES.md file at `<tracking_dir>/NOTES.md`

Synthesize results into a structured Markdown report:

```markdown
# Project Report: <name>
Generated: <date>

## Summary
- **Status**: <status>  **Priority**: <priority>
- **Target**: <date>
- <description>

## Progress
### Completed (<count>)
- ✅ **1** — Implement storage layer _(medium)_ (linked: abc1234)
- ✅ **3** — Write tests _(low)_
  - ✅ **3.1** — Unit tests _(low)_
  - ✅ **3.2** — Integration tests _(medium)_

### In Progress (<count>)
- 🔄 **4** — Write skills _(high)_

### Pending (<count>)
- 🔲 **5** — Documentation _(medium)_ [blocked by 4]

## Git Activity (last 30 days)
- 2026-02-26  abc1234  Fix storage layer
- 2026-02-25  bcd2345  Add todo nested support

## Recent Notes
<excerpt from NOTES.md>
```

## Failure paths
- **No active project**: If `mcp__proj__proj_get_active` returns no active project, stop and tell the user: "No active project set. Run `/proj:set-active <name>` first."
- **NOTES.md not found**: If Agent 3 cannot read NOTES.md (file absent), omit the "Recent Notes" section from the report and note "No notes found."
- **Agent failure**: If any agent fails, include partial results and note which section is unavailable.

Present the report to the user.

## Suggested next
- `/proj:todo list` — view open todos
- `/proj:update` — update project status or notes
- `/proj:full-workflow <id>` — pick up and execute a todo

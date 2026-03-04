---
name: report
description: Generate a comprehensive project report — progress, completed work, git history, remaining todos. Use when asked "project report", "progress report", or "summarize the project".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__todo_tree, mcp__proj__git_detect_work, mcp__proj__notes_append, Task
---

Generate a comprehensive project report for the active project.

Spawn three parallel Explore Task agents to gather data simultaneously:

1. **Agent 1 — Project & Todos**: Read project metadata and all todos (completed + open)
2. **Agent 2 — Git History**: Read git activity for the last 30 days
3. **Agent 3 — Notes**: Read the project NOTES.md for context

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

Present the report to the user.

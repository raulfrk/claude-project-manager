---
name: status
description: Show the current project status, open todos, and recent git activity. Use when asked "what's the project status", "what are my todos", "what should I work on next", or "project overview".
allowed-tools: mcp__proj__proj_status_context, mcp__proj__proj_search_knowledge, mcp__proj__todo_update
context: fork
agent: general-purpose
---

Show a comprehensive status report for the active project.

**1.** Call `mcp__proj__proj_status_context` to get config, project metadata, categorised todos, and git activity in one call. If no active project, stop with: "No active project. Run `/proj:load` to load one."

**2.** For each in-progress todo matched to recent commits in `git_activity`, call `mcp__proj__todo_update(todo_id, git={branch: <branch>, commits: [<sha>, ...]})` to record the association.

**3.** Present a structured status summary. Display todos as bullet points with status icons, bold ID, title, priority in italics. Show children indented 2 spaces under their parent. Include `[manual]` badge after priority for manual-tagged todos. Include `[blocked by X]` for blocked todos and `[blocks Y]` for todos that block others. Order: `_(priority)_ [manual] [blocked by X] [blocks Y]`.
   ```
   ## <project-name>  [status] [priority]
   Target: <date>   Tracking: <tracking_dir>

   ### In Progress
   - 🔄 **2** — Implement MCP server _(medium)_ [blocks 4] (branch: feat/mcp-server)

   ### Ready to Start
   - 🔲 **3** — Write skills _(low)_ [manual]

   ### Blocked
   - 🔲 **4** — Integration tests _(medium)_ [blocked by 2]

   ### Recent Git Activity
   - abc1234  Fix storage layer (2026-02-26)
   ```

## Prerequisites

- An active project must be loaded.

## Error Handling

- **No active project**: displays "No active project. Run `/proj:load` to load one." and stops.
- **Status context error**: displays error from `proj_status_context` and stops.

## Output

Structured status report: project header (name, status, priority, target date, tracking dir), then sections for In Progress, Ready to Start, Blocked todos (with status icons, badges), and Recent Git Activity.

Suggested next: `1. /proj:execute 3` -- start work on a ready task | `2. /proj:todo add` -- add a new task | `3. /proj:save` -- save session and reconcile git

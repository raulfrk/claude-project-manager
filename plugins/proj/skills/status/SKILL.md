---
name: status
description: Show the current project status, open todos, and recent git activity. Use when asked "what's the project status", "what are my todos", "what should I work on next", or "project overview".
allowed-tools: mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__todo_ready, mcp__proj__git_detect_work, mcp__claude_ai_Todoist__find-tasks, mcp__proj__config_load
---

Show a comprehensive status report for the active project.

1. Call `mcp__proj__config_load` to check if Todoist sync is enabled.

2. If Todoist `auto_sync: true`:
   - Call `mcp__claude_ai_Todoist__find-tasks` to get Todoist task state
   - Compare with local todos; apply any completions or new tasks from Todoist
   - Update local todos via `mcp__proj__todo_update` as needed

3. Call `mcp__proj__proj_get_active` to get project metadata.

4. Call `mcp__proj__todo_list` to get all open todos.

5. Call `mcp__proj__todo_ready` to identify what can be started now.

6. Call `mcp__proj__git_detect_work` with since_days=7 for recent git activity (skipped if git disabled).

7. Present a structured status summary. Display todos as bullet points with status icons (✅/🔄/🔲), bold ID, title, priority in italics. Show children indented 2 spaces under their parent.
   ```
   ## <project-name>  [status] [priority]
   Target: <date>   Tracking: <tracking_dir>

   ### In Progress
   - 🔄 **2** — Implement MCP server _(medium)_ (branch: feat/mcp-server)

   ### Ready to Start
   - 🔲 **3** — Write skills _(low)_

   ### Blocked
   - 🔲 **4** — Integration tests _(medium)_ [blocked by 2]

   ### Recent Git Activity
   - abc1234  Fix storage layer (2026-02-26)
   ```

💡 Suggested next: (1) /proj:execute 3 — start work on a ready task  (2) /proj:todo add — add a new task  (3) /proj:update — record recent progress

---
name: status
description: Show the current project status, open todos, and recent git activity. Use when asked "what's the project status", "what are my todos", "what should I work on next", or "project overview".
allowed-tools: mcp__proj__proj_status_context, mcp__proj__proj_search_knowledge, mcp__proj__todo_update, mcp__proj__todo_notes_patch, mcp__proj__todo_notes_append
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Show comprehensive status report for active project.

**1.** `mcp__proj__proj_status_context` → get config, project metadata, categorised todos, git activity. No active project → stop: "No active project. Run `/proj:load` to load one."

**2.** Each in-progress todo matched to recent commits in `git_activity`: `mcp__proj__todo_update(todo_id, git={branch: <branch>, commits: [<sha>, ...]})` to record association.

**3.** Present structured status summary. Todos as bullets w/ status icons, bold ID, title, priority in italics. Children indented 2 spaces under parent. `[manual]` badge after priority for manual-tagged. `[blocked by X]` for blocked; `[blocks Y]` for blockers. Order: `_(priority)_ [manual] [blocked by X] [blocks Y]`.
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

Active project must be loaded.

## Err Handling

- No active project → "No active project. Run `/proj:load` to load one." Stop.
- Status ctx err → show err from `proj_status_context`. Stop.

## Output

Structured status report: project header (name, status, priority, target date, tracking dir), sections for In Progress, Ready to Start, Blocked todos (status icons, badges), Recent Git Activity.

Suggested next: `1. /proj:execute 3` -- start work on ready task | `2. /proj:todo add` -- add new task | `3. /proj:save` -- save session, reconcile git

---
name: update
description: Update the project with recent progress — reconcile git activity with todos, append notes, and update CLAUDE.md. Use when the user says "update project", "record progress", or "save what I've done".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_git_reconcile_todos, mcp__proj__git_link_todo, mcp__proj__todo_complete, mcp__proj__todo_add, mcp__proj__notes_append, mcp__proj__claudemd_write, mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__claude_ai_Todoist__find-tasks, mcp__claude_ai_Todoist__complete-tasks, mcp__claude_ai_Todoist__update-tasks
argument-hint: "[optional note text]"
---

Update the active project with recent progress.

1. Call `mcp__proj__proj_get_active` and `mcp__proj__todo_list`.
   - If no active project is returned, stop with: "No active project. Run /proj:load first."

2. **Git reconciliation** (if git enabled):
   - Call `mcp__proj__proj_git_reconcile_todos` (since_days=7) — returns `{commits, branches, suggestions}` in one call
   - If `suggestions` is empty, display "No git activity detected. Skipping git-based todo suggestions." and skip the rest of this step.
   - Present suggestions to user as bullet points with status icons, bold ID, title, priority in italics, and linked commit. Example:
     ```
     Based on recent commits, these todos may be complete:
     - ✅ **2** — Fix storage layer _(high)_ (linked: abc1234)
     - ✅ **3** — Add todo nested support _(medium)_ (linked: bcd2345)
     Shall I mark these done?
     ```
   - Ask: "Should any commits be linked to specific todos?"
   - Apply completions via `mcp__proj__todo_complete`
   - Apply git links via `mcp__proj__git_link_todo`

3. **New todos** — Ask: "Any new todos to add?" If yes, gather and add them.

4. **Notes** — If $ARGUMENTS is non-empty, treat it as a note. Also ask if there's anything else to record.
   - Call `mcp__proj__notes_append` with the combined notes.

5. **CLAUDE.md update** — Rebuild CLAUDE.md to reflect current state:
   - Project status, current focus, in-progress todos, recent decisions
   - Call `mcp__proj__claudemd_write` for each repo that has claudemd=true

6. **Todoist sync** (if auto_sync: true):
   - Push local completions to Todoist via `mcp__claude_ai_Todoist__complete-tasks`
   - Push any title changes via `mcp__claude_ai_Todoist__update-tasks`

7. Show a brief summary of what was updated.

💡 Suggested next: (1) /proj:status — see the updated project overview  (2) /proj:execute — start working on a todo

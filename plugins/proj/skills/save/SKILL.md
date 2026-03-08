---
name: save
description: Save session notes, reconcile git activity with todos, and update project context. Use when asked "save session", "proj:save", or at the end of a work session.
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__config_load, mcp__proj__notes_append, mcp__proj__proj_git_reconcile_todos, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__tracking_git_flush, Bash, Write
---

Save session context and reconcile git activity for the active project.

1. Call `mcp__proj__proj_get_active` to get the project name and tracking directory path.

2. Call `mcp__proj__config_load` to confirm the tracking_dir.

3. **Git reconciliation** (if git_enabled):
   - Call `mcp__proj__proj_git_reconcile_todos` with `since_days=1` to detect recent commits.
   - If suggestions are returned: display them. For each todo that looks completed based on commit messages, ask the user if it should be marked done. Call `mcp__proj__todo_complete` for confirmed ones.
   - If no suggestions: skip silently.

4. Ask the user: "Anything you'd like to add to this session summary? (press Enter to skip)"

5. Synthesise the session content from the current conversation. Extract:
   - **Key Decisions**: important choices made during this session
   - **Todos Worked On**: which todo IDs were touched and their outcomes
   - **Insights Discovered**: technical findings, patterns, gotchas
   - **Open Questions**: unresolved questions or things to investigate next session

   If the user provided a note in step 4, include it under a "## User Note" section.

6. Determine the session filename:
   - Use Bash: `date +%Y-%m-%d` to get today's date
   - Use Bash: `ls <tracking_dir>/<name>/sessions/session-<date>*.md 2>/dev/null | wc -l` to count existing files
   - If count is 0: filename = `session-<date>.md`
   - If count >= 1: filename = `session-<date>-<count+1>.md`

7. Use Bash: `mkdir -p <tracking_dir>/<name>/sessions`

8. Write the session file using the Write tool to `<tracking_dir>/<name>/sessions/<filename>`:

   ```
   # Session: <date>

   ## User Note
   <only if user provided something>

   ## Key Decisions
   - <bullet>

   ## Todos Worked On
   - <bullet with todo ID and outcome>

   ## Insights Discovered
   - <bullet>

   ## Open Questions
   - <bullet>
   ```

9. **Update CLAUDE.md** (if project has repos with claudemd=true):
   - Call `mcp__proj__claudemd_write` to update the active todos section based on current state.

10. Call `mcp__proj__notes_append` with a one-line summary.

11. Display: "Session saved to sessions/<filename>"

12. **Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Save session"`.

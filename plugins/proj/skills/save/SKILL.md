---
name: save
description: Save session notes and context to the project. Appends a summary to NOTES.md and writes a detailed session file with key decisions, todos worked on, insights, and open questions.
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__config_load, mcp__proj__notes_append, Bash, Write
---

Save the current session's context and notes to the active project.

1. Call `mcp__proj__proj_get_active` to get the project name and tracking directory path.

2. Call `mcp__proj__config_load` to confirm the tracking_dir.

3. Ask the user: "Anything you'd like to add to this session summary? (press Enter to skip)"

4. Synthesise the session content from the current conversation. Extract:
   - **Key Decisions**: important choices made during this session (architecture decisions, approach selections, tradeoffs accepted)
   - **Todos Worked On**: which todo IDs were touched and their outcomes (completed, in-progress, blocked, skipped)
   - **Insights Discovered**: technical findings, patterns, gotchas, architectural notes, things that were surprising or worth remembering
   - **Open Questions**: unresolved questions or things to investigate next session

   If the user provided a note in step 3, include it at the top of the file under a "## User Note" section (omit the section entirely if user provided nothing).

5. Determine the session filename:
   - Use Bash: `date +%Y-%m-%d` to get today's date
   - Use Bash: `ls <tracking_dir>/<name>/sessions/session-<date>*.md 2>/dev/null | wc -l` to count existing session files for today
   - If count is 0: filename = `session-<date>.md`
   - If count >= 1: filename = `session-<date>-<count+1>.md`

6. Use Bash to create the sessions directory: `mkdir -p <tracking_dir>/<name>/sessions`

7. Write the session file using the Write tool (not Bash echo — avoids shell quoting issues with markdown content).
   Write to `<tracking_dir>/<name>/sessions/<filename>` with this structure:

   ```
   # Session: <date>

   ## User Note
   <user note — only include this section if the user provided something>

   ## Key Decisions
   - <bullet>

   ## Todos Worked On
   - <bullet with todo ID and outcome>

   ## Insights Discovered
   - <bullet>

   ## Open Questions
   - <bullet>
   ```

8. Call `mcp__proj__notes_append` with a one-line summary like:
   `"Session <date>: <brief 1-line summary of what was accomplished>"`

9. Display: "Session saved to sessions/<filename>"

---
name: archive
description: Archive a completed project, removing it from the active list. Use when the user says "archive project", "mark project complete", or "archive <name>".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_archive, mcp__proj__proj_get_active, mcp__proj__proj_get, mcp__proj__todo_list
argument-hint: "[project-name]"
---

Archive a project. $ARGUMENTS is the project name (optional — defaults to active project).

1. Call `mcp__proj__proj_get` (or `proj_get_active` if no name given) to show what will be archived.

2. Call `mcp__proj__todo_list` to check for open todos.
   If there are open todos, display them as bullet points with status icons (🔄/🔲), bold ID, title, and priority in italics, then warn the user:
   ```
   This project has 2 open todos:
   - 🔄 **3** — Write skills _(high)_
   - 🔲 **4** — Integration tests _(medium)_ [blocked by 3]
   Are you sure you want to archive it?
   ```

3. Confirm with the user: "Archive project '<name>'? It will be removed from the active list."

4. Call `mcp__proj__proj_archive`.

5. If this was the active project: "No active project now. Use /proj:switch to set a new one."

💡 Suggested next: (1) /proj:switch — switch to another project

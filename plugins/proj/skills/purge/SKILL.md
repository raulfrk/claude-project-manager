---
name: purge
description: Purge archived projects older than the configured purge_after_days threshold. Use when asked "purge old projects", "clean up archives", or "purge archives".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_purge_archive, mcp__proj__config_load, mcp__proj__tracking_git_flush
---

Purge archived projects that have exceeded the retention period.

1. Call `mcp__proj__config_load` to verify purge is configured (check `archive.purge_after_days`).
   If not configured: display "Purge not configured. Set archive.purge_after_days via /proj:init-plugin or config_update." and stop.

2. Call `mcp__proj__proj_purge_archive` (without confirm) to get candidates.

3. If no candidates: display "No projects eligible for purge." and stop.

4. Display candidates as a table:
   ```
   | Project | Archive Date | Days Since Archived |
   |---------|-------------|-------------------|
   | <name>  | <date>      | <days>            |
   ```

5. Ask: "Purge these projects? This cannot be undone. [yes/no]"

6. If yes: call `mcp__proj__proj_purge_archive` with `confirm=true`.

7. Display the result.

8. **Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Purge: archived projects"`.

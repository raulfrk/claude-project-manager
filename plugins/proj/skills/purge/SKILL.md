---
name: purge
description: Purge archived projects older than the configured purge_after_days threshold. Use when asked "purge old projects", "clean up archives", or "purge archives".
allowed-tools: mcp__proj__proj_purge_archive, mcp__proj__proj_session_context, mcp__proj__tracking_git_flush
---

Purge archived projects that have exceeded the retention period.

**1.** Call `mcp__proj__proj_session_context` to get config and integration settings. Check if `archive.purge_after_days` is configured.
   If not configured, stop with: "Purge not configured. Run `/proj:init-plugin` to set `archive.purge_after_days`."

**2.** Call `mcp__proj__proj_purge_archive` (without confirm) to get candidates.

**3.** If no candidates: display "No projects eligible for purge." and stop.

**4.** Display candidates as a table:
   ```
   | Project | Archive Date | Days Since Archived |
   |---------|-------------|-------------------|
   | <name>  | <date>      | <days>            |
   ```

**5.** Ask: "Purge these projects? This cannot be undone. [yes/no]"

**6.** If yes: call `mcp__proj__proj_purge_archive` with `confirm=true`.

**7.** Display the result.

**8.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Purge: archived projects"`.

## Prerequisites

- `archive.purge_after_days` must be configured in proj config.

## Error Handling

- **Purge not configured**: displays "Purge not configured. Run `/proj:init-plugin` to set `archive.purge_after_days`." and stops.
- **No candidates**: displays `No projects eligible for purge.` and stops.
- **User declines**: stops without purging.
- **Purge tool error**: displays error from `proj_purge_archive` and stops.

## Output

Candidates table (Project, Archive Date, Days Since Archived). After confirmation: purge result. Git tracking flush confirmation.

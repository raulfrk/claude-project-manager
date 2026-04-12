---
name: purge
description: Purge archived projects older than the configured purge_after_days threshold. Use when asked "purge old projects", "clean up archives", or "purge archives".
allowed-tools: mcp__proj__proj_purge_archive, mcp__proj__proj_session_context, mcp__proj__tracking_git_flush
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Purge archived projects past retention period.

**1.** `mcp__proj__proj_session_context` → get config. Check `archive.purge_after_days`.
 Not configured → stop: "Purge not configured. Run `/proj:init-plugin` to set `archive.purge_after_days`."

**2.** `mcp__proj__proj_purge_archive` (no confirm) → get candidates.

**3.** No candidates → "No projects eligible for purge." Stop.

**4.** Show candidates table:
   ```
   | Project | Archive Date | Days Since Archived |
   |---------|-------------|-------------------|
   | <name>  | <date>      | <days>            |
   ```

**5.** Ask: "Purge these projects? Cannot be undone. [yes/no]"

**6.** Yes → `mcp__proj__proj_purge_archive` w/ `confirm=true`.

**7.** Show result.

**8.** `mcp__proj__tracking_git_flush` w/ `commit_message="Purge: archived projects"`.

## Prerequisites

- `archive.purge_after_days` configured in proj config.

## Err Handling

- Not configured → show msg, stop.
- No candidates → show msg, stop.
- User declines → stop.
- Purge tool err → show err, stop.

## Output

Candidates table (Project, Archive Date, Days Since Archived). After confirm: purge result + git flush confirmation.

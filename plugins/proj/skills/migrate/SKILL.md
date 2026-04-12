---
name: migrate
description: Detect and migrate projects from legacy formats to current structure. Auto-detects needed migrations, creates backups, auto-rollbacks on failure. Use when asked "migrate projects", "fix legacy format", or "update project structure".
allowed-tools: mcp__proj__proj_migrate_ids, mcp__proj__proj_migrate_dirs, mcp__proj__proj_session_context, mcp__proj__proj_list_full, mcp__proj__tracking_git_flush, Bash
argument-hint: "[--dry-run] [--force] [--restore <timestamp>] [project-name]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Migrate projects from legacy formats to cur structure.

**1.** Parse `$ARGUMENTS`:
- `dry_run` = true if `--dry-run`
- `force` = true if `--force`
- `restore_ts` = val after `--restore` (if present)
- `project_name` = first non-flag token (opt)

No args/flags → migrate all projects.

**2.** `mcp__proj__proj_session_context`. No config → stop: "No config loaded. Run `/proj:init` to init."

**3.** If `restore_ts` set:
 - Search `.bak-{restore_ts}` files in tracking dirs:
     ```
     Bash: find <tracking_dir> -name "*.bak-{restore_ts}" -type f
     ```
 - No files → stop: "No backup found for timestamp `<restore_ts>`. Run `find <tracking_dir> -name '*.bak-*'` to see available backups."
 - Each backup: restore by copying over orig (strip `.bak-TIMESTAMP` suffix)
 - Show restored files, stop.

**4.** Pre-migration validation:
 - `mcp__proj__proj_list_full` — get all projects w/ details.
 - Empty list → stop: "No projects in index. Nothing to migrate."
 - Each non-archived project: verify tracking dir exists via `Bash: test -d <dir>`.
 - Not `force`: warn about projects w/ external sync IDs (Todoist/Trello/Jira) — preserved but user should know.
 - Validation fails + not `force` → stop: "Pre-migration validation failed for <N> project(s). Run `/proj:migrate --force` to skip validation."

**5.** Detection — summary table:
   ```
   ### Migration Detection

   | Project | T-Prefix IDs | Legacy Path | Status |
   |---------|-------------|-------------|--------|
   | my-proj | 5 todos     | yes         | needs migration |
   | other   | —           | —           | up to date |
   ```

 All up to date → "All projects are up to date. Nothing to migrate." Stop.

**6.** If `dry_run`:
 - `mcp__proj__proj_migrate_ids(dry_run=True)`
 - `mcp__proj__proj_migrate_dirs(dry_run=True)` + `project_name` if specified
 - Show preview, stop.

**7.** Run migrations:
 - `mcp__proj__proj_migrate_ids` (migrates T-prefix IDs, archive, decisions, w/ auto-rollback)
 - `mcp__proj__proj_migrate_dirs` w/ `project_name` if specified, else `all_projects=True` (migrates legacy path fmt, w/ auto-rollback)
 - Parse JSON results from both.

**8.** Post-migration validation:
 - Each migrated project: `mcp__proj__proj_list_full` to reload, verify IDs numeric
 - Check no errors in either tool's results
 - Show validation results (pass/fail per project)

**9.** Results:
   ```
   ### Migration Results

   **ID Migration**: <N> projects migrated, <N> todos remapped, <N> archived remapped, <N> decisions updated
   **Dir Migration**: <N> projects migrated from legacy path format
   **Errors**: none (or list)

   All backups saved with timestamp <YYYYMMDD-HHMMSS>. Use `/proj:migrate --restore <timestamp>` to rollback.
   ```

**10.** `mcp__proj__tracking_git_flush(commit_message="Migrate: legacy to current format")`.

Suggested next: `1. /proj:status` -- see updated project overview

## Prerequisites

- Config loaded (`proj.yaml` exists)
- ≥1 project in index

## Err Handling

- No config → "No config loaded. Run `/proj:init` to init."
- No projects → "No projects in index. Nothing to migrate."
- Restore ts not found → "No backup found for timestamp `<ts>`. Run `find <tracking_dir> -name '*.bak-*'` to list available backups."
- Migration tool err → show err from tool result, note auto-rollback occurred
- Validation fail → "Pre-migration validation failed for <N> project(s). Run `/proj:migrate --force` to skip validation."

## Output

Migration results: detection table, per-tool results (ID/dir counts), validation pass/fail, backup ts for rollback. Dry-run → preview only.

Suggested next: `1. /proj:status` -- see updated project overview

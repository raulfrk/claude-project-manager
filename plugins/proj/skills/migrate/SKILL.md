---
name: migrate
description: Detect and migrate projects from legacy formats to current structure. Auto-detects needed migrations, creates backups, auto-rollbacks on failure. Use when asked "migrate projects", "fix legacy format", or "update project structure".
allowed-tools: mcp__proj__proj_migrate_ids, mcp__proj__proj_migrate_dirs, mcp__proj__proj_session_context, mcp__proj__proj_list_full, mcp__proj__tracking_git_flush, Bash
argument-hint: "[--dry-run] [--force] [--restore <timestamp>] [project-name]"
context: fork
agent: general-purpose
---

Migrate projects from legacy formats to current structure.

**1.** Parse `$ARGUMENTS`:
- `dry_run` = true if `--dry-run` present
- `force` = true if `--force` present
- `restore_ts` = value after `--restore` (if present)
- `project_name` = first non-flag token (optional)

If no arguments and no flags: default to migrating all projects.

**2.** Call `mcp__proj__proj_session_context`. If no config loaded, stop with: "No config loaded. Run `/proj:init` to initialize."

**3.** If `restore_ts` is set:
   - Search for `.bak-{restore_ts}` files in tracking directories:
     ```
     Bash: find <tracking_dir> -name "*.bak-{restore_ts}" -type f
     ```
   - If no files found: stop with "No backup found for timestamp `<restore_ts>`. Run `find <tracking_dir> -name '*.bak-*'` to see available backups."
   - For each backup file: restore by copying over the original (remove the `.bak-TIMESTAMP` suffix to get original name)
   - Display restored files and stop.

**4.** Pre-migration validation:
   - Call `mcp__proj__proj_list_full` to get all projects with their details.
   - If project list is empty: stop with "No projects in index. Nothing to migrate."
   - For each non-archived project: verify tracking directory exists on disk via `Bash: test -d <dir>`.
   - If not `force`: warn about any projects with external sync IDs (Todoist, Trello, Jira) — these will be preserved but the user should be aware.
   - If any validation fails and not `force`: stop with "Pre-migration validation failed for <N> project(s). Run `/proj:migrate --force` to skip validation."

**5.** Detection — display summary table:
   ```
   ### Migration Detection

   | Project | T-Prefix IDs | Legacy Path | Status |
   |---------|-------------|-------------|--------|
   | my-proj | 5 todos     | yes         | needs migration |
   | other   | —           | —           | up to date |
   ```

   If all projects are up to date: display "All projects are up to date. Nothing to migrate." and stop.

**6.** If `dry_run`:
   - Call `mcp__proj__proj_migrate_ids` with `dry_run=True`
   - Call `mcp__proj__proj_migrate_dirs` with `dry_run=True` and `project_name` if specified
   - Display preview results and stop.

**7.** Run migrations:
   - Call `mcp__proj__proj_migrate_ids` (migrates all projects' T-prefix IDs, archive, decisions, with auto-rollback)
   - Call `mcp__proj__proj_migrate_dirs` with `project_name` if specified, else `all_projects=True` (migrates legacy path format, with auto-rollback)
   - Parse JSON results from both tools.

**8.** Post-migration validation:
   - For each migrated project: call `mcp__proj__proj_list_full` to reload, verify IDs are numeric
   - Check that no errors were reported in either tool's results
   - Display validation results (pass/fail per project)

**9.** Display results:
   ```
   ### Migration Results

   **ID Migration**: <N> projects migrated, <N> todos remapped, <N> archived remapped, <N> decisions updated
   **Dir Migration**: <N> projects migrated from legacy path format
   **Errors**: none (or list)

   All backups saved with timestamp <YYYYMMDD-HHMMSS>. Use `/proj:migrate --restore <timestamp>` to rollback.
   ```

**10.** Call `mcp__proj__tracking_git_flush` with `commit_message="Migrate: legacy to current format"`.

Suggested next: `1. /proj:status` -- see updated project overview

## Prerequisites

- Config must be loaded (`proj.yaml` must exist).
- At least one project must exist in the index.

## Error Handling

- **No config**: "No config loaded. Run `/proj:init` to initialize."
- **No projects**: "No projects in index. Nothing to migrate."
- **Restore timestamp not found**: "No backup found for timestamp `<ts>`. Run `find <tracking_dir> -name '*.bak-*'` to list available backups."
- **Migration tool error**: displays error from tool result, notes auto-rollback occurred.
- **Validation failure**: "Pre-migration validation failed for <N> project(s). Run `/proj:migrate --force` to skip validation."

## Output

Migration results: detection table, per-tool results (ID counts, dir counts), validation pass/fail, backup timestamp for rollback. If dry-run: preview only.

Suggested next: `1. /proj:status` -- see updated project overview

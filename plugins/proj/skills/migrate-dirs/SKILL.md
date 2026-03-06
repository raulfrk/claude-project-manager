---
name: migrate-dirs
description: Migrate a project from legacy single-path format to multi-dir repos format. Use when the user says "migrate dirs", "migrate directories", "migrate to multi-dir", "convert to multi-dir", or when a session-load warning suggests running this skill. Also trigger when the user mentions upgrading project format or fixing legacy path warnings.
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__proj_migrate_dirs, mcp__proj__proj_setup_permissions, mcp__proj__config_load
argument-hint: "[--dry-run]"
---

Migrate a project from the old single-path format (`path: /some/dir`) to the new multi-dir repos format (`repos: [{label, path}]`). Parse $ARGUMENTS:

- If `$ARGUMENTS` is exactly `--dry-run` or `dry-run`: this is a preview run
- Otherwise: this is a live run

## 1. Guard

Call `mcp__proj__proj_get_active`. If no active project, stop: "No active project. Run `/proj:load` first."

## 2. Detect

Call `mcp__proj__proj_migrate_dirs` with `dry_run=True` to check if migration is needed.

- If the result contains "already uses multi-dir format": stop with that message. No migration needed.
- If the result contains a preview: display it to the user. Note: the preview shows the default label "code" — the user will choose the actual label in the next step.

If this is a **dry-run**: stop here. Tell the user: "Run `/proj:migrate-dirs` to apply."

## 3. Prompt for label

Ask the user: "What label should the directory have? (e.g., code, app, frontend):"

Wait for the user's response. Do not assign a default — the user chooses the label.

## 4. Preview and confirm

Show the migration plan:
```
Migration plan for '<project_name>':
  Old format: path: <path>
  New format: repos:
    - label: <user_label>
      path: <path>

This will also re-run permissions setup if perms integration is enabled.
Proceed? [yes/no]
```

If the user says anything other than "yes": abort with "Migration cancelled."

## 5. Execute migration

Call `mcp__proj__proj_migrate_dirs` with `label=<user_label>`, `dry_run=False`.

- If the result contains `"migrated": true`: migration succeeded. Continue to step 6.
- If the result contains an error or "already uses multi-dir format": display the message and stop.

## 6. Re-run permissions

Call `mcp__proj__config_load` to get the configuration summary.

Check the output for `perms_integration`. If `perms_integration: true` appears in the output:
- Call `mcp__proj__proj_setup_permissions` with `grant_path_access=true`, `grant_investigation_tools=true`.
- If the result contains an error: display it as a warning but do not fail the migration (the migration itself already succeeded).

If `perms_integration` is false or not present: skip. Note to the user: "Permissions not auto-refreshed (perms integration disabled). Run `/proj:perms-sync` manually if needed."

## 7. Confirm

Display:
```
Migration complete for '<project_name>':
  - Converted path to repos entry with label '<label>'
```

If permissions were refreshed, also show: `- Permissions refreshed`

Suggested next: `/proj:status` — verify project looks correct

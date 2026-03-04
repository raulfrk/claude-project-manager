---
name: migrate-ids
description: Migrate todo IDs from legacy T-format (T001) to numeric dot-notation (1, 1.1, 2, etc.) across all projects. Use when the user says "migrate ids", "migrate todo ids", or "update todo ids".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_migrate_ids
argument-hint: "[--dry-run]"
---

Migrate todo IDs from legacy T-format (e.g. T001) to numeric dot-notation (e.g. 1, 1.1, 2). Parse $ARGUMENTS:

- If `$ARGUMENTS` contains `--dry-run` or `dry-run` → this is a preview run
- Otherwise → this is a live run

**Dry-run mode:**

1. Call `mcp__proj__proj_migrate_ids` with `dry_run=True`.
2. Display the mapping output (old ID → new ID, per project).
3. Tell the user: "Ready to migrate. Run `/proj:migrate-ids` to apply."

**Live run mode:**

1. Warn the user: "This will rewrite todos.yaml for all projects. A backup (todos.yaml.bak) will be created. Proceed? (yes/no)"
2. Wait for confirmation. If the user says anything other than "yes", abort and say "Migration cancelled."
3. Call `mcp__proj__proj_migrate_ids` with `dry_run=False`.
4. Display the per-project results clearly.
5. Handle failure paths from the results:
   - **No projects found**: If no projects were returned, say "No projects to migrate." and stop.
   - **Already migrated**: If a project already uses numeric IDs (no T-format IDs present), skip it and note: "<project> — already migrated, skipped."
   - **Partial failure**: If some projects succeeded and some failed, clearly report which succeeded and which failed with their error messages.
6. Remind the user: "Note: any skills or prompts referencing old T-format IDs (e.g. in CLAUDE.md) will need manual updates."

💡 Suggested next: /proj:status — review todos with new IDs

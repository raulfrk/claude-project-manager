---
name: perms-backup
description: Backup and restore permission configurations
allowed-tools: mcp__plugin_perms_perms__perms_backup, mcp__plugin_perms_perms__perms_restore, mcp__plugin_perms_perms__perms_list
argument-hint: "[list|create|restore <timestamp>]"
context: fork
agent: general-purpose
---

# perms-backup

Manage permission backups: list, create, or restore.

**1.** Parse arguments

The user may provide: `[list|create|restore <timestamp>]`

**2.** Handle each subcommand

**`list`** (or `ls`):
- Call `mcp__plugin_perms_perms__perms_backup()` in list mode.
- Display available backups with their timestamps.

**`create`** (or `save`):
- Call `mcp__plugin_perms_perms__perms_backup()` to create a new backup.
- Display the backup confirmation with its timestamp.

**`restore <timestamp>`**:
- Call `mcp__plugin_perms_perms__perms_restore(timestamp=<timestamp>)`.
- Display the restore result.
- Display: "Run `/proj:perms-audit` to verify the restored permissions."

**No arguments**:
- Display usage:
  - `perms:backup list` — show available backups
  - `perms:backup create` — create a new backup
  - `perms:backup restore <timestamp>` — restore from a specific backup

## Prerequisites

- Perms plugin MCP server must be running and reachable.

## Error Handling

- **No arguments**: displays usage message.
- **Perms MCP unavailable**: displays error from tool call and stops.
- **Invalid timestamp for restore**: displays error from `perms_restore` and stops.
- **No backups found (list)**: displays message indicating no backups available.

## Output

- **list**: available backups with timestamps.
- **create**: backup confirmation with timestamp.
- **restore**: restore result with suggestion to run `/proj:perms-audit`.

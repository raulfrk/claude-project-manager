---
name: perms-backup
description: Backup and restore permission configurations
---

# perms-backup

Manage permission backups: list, create, or restore.

## Parse arguments

The user may provide: `[list|create|restore <timestamp>]`

## Handle each subcommand

**`list`** (or `ls`):
- Call `mcp__plugin_perms_perms__perms_backup()` in list mode.
- Display available backups with their timestamps.

**`create`** (or `save`):
- Call `mcp__plugin_perms_perms__perms_backup()` to create a new backup.
- Display the backup confirmation with its timestamp.

**`restore <timestamp>`**:
- Call `mcp__plugin_perms_perms__perms_restore(timestamp=<timestamp>)`.
- Display the restore result.
- Suggest: "Run `perms:audit` to verify the restored permissions."

**No arguments**:
- Display usage:
  - `perms:backup list` — show available backups
  - `perms:backup create` — create a new backup
  - `perms:backup restore <timestamp>` — restore from a specific backup

---
name: perms-backup
description: Backup and restore permission configurations
allowed-tools: mcp__plugin_perms_perms__perms_backup, mcp__plugin_perms_perms__perms_restore, mcp__plugin_perms_perms__perms_list
argument-hint: "[list|create|restore <timestamp>]"
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

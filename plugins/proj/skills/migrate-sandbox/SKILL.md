---
name: migrate-sandbox
description: Migrate from permissions.allow rules to sandbox-primary permission management. Backs up settings, configures sandbox, cleans up stale rules, and verifies. Use when asked "migrate to sandbox", "clean up permissions", or "switch to sandbox mode".
allowed-tools: mcp__perms__perms_backup, mcp__perms__perms_restore, mcp__perms__perms_sandbox_init, mcp__perms__perms_cleanup_stale, mcp__perms__perms_list, mcp__perms__perms_deny_write, mcp__perms__perms_deny_read, mcp__proj__config_load, mcp__proj__proj_list, mcp__proj__proj_get, Bash
argument-hint: "[--dry-run]"
---

Migrate to sandbox-primary permissions: $ARGUMENTS

**1. Parse arguments**
- `dry_run` = true if `--dry-run` is in $ARGUMENTS

**2. Pre-flight check**

Call `mcp__perms__perms_list` with `scope="user"` and `target="auto"` to get current rule counts.

Display:
```
### Current State
- settings.json: N permission rules
- settings.local.json: M permission rules
- Sandbox enabled: yes/no
```

If `dry_run`: display what WOULD change and stop.

**3. Backup**

Call `mcp__perms__perms_backup`. Display the backup timestamp.

```
Backed up settings files with timestamp <timestamp>.
To restore: call perms_restore with this timestamp.
```

**4. Configure sandbox**

Call `mcp__perms__perms_sandbox_init`. This will:
- Enable sandbox if not already enabled
- Set `autoAllowBashIfSandboxed: true`
- Set `allowUnsandboxedCommands: false`
- Migrate existing Read/Edit paths from permissions.allow to sandbox.filesystem.allowWrite
- Strip the migrated Read/Edit rules from permissions.allow

Display the result.

**5. Clean up stale rules**

Call `mcp__perms__perms_cleanup_stale`. This strips all remaining Read/Edit/Bash rules from BOTH settings files, keeping only MCP and WebFetch rules.

Display before/after counts.

**6. Add deny rules for sensitive paths**

Call `mcp__perms__perms_deny_read` for each of:
- `~/.ssh`
- `~/.gnupg`
- `~/.aws`

**7. Handle reference repos**

Call `mcp__proj__proj_list` to get all projects.
For each project, call `mcp__proj__proj_get` to check for reference repos.
For each reference repo path, call `mcp__perms__perms_deny_write` with the repo path.

Display: "Added denyWrite for N reference repo paths."

**8. Verify**

Call `mcp__perms__perms_list` again to show the new state.

Display:
```
### Migration Complete
- settings.json: N permission rules (was M)
- settings.local.json: N permission rules (was M)
- Sandbox paths: N
- Sensitive paths denied: 3
- Reference repos in denyWrite: N

To rollback: /proj:migrate-sandbox --restore <timestamp>
```

**9. Rollback** (if $ARGUMENTS contains `--restore <timestamp>`)

Call `mcp__perms__perms_restore` with the provided timestamp.
Display: "Restored settings from backup."

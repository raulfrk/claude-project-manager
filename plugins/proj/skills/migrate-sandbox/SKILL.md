---
name: migrate-sandbox
description: Migrate from permissions.allow rules to sandbox-primary permission management. Backs up settings, configures sandbox, cleans up stale rules, reconciles MCP, installs deny rules, and verifies. Use when asked "migrate to sandbox", "clean up permissions", or "switch to sandbox mode".
allowed-tools: mcp__plugin_perms_perms__perms_set_sandbox_paths, mcp__plugin_perms_perms__perms_set_deny, mcp__plugin_perms_perms__perms_reconcile_mcp, mcp__plugin_proj_proj__config_update, mcp__plugin_proj_proj__proj_list, mcp__plugin_proj_proj__proj_get, mcp__plugin_perms_perms__perms_backup, mcp__plugin_perms_perms__perms_restore, mcp__plugin_perms_perms__perms_cleanup_stale, mcp__plugin_perms_perms__perms_list, mcp__plugin_perms_perms__perms_is_sandbox_enabled, mcp__plugin_proj_proj__proj_get_active, mcp__plugin_proj_proj__config_load, mcp__plugin_worktree_worktree__wt_config_get, Bash
argument-hint: "[--dry-run] [--restore <timestamp>]"
---

Migrate to sandbox-primary permissions: $ARGUMENTS

**0.** Parse arguments
- `dry_run` = true if `--dry-run` is in $ARGUMENTS
- `restore_timestamp` = the timestamp value if `--restore <timestamp>` is in $ARGUMENTS

If `restore_timestamp` is set, jump to **step 10 (Rollback)**.

**1.** Pre-flight audit

**1a.** Call `config_load` to get the current proj config.
- Derive `projects_root` from `config.permissions.projects_root` (fallback: `config.projects_base_dir`)
- Derive `tracking_root` from `config.permissions.tracking_root` (fallback: `config.tracking_dir`)
- Derive `archive_dest` from `config.archive.destination`

**1b.** Call `perms_list` with `scope="user"` and `target="auto"` to get all current rules.

Categorize all `permissions.allow` rules from BOTH files:
- **Stale Read/Edit/Bash**: any `Read(...)`, `Edit(...)`, or `Bash(...)` rule
- **MCP**: any `mcp__*` rule
- **WebFetch/WebSearch**: any `WebFetch(...)` or `WebSearch(...)` rule
- **Other**: anything not matching above categories

**1c.** Call `perms_is_sandbox_enabled` to check current sandbox state.

Categorize current `sandbox.filesystem.allowWrite` paths:
- **proj-managed**: matches any active project repo path (from `proj_list`), tracking_dir, archive_destination, or is a sub-path of `projects_root`
- **user-added**: everything else

**1d.** Display summary:

```
### Pre-flight Audit

**Rules (permissions.allow)**
- Stale Read/Edit/Bash: N (to remove)
- MCP tools: N (to reconcile)
- WebFetch/WebSearch: N (preserved)
- Other: N (preserved)

**Sandbox allowWrite paths**
- Proj-managed: N (to replace with root paths)
- User-added: N (preserved)
  - /path/one
  - /path/two

**Sandbox enabled**: yes/no
```

**1e.** If user-added paths were detected (paths not present in any known project directory, tracking directory, or archive destination), warn:

```
⚠️  These sandbox paths are not managed by proj:
- /path/one
- /path/two

These paths will be preserved during migration. Please confirm:
- Keep all listed paths? (y)
- Review and remove specific paths? (r)
```

If user picks `r`: display each path individually and ask `keep / remove` for each. Remove any paths the user chooses to drop before proceeding.

**1f.** If `dry_run`: display what WOULD change and **stop here**.

**1g.** Scan all project repos. Call `proj_list` to get all active projects, then `proj_get` for each to collect repo paths. For any repo path that is NOT under `projects_root`, list them and prompt:

```
These repos are outside projects_root (<root>):
- <project-name>: <repo-path>

The sandbox will NOT cover these paths — they will not be writable unless
you add them to sandbox.filesystem.allowWrite manually after migration.

Please move them under the root before migrating, or adjust projects_root
to cover them.

(1) Continue anyway (repos outside root will need manual sandbox paths)
(2) Stop — I'll move them first
```

If user picks 2: **stop migration**.

**2.** Backup

Call `perms_backup`. Record the returned timestamp.

Display:
```
Backed up settings files with timestamp <timestamp>.
To restore: /proj:migrate-sandbox --restore <timestamp>
```

On failure: display error and **stop**.

**3.** Compute target state

- `sandbox_paths` = `[projects_root, tracking_root]`
- If `archive_dest` is NOT a sub-path of `projects_root` (containment check): append `archive_dest` to `sandbox_paths`
- Call `mcp__plugin_worktree_worktree__wt_config_get` to get the worktree configuration.
  - If the call returns null or an error: display "Error: Worktree config not found. Ensure `/worktree:setup` has been run before migrating." and **stop migration**.
  - For each configured worktree base path in the worktree config: check if `archive_dest` is contained within that base path.
  - If `archive_dest` is within a worktree base path: append `archive_dest` to `sandbox_paths` (if not already added above).
- Derive expected MCP servers from config:
  - Always: `plugin_proj_proj`, `claude_ai_Excalidraw`, `claude_ai_Mermaid_Chart`
  - If `perms_integration: true`: `plugin_perms_perms`
  - If `worktree_integration: true`: `plugin_worktree_worktree`
  - If `todoist.enabled: true`: `todoist`
  - If `jira.enabled: true`: `plugin_jira_jira`
  - If `trello.enabled: true`: `plugin_trello_trello`
- Stale MCP servers (KNOWN_STALE_MCP_SERVERS):
  `perms`, `proj`, `worktree`, `sentry`, `Todoist`, `claude_ai_Todoist`, `remotion-documentation`, `claude_ai_WebSearch`, `claude_ai_WebFetch`

**4.** Clean stale rules

Call `perms_cleanup_stale`. This strips all Read/Edit/Bash rules from BOTH settings files, keeping only MCP and WebFetch rules.

Display before/after counts.

On failure: display "Migration failed at step 4. Restore with: `perms_restore('<timestamp>')`" and **stop**.

**5.** Replace sandbox paths

Call `perms_set_sandbox_paths` with:
- `paths` = the computed `sandbox_paths` from step 3
- `preserve_extra` = `true` (merge with user-added paths detected in step 1c)

On failure: display "Migration failed at step 5. Restore with: `perms_restore('<timestamp>')`" and **stop**.

**6.** Reconcile MCP wildcards

Call `perms_reconcile_mcp` with:
- `expected_servers` = the list computed in step 3
- `stale_servers` = `["perms", "proj", "worktree", "sentry", "Todoist", "claude_ai_Todoist", "remotion-documentation", "claude_ai_WebSearch", "claude_ai_WebFetch"]`

This removes stale MCP wildcards from BOTH files and adds missing expected wildcards to settings.local.json only. All non-stale MCP rules (user-managed servers) are preserved.

On failure: display "Migration failed at step 6. Restore with: `perms_restore('<timestamp>')`" and **stop**.

**7.** Install deny rules

**7a.** Call `perms_set_deny` with the DEFAULT_DENY_RULES. This writes deny rules to settings.local.json.

**7b.** If `permissions.deny` already exists in `settings.json`, warn (the user may have intentionally placed deny rules there):

```
settings.json has existing deny rules. These may conflict with the new
deny rules in settings.local.json.

(1) Clear deny rules from settings.json (recommended — consolidate in settings.local.json)
(2) Keep deny rules in settings.json (both files will have deny rules)
(3) Skip deny rule installation entirely
(4) Abort migration
```

If user picks 1: clear `permissions.deny` from `settings.json` via `perms_set_deny` targeting that file.
If user picks 2: leave them in place and note the conflict in the final summary.
If user picks 3: skip this step entirely (no deny rules installed), note in summary.
If user picks 4: display "Migration aborted at step 7. Restore with: `perms_restore('<timestamp>')`" and **stop**.

On failure: display "Migration failed at step 7. Restore with: `perms_restore('<timestamp>')`" and **stop**.

**8.** Persist config

Call `config_update` with:
- `permissions.projects_root` = the `projects_root` value
- `permissions.tracking_root` = the `tracking_root` value

On failure: display "Migration failed at step 8. Restore with: `perms_restore('<timestamp>')`" and **stop**.

**9.** Verify

Call `perms_list` with `scope="user"` and `target="auto"` to get the final state.
Call `perms_is_sandbox_enabled` to confirm sandbox is enabled.

Check:
- Sandbox is enabled
- No stale Read/Edit/Bash rules remain in permissions.allow
- Sandbox allowWrite contains the expected root paths
- Expected MCP wildcards are present
- Deny rules are present

If any check fails: display "Migration completed with warnings:" followed by the specific issues, and prominently show: "To rollback: `/proj:migrate-sandbox --restore <timestamp>`"

If all checks pass, display:

```
### Migration Complete

**Before → After**
- settings.json allow rules: M → N
- settings.local.json allow rules: M → N
- Sandbox allowWrite paths: M → N
- Deny rules: M → N

**Sandbox paths**:
- <projects_root>
- <tracking_root>
- <archive_dest> (if applicable)
- <user-added paths> (preserved)

**MCP wildcards**: N active
**Deny rules**: N installed

To rollback: /proj:migrate-sandbox --restore <timestamp>
```

**10.** Rollback (only if `--restore <timestamp>` was provided)

Call `perms_restore` with the provided timestamp.
Display: "Restored settings from backup `<timestamp>`."

## Prerequisites

- Perms plugin MCP server must be running and reachable.
- Proj plugin MCP server must be running and reachable.
- At least one active project must exist (for repo scanning).

## Error Handling

- **MCP unavailable**: displays error from tool call and stops.
- **Backup failure**: displays error from `perms_backup` and stops.
- **Any step failure**: displays which step failed and rollback instructions with the backup timestamp.
- **Invalid restore timestamp**: displays error from `perms_restore` and stops.

## Preserved Settings

The following are explicitly **preserved as-is** during migration:
- `sandbox.network.*` (allowedDomains, sockets, etc.)
- `sandbox.excludedCommands`
- `sandbox.allowUnsandboxedCommands`
- `sandbox.filesystem.denyRead`, `sandbox.filesystem.denyWrite`, `sandbox.filesystem.allowRead`
- `permissions.additionalDirectories`
- WebFetch/WebSearch rules in `permissions.allow`
- Non-stale MCP rules from non-proj servers (user-managed)

## Output

- **Dry-run**: pre-flight audit with rule categorization, sandbox path categorization, and what would change.
- **Full migration**: pre-flight audit, backup timestamp, step-by-step progress, verification results, before/after summary with rollback instructions.
- **Rollback**: `Restored settings from backup.`

---
name: perms-sync
description: Check if settings.json allow rules match the active project config. Reports missing rules without auto-fixing. Pass --apply to automatically add all missing rules. Use when asked "sync perms", "check permissions", or "are my perms correct".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__config_load, mcp__proj__proj_perms_sync, mcp__proj__proj_setup_permissions
argument-hint: "[--apply]"
---

Check if settings.json allow rules are in sync with the active project config.

**Guard:** Call `proj_get_active`. If no active project is returned, stop with: "No active project. Run /proj:load first."

If `--apply` is present in the arguments:
1. Call `proj_perms_sync(apply=true)` — it will add all missing rules automatically.
2. If the tool returns an error, display the error message and stop.
3. Display the result using the output format below. If all rules were already present show a "already in sync" message.

Otherwise (default dry-run mode):
1. Call `proj_perms_sync` (no apply flag) — it derives expected rules from the active project's repos and config, then compares against ~/.claude/settings.json. No changes are written.
2. If the tool returns an error, display the error message and stop.
3. Display the result using the output format below:
   - If in sync: show a "all rules present" message
   - If missing rules: show them grouped by type (directory rules first, then MCP rules)
4. If there are missing rules, suggest: "Run `/proj:perms-sync --apply` to add all missing rules at once, or use `proj_setup_permissions`, `proj_grant_tool_permissions` (Bash rules), and `perms_add_mcp_allow` (MCP rules) individually."

**Output format:** Show added or missing rules as a diff-style list:
- Added or expected-but-missing rules: `+ <rule>`
- Rules present but no longer needed: `- <rule>`
- Group by type: directory rules first, then MCP rules

**apply option:** Without `--apply` this skill is a dry-run — it reports what would change but makes no edits to `~/.claude/settings.json`. Pass `--apply` to write the changes.

Suggested next: /proj:status — see overall project status

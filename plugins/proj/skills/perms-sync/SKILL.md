---
name: perms-sync
description: Check if settings.json allow rules match the active project config. Reports missing rules without auto-fixing. Pass --apply to automatically add all missing rules. Use when asked "sync perms", "check permissions", or "are my perms correct".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__config_load, mcp__proj__proj_perms_sync, mcp__proj__proj_setup_permissions
argument-hint: "[--apply]"
---

Check if settings.json allow rules are in sync with the active project config.

If `--apply` is present in the arguments:
1. Call `mcp__proj__proj_perms_sync` with `apply=True` — it will add all missing rules automatically.
2. Display the result directly. If all rules were already present show a "already in sync" message; if rules were added show which rules were applied.

Otherwise (default check mode):
1. Call `mcp__proj__proj_perms_sync` (no apply flag) — it derives expected rules from the active project's repos and config, then compares against ~/.claude/settings.json.
2. Display the result:
   - If in sync: show a "all rules present" message
   - If missing rules: show them grouped by type (directory rules, MCP rules)
3. If there are missing rules, suggest: "Run `/proj:perms-sync --apply` to add all missing rules at once, or use `proj_setup_permissions`, `proj_grant_tool_permissions` (Bash rules), and `perms_add_mcp_allow` (MCP rules) individually."

Suggested next: /proj:status — see overall project status

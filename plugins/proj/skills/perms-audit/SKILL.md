---
name: perms-audit
description: Audit current permissions showing filesystem, MCP, and sandbox status
---

# perms-audit

Audit and display the current permission configuration.

## Step 1: List all permissions

Call `mcp__plugin_perms_perms__perms_list(scope="all", format="json")`.

## Step 2: Parse and display

From the JSON result, display a structured summary:

**Filesystem Allow Rules**
- Count of rules
- List each path

**MCP Allow Rules**
- Count of rules
- List each server name

**Sandbox Status**
- Whether sandbox mode is enabled or disabled

## Step 3: Check for stale paths

Call `mcp__plugin_perms_perms__perms_cleanup_stale()`.

If stale paths are found, display them under a "Stale Permissions" section with a warning.

## Step 4: Suggestions

- If there are stale or missing permissions, suggest `perms:grant` to add or `perms:debug` to investigate.
- If everything looks clean, confirm that permissions are in good shape.

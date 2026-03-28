---
name: perms-sandbox-setup
description: Initialize and verify sandbox mode for permissions
allowed-tools: mcp__plugin_perms_perms__perms_sandbox_init, mcp__plugin_perms_perms__perms_is_sandbox_enabled, mcp__plugin_perms_perms__perms_list
---

# perms-sandbox-setup

Set up sandbox mode for the permissions system.

**1.** Check current state

Call `mcp__plugin_perms_perms__perms_is_sandbox_enabled()`.

**If sandbox is already enabled**:
- Display: "Sandbox mode is already enabled."
- Show current status and exit. No further action needed.

**If sandbox is not enabled**:
- Proceed to step 2.

**2.** Initialize sandbox

Call `mcp__plugin_perms_perms__perms_sandbox_init()`.

Display the initialization result to the user.

**3.** Verify and suggest

- Confirm sandbox mode is now active.
Suggested next: (1) /proj:perms-audit — review your current permission rules under sandbox mode

---
name: remove-repo
description: Remove a directory or repository from the active project by label. Validates the label exists, guards against removing the last repo, confirms with user, revokes permissions. Use when the user says "remove repo", "unregister repo", or "remove directory from project".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_remove_repo, mcp__proj__proj_setup_permissions, mcp__perms__perms_remove_allow, mcp__proj__tracking_git_flush
argument-hint: "<label>"
---

Remove a directory or repository from the active project by label.

**Arguments:** Parse `$ARGUMENTS`:
- The first token is the **label** (required). If empty, stop with: "Label required. Usage: `/proj:remove-repo <label>`"

**Steps:**

**1.** Call `mcp__proj__proj_session_context` to get config, project metadata, and integration settings in one call. If no active project, stop with: "No active project. Run `/proj:load` to load one."
   - Extract `project.name` and `project.repos` from the session context.

**2.** Find the repo entry matching the provided label. If no repo with that label exists, stop with: "No repo with label `<label>` found in project `<name>`."

**3.** If there is only 1 repo in the project, stop with: "Cannot remove the last repo. Run `/proj:archive` to remove the entire project instead."

**4.** Display the repo details and ask the user for confirmation:
   ```
   Remove repo from project '<project_name>'?
     Label: <label>
     Path:  <path>
     Type:  <"reference (read-only)" if reference else "writable">
   [yes/no]
   ```
   If the user declines, stop with: "Cancelled."

**5.** Call `mcp__proj__proj_remove_repo` with `label=<label>`. If the tool returns an error, display it and stop.

**6.** Revoke permissions for the removed repo path:
   - Call `mcp__perms__perms_remove_allow` with `path=<repo_path>` to remove Read and Edit allow rules for that directory.
   - If the config has `perms_integration: true`, call `mcp__proj__proj_setup_permissions` to refresh sandbox write paths from the remaining repos.

**7.** Display confirmation summary:
   ```
   Repo removed from <project_name>:
   - Label: <label>
   - Path: <path>
   - Type: <"reference (read-only)" if reference else "writable">
   - Permissions revoked
   - Remaining repos: <count>
   ```

**8.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Remove repo: {label}"`.

## Prerequisites

- An active project must be loaded.
- A repo label must be provided.

## Error Handling

- **No active project**: displays "No active project. Run `/proj:load` to load one." and stops.
- **No label provided**: displays "Label required. Usage: `/proj:remove-repo <label>`" and stops.
- **Label not found**: displays "No repo with label `<label>` found in project `<name>`." and stops.
- **Last repo**: displays "Cannot remove the last repo. Run `/proj:archive` to remove the entire project instead." and stops.
- **User declines**: displays `Cancelled.` and stops.
- **Remove tool error**: displays error from `proj_remove_repo` and stops.

## Output

Confirmation summary: label, path, type (reference/writable), permissions revoked, remaining repo count. Git tracking flush confirmation.

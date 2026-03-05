---
name: remove-repo
description: Remove a directory or repository from the active project by label. Validates the label exists, guards against removing the last repo, confirms with user, revokes permissions. Use when the user says "remove repo", "unregister repo", or "remove directory from project".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__proj_get, mcp__proj__config_load, mcp__proj__proj_remove_repo, mcp__proj__proj_setup_permissions, mcp__perms__perms_remove_allow
argument-hint: "<label>"
---

Remove a directory or repository from the active project by label.

**Arguments:** Parse `$ARGUMENTS`:
- The first token is the **label** (required). If empty, stop with: "Label required. Usage: /proj:remove-repo <label>"

**Steps:**

1. Call `mcp__proj__proj_get_active`. If no active project is returned, stop with: "No active project. Run /proj:load first."

2. Call `mcp__proj__config_load` to load plugin configuration.

3. Call `mcp__proj__proj_get` to retrieve the active project's metadata including its `repos` list.

4. Find the repo entry matching the provided label. If no repo with that label exists, stop with: "No repo with label '<label>' found in project '<name>'."

5. If there is only 1 repo in the project, stop with: "Cannot remove the last repo -- a project must have at least one repo. Use /proj:archive to remove the entire project instead."

6. Display the repo details and ask the user for confirmation:
   ```
   Remove repo from project '<project_name>'?
     Label: <label>
     Path:  <path>
     Type:  <"reference (read-only)" if reference else "writable">
   [yes/no]
   ```
   If the user declines, stop with: "Cancelled."

7. Call `mcp__proj__proj_remove_repo` with `label=<label>`. If the tool returns an error, display it and stop.

8. Revoke permissions for the removed repo path:
   - Call `mcp__perms__perms_remove_allow` with `path=<repo_path>` to remove Read and Edit allow rules for that directory.
   - If the config has `perms_integration: true`, call `mcp__proj__proj_setup_permissions` with `grant_path_access=true` and `grant_investigation_tools=true` to refresh Bash investigation-tool rules from the remaining repos.

9. Display confirmation summary:
   ```
   Repo removed from <project_name>:
   - Label: <label>
   - Path: <path>
   - Type: <"reference (read-only)" if reference else "writable">
   - Permissions revoked
   - Remaining repos: <count>
   ```

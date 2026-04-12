---
name: remove-repo
description: Remove a directory or repository from the active project by label. Validates the label exists, guards against removing the last repo, confirms with user, revokes permissions. Use when the user says "remove repo", "unregister repo", or "remove directory from project".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_remove_repo, mcp__proj__proj_setup_permissions, mcp__perms__perms_remove_allow, mcp__proj__tracking_git_flush
argument-hint: "<label>"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Remove dir/repo from active project by label.

**Args:** Parse `$ARGUMENTS`:
- First token = label (required). Empty → "Label required. Usage: `/proj:remove-repo <label>`"

**Steps:**

**1.** `mcp__proj__proj_session_context` → get config, project meta, integrations. No active project → "No active project. Run `/proj:load` to load one."
 - Extract `project.name`, `project.repos`.

**2.** Find repo matching label. Not found → "No repo with label `<label>` found in project `<name>`."

**3.** Only 1 repo → "Cannot remove last repo. Run `/proj:archive` to remove entire project instead."

**4.** Show repo details, ask confirmation:
   ```
   Remove repo from project '<project_name>'?
     Label: <label>
     Path:  <path>
     Type:  <"reference (read-only)" if reference else "writable">
   [yes/no]
   ```
 Declined → "Cancelled."

**5.** `mcp__proj__proj_remove_repo(label=<label>)`. Error → show, stop.

**6.** Revoke perms for removed repo path:
 - `mcp__perms__perms_remove_allow(path=<repo_path>)` — remove Read/Edit allow rules.
 - If `sandbox_integration: true`: `mcp__proj__proj_setup_permissions` to refresh sandbox write paths.

**7.** Show confirmation:
   ```
   Repo removed from <project_name>:
   - Label: <label>
   - Path: <path>
   - Type: <"reference (read-only)" if reference else "writable">
   - Permissions revoked
   - Remaining repos: <count>
   ```

**8.** `mcp__proj__tracking_git_flush(commit_message="Remove repo: {label}")`.

## Prerequisites

- Active project loaded.
- Repo label provided.

## Err Handling

- No active project → "No active project. Run `/proj:load` to load one."
- No label → "Label required. Usage: `/proj:remove-repo <label>`"
- Label not found → "No repo with label `<label>` found in project `<name>`."
- Last repo → "Cannot remove last repo. Run `/proj:archive` to remove entire project instead."
- User declines → "Cancelled."
- Remove tool err → show err, stop.

## Output

Confirmation: label, path, type (ref/writable), perms revoked, remaining repo count. Git tracking flush confirm.

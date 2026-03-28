---
name: add-repo
description: Add a new directory or repository to the active project. Validates the path, detects git repos, registers via proj_add_repo, and auto-grants permissions. Use when the user says "add repo", "add directory to project", or "register another repo".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_add_repo, mcp__proj__proj_setup_permissions, mcp__proj__tracking_git_flush, Bash
argument-hint: "<path> [--label=<label>] [--reference] [--claudemd]"
---

Add a new directory or repository to the active project.

**Guard:** Call `mcp__proj__proj_session_context`. If no active project is returned, stop with: "No active project. Run `/proj:load` to load one."

**Arguments:** Parse `$ARGUMENTS`:
- The first non-flag token is the **path** (required). If empty, stop with: "Path required. Usage: `/proj:add-repo <path>`"
- `--label=<value>` — repo label (default: `"code"`)
- `--reference` — if present, add as read-only reference (default: false)
- `--claudemd` — if present, create a CLAUDE.md for this repo (default: false)

**Steps:**

**1.** Resolve the path to an absolute path if needed. Validate that it exists:
   ```
   Bash: test -d <path> && echo "exists" || echo "missing"
   ```
   If missing, stop with: "Path `<path>` does not exist."

**2.** Check if the path is a git repository:
   ```
   Bash: test -d <path>/.git && echo "git" || echo "plain"
   ```
   - If `git`: note "Detected git repository at `<path>`."
   - If `plain`: note "No git repository detected at `<path>` — adding as a plain directory."

**3.** Call `mcp__proj__proj_add_repo` with:
   - `repo_path`: the validated absolute path
   - `label`: parsed label or `"code"`
   - `claudemd`: true if `--claudemd` flag present, false otherwise
   - `reference`: true if `--reference` flag present, false otherwise

   If the tool returns an error (e.g., duplicate repo), display the error and stop.

**4.** Call `mcp__proj__proj_setup_permissions` to refresh sandbox write paths for the project including the new repo path.
   - **Note**: When `permissions.projects_root` is set, the `proj_setup_permissions` call is a no-op for sandbox paths. If the new repo is outside `projects_root`, display a warning: "Repo path `<path>` is outside projects_root `<root>`. Move it under the root for sandbox coverage, or add its path to sandbox.filesystem.allowWrite manually."

**5.** Display confirmation summary:
   ```
   Repo added to <project_name>:
   - Label: <label>
   - Path: <path>
   - Git repo: yes/no
   - Mode: reference (read-only) / writable
   - Permissions refreshed
   ```

**6.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Add repo: {label}"`.

## Prerequisites

- An active project must be loaded.
- A path must be provided.

## Error Handling

- **No active project**: displays "No active project. Run `/proj:load` to load one." and stops.
- **No path provided**: displays usage message and stops.
- **Path does not exist**: displays "Path `<path>` does not exist." and stops.
- **Duplicate repo**: displays error from `proj_add_repo` and stops.
- **Permissions refresh failure**: logs warning and continues.

## Output

Confirmation summary: label, path, git repo detection, mode (reference/writable), permissions refreshed status. Git tracking flush confirmation.

Suggested next: `1. /proj:status` -- see updated project overview

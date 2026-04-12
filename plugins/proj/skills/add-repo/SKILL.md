---
name: add-repo
description: Add a new directory or repository to the active project. Validates the path, detects git repos, registers via proj_add_repo, and auto-grants permissions. Use when the user says "add repo", "add directory to project", or "register another repo".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_add_repo, mcp__proj__proj_setup_permissions, mcp__proj__tracking_git_flush, Bash
argument-hint: "<path> [--label=<label>] [--reference] [--claudemd]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Add new dir/repo to active project.

**Guard:** `mcp__proj__proj_session_context`. No active project → stop: "No active project. Run `/proj:load` to load one."

**Args:** Parse `$ARGUMENTS`:
- First non-flag token = **path** (required). Empty → stop: "Path required. Usage: `/proj:add-repo <path>`"
- `--label=<value>` — repo label (default: `"code"`)
- `--reference` — add as read-only ref (default: false)
- `--claudemd` — create CLAUDE.md for repo (default: false)

**Steps:**

**1.** Resolve path to absolute. Validate exists:
   ```
   Bash: test -d <path> && echo "exists" || echo "missing"
   ```
 Missing → stop: "Path `<path>` does not exist."

**2.** Check if git repo:
   ```
   Bash: test -d <path>/.git && echo "git" || echo "plain"
   ```
 - `git` → note "Detected git repo at `<path>`."
 - `plain` → note "No git repo detected at `<path>` — adding as plain dir."

**3.** `mcp__proj__proj_add_repo` w/:
 - `repo_path`: validated absolute path
 - `label`: parsed label or `"code"`
 - `claudemd`: true if `--claudemd` flag
 - `reference`: true if `--reference` flag

 Error (e.g. duplicate) → show err, stop.

**4.** `mcp__proj__proj_setup_permissions` — refresh sandbox write paths.
 - When `permissions.projects_root` set, call is no-op for sandbox paths. New repo outside `projects_root` → warn: "Repo path `<path>` is outside projects_root `<root>`. Move under root for sandbox coverage, or add path to sandbox.filesystem.allowWrite manually."

**5.** Show confirmation:
   ```
   Repo added to <project_name>:
   - Label: <label>
   - Path: <path>
   - Git repo: yes/no
   - Mode: reference (read-only) / writable
   - Permissions refreshed
   ```

**6.** `mcp__proj__tracking_git_flush` w/ `commit_message="Add repo: {label}"`.

## Prerequisites

- Active project loaded.
- Path provided.

## Error Handling

- No active project → "No active project. Run `/proj:load` to load one." Stop.
- No path → usage msg. Stop.
- Path missing → "Path `<path>` does not exist." Stop.
- Duplicate repo → show `proj_add_repo` err. Stop.
- Permissions refresh fail → log warning, continue.

## Output

Confirmation: label, path, git detection, mode (ref/writable), permissions status. Git tracking flush confirm.

Suggested next: `1. /proj:status` -- see updated project overview

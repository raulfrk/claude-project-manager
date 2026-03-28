---
name: archive
description: Archive a completed project, removing it from the active list. Use when the user says "archive project", "mark project complete", or "archive <name>".
allowed-tools: mcp__proj__proj_archive_preflight, mcp__proj__proj_archive, mcp__proj__proj_session_context, mcp__proj__proj_setup_permissions, mcp__proj__tracking_git_flush, mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_remove, Bash
argument-hint: "[project-name]"
---

Archive a project. $ARGUMENTS is the project name (optional — defaults to active project).

**1.** Resolve project name: If `$ARGUMENTS` specifies a project name, use it. Otherwise call `mcp__proj__proj_session_context` to get the active project name.

**2.** Preflight: Call `mcp__proj__proj_archive_preflight` with the project name. This single call returns everything needed:
   - `config.archive_destination`, `config.trash_grace_days`
   - `project.name`, `project.status`, `project.repos` (each with `label`, `path`, `reference`), `project.trello_card_id`
   - `open_todos.count`, `open_todos.items` (list of `{id, title}`)
   - `worktrees` (list of `{path, label}`)

   If the result is an error string (not JSON), display it and stop.

**3.** Open todos warning: If `open_todos.count > 0`, display them as bullet points with status icons and dependency badges (`[manual]`, `[blocked by X]`, `[blocks Y]`), then warn the user:
   ```
   This project has N open todos:
   - 🔲 **1** — Write skills _(medium)_ [manual]
   - 🔲 **2** — Build API _(high)_ [blocks 3]
   - 🔲 **3** — Integration tests _(medium)_ [blocked by 2]
   Are you sure you want to archive it?
   ```

**4.** Setup permissions: Call `mcp__proj__proj_setup_permissions` with `archive_destination` set to the archive destination path from preflight. This auto-grants Bash `mv`/`rm`/`mkdir` rules for project paths and the archive destination, plus sandbox write access.

**5.** Worktree discovery (if worktrees were returned by preflight):
   If preflight returned worktrees, also call `mcp__plugin_worktree_worktree__wt_list` to get full worktree details (branch info) for the matched paths.

**6.** Consolidated cleanup prompt — present everything in one prompt and collect all choices:

   ```
   Archive project '<name>'?

   ## Repos
   1. <label> — <path>  →  [move / delete / skip] (default: move)
   2. <label> — <path> (reference)  →  [skip] (default: skip)

   ## Worktrees
   - <path> (branch: <branch>) — will be removed via git worktree remove
   (If no worktrees: "No worktrees found.")

   ## Tracking Directory
   <tracking_dir>  →  [move / delete / skip] (default: move)

   Archive destination: <archive.destination>

   Enter choices (or press Enter for defaults):
   ```

   Choices:
   - Non-reference repos: move (default), delete, or skip
   - Reference repos: skip (default, not deletable)
   - Worktrees: confirm removal (default: yes)
   - Tracking dir: move (default), delete, or skip

**6a.** Purgeable check: Ask "Should this project be purgeable? (If no, it will never be deleted by purge) [yes]"
     Store the answer as `purgeable` (default: true).

**6b.** Worktree base paths: If the project config has `worktree_integration` enabled, call `mcp__plugin_worktree_worktree__wt_list_repos` to get worktree base repo paths. Extract the path from each line (format: `[label] /path/to/repo (default: branch)`). Store as `_wt_base_paths` list. If `wt_list_repos` fails or returns no repos, set `_wt_base_paths = []`.

**7.** Call `mcp__proj__proj_archive` with `purgeable=<answer from 6a>` to mark the project as archived and clear session.

**8.** Worktree cleanup (if worktrees found and user confirmed):
   For each worktree path, call `mcp__plugin_worktree_worktree__wt_remove` with `path=<worktree_path>`.
   If it fails (uncommitted changes): "Worktree at <path> has uncommitted changes. Force remove? [yes/no]"
   If yes: call `wt_remove` with `force=true`. If no: skip and note it was left in place.

**9.** Repo cleanup (for each repo based on user's choice):
   - **move**: `mkdir -p <archive_dest>/<name> && mv <repo_path> <archive_dest>/<name>/<label>/`
   - **delete**: `mkdir -p <tracking_dir>/.trash/<name>/ && mv <repo_path> <tracking_dir>/.trash/<name>/<label>/`
   - **skip**: do nothing

**10.** Tracking directory cleanup (based on user's choice):
    - **move**: `mkdir -p <archive_dest>/<name> && mv <tracking_dir> <archive_dest>/<name>/tracking/`
    - **delete**: `mkdir -p <tracking_dir>/.trash/<name>/ && mv <tracking_dir>/<name> <tracking_dir>/.trash/<name>/tracking/`
    - **skip**: do nothing

   > Trash entries expire after `trash_grace_days` (default 7). Run `/proj:purge` to sweep expired entries.

**11.** If this was the active project: "No active project now. Run `/proj:switch` to set a new one."

**12.** Git tracking flush: Only if tracking dir was NOT moved/deleted, call `mcp__proj__tracking_git_flush` with `commit_message="Archive: {name}"`.

**13.** Display summary:
    ```
    Archived '<name>':
    - Metadata: marked as archived
    - Repos:
      - <label>: <action> (<path> → <new_path> | deleted | skipped)
    - Worktrees: <N> removed, <M> skipped
    - Tracking: <action>
    ```

## Prerequisites

- A project must exist (either active project or specified by name).
- Archive destination must be configured in config.

## Error Handling

- **No project found**: displays error from `proj_archive_preflight` and stops.
- **Preflight returns error**: displays the error and stops.
- **Open todos**: warns user and asks for confirmation before proceeding.
- **Worktree removal failure (uncommitted changes)**: asks user to force-remove or skip.
- **Move/delete failure**: displays error from Bash command.

## Output

Archive summary: metadata status, per-repo actions (moved/deleted/skipped with paths), worktrees removed/skipped count, tracking directory action.

Suggested next: `1. /proj:switch` -- switch to another project

---
name: archive
description: Archive a completed project, removing it from the active list. Use when the user says "archive project", "mark project complete", or "archive <name>".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_archive, mcp__proj__proj_get_active, mcp__proj__proj_get, mcp__proj__todo_list, mcp__proj__config_load, mcp__proj__proj_setup_permissions, mcp__proj__tracking_git_flush, mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_remove, Bash
argument-hint: "[project-name]"
---

Archive a project. $ARGUMENTS is the project name (optional — defaults to active project).

1. Call `mcp__proj__config_load` to load plugin configuration. Extract:
   - `worktree_integration` (bool)
   - `archive.destination` (path, default `~/projects/archived`)

2. Call `mcp__proj__proj_get` (or `proj_get_active` if no name given) to get the project metadata. Extract:
   - `name`
   - `repos` list (each with `label`, `path`, `reference`)

3. Call `mcp__proj__todo_list` to check for open todos.
   If there are open todos, display them as bullet points with status icons (🔄/🔲), bold ID, title, and priority in italics, then warn the user:
   ```
   This project has N open todos:
   - 🔄 **3** — Write skills _(high)_
   - 🔲 **4** — Integration tests _(medium)_ [blocked by 3]
   Are you sure you want to archive it?
   ```

4. **Setup permissions**: Call `mcp__proj__proj_setup_permissions` with `archive_destination` set to the archive destination path. This auto-grants Bash `mv`/`rm`/`mkdir` rules for project paths and the archive destination, plus sandbox write access.

5. **Worktree discovery** (if `worktree_integration` is true):
   Call `mcp__plugin_worktree_worktree__wt_list` with no arguments. Filter the output for worktrees whose base repo paths match any of the project's repo paths. Collect all matching worktree entries (path, branch).

6. **Consolidated cleanup prompt** — present everything in one prompt and collect all choices:

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

6.5. **Purgeable check**: Ask "Should this project be purgeable? (If no, it will never be deleted by purge) [yes]"
     Store the answer as `purgeable` (default: true).

7. Call `mcp__proj__proj_archive` with `purgeable=<answer from 6.5>` to mark the project as archived, clear session, and clean zoxide.

8. **Worktree cleanup** (if worktrees found and user confirmed):
   For each worktree path, call `mcp__plugin_worktree_worktree__wt_remove` with `path=<worktree_path>`.
   If it fails (uncommitted changes): "Worktree at <path> has uncommitted changes. Force remove? [yes/no]"
   If yes: call `wt_remove` with `force=true`. If no: skip and note it was left in place.

9. **Repo cleanup** (for each repo based on user's choice):
   - **move**: `mkdir -p <archive_dest>/<name> && mv <repo_path> <archive_dest>/<name>/<label>/`
   - **delete**: `rm -rf <repo_path>`
   - **skip**: do nothing

10. **Tracking directory cleanup** (based on user's choice):
    - **move**: `mkdir -p <archive_dest>/<name> && mv <tracking_dir> <archive_dest>/<name>/tracking/`
    - **delete**: `rm -rf <tracking_dir>`
    - **skip**: do nothing

11. If this was the active project: "No active project now. Use /proj:switch to set a new one."

12. **Git tracking flush**: Only if tracking dir was NOT moved/deleted, call `mcp__proj__tracking_git_flush` with `commit_message="Archive: {name}"`.

13. Display summary:
    ```
    Archived '<name>':
    - Metadata: marked as archived
    - Repos:
      - <label>: <action> (<path> → <new_path> | deleted | skipped)
    - Worktrees: <N> removed, <M> skipped
    - Tracking: <action>
    ```

💡 Suggested next: (1) /proj:switch — switch to another project

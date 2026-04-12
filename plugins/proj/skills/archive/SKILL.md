---
name: archive
description: Archive a completed project, removing it from the active list. Use when the user says "archive project", "mark project complete", or "archive <name>".
allowed-tools: mcp__proj__proj_archive_preflight, mcp__proj__proj_archive, mcp__proj__proj_session_context, mcp__proj__proj_setup_permissions, mcp__proj__tracking_git_flush, mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_remove, Bash
argument-hint: "[project-name]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Archive project. $ARGUMENTS = project name (opt, defaults to active).

**1.** Resolve name: $ARGUMENTS given → use it. Else `mcp__proj__proj_session_context` → active project name.

**2.** Preflight: `mcp__proj__proj_archive_preflight` w/ project name. Returns:
 - `config.archive_destination`, `config.trash_grace_days`
 - `project.name`, `project.status`, `project.repos` (each: `label`, `path`, `reference`), `project.trello_card_id`
 - `open_todos.count`, `open_todos.items` (list `{id, title}`)
 - `worktrees` (list `{path, label}`)

 Error string (not JSON) → display, stop.

**3.** Open todos warning: `open_todos.count > 0` → display as bullets w/ status icons + dependency badges (`[manual]`, `[blocked by X]`, `[blocks Y]`), warn:
   ```
   This project has N open todos:
   - 🔲 **1** — Write skills _(medium)_ [manual]
   - 🔲 **2** — Build API _(high)_ [blocks 3]
   - 🔲 **3** — Integration tests _(medium)_ [blocked by 2]
   Are you sure you want to archive it?
   ```

**4.** Setup perms: `mcp__proj__proj_setup_permissions` w/ `archive_destination` from preflight. Auto-grants Bash `mv`/`rm`/`mkdir` rules for project paths + archive dest + sandbox write.
 - `permissions.projects_root` set → no per-project path revocation needed. `proj_revoke_all_permissions` only removes MCP wildcards when explicitly requested.

**5.** Worktree discovery (if preflight returned worktrees): call `mcp__plugin_worktree_worktree__wt_list` for full details (branch info) on matched paths.

**6.** Consolidated cleanup prompt — one prompt, all choices:

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
 - Non-ref repos: move (default), delete, skip
 - Ref repos: skip (default, not deletable)
 - Worktrees: confirm removal (default: yes)
 - Tracking dir: move (default), delete, skip

**6a.** Ask "Should this project be purgeable? (If no, never deleted by purge) [yes]" → store as `purgeable` (default: true).

**6b.** Worktree base paths: `worktree_integration` enabled → `mcp__plugin_worktree_worktree__wt_list_repos` → extract path from each line (fmt: `[label] /path/to/repo (default: branch)`). Store as `_wt_base_paths`. Fails/empty → `_wt_base_paths = []`.

**7.** `mcp__proj__proj_archive` w/ `purgeable=<6a answer>` → mark archived, clear session.

**8.** Worktree cleanup (if found + confirmed): each worktree → `mcp__plugin_worktree_worktree__wt_remove` w/ `path=<worktree_path>`.
 Fails (uncommitted changes) → "Worktree at <path> has uncommitted changes. Force remove? [yes/no]"
 Yes → `wt_remove` w/ `force=true`. No → skip, note left in place.

**9.** Repo cleanup per user choice:
 - move: `mkdir -p <archive_dest>/<name> && mv <repo_path> <archive_dest>/<name>/<label>/`
 - delete: `mkdir -p <tracking_dir>/.trash/<name>/ && mv <repo_path> <tracking_dir>/.trash/<name>/<label>/`
 - skip: noop

**10.** Tracking dir cleanup per user choice:
 - move: `mkdir -p <archive_dest>/<name> && mv <tracking_dir> <archive_dest>/<name>/tracking/`
 - delete: `mkdir -p <tracking_dir>/.trash/<name>/ && mv <tracking_dir>/<name> <tracking_dir>/.trash/<name>/tracking/`
 - skip: noop

 > Trash expires after `trash_grace_days` (default 7). `/proj:purge` sweeps expired.

**11.** Was active project → "No active project now. Run `/proj:switch` to set new one."

**12.** Git tracking flush: only if tracking dir NOT moved/deleted → `mcp__proj__tracking_git_flush` w/ `commit_message="Archive: {name}"`.

**13.** Summary:
    ```
    Archived '<name>':
    - Metadata: marked as archived
    - Repos:
      - <label>: <action> (<path> → <new_path> | deleted | skipped)
    - Worktrees: <N> removed, <M> skipped
    - Tracking: <action>
    ```

## Prerequisites

- Project must exist (active or specified by name).
- Archive dest configured in config.

## Error Handling

- No project found → display preflight err, stop.
- Preflight err → display, stop.
- Open todos → warn, confirm before proceeding.
- Worktree removal fail (uncommitted) → ask force-remove or skip.
- Move/delete fail → display Bash err.

## Output

Archive summary: metadata status, per-repo actions (moved/deleted/skipped w/ paths), worktrees removed/skipped count, tracking dir action.

Suggested next: `1. /proj:switch` -- switch to another project

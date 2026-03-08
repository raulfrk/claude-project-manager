---
name: init
description: Initialize project tracking for a project. Use when the user says "start tracking this project", "init project", "track this project", "set up project tracking for X", "new project", "create project", or "initialize tracking".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_init, mcp__proj__proj_load_session, mcp__proj__proj_add_repo, mcp__proj__claudemd_write, mcp__proj__claudemd_read, mcp__proj__config_load, mcp__proj__proj_set_permissions, mcp__proj__proj_setup_permissions, mcp__proj__proj_explore_codebase, mcp__proj__notes_append, mcp__proj__proj_update_meta, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, mcp__plugin_worktree_worktree__wt_list, mcp__proj__tracking_git_flush, Bash
argument-hint: "[project-name]"
---

Initialize project tracking. $ARGUMENTS may contain a project name (optional).

1. Load config with `mcp__proj__config_load` to check settings.

2. Determine project name:
   - If $ARGUMENTS is non-empty, use that as the name
   - Otherwise, **ask**: "What is the project name?" (do not assume from cwd)
   - Confirm: "Project name: <name>?"

3. Collect project directories (multi-directory loop):

   Initialize: `_dirs = []` (list of `{path, label}` dicts), `_worktree_entries = []` (deferred worktree creations), `_explored_dirs = set()` (labels of directories that had repo mapping + CLAUDE.md written).

   **Directory collection loop** — repeat until the user says done:

   a. Ask: "Add a directory to this project (path):" (or for the first iteration: "What is the first content directory for this project?")

   b. If `worktree_integration: true` AND `projects_base_dir` is set:
      - Call `mcp__plugin_worktree_worktree__wt_list_repos` (once, cache the result).
      - Present mode selection for this directory:
        ```
        How should this directory be set up?
        1. New directory — create at the given path  [default]
        2. Use existing repo — point directly to a registered repo
        3. Create worktree — new worktree from a registered repo
        ```
        (Omit option 2/3 if no repos are registered.)

      - **Mode 1**: Ask for path (default: `<projects_base_dir>/<name>`). Ask for label. Set `_content_mode = "new-dir"`.
      - **Mode 2**: Display registered repos. Ask user to select by label. Set path = selected repo path. Ask for label (default: repo label). Set `_content_mode = "existing-repo"`.
      - **Mode 3**: Display registered repos. Ask user to select. Set path = `<projects_base_dir>/worktrees/<name>`. Ask for label. Store in `_worktree_entries` for deferred creation. Set `_content_mode = "worktree"`.

   c. **Otherwise** (no worktree integration):
      - If first directory and `projects_base_dir` is set: default path = `<projects_base_dir>/<name>`
      - If first directory and no `projects_base_dir`: default path = current working directory
      - Ask for path (show default). Ask for label (default: "code" for first dir, require explicit for subsequent).

   d. Validate:
      - Label must be unique within `_dirs`. If duplicate: "Label '<label>' already used. Choose a different label."
      - Path must not be empty.

   e. Add `{path: <resolved_path>, label: <label>}` to `_dirs`.

   f. **Directory creation check** (skip for worktree mode):
      - If path does not exist: "Directory `<path>` does not exist. Create it now? [y/n]" -> `mkdir -p`
      - If path exists: "Found directory: `<path>`"

   g. Ask: "Add another directory? (Enter to skip, or type a path):"
      - If the user presses Enter (empty): exit loop.
      - If the user types a path: use it as the next directory's path and loop back to (b) or (c) for mode/label selection.

   At least one directory is required. If `_dirs` is empty after the loop, error.

3b. **Repo mapping** (for each directory that exists and has files):
   - For each dir in `_dirs`:
     - Check: `Bash: ls -A <path> | head -1`
     - If output is **non-empty** (directory has existing content):
       - Ask: "Directory '<label>' at `<path>` has existing content. Map the repo? [yes/no]"
       - If **yes** — run the full exploration sequence and add to `_explored_dirs`:
         1. Call `mcp__proj__proj_explore_codebase` with `path=<path>`. Returns JSON with `tech_stack`, `entry_points`, `key_dirs`, `config_files`, `file_types`, `file_tree`, `arch_note`.
         2. Synthesise: primary language/framework, key directories, entry points, architecture from the returned data.
         3. Call `mcp__proj__claudemd_read` for the path. If CLAUDE.md exists, merge findings into it (preserve all existing sections; add/update `## Architecture` and `## Key Files`). If not, create fresh CLAUDE.md with Overview, Architecture, Key Files sections.
         4. Call `mcp__proj__claudemd_write` with the result.
         5. Add `label` to `_explored_dirs`.
         6. Call `mcp__proj__notes_append` with project_name=<name> and text: `## Repo Exploration — <date>\n**Tech stack**: ...\n**Entry points**: ...\n**Key dirs**: ...\n**Architecture note**: ...`
       - If **no**: continue normally.
     - If output is **empty**: skip.

4. Ask all metadata in one prompt:
   ```
   Project details (all optional, press Enter to use defaults):
   - Description:
   - Tags (comma-separated):
   - Git integration? [yes]:
   ```

5. Call `mcp__proj__proj_init` with name, dirs=_dirs, description, tags, git_enabled.
   - Pass the `dirs` parameter (list of `{path, label}` dicts) — do NOT use the legacy `path` parameter.
   - If `proj_init` returns an error: display the error message and stop (do not call `proj_load_session` or proceed further).
   Call `mcp__proj__proj_load_session` to set as active for this session.

6. **Permissions** (if `perms_integration: true` in config and project's auto_grant != false):
   - Ask: "Allow Claude to freely access this project directory? [yes/no/use global: yes]"
   - Ask: "Auto-allow plugin MCP tools for this project? [yes/no/use global: yes]"
   - If either answer is yes, call `mcp__proj__proj_setup_permissions` once:
     - `grant_path_access=<first answer is yes>`
     - `grant_investigation_tools=<first answer is yes>` (same as grant_path_access)
     - `mcp_servers=[<list>]` — build list when second answer is yes:
       always include `"plugin_proj_proj"`, `"plugin_perms_perms"`;
       add `"plugin_worktree_worktree"` if worktree_integration; add the value of `todoist.mcp_server` if todoist.enabled
     - (If second answer is no, pass `mcp_servers=[]`)
   - Store the decisions in `mcp__proj__proj_set_permissions`
   - If `proj_setup_permissions` returns an error (e.g. perms plugin not available), warn: "Permissions could not be set automatically. Install the perms plugin when available." and continue.

7. **CLAUDE.md** — For each dir in `_dirs` whose label is NOT in `_explored_dirs` (those already had CLAUDE.md written during repo mapping):
   Ask: "Create a CLAUDE.md in '<label>' (`<path>`) to help Claude understand the project context? [yes]"
   - If yes: call `mcp__proj__claudemd_write` with initial content:
     ```markdown
     # <project-name>

     **Status**: active | **Priority**: medium
     **Tracking**: <tracking_dir>/<name>

     ## Overview
     <description or 'Add description here'>

     ## Active Todos
     None yet. Use /proj:todo add to add todos.
     ```

8. **Worktrees** — executes deferred worktree creations from step 3:

   - If `_worktree_entries` is empty: skip this step silently.

   - For each entry in `_worktree_entries`:
     1. Call `mcp__plugin_worktree_worktree__wt_create` with:
        - `repo_label`: entry's repo label
        - `branch`: entry's branch name
        - `new_branch`: true
        - `path`: entry's worktree path
     2. **On success**: inform the user — "Worktree created at `<path>` on branch `<branch>`."
     3. **On failure**: inform the user of the error. Offer fallback:
        "Worktree creation failed for '<label>'. Fall back to creating a new directory? [yes/no]"
        - If **yes**: `mkdir -p <path>`, note the fallback.
        - If **no**: note the failure and continue.

9. **Git tracking overrides** (if `git_tracking.enabled: true` in config):
   Ask:
   ```
   Per-project git tracking overrides (Enter to use global defaults):
   - Override git tracking for this project? [use global]:
   - Override GitHub push for this project? [use global]:
   - Custom GitHub repo name format? [use global]:
   ```
   - If any answer is not "use global" / empty, call `mcp__proj__proj_update_meta` with the corresponding `git_tracking_enabled`, `git_tracking_github_enabled`, or `git_tracking_github_repo_format` values.
   - If all answers are empty/default: skip (None values inherit global defaults).

10. **Todoist** (if `todoist.enabled: true` in config):
   - Use `mcp__{todoist.mcp_server}__add-projects` with the project name (server name from config)
   - Store todoist_project_id via `mcp__proj__proj_update_meta`
   - If the Todoist tool call fails (server not running or not configured), warn: "Todoist project could not be created. You can link it later via `/proj:sync`." and continue.

11. Show summary of what was created. List all directories:
    ```
    Directories:
      - <label>: <path> (new directory | existing repo | worktree of <repo>, branch: <branch>)
      ...
    ```

12. **Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Init: {name}"`.

💡 Suggested next: (1) /proj:todo add — add your first task  (2) /proj:status — see the project overview

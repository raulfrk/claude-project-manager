---
name: init
description: Initialize project tracking for a project. Use when the user says "start tracking this project", "init project", "track this project", or "set up project tracking for X".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_init, mcp__proj__proj_set_active, mcp__proj__proj_add_repo, mcp__proj__claudemd_write, mcp__proj__claudemd_read, mcp__proj__config_load, mcp__proj__proj_set_permissions, mcp__proj__proj_setup_permissions, mcp__proj__proj_explore_codebase, mcp__proj__notes_append, mcp__proj__proj_update_meta, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, mcp__plugin_worktree_worktree__wt_list, Bash
argument-hint: "[project-name]"
---

Initialize project tracking. $ARGUMENTS may contain a project name (optional).

1. Load config with `mcp__proj__config_load` to check settings.

2. Determine project name:
   - If $ARGUMENTS is non-empty, use that as the name
   - Otherwise, **ask**: "What is the project name?" (do not assume from cwd)
   - Confirm: "Project name: <name>?"

3. Determine content path:

   **If `worktree_integration: true` in config AND `projects_base_dir` is set**:

   a. Call `mcp__plugin_worktree_worktree__wt_list_repos` to get the list of pre-registered repos.

   b. If **no repos are registered**:
      - Inform the user: "No repos are registered. Worktree and existing-repo options are unavailable. To enable them, run `/worktree:add-repo` first."
      - Proceed with Mode 1 (default new directory behavior, see below).

   c. If **repos are registered**, present mode selection:
      ```
      How should the content directory be set up?
      1. New directory — create <projects_base_dir>/<name>  [default]
      2. Use existing repo — point directly to a registered repo
      3. Create worktree — new worktree from a registered repo
      ```
      (If `projects_base_dir` is not set, omit option 3 from the menu.)

   d. **Mode 1** (option 1, or Enter): set content path = `<projects_base_dir>/<name>`. Set `_content_mode = "new-dir"`. Proceed with existing directory check below.

   e. **Mode 2** (option 2):
      - Display the registered repos (label + path).
      - Ask: "Select a repo by label:"
      - Set content path = the selected repo's local path.
      - Skip directory creation checks (path already exists).
      - Set `_content_mode = "existing-repo"`, `_content_repo_label = <selected label>`.
      - Jump to step 3b.

   f. **Mode 3** (option 3, only if `projects_base_dir` is set):
      - Display the registered repos (label + path).
      - Ask: "Select a repo by label:"
      - Set `_worktree_repo_label = <selected label>`.
      - Set `_worktree_path = <projects_base_dir>/worktrees/<project-name>`.
      - Set `_worktree_branch = <project-name>`.
      - Inform the user: "Will create worktree at `<_worktree_path>` on branch `<_worktree_branch>`."
      - Set content path = `_worktree_path` (will be created in step 8).
      - Set `_content_mode = "worktree"`.
      - Skip directory creation checks (worktree does not exist yet).
      - Jump to step 3b.

   **Otherwise** (worktree_integration is false/unset OR projects_base_dir is not set):
   - If `projects_base_dir` is set in config: content path = `<projects_base_dir>/<name>`
   - Otherwise: use the current working directory as content path
   - Set `_content_mode = "new-dir"`.

   **Directory creation checks** (Mode 1 and Mode 2 only — skip for Mode 3):
   - Check if the content path directory exists on disk (use Bash `test -d <path>`):
     - If it **does not exist**: "Content directory `<path>` does not exist. Create it now? [y/n]"
       - If yes: `mkdir -p <path>`
       - If no: proceed without creating (note it in summary)
     - If it **exists**: "Found content directory: `<path>` ✓"
   - Check if the tracking path directory exists (`<tracking_dir>/<name>`):
     - If it **does not exist**: "Tracking directory `<path>` does not exist. Create it now? [y/n]"
       - If yes: `mkdir -p <path>`
       - If no: proceed (the MCP tool will create it anyway)
     - If it **exists**: "Found tracking directory: `<path>` ✓"

3b. **Repo mapping** (only if the content directory exists and has files):
   - Check: `Bash: find <content_path> -maxdepth 1 -mindepth 1 | head -1`
   - If output is **non-empty** (directory has existing content):
     - Ask: "This directory has existing content. Map the repo? Claude will scan it and write findings to CLAUDE.md and NOTES.md. [yes/no]"
     - If **yes** — run the full exploration sequence and set `_explored = true`:
       1. Call `mcp__proj__proj_explore_codebase` with `path=<content_path>`. Returns JSON with `tech_stack`, `entry_points`, `key_dirs`, `config_files`, `file_types`, `file_tree`, `arch_note`.
       2. Synthesise: primary language/framework, key directories, entry points, architecture from the returned data.
       3. Call `mcp__proj__claudemd_read` for the content path. If CLAUDE.md exists, merge findings into it (preserve all existing sections; add/update `## Architecture` and `## Key Files`). If not, create fresh CLAUDE.md with Overview, Architecture, Key Files sections.
       4. Call `mcp__proj__claudemd_write` with the result.
       5. Call `mcp__proj__notes_append` with: `## Repo Exploration — <date>\n**Tech stack**: ...\n**Entry points**: ...\n**Key dirs**: ...\n**Architecture note**: ...`
     - If **no**: continue normally.
   - If output is **empty** (new or empty directory): skip this step.

4. Ask:
   - Description (optional, hit enter to skip)
   - Tags (optional, comma-separated)
   - "Git integration enabled for this project? [global default]"

5. Call `mcp__proj__proj_init` with name, path=<resolved content path>, description, tags, git_enabled.
   - If `proj_init` returns an error: display the error message and stop (do not call `proj_set_active` or proceed further).
   Call `mcp__proj__proj_set_active` to set as active.

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

7. **CLAUDE.md** — Skip if `_explored = true` (already written during repo mapping).
   Otherwise ask: "Create a CLAUDE.md in the project directory to help Claude understand the project context? [yes]"
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

8. **Worktree** — executes deferred worktree creation from step 3 (Mode 3 only):

   - If `_content_mode != "worktree"`: skip this step silently.

   - If `_content_mode == "worktree"`:
     1. Call `mcp__plugin_worktree_worktree__wt_create` with:
        - `repo_label`: `_worktree_repo_label`
        - `branch`: `_worktree_branch`
        - `new_branch`: true
        - `path`: `_worktree_path`
     2. **On success**: inform the user — "Worktree created at `<_worktree_path>` on branch `<_worktree_branch>`."
     3. **On failure**: inform the user of the error. Offer fallback:
        "Worktree creation failed. Fall back to creating a new directory at `<projects_base_dir>/<name>`? [yes/no]"
        - If **yes**:
          - Run `mkdir -p <projects_base_dir>/<name>`
          - Update content path to `<projects_base_dir>/<name>`
          - Set `_content_mode = "new-dir"` (so the summary reflects the actual state)
          - Note the fallback in the summary.
        - If **no**: note the failure in the summary and continue.

9. **Todoist** (if `todoist.enabled: true` in config):
   - Use `mcp__{todoist.mcp_server}__add-projects` with the project name (server name from config)
   - Store todoist_project_id via `mcp__proj__proj_update_meta`

10. Show summary of what was created. Include a content directory line reflecting the mode used:
    - Mode 1 (`_content_mode == "new-dir"`): "Content directory: `<path>` (new directory)"
    - Mode 2 (`_content_mode == "existing-repo"`): "Content directory: `<path>` (existing repo: `<_content_repo_label>`)"
    - Mode 3 (`_content_mode == "worktree"`): "Content directory: `<path>` (worktree of `<_worktree_repo_label>`, branch: `<_worktree_branch>`)"

💡 Suggested next: (1) /proj:todo add — add your first task  (2) /proj:status — see the project overview

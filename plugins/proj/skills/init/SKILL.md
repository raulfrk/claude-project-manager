---
name: init
description: Initialize project tracking for a project. Use when the user says "start tracking this project", "init project", "track this project", "set up project tracking for X", "new project", "create project", or "initialize tracking".
allowed-tools: mcp__proj__proj_init, mcp__proj__proj_load_session, mcp__proj__proj_add_repo, mcp__proj__claudemd_write, mcp__proj__claudemd_read, mcp__proj__config_load, mcp__proj__proj_set_permissions, mcp__proj__proj_setup_permissions, mcp__proj__proj_explore_codebase, mcp__proj__notes_append, mcp__proj__proj_update_meta, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, mcp__plugin_worktree_worktree__wt_list, mcp__proj__tracking_git_flush, Bash
argument-hint: "[project-name]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Init project tracking. $ARGUMENTS may contain project name (opt).

**1.** Load config w/ `mcp__proj__config_load`.

**2.** Determine project name:
 - $ARGUMENTS non-empty → use as name
 - Otherwise ask: "What is project name?" (don't assume from cwd)
 - Confirm: "Project name: <name>?"

**3.** Collect project dirs (multi-dir loop):

 Init: `_dirs = []` (list of `{path, label}` dicts), `_worktree_entries = []` (deferred wt creations), `_explored_dirs = set()` (labels w/ repo mapping + CLAUDE.md written).

 **Dir collection loop** — repeat until user says done:

 a. Ask: "Add dir to project (path):" (first iteration: "First content dir for project?")

 b. If `worktree_integration: true` AND `projects_base_dir` set:
 - Call `mcp__plugin_worktree_worktree__wt_list_repos` (once, cache). Extract base repo paths from each line (fmt: `[label] /path/to/repo (default: branch)`), store as `_wt_base_paths`.
 - Present mode selection:
        ```
        How should this directory be set up?
        1. New directory — create at the given path  [default]
        2. Use existing repo — point directly to a registered repo
        3. Create worktree — new worktree from a registered repo
        ```
 (Omit opt 2/3 if no repos registered.)

 - Mode 1: Ask path (default: `<projects_base_dir>/<name>`). Ask label. `_content_mode = "new-dir"`.
 - Mode 2: Show registered repos. User selects by label. path = selected repo path. Ask label (default: repo label). `_content_mode = "existing-repo"`.
 - Mode 3: Show registered repos. User selects. path = `<projects_base_dir>/worktrees/<name>`. Ask label. Store in `_worktree_entries` for deferred creation. `_content_mode = "worktree"`.

 c. Otherwise (no wt integration):
 - First dir + `projects_base_dir` set → default path = `<projects_base_dir>/<name>`
 - First dir + no `projects_base_dir` → default path = cwd
 - Ask path (show default). Ask label (default: "code" first dir, explicit for subsequent).

 d. Validate:
 - Label must be unique in `_dirs`. Duplicate → stop: "Label `<label>` already used. Run `/proj:remove-repo` to free it."
 - Path must not be empty.

 e. Add `{path: <resolved_path>, label: <label>}` to `_dirs`.

 f. Dir creation check (skip for wt mode):
 - Path missing → "Dir `<path>` doesn't exist. Create? [y/n]" → `mkdir -p`
 - Path exists → "Found dir: `<path>`"

 g. Ask: "Add another dir? (Enter to skip, or type path):"
 - Enter (empty) → exit loop
 - Path typed → use as next dir's path, loop back to (b)/(c)

 Min one dir required. `_dirs` empty after loop → err.

**3a.** Repo mapping (each dir that exists w/ files):
 - Each dir in `_dirs`:
 - Check: `Bash: ls -A <path> | head -1`
 - Non-empty (has content):
 - Ask: "Dir '<label>' at `<path>` has content. Map repo? [yes/no]"
 - Yes → full exploration, add to `_explored_dirs`:
 1. `mcp__proj__proj_explore_codebase` w/ `path=<path>`. Returns JSON: `tech_stack`, `entry_points`, `key_dirs`, `config_files`, `file_types`, `file_tree`, `arch_note`.
 2. Synthesise: primary lang/framework, key dirs, entry points, architecture.
 3. `mcp__proj__claudemd_read` for path. CLAUDE.md exists → merge findings (preserve existing sections; add/update `## Architecture` + `## Key Files`). Missing → create fresh w/ Overview, Architecture, Key Files.
 4. `mcp__proj__claudemd_write` w/ result.
 5. Add `label` to `_explored_dirs`.
 6. `mcp__proj__notes_append` w/ project_name=<name>, text: `## Repo Exploration — <date>\n**Tech stack**: ...\n**Entry points**: ...\n**Key dirs**: ...\n**Architecture note**: ...`
 - No → continue.
 - Empty → skip.

**4.** Ask all metadata in one prompt:
   ```
   Project details (all optional, press Enter to use defaults):
   - Description:
   - Tags (comma-separated):
   - Git integration? [yes]:
   ```

**4a.** Zoxide:
 - Config `zoxide_integration: True` → `_zoxide = true` (inherits global).
 - Config `zoxide_integration: False` → ask "Enable zoxide? (boosts project dirs for faster cd) [no]"
 - Yes → `_zoxide = true`; no → `_zoxide = null` (global default)

**5.** Before `proj_init`, filter `_dirs` excluding entries w/ path matching `_worktree_entries` path. Store excluded as `_deferred_dirs` — registered via `proj_add_repo` after wt creation in step 8.

 `mcp__proj__proj_init` w/ name, dirs=<filtered _dirs>, desc, tags, git_enabled, zoxide_integration=_zoxide.
 - Pass `dirs` param (list of `{path, label}` dicts) — NOT legacy `path` param.
 - Err → display + stop (don't call `proj_load_session`).
 `mcp__proj__proj_load_session` to set active.

**6.** Permissions (if `sandbox_integration: true` in config + project's auto_grant != false):
 - Ask: "Allow Claude free access to project dir? [yes/no/use global: yes]"
 - Ask: "Auto-allow plugin MCP tools? [yes/no/use global: yes]"
 - Either yes → `mcp__proj__proj_setup_permissions` once:
 - `mcp_servers=[<list>]` — build when second=yes:
 always: `"plugin_proj_proj"`, `"plugin_sandbox_sandbox"`, `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`;
 add `"plugin_worktree_worktree"` if wt_integration; `"jira"` if jira.enabled; `"trello"` if trello.enabled
 - Second=no → `mcp_servers=[]`
 - Store decisions in `mcp__proj__proj_set_permissions`
 - When `permissions.projects_root` set in config, `proj_setup_permissions` skips per-repo sandbox path additions (root covers all). Only ensures MCP wildcards present.
 - `proj_setup_permissions` err → warn: "Permissions not set automatically. Install sandbox plugin when available." Continue.

**7.** CLAUDE.md — Each dir in `_dirs` whose label NOT in `_explored_dirs` (already had CLAUDE.md from repo mapping):
 Ask: "Create CLAUDE.md in '<label>' (`<path>`)? [yes]"
 - Yes → `mcp__proj__claudemd_write` w/ initial content:
     ```markdown
     # <project-name>

     **Status**: active | **Priority**: medium
     **Tracking**: <tracking_dir>/<name>

     ## Overview
     <description or 'Add description here'>

     ## Active Todos
     None yet. Use /proj:todo add to add todos.
     ```

**8.** Worktrees — exec deferred wt creations from step 3:

 - `_worktree_entries` empty → skip silently.

 - Each entry in `_worktree_entries`:
 1. `mcp__plugin_worktree_worktree__wt_create` w/:
 - `repo_label`: entry's repo label
 - `branch`: entry's branch name
 - `new_branch`: true
 - `path`: entry's wt path
 2. Success → `mcp__proj__proj_add_repo` w/ `repo_path=<wt path>`, `label=<entry's label>` to register + boost zoxide (path now exists). Inform: "Worktree created at `<path>` on branch `<branch>`."
 3. Failure → inform err. Offer fallback:
 "Wt creation failed for '<label>'. Fall back to new dir? [yes/no]"
 - Yes → `mkdir -p <path>`, note fallback.
 - No → note failure, continue.

**9.** Git tracking overrides (if `git_tracking.enabled: true` in config):
 Ask:
   ```
   Per-project git tracking configuration overrides for the shared tracking repo (Enter to use global defaults):
   - Override git tracking for this project? [use global]:
   - Override GitHub push for this project? [use global]:
   - Custom GitHub repo name format? [use global]:
   ```
 - Any answer not "use global"/empty → `mcp__proj__proj_update_meta` w/ corresponding `git_tracking_enabled`, `git_tracking_github_enabled`, or `git_tracking_github_repo_format` vals.
 - All default/empty → skip (None vals inherit global defaults).

**10.** Show summary. List all dirs:
    ```
    Directories:
      - <label>: <path> (new directory | existing repo | worktree of <repo>, branch: <branch>)
      ...
    ```

**11.** Git tracking flush: `mcp__proj__tracking_git_flush` w/ `commit_message="Init: {name}"`.

## Prerequisites

- Proj plugin configured (`/proj:init-plugin` first if `~/.claude/proj.yaml` missing).

## Err Handling

- Config not found → display err from `config_load`, stop.
- Duplicate project name → display err from `proj_init`, stop.
- Invalid dir path → display err, stop.
- Duplicate label → display err, ask different label.
- Wt creation failure → fallback to plain dir.
- Permissions setup failure → warn, continue (non-fatal).

## Output

Summary: project name, all dirs (label, path, type), permissions status. Git tracking flush confirmation.

Suggested next: `1. /proj:todo add` -- add first task | `2. /proj:status` -- project overview

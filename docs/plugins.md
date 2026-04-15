# Plugins

Detailed reference for all 9 plugins in the claude-project-manager marketplace.

---

## Table of Contents

- [sandbox](#sandbox)
- [worktree](#worktree)
- [proj](#proj)
- [router](#router)
- [todoist](#todoist)
- [trello](#trello)
- [jira](#jira)
- [zoxide](#zoxide)
- [analyse](#analyse)

---

## sandbox

**Version**: 0.2.0 | **Category**: utilities | **License**: MIT

Manages Claude Code sandbox-mode `settings.json`. Provides atomic read/write access for sandbox write paths, MCP allow rules, Skill allow rules, network domains, and deny rules. Used internally by `proj` and `worktree` during setup, and can be called directly.

### Install

```console
/plugin install raulfrk/claude-project-manager:sandbox
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `sandbox_add_write_path(path)` | Add directory to sandbox write allowlist and Edit rules |
| `sandbox_remove_write_path(path)` | Remove directory from sandbox write allowlist and Edit rules |
| `sandbox_set_deny(rules)` | Replace `permissions.deny` rules atomically |
| `sandbox_batch_setup(paths?, mcp_servers?, domains?, skill_prefixes?)` | Add write paths, MCP rules, domains, and Skill rules in one atomic write |
| `sandbox_batch_revoke(paths?, mcp_servers?, domains?, skill_prefixes?)` | Remove write paths, MCP rules, domains, and Skill rules in one atomic write |
| `sandbox_list(format?)` | List current sandbox configuration |
| `sandbox_check(path?, server?, domain?, skill?)` | Check if a path, server, domain, or skill prefix is configured |
| `sandbox_reconcile(...)` | Sync expected vs actual MCP servers, paths, and skill prefixes |

All operations are idempotent. Changes take effect immediately.

### Skills

None. This is an MCP-only plugin.

### Config

Reads and writes `~/.claude/settings.json`. No plugin-specific configuration file.

### Examples

```
# Add a project directory to sandbox write paths
sandbox_add_write_path("/home/user/projects/my-app")

# Batch setup for a new project (MCP servers, domains, skill prefixes via batch tools)
sandbox_batch_setup(
  paths=["/home/user/projects/my-app"],
  mcp_servers=["plugin_proj_proj", "plugin_worktree_worktree"],
  domains=["api.github.com"],
  skill_prefixes=["proj", "worktree"]
)
```

---

## worktree

**Version**: 2.6.0 | **Category**: utilities | **License**: MIT

Registry-based git worktree management. Register a repository once with a label, then create isolated worktrees for branches or parallel work. Automatically manages sandbox permissions when the sandbox plugin is installed.

### Install

```console
/plugin install raulfrk/claude-project-manager:worktree
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `wt_add_repo(path, label?)` | Register a base git repository |
| `wt_remove_repo(label)` | Unregister a base repository |
| `wt_list_repos()` | List all registered repositories |
| `wt_create(repo, branch, path?)` | Create a worktree from a registered repo |
| `wt_get(path)` | Get details of a specific worktree |
| `wt_list(repo?)` | List all worktrees, optionally filtered by repo |
| `wt_remove(path)` | Remove a worktree |
| `wt_lock(path, reason?)` | Lock a worktree to prevent removal |
| `wt_unlock(path)` | Unlock a locked worktree |
| `wt_prune(repo?)` | Clean up stale worktree admin files |
| `wt_merge(path, target?)` | Merge a worktree branch |
| `wt_config_get()` | Get worktree plugin configuration |

### Skills

| Skill | Description | Arguments |
|-------|-------------|-----------|
| `/worktree:setup` | Configure the worktree plugin (base dir, initial repos) | -- |
| `/worktree:add-repo` | Register a base git repository | `[label] [path]` |
| `/worktree:create` | Create a worktree from a registered repo | `[repo-label] [branch]` |
| `/worktree:list` | List all worktrees across registered repos | `[repo-label]` |
| `/worktree:remove` | Remove a worktree by path | `[path]` |
| `/worktree:prune` | Clean up stale worktree metadata | `[repo-label]` |

### Config

Stored in `~/.claude/worktree.yaml`. Created during `/worktree:setup`.

Key fields:
- `worktree_dir` -- Base directory for new worktrees (e.g., `~/worktrees`)
- `repos` -- Map of label to repository path

### Examples

```
# Set up the worktree plugin
/worktree:setup

# Register a repository
/worktree:add-repo my-project ~/projects/my-project

# Create a worktree for a feature branch
/worktree:create my-project feature/new-auth

# List all worktrees
/worktree:list
```

---

## proj

**Version**: 3.0.1 | **Category**: productivity | **License**: MIT

The core plugin. Tracks project metadata, todos with nested dependencies and blocking relationships, timestamped notes, and git activity across multiple repositories. Supports bidirectional Todoist, Trello, and Jira sync. Provides AI-powered workflows (define, decompose, execute).

### Install

```console
/plugin install raulfrk/claude-project-manager:proj
```

### MCP Tools

#### Project Management

| Tool | Description |
|------|-------------|
| `proj_init(name, path, ...)` | Initialize a new project |
| `proj_get(name)` | Get project details |
| `proj_get_active()` | Get the currently active project |
| `proj_list()` | List all tracked projects |
| `proj_list_full()` | List all projects with full details |
| `proj_update_meta(...)` | Update project metadata |
| `proj_archive(name)` | Archive a project |
| `proj_archive_preflight(name)` | Dry-run archive check |
| `proj_find_archived_by_title(title)` | Search archived projects |
| `proj_purge_archive()` | Purge old archived projects |
| `proj_add_repo(path, label?)` | Add a directory/repo to the active project |
| `proj_remove_repo(label)` | Remove a directory/repo from the active project |
| `proj_migrate_dirs()` | Migrate legacy single-dir to multi-dir format |
| `proj_migrate_ids()` | Migrate legacy todo ID format |

#### Todo Management

| Tool | Description |
|------|-------------|
| `todo_add(title, priority?, parent?)` | Add a new todo |
| `todo_add_child(parent_id, title, ...)` | Add a child todo |
| `todo_batch_add_children(parent_id, children)` | Batch-add child todos |
| `todo_get(id)` | Get a specific todo |
| `todo_list(status?)` | List todos with optional status filter |
| `todo_list_all()` | List all todos across all projects |
| `todo_tree()` | Show todos as a dependency tree |
| `todo_update(id, ...)` | Update a todo |
| `todo_complete(id)` | Mark a todo as done |
| `todo_uncomplete(id)` | Re-open a completed todo |
| `todo_delete(id)` | Delete a todo |
| `todo_block(id, blocked_by)` | Set a blocking dependency |
| `todo_unblock(id, blocked_by)` | Remove a blocking dependency |
| `todo_ready()` | List todos ready for work (unblocked) |
| `todo_check_executable(id)` | Check if a todo can be executed (not manual-tagged) |
| `todo_set_content_flag(id, flag, value)` | Set content flags (has_requirements, has_research) |

#### Content and Context

| Tool | Description |
|------|-------------|
| `content_get_requirements(id)` | Read requirements.md for a todo |
| `content_set_requirements(id, content)` | Write requirements.md for a todo |
| `content_get_research(id)` | Read research.md for a todo |
| `content_set_research(id, content)` | Write research.md for a todo |
| `notes_append(text)` | Append timestamped note |
| `claudemd_read()` | Read the project's CLAUDE.md |
| `claudemd_write(content)` | Write the project's CLAUDE.md |
| `proj_explore_codebase(path?, depth?)` | Explore project codebase structure |
| `proj_search_knowledge(query)` | Search project knowledge base |
| `proj_decision_log(decision, context?)` | Log an architectural decision |
| `proj_get_todo_context(id)` | Get full context for a todo (requirements + research) |

#### Configuration and Session

| Tool | Description |
|------|-------------|
| `config_init(...)` | Initialize plugin configuration |
| `config_load()` | Load current configuration |
| `config_update(key, value)` | Update a configuration key |
| `ctx_detect_project()` | Detect project from current working directory |
| `ctx_session_start()` | Start a session (hook target) |
| `ctx_session_end()` | End a session (hook target) |
| `proj_load_session(name)` | Load a project for the current session |
| `proj_session_context()` | Get current session context |
| `proj_session_digest()` | Get a compact session digest |
| `proj_status_context()` | Get project status with context |

#### Git Integration

| Tool | Description |
|------|-------------|
| `git_detect_work()` | Detect uncommitted work in project repos |
| `git_link_todo(commit, todo_id)` | Link a commit to a todo |
| `git_suggest_todos()` | Suggest todos from recent git activity |
| `tracking_git_flush(message)` | Flush tracking data to git |
| `proj_git_reconcile_todos()` | Reconcile git activity with todos |

#### Permissions

| Tool | Description |
|------|-------------|
| `proj_set_permissions(...)` | Set project permissions |
| `proj_setup_permissions()` | Auto-setup permissions for a project |
| `proj_revoke_all_permissions()` | Revoke all project permissions |
| `proj_perms_sync()` | Sync permissions with sandbox |

#### External Sync

| Tool | Description |
|------|-------------|
| `proj_todoist_full_sync()` | Full bidirectional Todoist sync |
| `proj_trello_full_sync()` | Full bidirectional Trello sync |
| `proj_trello_diff()` | Compute Trello sync diff |
| `proj_trello_apply(operations)` | Apply Trello sync operations |
| `proj_jira_full_sync()` | Full Jira sync |
| `proj_jira_map()` | Compute Jira-to-local mapping |
| `proj_jira_apply(mapping)` | Apply Jira mapping |
| `proj_identify_batches()` | Identify independent todo batches for parallel work |

### Skills

| Skill | Description | Arguments |
|-------|-------------|-----------|
| `/proj:init-plugin` | First-time setup wizard | -- |
| `/proj:init` | Initialize project tracking | `[project-name]` |
| `/proj:quick` | Create project and launch full workflow | `[project-name]` |
| `/proj:status` | Show project status, todos, git activity | -- |
| `/proj:todo` | Manage todos (add/done/list/tree/block/delete) | `[operation] [args]` |
| `/proj:define` | Gather requirements via iterative Q&A | `<todo-id>` |
| `/proj:refine` | Stress-test requirements with 3 review agents | `<todo-id>` |
| `/proj:decompose` | Break todo into sub-todos with dependencies | `<todo-id>` |
| `/proj:execute` | Execute a todo (implement changes) | `<todo-id>` |
| `/proj:run` | Full workflow: define, decompose, execute | `<id \| range>` `[--steps]` `[--from]` `[--iter N]` |
| `/proj:run-batch` | Batch/range execution workflow for multiple todos | `<id-range\|comma-list>` `[--steps]` `[--fast\|--careful]` `[--trust N]` |
| `/proj:save` | Save session notes and reconcile git | -- |
| `/proj:load` | Load project for session (cross-directory) | `[project-name]` |
| `/proj:switch` | Switch active project context | `[project-name]` |
| `/proj:archive` | Archive a completed project | `[project-name]` |
| `/proj:purge` | Purge old archived projects | -- |
| `/proj:list-proj` | List all tracked projects | -- |
| `/proj:explore` | Walk through codebase in guided chapters | `[todo-id \| path \| description]` |
| `/proj:migrate` | Migrate legacy project formats | -- |
| `/proj:add-repo` | Add directory/repo to active project | `<path> [--label] [--claudemd]` |
| `/proj:remove-repo` | Remove directory/repo by label | `<label>` |
| `/proj:team-status` | Show active teams and agent status | -- |
| `/proj:todoist-sync` | Full bidirectional Todoist sync | -- |
| `/proj:trello-sync` | Full bidirectional Trello sync | -- |
| `/proj:jira-sync` | Pull Jira issues and sync to local | -- |
| `/proj:jira-sync-trello` | Jira pull then Trello push | -- |
| `/proj:sandbox` | Unified sandbox management | `[--setup] [--debug] [--apply]` |
| `/proj:sandbox-setup` | Initialize sandbox and grant permissions | -- |
| `/proj:sandbox-sync` | Check sandbox settings match expected config | -- |
| `/proj:sandbox-audit` | Audit current permissions | -- |
| `/proj:sandbox-debug` | Debug permission issues | -- |
| `/router:add` | Register a new hook | -- |
| `/router:list` | List all registered hooks | -- |
| `/router:remove` | Remove a hook by ID | -- |
| `/router:test` | Test-fire a hook by ID | -- |
| `/router:recover` | Recover from hook failures | -- |
| `/router:debug` | Debug hook execution failures | -- |

### Sub-skills (not user-invocable)

These skills are invoked by parent skills, not directly by users:

| Skill | Parent | Description |
|-------|--------|-------------|
| `/proj:trello-setup` | trello-sync | Ensure Trello board, label, and project card exist |
| `/proj:jira-map` | jira-sync | Compute Jira-to-local mapping |
| `/proj:jira-apply` | jira-sync | Apply Jira mapping |
| `/proj:refine` | run | Stress-test requirements |

### Config

Stored in `~/.claude/proj.yaml`. Created during `/proj:init-plugin`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tracking_dir` | string | `~/projects/tracking` | Root directory for project tracking data |
| `projects_base_dir` | string | -- | Base directory for new projects |
| `git_integration` | boolean | `true` | Enable git activity detection |
| `default_priority` | string | `medium` | Default todo priority (`low`/`medium`/`high`) |
| `permissions.auto_grant` | boolean | `true` | Auto-grant sandbox paths for project dirs |
| `permissions.auto_allow_mcps` | boolean | `true` | Auto-allow plugin MCP tools |
| `sandbox_integration` | boolean | `false` | Whether sandbox plugin is installed |
| `worktree_integration` | boolean | `false` | Whether worktree plugin is installed |
| `claudemd_management` | boolean | `false` | Enable CLAUDE.md write guard |
| `sync.todoist.enabled` | boolean | `false` | Enable Todoist sync |
| `sync.todoist.auto_sync` | boolean | `true` | Auto-sync on every proj command |
| `sync.todoist.mcp_server` | string | `claude_ai_Todoist` | MCP server name |
| `sync.todoist.root_only` | boolean | `false` | Sync only root-level todos |
| `sync.trello.enabled` | boolean | `false` | Enable Trello sync |
| `sync.trello.mcp_server` | string | `trello` | MCP server name |
| `sync.trello.default_board_id` | string | -- | Trello board ID |
| `sync.trello.on_delete` | string | `archive` | Card handling on todo delete |

### Examples

```
# First-time setup
/proj:init-plugin

# Create and track a new project
/proj:init my-app

# Add a todo and run the full workflow
/proj:todo add Build authentication system
/proj:run 1

# Sync with Todoist
/proj:todoist-sync
```

---

## router

**Version**: 1.10.1 | **Category**: utilities | **License**: MIT

Central MCP-to-MCP router (formerly `hooks`). Manages hook registrations, fires hooks when trigger tools execute, evaluates conditions against `~/.claude/proj.yaml`, and provides recovery for failed hooks.

### Install

```console
/plugin install raulfrk/claude-project-manager:router
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `router_fire_tool(trigger_tool, source_result, depth)` | Fire hooks for a trigger tool (called by dispatch, not directly) |
| `router_register_tool(hook_id, trigger_tool, target_tool, server, ...)` | Register a new hook |
| `router_unregister_tool(hook_id)` | Remove a hook registration |
| `router_list_tool(trigger_tool?)` | List hooks, optionally filtered by trigger |
| `router_sync_tool()` | Sync hook registry with default-hooks.yaml files |
| `router_recover_tool(hook_id?)` | Recover from hook failures |
| `router_verify_tool(hook_id)` | Verify a hook is correctly configured |
| `router_invocations_tool(hook_id?, limit?)` | View recent hook invocations and failures |

### Skills

| Skill | Description |
|-------|-------------|
| `/router:map` | Generate interactive HTML visualization of the hook network |
| `/router:add` | Register a new hook |
| `/router:list` | List all registered hooks |
| `/router:remove` | Remove a hook by ID |
| `/router:test` | Test-fire a hook by ID |
| `/router:recover` | Recover from hook failures |
| `/router:debug` | Debug hook execution failures |
| `/router:activity` | View recent hook invocation activity |

### Config

Hook registry stored in `hooks.yaml` (auto-discovered). Default hooks defined in each plugin's `default-hooks.yaml`.

Settings:
- `settings.max_depth` -- Maximum hook cascade depth (default: 3)
- Per-hook: `blocking`, `verification`, `condition`, `param_mapping`

### Examples

```
# List all registered hooks
/router:list

# Test-fire a specific hook
/router:test hook-123

# View the hook network as a graph
/router:map
```

---

## todoist

**Version**: 1.4.5 | **Category**: integrations | **License**: MIT

Local Todoist MCP server providing task and project management via the Todoist REST API. Replaces the external Todoist MCP server with a local implementation that integrates with the hook system.

### Install

```console
/plugin install raulfrk/claude-project-manager:todoist
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `todoist_init(api_token)` | Initialize with Todoist API token |
| `todoist_add_tasks(tasks)` | Create one or more tasks |
| `todoist_update_tasks(tasks)` | Update existing tasks |
| `todoist_complete_tasks(task_ids)` | Complete tasks |
| `todoist_uncomplete_tasks(task_ids)` | Re-open completed tasks |
| `todoist_delete(task_ids)` | Delete tasks |
| `todoist_find_tasks(project_id?, filter?)` | Search for tasks |
| `todoist_add_projects(projects)` | Create projects |
| `todoist_find_projects(name?)` | Search for projects |
| `todoist_verify_complete(...)` | Verification hook: confirm completion |

### Skills

None. Todoist sync is managed through `/proj:todoist-sync`.

### Config

Requires Todoist API token, configured via `todoist_init`. Integration enabled in `~/.claude/proj.yaml`:

```yaml
sync:
  todoist:
    enabled: true
    auto_sync: true
```

---

## trello

**Version**: 2.4.3 | **Category**: integrations | **License**: MIT

Full Trello board, card, and list management via REST API. Supports boards, lists, cards, labels, members, comments, checklists, and attachments.

### Install

```console
/plugin install raulfrk/claude-project-manager:trello
```

### MCP Tools

#### Boards

| Tool | Description |
|------|-------------|
| `list_boards()` | List all accessible boards |
| `get_board(board_id)` | Get board details |
| `get_board_members(board_id)` | Get board members |
| `update_board(board_id, ...)` | Update board properties |

#### Lists

| Tool | Description |
|------|-------------|
| `get_lists(board_id)` | Get all lists on a board |
| `get_list(list_id)` | Get list details |
| `create_list(board_id, name)` | Create a new list |
| `update_list(list_id, ...)` | Update list properties |

#### Cards

| Tool | Description |
|------|-------------|
| `get_card(card_id)` | Get card details |
| `get_cards_by_list_id(list_id)` | Get all cards in a list |
| `add_card_to_list(list_id, name, ...)` | Create a card in a list |
| `batch_create_cards(cards)` | Batch-create cards |
| `update_card_details(card_id, ...)` | Update card properties |
| `move_card(card_id, list_id)` | Move card to a different list |
| `archive_card(card_id)` | Archive a card |
| `delete_card(card_id)` | Delete a card |
| `add_card_member(card_id, member_id)` | Add member to card |
| `remove_card_member(card_id, member_id)` | Remove member from card |
| `toggle_card_label(card_id, label_id)` | Toggle a label on a card |

#### Checklists

| Tool | Description |
|------|-------------|
| `get_card_checklists(card_id)` | Get card checklists |
| `create_checklist(card_id, name)` | Create a checklist on a card |
| `rename_checklist(checklist_id, name)` | Rename a checklist |
| `delete_checklist(checklist_id)` | Delete a checklist |
| `add_checklist_item(checklist_id, name)` | Add item to checklist |
| `batch_add_checklist_items(checklist_id, items)` | Batch-add checklist items |
| `update_checklist_item(card_id, item_id, ...)` | Update a checklist item |
| `batch_update_checklist_items(card_id, items)` | Batch-update checklist items |
| `rename_checklist_item(card_id, item_id, name)` | Rename a checklist item |
| `delete_checklist_item(checklist_id, item_id)` | Delete a checklist item |

#### Labels, Comments, Attachments

| Tool | Description |
|------|-------------|
| `get_labels(board_id)` | Get board labels |
| `create_label(board_id, name, color)` | Create a label |
| `update_label(label_id, ...)` | Update a label |
| `delete_label(label_id)` | Delete a label |
| `get_card_comments(card_id)` | Get card comments |
| `add_comment(card_id, text)` | Add a comment |
| `update_comment(card_id, comment_id, text)` | Update a comment |
| `delete_comment(card_id, comment_id)` | Delete a comment |
| `get_card_attachments(card_id)` | Get card attachments |
| `add_attachment(card_id, url, name?)` | Add an attachment |
| `delete_attachment(card_id, attachment_id)` | Delete an attachment |

#### Hook Targets

| Tool | Description |
|------|-------------|
| `trello_init(api_key, token)` | Initialize with Trello credentials |
| `trello_add_card_hook(...)` | Hook target: create card |
| `trello_add_checklist_item_hook(...)` | Hook target: add checklist item |
| `trello_batch_add_checklist_items_hook(...)` | Hook target: batch add items |
| `trello_verify_checklist_item(...)` | Verification hook: confirm item state |

### Skills

None. Trello sync is managed through `/proj:trello-sync`.

### Config

Requires Trello API key and token, configured via `trello_init`. Integration enabled in `~/.claude/proj.yaml`:

```yaml
sync:
  trello:
    enabled: true
    default_board_id: "abc123"
    on_delete: archive
```

---

## jira

**Version**: 2.1.4 | **Category**: integrations | **License**: MIT

Read-only Jira Server issue and project access via REST API. Supports issues, projects, epics, sprints, comments, labels, attachments, worklogs, and bulk operations.

### Install

```console
/plugin install raulfrk/claude-project-manager:jira
```

### MCP Tools

#### Core

| Tool | Description |
|------|-------------|
| `jira_init(base_url, email, api_token)` | Initialize with Jira credentials |
| `jira_search(jql, fields?, max_results?)` | Search issues with JQL |
| `jira_get_issue(issue_key)` | Get issue details |
| `jira_get_issue_comments(issue_key)` | Get issue comments |
| `jira_create_issue(project, summary, ...)` | Create an issue |
| `jira_bulk_create_issues(issues)` | Batch-create issues |
| `jira_update_issues(issues)` | Batch-update issues |

#### Projects and Epics

| Tool | Description |
|------|-------------|
| `jira_list_projects()` | List all accessible projects |
| `jira_get_project(project_key)` | Get project details |
| `jira_get_epic_issues(epic_key)` | Get all issues in an epic |
| `jira_get_user_issues(username?)` | Get issues assigned to a user |

### Skills

None. Jira sync is managed through `/proj:jira-sync`.

### Config

Requires Jira base URL, email, and API token, configured via `jira_init`. Integration enabled in `~/.claude/proj.yaml`.

---

## zoxide

**Version**: 1.3.1 | **Category**: utilities | **License**: MIT

Zoxide frecency database integration for fast directory jumping in Claude Code workflows. Boost, remove, and query paths using zoxide's frecency algorithm.

### Install

```console
/plugin install raulfrk/claude-project-manager:zoxide
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `zoxide_query(query)` | Query zoxide for matching paths |
| `zoxide_boost(path)` | Boost a path's frecency score |
| `zoxide_remove(path)` | Remove a path from the zoxide database |

### Skills

None.

### Config

Requires zoxide to be installed on the system. Integration flag in `~/.claude/proj.yaml`:

```yaml
zoxide_integration: true
```

---

## analyse

**Version**: 1.0.0 | **Category**: utilities | **License**: MIT

Guided code review skill that walks users through features or code sections in structured chapters, explains the logic, and creates improvement todos. This is a skills-only plugin with no MCP server.

### Install

```console
/plugin install raulfrk/claude-project-manager:analyse
```

### MCP Tools

None. This is a skills-only plugin.

### Skills

| Skill | Description | Arguments |
|-------|-------------|-----------|
| `/review:review` | Walk through code in guided chapters and create todos | `[todo-id \| path \| description]` |

### Config

No plugin-specific configuration.

### Examples

```
# Review a specific code path
/review:review src/auth/

# Review a feature related to a todo
/review:review 42

# Free-form review
/review:review the hook dispatch flow
```

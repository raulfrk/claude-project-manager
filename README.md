# claude-project-manager

Project management plugins for Claude Code -- track todos, manage permissions, and orchestrate workflows from inside your conversations.

<!-- AUTO:badges-start -->
[![version](https://img.shields.io/badge/version-4.0.0-blue?style=flat-square)](CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-752%20passing-brightgreen?style=flat-square)](#contributing)
[![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
<!-- AUTO:badges-end -->

---

## Quick Start

```console
# Install the core plugins
/plugin install raulfrk/claude-project-manager:proj
/plugin install raulfrk/claude-project-manager:sandbox
/plugin install raulfrk/claude-project-manager:hooks

# First-time setup (creates ~/.claude/proj.yaml)
/proj:init-plugin

# Start tracking a project
/proj:init

# Add your first todo and check status
/proj:todo add Build something awesome
/proj:status
```

Install additional plugins as needed: `worktree`, `trello`, `jira`, `todoist`, `zoxide`, `analyse`.

The installer wizard now prompts for an advanced tier after the basic questions — press Enter (Rich path) or toggle the Advanced button (Textual path) to drill into team_mode, smart_gate, context_injection, archive, and other fine-grained settings. Leave the toggle off to accept all defaults on fresh installs.

---

## Plugins

<!-- AUTO:plugins-start -->
| Plugin | Version | Category | Description |
|--------|---------|----------|-------------|
| [sandbox](plugins/sandbox/) | 0.2.0 | utilities | Manage Claude Code sandbox-mode settings.json -- write paths, MCP allow rules, network domains, deny rules |
| [worktree](plugins/worktree/) | 2.6.0 | utilities | Git worktree management -- create, list, and remove worktrees from configured base repositories |
| [proj](plugins/proj/) | 3.0.1 | productivity | Project lifecycle management: init, explore, status, update, todo, report, archive |
| [trello](plugins/trello/) | 2.4.3 | integrations | Trello board, card, and list management via REST API |
| [jira](plugins/jira/) | 2.1.4 | integrations | Read-only Jira Server issue and project access via REST API |
| [hooks](plugins/hooks/) | 1.10.1 | utilities | Central MCP-to-MCP hook registry with schema-based param mapping, auto-registration, and recovery |
| [zoxide](plugins/zoxide/) | 1.3.1 | utilities | Zoxide frecency database integration -- boost, remove, and query paths |
| [todoist](plugins/todoist/) | 1.4.5 | integrations | Todoist task and project management via REST API |
| [analyse](plugins/analyse/) | 1.0.0 | utilities | Guided code review that walks through features, explains code, and creates todos |
<!-- AUTO:plugins-end -->

---

## Usage

**Project setup and daily workflow:**

```
/proj:init              # Initialize tracking for this directory
/proj:status            # Show open todos, git activity, project health
/proj:todo add <text>   # Add a todo
/proj:todo done <id>    # Mark a todo complete
/proj:save              # Save session notes and reconcile git
```

**AI-powered deep work:**

```
/proj:define <id>       # Gather requirements via iterative Q&A
/proj:decompose <id>    # Break a todo into sub-todos with dependencies
/proj:execute <id>      # Implement a todo (reads requirements, spawns agents)
/proj:run <id>          # Full workflow: define -> decompose -> execute
/proj:explore           # Walk through codebase in guided chapters
```

**Sync and integrations:**

```
/proj:todoist-sync      # Bidirectional Todoist sync
/proj:trello-sync       # Bidirectional Trello sync
/proj:jira-sync         # Pull Jira issues to local projects
/proj:sandbox           # Manage sandbox permissions (setup, sync, audit)
```

---

## Architecture

The marketplace contains nine plugins that work independently or together. Three form the core (`proj`, `sandbox`, `hooks`) while the rest add optional capabilities.

**proj** is the main plugin. It provides an MCP server for todo management, notes, and git tracking, plus 25+ skills for the full project lifecycle. Todos use dot-notation IDs (`1`, `1.1`, `1.1.1`) with blocking relationships. The `run` skill chains define, decompose, and execute steps with parallel agent execution.

**sandbox** is the single source of truth for Claude Code's `settings.json`. All permission changes (write paths, MCP allow rules, network domains) go through sandbox's MCP tools. Both `proj` and `worktree` delegate permission management to sandbox.

**hooks** provides an MCP-to-MCP hook registry. When a tool fires on one plugin, hooks can trigger tools on other plugins based on conditions evaluated against `~/.claude/proj.yaml`. This enables automatic Todoist sync on todo completion, permission grants on project init, and similar cross-plugin workflows.

**Transport** between plugins uses Unix domain sockets at `/tmp/claude-hooks-{plugin}.sock`. Hook dispatch is injected via `enable_hook_dispatch()` in each plugin's `main.py`, which monkey-patches `mcp.tool()` to add post-execution wrappers.

For the full architecture with diagrams and interaction flows, see [docs/architecture.md](docs/architecture.md).

---

## Documentation

| Document | Contents |
|----------|----------|
| [Architecture](docs/architecture.md) | System design, plugin interaction, hook dispatch flow |
| [Plugins](docs/plugins.md) | Detailed plugin reference -- tools, skills, configuration |
| [Development](docs/development.md) | Dev setup, testing, quality tools, contribution guide |
| [Changelog](CHANGELOG.md) | Version history and release notes |

---

## License

MIT

# claude-project-manager

Project management plugins for Claude Code -- track todos, manage permissions, and orchestrate workflows from inside your conversations.

<!-- AUTO:badges-start -->
[![version](https://img.shields.io/badge/version-5.1.6-blue?style=flat-square)](CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-752%20passing-brightgreen?style=flat-square)](#contributing)
[![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
<!-- AUTO:badges-end -->

---

## Quick Start

```console
# Install the core plugins
/plugin install raulfrk/claude-project-manager:proj
/plugin install raulfrk/claude-project-manager:sandbox
/plugin install raulfrk/claude-project-manager:router

# First-time setup (creates ~/.claude/proj.yaml)
/proj:init-plugin

# Start tracking a project
/proj:init

# Add your first todo and check status
/proj:todo add Build something awesome
/proj:status
```

Install additional plugins as needed: `worktree`, `trello`, `jira`, `todoist`, `confluence`.

### Installer Wizard (recommended)

Run the TUI installer directly from the repo with `uv`:

```console
# Install and run (one command)
uvx --from git+https://github.com/raulfrk/claude-project-manager cpm-install

# Or clone first, then run locally
git clone https://github.com/raulfrk/claude-project-manager.git
cd claude-project-manager
uv run cpm-install
```

The wizard handles plugin installation, first-time config (`~/.claude/proj.yaml`), integration setup (Todoist/Trello/Jira), and advanced settings (smart-gate, context-injection, archive, etc.).

---

## Plugins

<!-- AUTO:plugins-table-start -->
| Plugin | Version | Category | Description |
|--------|---------|----------|-------------|
| [worktree](plugins/worktree/) | 5.0.1 | utilities | Git worktree management — create, list, and remove worktrees from configured base repositories |
| [proj](plugins/proj/) | 5.1.6 | productivity | Project lifecycle management: init, explore, status, update, todo, report, archive |
| [trello](plugins/trello/) | 5.0.0 | integrations | Trello board, card, and list management via REST API — full CRUD for boards, lists, cards, labels, members, comments, checklists, attachments |
| [confluence](plugins/confluence/) | 1.0.0 | integrations | Read-only Confluence Cloud + Server/Data Center access via REST API. |
| [wiki](plugins/wiki/) | 0.1.4 | productivity | Karpathy-style LLM wiki: persistent markdown knowledge base with entity pages, cross-refs, + append-only log |
| [jira](plugins/jira/) | 5.1.0 | integrations | Read-only Jira Server issue and project access via REST API. |
| [router](plugins/router/) | 5.0.0 | utilities | MCP-to-MCP dispatch registry for cpm plugins. Chain tool execution across plugins via post-execution hooks on a shared socket registry. Not to be confused with Claude Code's native hooks feature in settings.json. |
| [todoist](plugins/todoist/) | 5.0.0 | integrations | Todoist task and project management via REST API — create, complete, update, find, and delete tasks and projects |
<!-- AUTO:plugins-table-end -->

---

## Usage

**Project setup and daily workflow:**

```
/proj:init              # Initialize tracking for this directory
/proj:status            # Show open todos, git activity, project health
/proj:todo add <text>   # Add a todo
/proj:todo done <id>    # Mark a todo complete
/proj:checkpoint        # Mid-execution review: continue, reset, or tighten scope
/proj:save              # Save session notes and reconcile git
/proj:parallel-batch-execute  # Orchestrate >=2 disjoint todos in parallel w/ full superpowers gate fidelity
```

**AI-powered deep work:**

```
/proj:explore           # Walk through codebase in guided chapters
```

**Sync and integrations:**

```
/proj:todoist-sync      # Bidirectional Todoist sync
/proj:trello-sync       # Bidirectional Trello sync
/proj:jira-sync         # Pull Jira issues to local projects
/proj:sandbox           # Manage sandbox permissions (setup, sync, audit)
```

**Confluence:**

```
/confluence:search      # Search Confluence content via CQL or text
/confluence:page        # Fetch Confluence page as markdown
/confluence:spaces      # List Confluence spaces
/confluence:pages       # List pages in a Confluence space
/confluence:tree        # Fetch descendant page tree
/confluence:metadata    # Attachments + comments for a page
```

---

## Architecture

The marketplace contains nine plugins that work independently or together. Three form the core (`proj`, `sandbox`, `router`) while the rest add optional capabilities.

**proj** is the main plugin. It provides an MCP server for todo management, notes, and git tracking, plus 25+ skills for the full project lifecycle. Todos use dot-notation IDs (`1`, `1.1`, `1.1.1`) with blocking relationships.

**sandbox** is the single source of truth for Claude Code's `settings.json`. All permission changes (write paths, MCP allow rules, network domains) go through sandbox's MCP tools. Both `proj` and `worktree` delegate permission management to sandbox.

**router** provides an MCP-to-MCP router (formerly `hooks`). When a tool fires on one plugin, the router can trigger tools on other plugins based on conditions evaluated against `~/.claude/proj.yaml`. This enables automatic Todoist sync on todo completion, permission grants on project init, and similar cross-plugin workflows.

**Transport** between plugins uses Unix domain sockets at `/tmp/claude-cpm-{plugin}-{pid}.sock`. Hook dispatch is injected via `enable_hook_dispatch()` in each plugin's `main.py`, which monkey-patches `mcp.tool()` to add post-execution wrappers.

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

## Karpathy alignment

The managed CLAUDE.md block adopts Andrej Karpathy's late-2025 LLM-coding-pitfalls observations as 4 of its rules (Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution), via the [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) distillation (MIT-licensed).

Original Karpathy tweet: https://x.com/karpathy/status/2015883857489522876

These rules are layered with cpm-specific operationalizations:
- Append-only log convention (chronological project history grep-able via `## [YYYY-MM-DD HH:MM] op | title` headings)
- Reset-over-recover discipline (prefer `wt_remove` + new `wt_create` with tightened scope over patching agent drift)
- Reproduce-before-fix for bug-work
- Mid-execution checkpoint rhythm (`/proj:checkpoint`)
- Principled-across-config-scales constraint

See `~/.claude/CLAUDE.md` for the full block (auto-installed by the cpm installer; refresh via `/proj:claudemd-refresh`).

---

## Local development

Install `just` (`brew install just` on macOS, `cargo install just` elsewhere)
and `uv` (https://docs.astral.sh/uv/). Then, from the repo root:

```bash
just sync   # uv sync --all-groups in installer + every plugin server
just test   # pytest in the same set; does not fail-fast
just ci     # sync + test
```

Per-plugin justfiles remain under `plugins/<name>/server/justfile` for
single-plugin workflows (`just check`, `just test-cov`, etc.).

---

## License

MIT

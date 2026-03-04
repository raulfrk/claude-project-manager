# worktree

Git worktree management for Claude Code. Create, list, lock, and remove git
worktrees from a registry of configured base repositories.

## What it does

The `worktree` plugin exposes an MCP server that wraps `git worktree`
operations behind a simple registry model. You register one or more base
repositories by label, then create isolated worktrees from them without
needing to remember paths or branch flags.

## Installation

Install from the Claude Code plugin marketplace:

```
/plugins install worktree
```

After installation the MCP server is registered automatically via `.mcp.json`.
No additional setup is required — the config file is created on first use.

## Configuration

Config is stored at `~/.claude/worktree.yaml` (overridable via the
`WORKTREE_CONFIG` environment variable).

```yaml
version: 1
default_worktree_dir: ~/worktrees   # base directory for auto-generated paths
base_repos:
  - label: myapp
    path: /home/user/projects/myapp
    default_branch: main
```

All writes are atomic (write to a temp file, then rename) so the config is
never left in a partial state.

**Fields:**

| Field | Default | Description |
|---|---|---|
| `default_worktree_dir` | `~/worktrees` | Parent directory used when no custom path is given to `wt_create` |
| `base_repos` | `[]` | List of registered repositories |

Each entry in `base_repos` has:

| Field | Default | Description |
|---|---|---|
| `label` | — | Short unique identifier used in all tool calls |
| `path` | — | Absolute path to the bare/normal git repository |
| `default_branch` | `main` | Informational; not currently used by `wt_create` |

## MCP Tools

All tools are prefixed `wt_` and available as `mcp__plugin_worktree_worktree__<tool>`.

### Repository registry

| Tool | Parameters | Description |
|---|---|---|
| `wt_add_repo` | `label`, `path`, `default_branch="main"` | Register a git repository under a short label |
| `wt_remove_repo` | `label` | Unregister a repository by label |
| `wt_list_repos` | — | List all registered repositories |

### Worktree operations

| Tool | Parameters | Description |
|---|---|---|
| `wt_create` | `repo_label`, `branch`, `path=None`, `new_branch=True` | Create a worktree from a registered repo |
| `wt_list` | `repo_label=None` | List worktrees for one or all repos |
| `wt_get` | `path` | Get full details for a specific worktree by path (returns JSON) |
| `wt_remove` | `path`, `force=False` | Remove a worktree; use `force=True` for unclean worktrees |
| `wt_prune` | `repo_label=None` | Prune stale worktree admin files for one or all repos |
| `wt_lock` | `path`, `reason=""` | Lock a worktree to prevent pruning or deletion |
| `wt_unlock` | `path` | Unlock a previously locked worktree |

### wt_create path resolution

When `path` is omitted, the worktree is created at:

```
<default_worktree_dir>/<repo_label>/<branch>
```

Forward slashes in branch names are replaced with hyphens, so
`feature/my-thing` becomes `feature-my-thing`.

When `new_branch=True` (the default), a new branch is created. Set
`new_branch=False` to check out an existing remote branch.

## Common workflow

```
# 1. Register a repository
wt_add_repo(label="myapp", path="/home/user/projects/myapp")

# 2. Create a worktree for a new feature branch
wt_create(repo_label="myapp", branch="feature/my-thing")
# -> Created worktree at ~/worktrees/myapp/feature-my-thing (branch: feature/my-thing, repo: myapp)

# 3. List all worktrees for this repo
wt_list(repo_label="myapp")

# 4. Inspect a specific worktree
wt_get(path="~/worktrees/myapp/feature-my-thing")

# 5. Lock it while long-running work is in progress
wt_lock(path="~/worktrees/myapp/feature-my-thing", reason="active CI run")

# 6. Unlock and remove when done
wt_unlock(path="~/worktrees/myapp/feature-my-thing")
wt_remove(path="~/worktrees/myapp/feature-my-thing")

# 7. Clean up any leftover git admin files
wt_prune(repo_label="myapp")
```

## Technical notes

- **Atomic config writes** — config updates use `tempfile.mkstemp` + `Path.replace` so a crash during a write never corrupts the YAML file.
- **Path resolution** — all paths passed to tools are resolved to absolute form via `Path.expanduser().resolve()` before being used, so `~` and relative paths are accepted everywhere.
- **Repo discovery** — `wt_remove`, `wt_get`, `wt_lock`, and `wt_unlock` scan all registered repos to find the owning repo for a given worktree path; you do not need to specify which repo a worktree belongs to.
- **Error handling** — git errors are caught and returned as human-readable strings rather than raising exceptions; Claude can act on the message directly.
- **Python 3.12+**, dependencies: `mcp>=1.2.0`, `pyyaml>=6.0`.

# Changelog — worktree

## [0.7.0] — 2026-02-28
### Added
- Skills: `add-repo`, `create`, `list`, `prune`, `remove`, `setup` for interactive worktree management via `/worktree:<name>`

## [0.6.0] — 2026-02-26
### Added
- No worktree-specific changes; version bumped in sync with marketplace-wide MCP auto-allow work

## [0.5.0] — 2026-02-26
### Fixed
- Source package moved to `server/server/` subdirectory, resolving `ModuleNotFoundError` at runtime

## [0.4.0] — 2026-02-26
### Fixed
- Removed explicit `"hooks"` key from `plugin.json` (duplicate auto-discovery fix shared with all plugins)

## [0.3.0] — 2026-02-26
### Fixed
- Corrected `hooks.json` schema (two-level nesting)

## [0.2.0] — 2026-02-26
### Added
- Initial full implementation: MCP server with two tool modules
  - Repo registry tools (`wt_add_repo`, `wt_remove_repo`, `wt_list_repos`): register/unregister base git repositories stored in `~/.claude/worktree.yaml`
  - Worktree CRUD tools (`wt_create`, `wt_list`, `wt_get`, `wt_remove`, `wt_prune`, `wt_lock`, `wt_unlock`): create worktrees under a configurable default directory, list with lock/prunable status, force-remove, prune stale admin files
- Worktrees created at `<default_worktree_dir>/<repo_label>/<branch>` by default; custom path supported
- Lock/unlock to prevent accidental pruning

## [0.1.0] — 2026-02-26
### Added
- Initial skeleton — marketplace manifest and plugin scaffold

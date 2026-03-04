# Changelog — perms

## [0.7.0] — 2026-02-28
### Added
- `perms_batch_add_mcp_allow` tool: add wildcard allow rules for multiple MCP servers in a single atomic `settings.json` write (idempotent)

## [0.6.0] — 2026-02-26
### Added
- `perms_add_mcp_allow` tool: add `mcp__<server>__*` wildcard allow rule to `settings.json`
- `perms_remove_mcp_allow` tool: remove a previously added MCP server wildcard rule
- 10 new tests covering MCP allow rules

## [0.5.0] — 2026-02-26
### Fixed
- Source package moved to `server/server/` subdirectory, resolving `ModuleNotFoundError: No module named 'server'` at runtime
- Added 4 regression tests (`test_server_structure.py`) to guard against this

## [0.4.0] — 2026-02-26
### Fixed
- Removed explicit `"hooks"` key from `plugin.json`; Claude Code auto-discovers `hooks/hooks.json` and the duplicate caused a startup error

## [0.3.0] — 2026-02-26
### Fixed
- Corrected `hooks.json` schema to use the required two-level nesting (matcher group → hooks array)

## [0.2.0] — 2026-02-26
### Added
- Initial full implementation: MCP server with four tools
  - `perms_add_allow`: add `Read` and `Edit` allow rules for a directory path
  - `perms_remove_allow`: remove those rules
  - `perms_list`: list all current allow rules from `settings.json`
  - `perms_check`: check whether a path already has allow rules
- Atomic write via temp-file replace; double-slash absolute path prefix applied automatically
- User-scope and project-scope support

## [0.1.0] — 2026-02-26
### Added
- Initial skeleton — marketplace manifest and plugin scaffold

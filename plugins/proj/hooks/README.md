# proj hooks

This directory contains `hooks.json`, which is auto-discovered by the Claude Code
plugin system. No explicit reference to this file is needed in `plugin.json`.

## Hooks

### SessionStart

Runs `server.cli session-start` at the beginning of every Claude Code session.
Prints project context (active project name, open todos, recent notes) to stdout,
which Claude Code injects into the session as context.

**Two-layer activation:**

1. **MCP server startup** — when the MCP server process starts, it reads
   `$CLAUDE_PROJECT_DIR` and calls `ctx_detect_project_name()` to pre-populate
   the in-memory active project before any tool is called. This means
   `proj_get_active` works immediately without any manual `/proj:load`.

2. **Hook output fallback** — the hook also prints an explicit
   `proj_load_session("name")` instruction to stdout. Claude acts on this as a
   fallback, reinforcing activation on session resume or in edge cases where
   the env var wasn't set at server startup time.

Each Claude session is a separate MCP server process, so parallel sessions on
different projects activate independently without conflict.

### SessionEnd

Runs `server.cli session-end` asynchronously when a session ends.
Bumps the `last_updated` timestamp on the active project. No output is produced.

### PreCompact

Runs `server.cli session-start --compact` before Claude Code compacts the context
window. Re-injects a condensed project summary so the active project is not lost
after compaction.

## Environment Variables

Both `$CLAUDE_PLUGIN_ROOT` and `$CLAUDE_PROJECT_DIR` must be set for the hooks to
work. Claude Code sets these automatically when a plugin is installed.

| Variable | Set by | Description |
|---|---|---|
| `CLAUDE_PLUGIN_ROOT` | Claude Code (plugin install) | Absolute path to the installed plugin directory. Used to locate `server/` for `uv run`. |
| `CLAUDE_PROJECT_DIR` | Claude Code (session start) | The working directory of the current Claude Code session. Used to auto-detect the active project. |

## Failure behaviour

- If `CLAUDE_PLUGIN_ROOT` is not set, the `uv` command cannot locate the server
  package and the hook exits with an error. Claude Code logs hook errors to stderr
  but does not abort the session.
- If `CLAUDE_PROJECT_DIR` is not set, the `--cwd` argument receives an empty
  string. The CLI handles this gracefully: auto-detection is skipped, and the hook
  exits silently with no output.
- If the plugin has not been initialised (`/proj:init-plugin` not yet run), the CLI
  detects that no config file exists and exits silently with no output or error.

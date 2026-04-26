# Wizard Sandbox Reconcile During Install

**Date**: 2026-04-25
**Status**: design
**Owner**: claude-project-manager
**Tracking todo**: 752

## Problem

The installer wizard collects `sandbox_integration: true/false` (`installer/wizard_specs.py:172`)
and writes it to `~/.claude/proj.yaml`, but never populates `~/.claude/settings.json` with the
MCP allow rules each plugin needs. Sandbox setup is deferred to a manual `/proj:init-plugin`
skill the user must invoke post-install. Two consequences:

1. **No automated population during install** — first-time users get a plugin marketplace
   that runs but lacks the `mcp__plugin_*__*` allow rules, prompting permission dialogs on
   every tool use.
2. **No reconcile mechanism** — when plugins fold (e.g. `sandbox` → `proj/sandbox`) or
   rename, stale entries linger in `settings.json` forever.

Concrete state on this host: `settings.json` has stale entries (`perms`, `sandbox`,
`hooks`, `zoxide` — all gone/folded/renamed) and missing entries (`router`, `confluence`,
`wiki`). 5 of 9 `mcp__plugin_*` entries wrong.

The pure reconcile logic already exists at `plugins/proj/server/server/tools/sandbox.py:321`
(`sandbox_reconcile`) — it auto-infers stale entries (any `mcp__*__*` rule not in expected)
and adds missing ones. The gap is wiring: the installer can't reach that logic without
either spawning the proj MCP server (path A — heavy + brittle) or duplicating the logic
(path B — drift risk + violates "proj is single source of truth for settings.json").

## Approach

Three changes:

1. **Factor sandbox lib to `_shared`** — move the pure-Python sandbox library out of
   `plugins/proj/server/server/lib/sandbox/` into `plugins/_shared/sandbox/`, alongside
   existing cross-plugin shared code (`claudemd`, `session_key`, `hook_dispatch`). The
   reconcile primitive becomes `from sandbox import reconcile_settings`. Proj's MCP tool
   stays as a thin wrapper. ONE implementation; "proj is single source of truth" preserved
   (proj plugin authoring `_shared/sandbox/` doesn't change which subsystem owns
   `settings.json`).

2. **Wire reconcile into install flow** — new `_finalize_sandbox(args, selected_plugins, console)`
   step in both `installer/flow/installer_flow.py` (TUI default) and `installer/main.py`
   (`--no-tui`). Fires AFTER `_execute_install_plan` succeeds and AFTER
   `prompt_kill_stale_sessions`, BEFORE `_finalize_shared_venv`. Sandbox state lands before
   the heavy venv rebuild, so even if venv build fails the user already has correct
   permissions.

3. **SKILL.md cleanup** — 29 sed-replacements of stale tool names
   `mcp__plugin_sandbox_sandbox__*` → `mcp__plugin_proj_proj__sandbox_*` across
   `plugins/proj/skills/sandbox/SKILL.md` (16), `plugins/proj/skills/init-plugin/SKILL.md`
   (7), `plugins/proj/evals/init-plugin.md` (4), `plugins/worktree/skills/create/SKILL.md` (2).

### Data flow

```
plugins selected → execute_install_plan → prompt_kill_stale → reconcile_sandbox → finalize_shared_venv
                                                                ↓
                                                        ~/.claude/settings.json:
                                                          + missing (router, confluence, wiki, …)
                                                          − stale (perms, sandbox, hooks, zoxide, …)
```

### Plugin name → MCP server mapping

A small static map in `plugins/_shared/sandbox/__init__.py`:

```python
PLUGIN_TO_MCP_SERVER: dict[str, str] = {
    "proj": "plugin_proj_proj",
    "router": "plugin_router_router",
    "todoist": "plugin_todoist_todoist",
    "trello": "plugin_trello_trello",
    "jira": "plugin_jira_jira",
    "confluence": "plugin_confluence_confluence",
    "wiki": "plugin_wiki_wiki",
    "worktree": "plugin_worktree_worktree",
}
```

The map captures the existing convention (`plugin_<name>_<name>` server IDs verified in
`tools/sandbox.py:mcp_allow_entry`). A plugin not in the map → skipped from reconcile w/
warning (defensive — future plugins added without map update fail loud, not silent).

### Expected-plugin set

`_finalize_sandbox` passes the union of:
- `selected_plugins` from this install's wizard selection
- `get_installed_plugins()` parsed names (covers plugins from prior installs the user
  didn't touch this run)

This avoids removing entries for plugins installed in a previous session that aren't being
re-installed now. Stale inference still removes entries for plugins NOT installed at all.

## Files modified

| File | Action |
|------|--------|
| `plugins/_shared/sandbox/__init__.py` | NEW — exports `reconcile_settings`, `PLUGIN_TO_MCP_SERVER` |
| `plugins/_shared/sandbox/models.py` | NEW (moved from `plugins/proj/server/server/lib/sandbox/models.py`) |
| `plugins/_shared/sandbox/storage.py` | NEW (moved from `plugins/proj/server/server/lib/sandbox/storage.py`) |
| `plugins/_shared/sandbox/reconcile.py` | NEW — pure `reconcile_settings(expected_servers, expected_paths=None, expected_skill_prefixes=None) -> ReconcileResult` factored from `tools/sandbox.py:sandbox_reconcile` |
| `plugins/_shared/pyproject.toml` | Add `sandbox` to `[tool.hatch.build.targets.wheel].packages`; bump version (≥ 0.4.30) |
| `plugins/proj/server/server/lib/sandbox/storage.py` | Delete (moved) |
| `plugins/proj/server/server/lib/sandbox/models.py` | Delete (moved) |
| `plugins/proj/server/server/lib/sandbox/__init__.py` | Replace with re-export shim: `from sandbox.storage import *` etc. for back-compat |
| `plugins/proj/server/server/tools/sandbox.py` | Update imports (`from sandbox import storage, reconcile_settings, mcp_allow_entry, …`); `sandbox_reconcile` MCP tool becomes thin wrapper invoking `reconcile_settings(...)` and serializing the result. |
| `installer/flow/installer_flow.py` | Add `_finalize_sandbox(args, selected_plugins, console)` helper. Update `_run_install` + `_run_reinstall` to call it after `prompt_kill_stale_sessions` and before `_finalize_shared_venv`. `_run_update` similarly. |
| `installer/main.py` | Same wiring in `_install` and `_reinstall` (`--no-tui` paths). |
| `plugins/proj/skills/sandbox/SKILL.md` | sed (16 hits) |
| `plugins/proj/skills/init-plugin/SKILL.md` | sed (7 hits) |
| `plugins/proj/evals/init-plugin.md` | sed (4 hits) |
| `plugins/worktree/skills/create/SKILL.md` | sed (2 hits) |

## API: `reconcile_settings`

```python
@dataclass
class ReconcileResult:
    added: int
    removed: int
    expected_servers: list[str]
    stale_removed: list[str]
    paths_added: list[str]


def reconcile_settings(
    expected_servers: list[str],
    expected_paths: list[str] | None = None,
    expected_skill_prefixes: list[str] | None = None,
) -> ReconcileResult:
    """Sync expected vs actual MCP servers, paths, and skill prefixes in
    ~/.claude/settings.json. Removes stale, adds missing. Atomic write.

    `expected_servers`: list of MCP server names (e.g. `plugin_proj_proj`).
    `expected_paths`: optional sandbox.filesystem.allow_write paths.
    `expected_skill_prefixes`: optional skill-allow prefix strings.

    Stale inference: any `mcp__<name>__*` allow rule whose `<name>` is not
    in expected_servers is removed.

    Returns counts + lists for diagnostics. Raises ValueError on malformed
    server names; OSError on filesystem failure (caller handles).
    """
```

The current `tools/sandbox.py:sandbox_reconcile` returns `_json_result(...)` (string). The
new `_shared` function returns `ReconcileResult` (typed dataclass). Proj's MCP tool wrapper
serializes `ReconcileResult → JSON` for backward compat with existing skill consumers.

## `_finalize_sandbox` step

```python
def _finalize_sandbox(
    args: Any, selected_plugins: list[str], console: Console
) -> None:
    """Reconcile ~/.claude/settings.json MCP allow rules with selected plugins.

    Runs AFTER plugin install + kill_stale, BEFORE shared venv build. Failures
    are warnings only — start.sh + plugin runtime degrade gracefully w/o
    sandbox rules (Claude prompts per-tool permissions instead of auto-allow).
    """
    from sandbox import PLUGIN_TO_MCP_SERVER, reconcile_settings

    # Union of this run's selection + already-installed plugins.
    name_to_id = _name_to_id_map()  # already exists in installer_flow.py
    union = set(selected_plugins) | {n for n in name_to_id}

    expected_servers = []
    skipped: list[str] = []
    for plugin_name in sorted(union):
        server = PLUGIN_TO_MCP_SERVER.get(plugin_name)
        if server is None:
            skipped.append(plugin_name)
            continue
        expected_servers.append(server)

    if skipped:
        console.print(
            f"[dim]Skipped sandbox reconcile for unmapped plugins: {', '.join(skipped)}[/dim]"
        )

    try:
        result = reconcile_settings(expected_servers)
    except (OSError, ValueError) as exc:
        console.print(
            f"[yellow]Failed to reconcile settings.json sandbox rules: {exc}[/yellow]"
        )
        return

    if result.added or result.removed:
        msg_parts: list[str] = []
        if result.added:
            msg_parts.append(f"added {result.added}")
        if result.removed:
            msg_parts.append(
                f"removed {result.removed} stale ({', '.join(result.stale_removed)})"
            )
        console.print(f"  [green]✓[/green] Sandbox rules reconciled: {', '.join(msg_parts)}")
    else:
        console.print("  [dim]✓ Sandbox rules already in sync[/dim]")
```

For `--no-tui` paths in `installer/main.py`, the call shape is identical (the `console`
parameter is the existing Rich `Console()` already created in those flows).

## Tests

### `plugins/_shared/tests/test_sandbox_reconcile.py` (NEW)

Pure unit tests on `reconcile_settings`:

| Case | Setup | Assert |
|------|-------|--------|
| Empty settings → all expected added | `tmp_path` settings.json absent | `result.added == len(expected_servers)`; rules present in saved JSON |
| Existing stale → removed | settings has `mcp__plugin_old__*`; expected = `[plugin_proj_proj]` | `result.removed == 1`; stale rule gone |
| Existing correct → no-op | settings already has all expected; expected unchanged | `result.added == 0 and result.removed == 0` |
| Idempotent | call twice with same expected | second call returns `(0, 0)` |
| Atomic write | inject failure mid-write (mock storage.save to raise) | settings.json unchanged on disk |

Use `monkeypatch.setattr(plugins._shared.sandbox.storage, "_HOME", tmp_path)` (or whatever
the moved storage's settings-path constant is) to redirect ~/.claude/settings.json into
tmp.

### `installer/tests/test_finalize_sandbox.py` (NEW)

| Case | Setup | Assert |
|------|-------|--------|
| Selected = `["proj", "wiki"]`; existing = `["worktree"]` | mock `reconcile_settings`, `_name_to_id_map` | `reconcile_settings` called once with expected_servers ⊇ `[plugin_proj_proj, plugin_wiki_wiki, plugin_worktree_worktree]` |
| Unmapped plugin in selection | selected = `["new-plugin"]` not in PLUGIN_TO_MCP_SERVER | warning printed; `reconcile_settings` called with expected = `[]` (or other mapped plugins) |
| Reconcile failure | `reconcile_settings` raises `OSError` | yellow warning; install does NOT abort |
| Add/remove counters | mock returns `ReconcileResult(added=2, removed=1, …)` | green ✓ message includes counts |

### Extend `installer/tests/flow/test_installer_flow.py::TestKillStaleOrdering`

Add ordering assertion: `prompt_kill_stale < _finalize_sandbox < _finalize_shared_venv` for
`_run_install`, `_run_reinstall`, `_run_update`. Pattern matches existing
`_assert_kill_before_finalize` helper (parent MagicMock with three children).

### Extend `installer/tests/test_main.py`

Same ordering for `--no-tui` paths in `_install` and `_reinstall`.

### Existing `plugins/proj/.../tools/sandbox.py` MCP tool tests

Verify thin wrapper still delegates correctly. Spot-check:

- `sandbox_reconcile` MCP tool returns the same JSON shape it did before (consumers parse it).
- Failures in `reconcile_settings` propagate as JSON error envelope.

No major rewrite — the wrapper is ~10 lines.

## Verification

1. `uv run --no-sync pytest plugins/_shared/tests -x` — 24+ green (existing 24 + new
   reconcile tests).
2. `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x` — no regression.
3. `uv run --no-sync pytest plugins/proj -x` — proj plugin tests still green (sandbox tool
   wrapper).
4. `uv run --no-sync pytest installer/tests -m slow --ignore=installer/tests/e2e -x` —
   cross-plugin integration test still green.
5. Manual on this host: `cpm-install --reinstall`, restart Claude Code. Verify
   `~/.claude/settings.json` contains `mcp__plugin_router_router__*`,
   `mcp__plugin_confluence_confluence__*`, `mcp__plugin_wiki_wiki__*` (currently missing)
   and DOES NOT contain `mcp__plugin_perms_perms__*`, `mcp__plugin_sandbox_sandbox__*`,
   `mcp__plugin_hooks_hooks__*`, `mcp__plugin_zoxide_zoxide__*` (stale).
6. Manual: invoke any proj MCP tool — no permission prompt (allow rule auto-matched).

## Out of scope

- Reconcile of `sandbox.filesystem.allow_write` paths (current `sandbox_reconcile` handles
  via `expected_paths` arg; install-time fix doesn't populate paths — proj.yaml's
  `tracking_dir` / `projects_base_dir` flow is user-driven via `/proj:add-repo`).
- Reconcile of skill prefixes (`expected_skill_prefixes`). Wizard doesn't track which skill
  prefixes a user wants enabled. Future work if needed.
- Renaming `_finalize_shared_venv` or restructuring the install flow beyond inserting one
  step. The `_kill_then_finalize` helper from P2 stays — `_finalize_sandbox` is a peer step
  invoked between kill and finalize, not folded into the helper.

## Risks

- **Reconcile fails mid-install**: `storage.save()` already does atomic write (verify in
  T2). Failure → yellow warning + continue (does NOT abort install). Matches existing
  venv-finalize failure semantics.
- **Selected_plugins vs cache state**: covered by passing the union of `selected_plugins`
  and `get_installed_plugins()` parsed names. A plugin previously installed but absent
  from the current run's selection isn't treated as stale.
- **`_shared` version bump**: triggers per-plugin path-dep cache invalidation. Same
  pattern as P3's e4fee71 (0.4.28→0.4.29). Bump to 0.4.30 here. Acceptable cost.
- **MCP server name format assumption**: `plugin_<name>_<name>`. Verified in
  `tools/sandbox.py:mcp_allow_entry` today. Static map captures it. If a future plugin
  uses a different convention, update `PLUGIN_TO_MCP_SERVER` (single source).
- **Back-compat shim in `proj/.../lib/sandbox/__init__.py`**: re-exports from `_shared`.
  Adds one indirection but zero blast radius — existing in-tree callers like
  `tools/sandbox.py` and `tools/sandbox_*.py` keep their import lines. After all callers
  migrate to `from sandbox import ...`, the shim can be removed in a separate cleanup.

# Installer fixes — 657 (wizard plugin-removal) + 658 (TodoistResync auth)

**Status**: draft
**Date**: 2026-04-19
**Scope**: pair fix — both installer-path issues, both high priority
**Deferred**: #659 (migrate flag unification + UI framework pick) → own spec after these ship
**Split-out**: #660 (`todoist_full_sync.py` raw-tags push vs `synced_tags`) — filed separately; runtime code, not installer

## Problem

### 657 — Wizard update uninstalls other plugins

Running `cpm-install` (Textual wizard), selecting one outdated plugin, clicking update → target plugin is updated but other installed plugins are silently removed. Expected: only the selected plugin is touched.

Root cause in `installer/app.py:638` (`_run_update_worker`):

```python
await asyncio.to_thread(update_plugin, plugin_name)  # passes bare name e.g. "proj"
```

Install path at `installer/app.py:490-498` (`_run_status_install_worker`) correctly resolves bare name to fully qualified `plugin_id` via `name_to_id` dict built from `get_available_plugins()` + `get_installed_plugins()`:

```python
plugin_id = name_to_id.get(plugin_name, f"{plugin_name}@claude-project-manager")
```

Update path skips this resolution. `claude plugin update proj` (bare) vs `claude plugin update proj@claude-project-manager` (qualified) behave differently — the former is the operative trigger for the observed plugin-set corruption.

### 658 — TodoistResync config lookup wrong

`installer/migrations/integrations/todoist.py:64`:

```python
token = cfg["sync"]["todoist"].get("api_token")
```

Reads `api_token` from `~/.claude/proj.yaml`. That field does not exist in the project config — proj.yaml only carries `sync.todoist.mcp_server` (the MCP server name). Real token location:

- **Local `plugins/todoist` plugin** → `~/.claude/todoist.yaml` w/ `api_token: <tok>`.
- **External `claude_ai_Todoist` MCP server** → token in Claude Code's MCP server config (not reachable by installer).

Current behavior: every action fails w/ `ConfigError: todoist api_token missing`, one per queued action, spamming `errors.log`. Result after `cpm-install --migrate` on a project w/ Todoist-linked children: local yaml is flat (parent → `group:<id>` tag), Todoist still nested.

## Fix — 657

### Change

`installer/app.py::_run_update_worker` mirrors the install path's name→ID resolution:

```python
async def _run_update_worker(
    self, selected: list[str], progress: ProgressScreen
) -> None:
    """Execute plugin updates, advancing the progress bar."""
    await progress.wait_ready()

    # Build name→ID map (same as _run_status_install_worker).
    try:
        available = await asyncio.to_thread(get_available_plugins)
        installed_ids = await asyncio.to_thread(get_installed_plugins)
    except InstallerError as exc:
        progress.write_log(f"  [yellow]name resolution failed: {exc}[/yellow]")
        available, installed_ids = [], []

    name_to_id: dict[str, str] = {}
    for pid in available + installed_ids:
        name_to_id.setdefault(pid.split("@")[0], pid)

    for plugin_name in selected:
        plugin_id = name_to_id.get(
            plugin_name, f"{plugin_name}@claude-project-manager"
        )
        try:
            progress.write_log(f"  Updating {plugin_id}...")
            await asyncio.to_thread(update_plugin, plugin_id)
            progress.write_log(f"  [green]✓ {plugin_name} updated[/green]")
            progress.advance(1, detail=f"Updated {plugin_name}")
        except InstallerError as exc:
            progress.write_log(f"  [red]✗ {plugin_name} failed: {exc}[/red]")
            progress.advance(1, detail=f"Failed: {plugin_name}")
```

### Err handling

- `get_available_plugins` / `get_installed_plugins` raising `InstallerError` → log yellow warning, fall back to empty maps. Per-plugin loop still runs w/ `f"{plugin_name}@claude-project-manager"` default. Preserves prior behavior when CLI enumeration fails.
- `update_plugin(plugin_id)` raising `InstallerError` → log red line, continue loop (unchanged).

### No other changes

Update path calls no `_write_config_files` or `ensure_managed_section`; no other code path touches the installed-plugins list based on `selected_plugins` during update mode. Scope stays minimal.

## Fix — 658

### Change — api_token lookup

`installer/migrations/integrations/todoist.py` — add `_load_api_token()` helper, swap `execute()` to use it.

```python
from pathlib import Path

def _load_api_token(project_cfg: dict[str, Any] | None = None) -> str | None:
    """Resolve Todoist api_token. Priority: ~/.claude/todoist.yaml → proj.yaml fallback.

    Returns None if no non-empty token is found.
    """
    import yaml

    # 1. Local plugins/todoist config.
    todoist_yaml = Path.home() / ".claude" / "todoist.yaml"
    if todoist_yaml.exists():
        try:
            data = yaml.safe_load(todoist_yaml.read_text()) or {}
            tok = str(data.get("api_token", "")).strip()
            if tok:
                return tok
        except yaml.YAMLError:
            pass  # fall through to proj.yaml fallback

    # 2. Legacy / opt-in: proj.yaml sync.todoist.api_token.
    cfg = project_cfg or {}
    tok = str(cfg.get("sync", {}).get("todoist", {}).get("api_token", "")).strip()
    return tok or None
```

Updated `execute()`:

```python
def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult:
    result = ResyncResult()
    if not actions:
        return result

    cfg = _load_cfg(project)
    token = _load_api_token(cfg)
    if not token:
        result.aborted = True
        # One synthetic failure w/ runbook, not one-per-action spam.
        result.failed.append(
            FailedAction(
                actions[0],
                "ConfigError",
                (
                    "todoist api_token not found in ~/.claude/todoist.yaml or "
                    "proj.yaml. Run `/proj:todoist-sync` on this project "
                    "after migration completes to push the flat structure "
                    "to Todoist."
                ),
                retryable=False,
            )
        )
        return result

    # ... existing httpx batch loop unchanged ...
```

### Change — report output

`installer/migrations/report.py` — when `ResyncResult.aborted` is True AND the synthetic FailedAction's message contains `"api_token not found"`, surface in the terminal summary:

```
Todoist resync skipped — api_token not found.
Run `/proj:todoist-sync` on each migrated project to push the flat
structure to Todoist (this reshapes remote parent_id chains to match
the new flat-group tag model).
```

(Detection key: `result.aborted is True and any("api_token not found" in fa.message for fa in result.failed)`.)

### Err handling

- `todoist.yaml` missing → silent fallback to proj.yaml (no warning — this is the default state for `claude_ai_Todoist` external-MCP users).
- `todoist.yaml` unparseable (YAMLError) → silent fallback.
- Neither yields a token → one `FailedAction`, `aborted=True`, clean runbook message.
- Happy path (token present) → unchanged.

## Data flow

### 657 update flow (post-fix)

```
UpdateScreen.dismiss([selected])
  → _on_update_selected(selected)
    → _run_update_worker(selected, progress)
      → get_available_plugins() + get_installed_plugins()  # new: build name_to_id
      → for plugin_name in selected:
          plugin_id = name_to_id[plugin_name]  # e.g. "proj@claude-project-manager"
          update_plugin(plugin_id)  # claude plugin update proj@claude-project-manager
```

### 658 migration flow (post-fix)

```
cpm-install --migrate
  → flat-yaml migration completes (local flattening happens regardless of remote)
  → TodoistResync.execute()
    → _load_api_token(cfg)
      ├─ ~/.claude/todoist.yaml has api_token → return, proceed w/ httpx item_move
      ├─ proj.yaml has api_token → return, proceed
      └─ neither → aborted=True + synthetic FailedAction w/ runbook → skip loop
  → migrations/report.py prints summary; if aborted w/ token-missing cause, surfaces runbook
```

## Testing

### 657 unit — `installer/tests/test_app.py` (extend)

- `test_update_worker_uses_qualified_plugin_id`:
  - Monkeypatch `installer.app.get_available_plugins` → `["proj@claude-project-manager", "router@claude-project-manager"]`.
  - Monkeypatch `installer.app.get_installed_plugins` → same list.
  - Stub `update_plugin` to append each arg to a capture list.
  - Invoke `_run_update_worker(["proj"], progress_stub)`.
  - Assert capture == `["proj@claude-project-manager"]`.
- `test_update_worker_fallback_when_plugin_absent_from_lists`:
  - Both CLI calls return `[]`.
  - Invoke `_run_update_worker(["weird_plugin"], progress_stub)`.
  - Assert capture == `["weird_plugin@claude-project-manager"]` (fallback literal).
- `test_update_worker_continues_when_enumeration_fails`:
  - `get_available_plugins` raises `InstallerError`.
  - Assert no crash; yellow warning line written; loop proceeds w/ fallback id.

### 657 e2e — `installer/tests/e2e/test_update_flows.py` (extend)

- `test_update_one_preserves_others`:
  - Fixture: `get_installed_plugins` mocked to return 3 ids (`proj`, `router`, `worktree`).
  - Fixture: `compare_versions` returns diffs for all 3.
  - Drive UpdateScreen via Textual pilot: deselect 2, keep `proj`, press Update.
  - Assert `update_plugin` called once w/ `"proj@claude-project-manager"`; `uninstall_plugin` never called.
  - Assert post-run mocked `get_installed_plugins` still returns all 3 ids.

### 658 unit — `installer/tests/migrations/test_integrations_todoist.py` (new file or extend existing)

- `test_load_api_token_from_todoist_yaml`:
  - `tmp_path / ".claude" / "todoist.yaml"` with `api_token: tok-1`.
  - Monkeypatch `Path.home()` to tmp.
  - Assert `_load_api_token({}) == "tok-1"`.
- `test_load_api_token_fallback_proj_yaml`:
  - No todoist.yaml; proj.yaml dict `{"sync": {"todoist": {"api_token": "tok-2"}}}`.
  - Assert returns `"tok-2"`.
- `test_load_api_token_none_when_both_missing`:
  - No todoist.yaml; proj.yaml cfg lacks field.
  - Assert returns `None`.
- `test_load_api_token_yaml_error_fallbacks`:
  - todoist.yaml contains invalid YAML (`:::`).
  - proj.yaml cfg has token.
  - Assert fallback token returned (YAMLError swallowed).
- `test_execute_aborts_with_runbook_when_no_token`:
  - `_load_api_token` returns None.
  - `execute(project, [action1, action2])` → result.aborted True, `len(result.failed) == 1`, message contains `"run \`/proj:todoist-sync\`"`.
- `test_execute_proceeds_with_todoist_yaml_token`:
  - todoist.yaml has token; mock httpx client; `execute` posts expected batch.

### 658 e2e — `installer/tests/migrations/e2e/test_e2e_v1_to_v3_chain.py` (extend)

- `test_migration_completes_when_todoist_token_missing`:
  - Fixture: v1 project w/ Todoist-linked children, no todoist.yaml, no proj.yaml api_token.
  - Run full `cpm-install --migrate` via CLI harness.
  - Assert exit code 0.
  - Assert local yaml is flat (parent → group:* tags).
  - Assert report output contains the runbook notice.
  - Assert `errors.log` (if any) has at most 1 entry, not N-per-action spam.

## Acceptance criteria

1. `cpm-install` w/ 3 plugins installed, update 1 → all 3 remain installed post-run.
2. `cpm-install --migrate` w/ Todoist-linked todos + no api_token anywhere → migration completes (exit 0), local flat, report prints runbook.
3. `cpm-install --migrate` w/ `~/.claude/todoist.yaml` present → TodoistResync succeeds (existing happy-path regression intact).
4. Existing tests assuming `proj.yaml.sync.todoist.api_token` work via fallback path (no breaking change).

## Out of scope

- #659 (`--migrate` unification + Rich vs Textual) — separate spec per user decision.
- #660 (`todoist_full_sync.py` raw-tags push) — separate todo, runtime code.
- Broader audit of every `install_plugin` / `update_plugin` / `uninstall_plugin` caller — user chose narrow fix for 657.
- External `claude_ai_Todoist` MCP server token discovery — user chose todoist.yaml-first strategy. External-MCP users get the runbook notice path.

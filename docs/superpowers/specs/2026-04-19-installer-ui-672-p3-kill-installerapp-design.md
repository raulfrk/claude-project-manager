# Installer UI Migration — Phase 3: Kill InstallerApp + Port 7 Screens

**Todo:** 672
**Date:** 2026-04-19
**Status:** Draft → pending user review

**Parent spec:** `docs/superpowers/specs/2026-04-19-installer-ui-framework-migration-design.md` (original 8-phase plan)
**Parent plans shipped:** P1 (`2026-04-19-installer-ui-672-p1-progress-migration.md`), P2 (`2026-04-19-installer-ui-672-p2-readonly-screens.md`)

---

## Goal

Eliminate `installer/app.py::InstallerApp` (the Textual `App` subclass that currently hosts install/update/reinstall/uninstall modes). Port 7 screens from Textual to Rich + prompt_toolkit. Replace the top-level `InstallerApp().run()` entry point with a plain-Python `run_installer_flow(mode, args)` dispatcher in `installer/main.py`.

After P3, only 5 Textual screens remain (wizard, advanced_config, integration_config × 3 — all multi-field forms with focus cycling). Those ship in P4. Textual is removed from deps in P5.

## Motivation

The original 8-phase spec kept `InstallerApp` alive until P7, porting screens one-at-a-time while InstallerApp hosted them. This creates a paradoxical middle state: Rich flow helpers live alongside a Textual event-loop host, with every "port a screen to Rich" phase needing temporary scaffolding to run Rich during Textual's lifetime. That scaffolding is throwaway work.

P1 + P2 proved this pattern had a limit: migration screens got a post-exit Rich phase, and P2 deleted the nested `MigrationApp` to run migrate mode entirely outside Textual. P3 extends the same insight to install/update/reinstall/uninstall: if Textual isn't load-bearing for screens that are simple prompts or read-only displays, deleting the Textual host entirely is cleaner than propping it up.

Collapsing P3-P7 of the original plan into 3 phases (new P3 bulk-port + InstallerApp kill; P4 remaining Textual forms; P5 Textual removal) removes the throwaway scaffolding.

## Scope

**Ported in P3:**

| Screen | Target | Module |
|---|---|---|
| `confirm.py` (ConfirmScreen) | Rich `Prompt.ask` per option | `installer/flow/confirm.py` |
| `detection.py` (DetectionScreen) | Rich `Table` + `Prompt.ask(y/n)` | `installer/flow/detection.py` |
| `corrupt_yaml.py` (CorruptYamlScreen) | Rich `Panel` + `Prompt.ask(y/n)` | `installer/flow/corrupt_yaml.py` |
| `hooks_diff.py` (HooksDiffScreen) | Rich `Syntax` + `Prompt.ask` | `installer/flow/hooks_diff.py` |
| `config_diff.py` (ConfigDiffScreen) | Rich `Syntax` + `Prompt.ask` | `installer/flow/config_diff.py` |
| `update.py` (UpdateScreen) | prompt_toolkit `checkboxlist_dialog` | `installer/flow/update.py` |
| `plugin_select.py` (PluginStatusScreen) | prompt_toolkit `checkboxlist_dialog` | `installer/flow/plugin_select.py` |

**InstallerApp deleted.** Replaced by `installer/flow/installer_flow.py::run_installer_flow(mode, args)` — a plain function that dispatches per mode.

**Left for P4:** wizard + advanced_config + integration_config × 3 (all multi-field form screens with focus cycling).

**Left for P5:** remove Textual + pytest-textual-snapshot from deps; final cleanup.

## Approach

### New module: `installer/flow/installer_flow.py`

Top-level orchestrator. Entry point:

```python
def run_installer_flow(mode: InstallerMode, args, console: Console) -> int:
    """Drive the entire install/update/reinstall/uninstall flow.

    Replaces InstallerApp().run(). Returns exit code.
    """
    # 1. Pre-phase: detection, corrupt-yaml, confirms (Rich).
    pre_result = pre_install_phase(mode, args, console)
    if not pre_result.proceed:
        return pre_result.exit_code

    # 2. Mode-specific interactive phase.
    if mode == "install":
        actions = _run_install_interactive(pre_result, console)      # prompt_toolkit + hooks_diff
    elif mode == "update":
        actions = _run_update_interactive(pre_result, console)       # prompt_toolkit
    elif mode == "reinstall":
        actions = _build_reinstall_actions(pre_result)               # plain
    elif mode == "uninstall":
        actions = _build_uninstall_actions(pre_result)               # plain

    if not actions:
        console.print("[dim]Nothing to do.[/dim]")
        return 0

    # 3. Execute phase: Rich progress + orphan cleanup.
    plan = InstallPlan(description=..., actions=actions)
    result = execute_install_plan(plan, console)
    cleanup_orphaned_plugin_caches(...)
    return 0 if result.failure_count == 0 else 1
```

`main.py` simplifies to: parse args → instantiate console → call `run_installer_flow(mode, args, console)` → return exit code.

### New dataclass: `PreInstallResult`

```python
@dataclass(frozen=True)
class PreInstallResult:
    state: InstallState | None                 # None on abort
    proceed: bool                              # False → stop
    mode_options: dict[str, bool]              # reset_configs, full_cleanup, etc.
    exit_code: int = 0                         # 0 unless aborted with non-zero
    error_message: str | None = None
```

### `pre_install_phase` logic (per mode)

- **Load configs.** If any `ConfigLoadError` → `show_corrupt_yaml_and_confirm`. If user cancels → abort.
- **Install mode:**
  - Marketplace check (+ auto-register if needed).
  - `build_plugin_status_list` (existing helper).
  - Return `PreInstallResult(state, proceed=True, mode_options={})`.
- **Update / Reinstall / Uninstall:**
  - `detect_existing()`.
  - `show_detection_and_confirm(state, rows, title)` → if user cancels, abort.
  - Reinstall-specific: `confirm_with_options(title="Reinstall", options=[reset_configs])` → if cancelled, abort. Then `scan_stale_cache` + (if orphans) `confirm_with_options(orphans list, y/n)`.
  - Uninstall-specific: `confirm_with_options(title="Uninstall", options=[full_cleanup])` → if cancelled, abort.
- Return `PreInstallResult` with populated `mode_options`.

### Install-mode interactive screens — all ported in P3

All 7 Textual screens listed in "Scope" above are ported in P3, including the ones Install mode uses (`PluginStatusScreen`, `HooksDiffScreen`, `ConfigDiffScreen`). No Textual screens survive in the install/update/reinstall/uninstall flow.

- `PluginStatusScreen` → `installer/flow/plugin_select.py::select_plugin_actions(statuses, console)` using `prompt_toolkit.shortcuts.checkboxlist_dialog`. Returns list of (plugin_name, action) tuples.
- `HooksDiffScreen` → `installer/flow/hooks_diff.py::review_hooks_diff(diffs, console)` using Rich `Syntax` panel + `Prompt.ask("apply/skip/abort")`.
- `ConfigDiffScreen` → same pattern as hooks_diff (display diff + prompt).

`UpdateScreen` → `installer/flow/update.py::select_updates(version_diffs, console)` using `prompt_toolkit.shortcuts.checkboxlist_dialog`.

All 7 ported screens live under `installer/flow/`.

### Deleted from P3

Source:
- `installer/screens/confirm.py`
- `installer/screens/detection.py`
- `installer/screens/corrupt_yaml.py`
- `installer/screens/hooks_diff.py`
- `installer/screens/config_diff.py`
- `installer/screens/update.py`
- `installer/screens/plugin_select.py`
- `installer/app.py` (the `InstallerApp` class — replaced entirely; file may survive as a thin module holding `run_migration_tui` which already lives there post-P2)

Tests:
- All Textual snapshot tests for the 7 ported screens (SVG goldens under `installer/tests/e2e/snapshots/`).
- Unit tests targeting InstallerApp state transitions; rewritten to target `run_installer_flow` + `pre_install_phase`.

Deps: **not removed in P3.** 5 remaining Textual screens (wizard, advanced_config, 3 integration configs) still need it. Removal happens in P5.

## Testing strategy

**Replaced:**
- Delete Textual SVG snapshot tests for the 7 ported screens.
- Delete InstallerApp pilot-driven integration tests.

**Added:**
- Unit tests per new `flow/*` helper (mock `Prompt.ask` + `checkboxlist_dialog`). Pattern from P2.
- Syrupy text snapshots for display-heavy outputs (detection table, corrupt-yaml panel, hooks/config diff panels, update table).
- `installer/tests/flow/test_pre_install_phase.py` — integration tests for the orchestrator per mode.
- `installer/tests/flow/test_installer_flow.py` — end-to-end `run_installer_flow` test per mode (mock subprocess + prompts, assert final exit code + plan shape).
- `installer/tests/test_main.py` — update existing tests: `run_installer_flow` replaces `InstallerApp`.

**Preserved:**
- `installer/tests/e2e/test_install_flow.py`, `test_update_flows.py`, `test_integration_flow.py` — behavioral e2e tests that drive `main.py` via subprocess. Update mocks to target the new flow helpers instead of `InstallerApp.run_test`.

### Latent bugs addressed (from parent spec)

- **B9** (`confirm.py:204-205` bare except in `_gather_options`) — eliminated: Rich `confirm_with_options` has no widget-query hazards.
- **B13** (app.py plugin-name validation timing) — deferred to P4.
- **B10** (plugin_select Enter=toggle vs confirm) — eliminated: prompt_toolkit `checkboxlist_dialog` has standard Enter-to-confirm semantics.
- **B14** (app.py `_show_error` try/except) — eliminated: `InstallerApp` deleted.

## Rollout

Single FF-merge feature branch `feat/672-p3-kill-installerapp`. Tasks broken into ~11 bite-sized units in the implementation plan (written next).

**Order:**

1. Add `prompt_toolkit>=3.0` dep.
2. Port confirm + detection + corrupt_yaml → `installer/flow/` (simplest, Rich-only).
3. Port hooks_diff + config_diff → `installer/flow/` (Rich `Syntax`).
4. Port update + plugin_select → `installer/flow/` (prompt_toolkit `checkboxlist_dialog`).
5. Create `pre_install_phase` + `PreInstallResult`.
6. Create `run_installer_flow` + per-mode helpers.
7. Rewire `main.py` to call `run_installer_flow`.
8. Delete InstallerApp + all references.
9. Delete 7 Textual screen files + their snapshot tests + SVG goldens.
10. Update `screens/__init__.py` exports.
11. Add syrupy snapshots for Rich output + final test sweep + FF-merge.

**Exit criteria:**

- `grep -rn "class InstallerApp" installer/` returns empty.
- `grep -rn "ConfirmScreen|DetectionScreen|CorruptYamlScreen|HooksDiffScreen|ConfigDiffScreen|UpdateScreen|PluginStatusScreen" installer/` returns empty.
- `installer/flow/` contains the 7 new helpers + `installer_flow.py` + `pre_install_phase.py`.
- Textual + pytest-textual-snapshot NOT removed from deps (still used by wizard etc.).
- CI green (modulo known `test (_shared)` flake from todo 675).

**Rollback:** feature branch is atomic FF-merge; `git revert <merge>` restores the full Textual+InstallerApp stack for the 7 ported screens.

## Non-goals

- Not porting wizard, advanced_config, integration_config × 3 (P4).
- Not removing Textual from deps (P5).
- No changes to the `cpm-install` CLI interface.
- No new user-facing features.

## Open questions

None — all decisions captured in brainstorming.

## References

- Todo 672 (parent investigation)
- Parent spec: `docs/superpowers/specs/2026-04-19-installer-ui-framework-migration-design.md`
- P1 spec/plan + commits d8a9e06..5cd0a9c
- P2 spec/plan + commits 7d1cc4d..675caed

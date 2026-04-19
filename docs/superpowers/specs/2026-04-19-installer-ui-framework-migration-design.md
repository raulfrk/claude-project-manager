# Installer UI Framework Migration — Design Spec

**Todo:** 672
**Date:** 2026-04-19
**Status:** Draft → pending user review

---

## Goal

Migrate `installer/` from **Textual + Rich (hybrid)** to **prompt_toolkit + Rich**. End state: Textual is removed entirely from deps, tests, and source. Migration happens screen-by-screen, one FF-merge per phase. Latent bugs found in the Textual codebase are fixed in the ported version (not carried forward).

## Motivation

Three pain points with the current Textual+Rich hybrid:

1. **Snapshot flake (blocks CI).** Rich's SVG export assigns auto-numbered CSS classes (`r1, r2, ...`) whose order depends on process/path/dict-iteration entropy → the same rendered output produces different SVG bytes → 8 snapshot tests fail deterministically in CI. Current `_normalize_svg` only handles the `terminal-<hash>-` prefix, not the class-index suffix. Root cause is test-infra + Rich's SVG renderer, not Textual per se — but the test infrastructure is tightly coupled to Textual's SVG export.
2. **Split-brain codebase.** 17 Textual screens (~4900 LOC) vs 5 Rich modules (~1100 LOC). Two mental models, two test strategies, two libraries to maintain.
3. **Latent bugs accumulated in Textual screens.** 14 findings catalogued (see *Latent bug inventory* section below) — validation gaps, bare `except Exception: pass`, focus inconsistencies. Easier to fix these as part of a port than to paper over them.

## Approach: prompt_toolkit + Rich

**Library decisions:**

- **`prompt_toolkit`** handles input: focus cycling across multi-field forms, key bindings, checkbox multi-select, validation hooks, autocomplete. Used by IPython, aws-cli, poetry, pdb++, ptpython — industry-proven.
- **`rich`** handles output: tables, panels, progress bars, syntax-highlighted diffs. Already in use; `Console.export_text()` is deterministic → clean snapshot story.
- The two compose: prompt_toolkit's `Application` drives the event loop; Rich's `Console(record=True)` renders output segments passed to `prompt_toolkit.print_formatted_text(ANSI(...))`.

**Why this beats the alternatives evaluated:**

- vs. **Textual stay + fix snapshot test-infra**: keeps the split-brain problem + doesn't address the 14 latent bugs.
- vs. **Rich-only (no prompt_toolkit)**: loses focus cycling + back-nav in the wizard; user wants that preserved.
- vs. **urwid**: older API, less ergonomic, weaker docs than prompt_toolkit+Rich.
- vs. **asciimatics**: smaller ecosystem, less proven at installer-scale.
- vs. **raw ANSI + input()**: loses all polish for minor LOC savings.

## Architecture

### Control flow

Replace `installer/app.py::InstallerApp` (Textual `App` subclass, 1179 LOC) with a plain `installer/flow.py::run_installer_flow(mode, console)` function:

```python
def run_installer_flow(mode: InstallerMode, console: Console) -> int:
    state = detect_state(console)                           # was DetectionScreen
    if state.needs_plugin_select:
        state = select_plugins(state, console)              # was PluginSelectScreen
    if state.needs_wizard:
        state = run_wizard(state, console)                  # was WizardScreen
    if state.advanced_requested:
        state = configure_advanced(state, console)          # was AdvancedConfigScreen
    for integration in enabled_integrations(state):
        state = configure_integration(integration, state, console)
    if state.mode == "update" and state.has_diff:
        state = show_config_diff(state, console)
        state = show_hooks_diff(state, console)
    if not confirm_install(state, console):                 # was ConfirmScreen
        return 130
    result = run_install(state, console)                    # was ProgressScreen (rich.Progress)
    show_summary(result, console)                           # was SummaryScreen
    return result.exit_code
```

No screen stack, no `push_screen`/`pop_screen`, no event-driven state. Each step is a synchronous function that takes state + console, returns new state. Cancellation is `KeyboardInterrupt` caught at `main.py`.

### Screen port map (17 screens → function equivalents)

| # | Textual screen (LOC) | New implementation | Primary primitive |
|---|---|---|---|
| 1 | `wizard.py` (282) | `run_wizard(state, console) -> InstallState` | `prompt_toolkit.Application` with `TextArea` fields + Tab focus |
| 2 | `integration_config.py` (735) | `configure_todoist()`, `configure_trello()`, `configure_jira()` (≈100 LOC each) | prompt_toolkit multi-field form + Rich Panel for header |
| 3 | `plugin_select.py` (653) | `select_plugins(state, console)` | `prompt_toolkit.shortcuts.checkboxlist_dialog` |
| 4 | `detection.py` (222) | `detect_state(console)` | Rich Panel + `Prompt.ask` |
| 5 | `confirm.py` (218) | `confirm_install(state, console) -> bool` | Rich Panel variant (primary/warning/error) + `Confirm.ask` |
| 6 | `advanced_config.py` (243) | `configure_advanced(state, console)` | prompt_toolkit multi-field form (same pattern as wizard) |
| 7 | `progress.py` (176) | `run_install(state, console) -> InstallResult` | `rich.progress.Progress` (identical UX) |
| 8 | `migration_overview.py` (71) | `show_migration_overview(projects, console)` | Rich `Table` + `Prompt.ask` |
| 9 | `migration_review.py` (142) | `review_migration(projects, console) -> bool` | Rich `Layout` with 2 columns, read-only |
| 10 | `migration_progress.py` (52) | `run_migration(projects, console)` | `rich.progress.Progress` |
| 11 | `summary.py` (127) | `show_summary(result, console)` | Rich `Table`, read-only |
| 12 | `hooks_diff.py` (289) | `show_hooks_diff(state, console)` | Rich `Syntax` in Panel |
| 13 | `config_diff.py` (118) | `show_config_diff(state, console)` | Rich `Syntax` in Panel (same helper as hooks_diff) |
| 14 | `corrupt_yaml.py` (130) | `handle_corrupt_yaml(path, console) -> Action` | Rich Panel + `Confirm.ask` |
| 15 | `update.py` (198) | `select_updates(state, console) -> list[str]` | Rich `Table` + `checkboxlist_dialog` |
| 16 | `__init__.py` (28) | deleted | — |
| 17 | `app.py::InstallerApp` (≈1000 of 1179 LOC) | replaced by `flow.py::run_installer_flow` | — |

### Data flow

- `InstallState` dataclass (already exists at `installer/detect.py`) carries all wizard/config state through the pipeline. Immutable — each stage returns a new `InstallState`.
- No shared mutable `App.state`. No event buses.
- Validation happens at each prompt via `prompt_toolkit.Validator` subclasses (non-empty, path-exists, URL-scheme, etc.).

### Error handling

- Validation errors: `Validator.validate()` raises `ValidationError` → prompt_toolkit re-prompts with inline error message.
- Non-TTY: `sys.stdin.isatty()` check at `run_installer_flow` entry; non-TTY falls through to argparse-only mode (existing behavior preserved).
- Abort: `KeyboardInterrupt` caught in `main.py`, prints "Installation aborted" via Rich, exits 130.
- Unrecoverable errors (missing binary, disk full): raise `InstallerError`, caught at `main.py`, printed via Rich Panel with error variant, exits 1.

## Testing strategy

### Snapshot tests

**Replace SVG snapshots with text snapshots.**

- Delete `installer/tests/e2e/test_snapshots_*.py` (6 files, ~1500 LOC of test code).
- Delete `installer/tests/e2e/snapshots/*.svg` goldens (~15 files).
- Remove `pytest-textual-snapshot` from test deps.
- Add new `installer/tests/e2e/test_console_snapshots.py` using `rich.Console(record=True)` + `console.export_text()` + `syrupy` or `pytest-snapshot`. Text snapshots are deterministic — no CSS class numbering.

### prompt_toolkit testing

- Use `prompt_toolkit.input.create_pipe_input` + `AppSession` to drive the event loop with canned key inputs in unit tests.
- Each new screen function has unit tests: given input state + mocked answers, assert output state + Rich console output.

### Behavioral e2e tests (preserved)

- `installer/tests/e2e/test_install_flow.py`, `test_update_flows.py`, `test_integration_flow.py`, `test_wizard_full_config.py` — unchanged. These drive `main.py` subprocess + assert exit codes + files written.

## Latent bug inventory — fix during port, don't carry forward

Audit (2026-04-19) surfaced 14 issues across the Textual screens. Each port PR includes a **"Fixed during port"** section in the commit body listing addressed items from this list. Each fix gets a focused test that would have failed against the Textual-era behavior.

| # | File:Line | Category | Severity | Fix |
|---|---|---|---|---|
| B1 | `integration_config.py:701-723` | validation | high | Add synchronous Jira base_url validation (https:// prefix, domain format, trailing slash strip) before async test |
| B2 | `integration_config.py:512,615-617` | validation | high | Always validate non-empty credentials when integration enabled (bypass-when-disabled must not store empty strings) |
| B3 | `integration_config.py:614-723` | validation | high | Normalize URL trailing slash on blur (not just at `_collect_values` time) |
| B4 | `integration_config.py:544-545` | error-handling | medium | Replace bare `except Exception: pass` (todoist-root-only) with logging + safe default |
| B5 | `integration_config.py:647-654` | error-handling | medium | Replace 2 bare `except Exception: pass` (Trello list name + on_delete) with specific exception + log |
| B6 | `advanced_config.py:189-190` | error-handling | medium | Replace bare exception swallowing when querying widgets |
| B7 | `wizard.py:227-228,252-253` | error-handling | medium | Catch specific `NoMatches`, log, apply field defaults |
| B8 | `wizard.py:179-184` | validation | medium | Always `.strip()` Input field values before returning |
| B9 | `confirm.py:204-205` | error-handling | medium | Replace bare exception with logged failure (missing checkbox should fail loudly) |
| B10 | `plugin_select.py:268` | focus | medium | Enter should confirm, not toggle (convention) — toggle stays on space |
| B11 | `integration_config.py:385-387` | focus | low | Set initial focus to first Input field, not Continue button |
| B12 | `progress.py:440` | async | low | Document + assert screen-push-before-worker-start guarantee |
| B13 | `app.py:278-286` | validation | low | Move plugin name regex validation into `PluginStatusScreen.on_mount` |
| B14 | `app.py:569-570` | error-handling | low | Remove try/except around `_show_error` placeholder query — always present |

**Note on severity:** "high" severity items (B1, B2, B3) ship with the first port PR that touches their screen (integration_config). No high-severity latent bug survives to a later phase.

## Rollout plan — 8 PRs

Each phase = one branch (`feat/672-NN-<screen>`), one FF-merge to dev, CI green before next phase. Per CLAUDE.md: "FF-merge to dev, no PR". Order is smallest/simplest → most complex, so the pattern is proven before the hardest screens:

| Phase | Screens | LOC delta | Latent bugs fixed | Why this position |
|---|---|---|---|---|
| P1 | `progress` + `migration_progress` | ~-228 / +400 | B12 | Trivial — Rich.Progress is 1:1 mapping. Proves the plumbing (flow.py entry, Console instantiation, test approach). |
| P2 | `summary` + `migration_overview` + `migration_review` | ~-340 / +250 | — | Read-only display screens. No input. Low risk. |
| P3 | `confirm` + `corrupt_yaml` + `detection` | ~-570 / +400 | B9 | Simple y/n prompts. First Rich-only Prompt/Confirm work. |
| P4 | `config_diff` + `hooks_diff` | ~-407 / +250 | — | Read-only diff views. Rich `Syntax` showcase. |
| P5 | `update` + `plugin_select` | ~-851 / +600 | B10, B13 | First prompt_toolkit work (checkboxlist_dialog). Proves input-layer pattern before forms. |
| P6 | `advanced_config` + all 3 `*_config_screen` (integration_config.py split) | ~-978 / +700 | B1, B2, B3, B4, B5, B6, B11 | Multi-field forms — the hardest UI pattern. All high-severity bugs land here. |
| P7 | `wizard` | ~-282 / +350 | B7, B8 | Trickiest screen (focus cycling, field validation). Benefits from P5+P6 pattern maturity. |
| P8 | Delete residual `installer/app.py` (whatever's left post-P1-P7) + `installer/screens/__init__.py`, remove Textual + pytest-textual-snapshot from deps, drop SVG goldens + textual snapshot test files, delete `installer/flow.py` transitional glue if any | ~-1500 / +100 | B14 | Final cleanup. **This phase is load-bearing — the migration isn't complete until Textual is 100% gone from source + deps + tests.** |

**Exit criteria** (all must hold after P8):

- `grep -rn 'from textual\|import textual' installer/` returns empty.
- `installer/screens/` directory does not exist.
- `installer/app.py` does not exist (replaced by `installer/flow.py`).
- `textual` and `pytest-textual-snapshot` not in `pyproject.toml` deps.
- `installer/tests/e2e/snapshots/` contains zero `.svg` files (only text snapshots).
- CI green on dev without any flaky or xfail'd snapshot tests.
- All 14 latent bugs from §7 have corresponding test coverage in the new implementation.

**Rollback strategy:** each phase's commit is an atomic FF-merge that both adds the new `flow.py` helper(s) AND deletes the matched Textual screen file(s). If a phase breaks user-facing behavior, `git revert <merge-commit>` restores the Textual screen from that phase (other phases' screens remain already-migrated). After P8, rollback requires unwinding through prior phases — so P8 ships only after P1-P7 have soaked a minimum of 24h on dev with green CI.

**Timeline estimate:** 8 phases × ~0.5-1 day each = 4-8 days. Heavier phases (P6, P7) may take 1-1.5 days each; lighter phases (P1, P2) under half a day.

## Non-goals

- No functional changes to the installer's user-facing behavior beyond the 14 latent-bug fixes.
- No new features (e.g. themes, config profiles, undo).
- No API changes to `cpm-install` CLI flags.
- No change to the `installer/migrations/` subtree (already has its own screens path in `installer/screens/migration_*`, covered by this plan).

## Open questions

None — all decisions captured via brainstorming Q&A with user.

## References

- Todo 672 (parent investigation)
- Todo 670 (CI snapshot flake — subsumed by this work)
- Todo 671 (UI framework split — subsumed by this work)
- Latent-bug audit: inline in §7 above (originally generated by Explore subagent 2026-04-19)

# Installer UI Migration — Phase 4: 5 Textual Form Screens → prompt_toolkit

**Todo:** 672 / 677
**Date:** 2026-04-19
**Status:** Draft → pending user review

**Parent spec:** `docs/superpowers/specs/2026-04-19-installer-ui-framework-migration-design.md`
**Sibling specs shipped:** P1, P2, P3 (see their dated design files).
**Blocks:** P5 (todo 678 — Textual dep removal).
**Also fixes:** todo 679 (corrupt-yaml wiring; folded into P4 as task 0).

---

## Goal

Port the remaining 5 Textual form screens — `WizardScreen`, `AdvancedConfigScreen`, `TodoistConfigScreen`, `TrelloConfigScreen`, `JiraConfigScreen` (latter 3 extending `BaseIntegrationScreen`) — to prompt_toolkit `Application`-based forms via a shared `installer/flow/form.py::run_form()` helper. Wire the new helpers into `run_installer_flow` (P3). Load existing yaml values as field defaults so users never re-enter unchanged data.

After P4 lands: zero Textual screen files remain in source. Textual dep stays in P4 (still needed by P4 tests if any snapshot tests remain) — removal is P5.

## Motivation

Five multi-field forms are the last Textual surface. Each needs focus cycling + validation + submit/cancel — the exact use case prompt_toolkit was built for. Keeping them in Textual means keeping Textual in deps. Porting unblocks P5 cleanup + eliminates the last known source of CI snapshot flakes.

Sharing a single `run_form` helper across all 5 prevents 5 parallel divergent form implementations + keeps per-screen LOC low.

## Approach

### Shared form builder: `installer/flow/form.py`

```python
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

FieldKind = Literal["text", "password", "bool", "int", "select"]


@dataclass(frozen=True)
class FieldSpec:
    key: str                                        # output dict key
    label: str                                      # shown next to input
    kind: FieldKind
    default: Any = None                             # pre-filled value
    choices: list[str] | None = None                # for kind="select"
    validator: Callable[[Any], str | None] | None = None  # returns error or None
    help_text: str | None = None                    # hint line under label
    group: str | None = None                        # grouped header (e.g. "Git Tracking")


def run_form(
    fields: list[FieldSpec],
    console: Console,
    *,
    title: str | None = None,
    error_message: str | None = None,   # pre-populated error (for re-prompt after validation fail)
) -> dict[str, Any] | None:
    """Render form + return {key: value} dict on submit, None on cancel.

    prompt_toolkit Application with:
    - Tab / Shift-Tab focus cycling across fields
    - per-field validator displayed inline
    - Enter on last field (or Ctrl-S anywhere) submits
    - Escape cancels
    """
    ...
```

### Per-screen port pattern

Each ported screen becomes a function that:

1. **Loads existing config** via `load_existing_yaml(path)` for the relevant bucket(s). On `ConfigLoadError`, the error bubbles up to `pre_install_phase`'s corrupt-yaml gate (fixed by task 0).
2. **Builds `list[FieldSpec]`** with `default=` pre-populated from the loaded config. If a field has no existing value, falls back to `defaults.yaml` (for wizard) or hard-coded default.
3. **Calls `run_form(fields, console, title=...)`**.
4. **On cancel (None return)** → returns None; caller decides what to do.
5. **On submit (dict return)** → transforms into nested output shape (e.g. integration screens build `{"sync": {"todoist": {...}}}`) and writes yaml via existing `write_bucket` / equivalent.
6. **Integration-specific:** after submit + before yaml write, synchronously validates credentials via `httpx` inside `console.status("Validating...")`. On validation failure, re-prompts with same fields + pre-filled current answers + error banner.

### Feature-parity critical requirement — existing-config defaults

**MUST:** Every field MUST be pre-filled from the existing yaml config if present. Users with `~/.claude/proj.yaml` containing `tracking_dir: /home/raul/projects/tracking` MUST see that value as the default when re-running the wizard — not a blank field or the hard-coded default.

Implementation:
- Wizard: partition existing buckets via `partition_answers_by_bucket` (existing helper) → lookup each `AnswerSpec.key` in the partitioned dict → use that value as `FieldSpec.default`.
- Integration configs: read existing bucket yaml (e.g. `~/.claude/todoist.yaml` + `~/.claude/proj.yaml::sync.todoist`) → populate api_token / api_key / base_url / email / sync toggles as defaults.
- Advanced config: similar — read current `~/.claude/proj.yaml::advanced` section.

**Test requirement:** Each ported screen has a test that asserts: given pre-existing yaml with values X, form receives FieldSpec list with defaults == X.

### Async credential validation — sync-blocking port

The Textual `BaseIntegrationScreen._validate_credentials()` returns `str | None` (error or ok) asynchronously. The Rich port runs it synchronously inside a `console.status("Validating...")` spinner context, using `httpx.Client(timeout=30.0)` instead of `httpx.AsyncClient`. Same API calls, same error conditions, no event loop.

On failure:
- Show error via Rich panel (red variant).
- Re-run `run_form` with same FieldSpec list + pre-filled current answers + `error_message=` banner.
- User can edit + re-submit OR cancel.
- Max retry count: none (user cancels if stuck).

### Corrupt-yaml gate (todo 679 fix)

Add a pre-task to `pre_install_phase`:

```python
def _check_corrupt_yaml(mode: str, console: Console) -> bool:
    """Preload known ~/.claude/*.yaml buckets. If any fails, prompt user."""
    from installer._config_loader import ConfigLoadError, load_existing_yaml
    from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm

    buckets = ("proj", "worktree", "todoist", "trello", "jira")
    claude_home = Path.home() / ".claude"
    errors: dict[str, Exception] = {}
    for bucket in buckets:
        path = claude_home / f"{bucket}.yaml"
        if not path.exists():
            continue
        try:
            load_existing_yaml(path)
        except ConfigLoadError as exc:
            errors[bucket] = exc.original
    if errors:
        return show_corrupt_yaml_and_confirm(errors, console)
    return True
```

Invoked at top of `pre_install_phase` for ALL modes. If user cancels → return `PreInstallResult(proceed=False)`.

## File structure

**Created:**
- `installer/flow/form.py` — FieldSpec + run_form.
- `installer/flow/wizard.py` — `run_wizard(state, args, console) -> dict | None`.
- `installer/flow/advanced_config.py` — `run_advanced_config(console) -> dict | None`.
- `installer/flow/integration_config.py` — `configure_todoist(console) -> dict | None`, `configure_trello`, `configure_jira`, shared `_run_integration_form`.
- `installer/tests/flow/test_form.py`, `test_wizard.py`, `test_advanced_config.py`, `test_integration_config.py`, plus snapshot tests.

**Modified:**
- `installer/flow/installer_flow.py::_run_install` — invoke `run_wizard` + `configure_<integration>` after plugin selection, before hooks_diff. Also wire `run_advanced_config` on user request.
- `installer/flow/pre_install_phase.py` — add `_check_corrupt_yaml` step at top of every mode.

**Deleted at end:**
- `installer/screens/wizard.py`
- `installer/screens/advanced_config.py`
- `installer/screens/integration_config.py`
- `installer/screens/__init__.py` — becomes empty (`installer/screens/` directory removed entirely).
- Remaining Textual tests: `test_wizard.py`, `test_integration_screens.py`, `test_config_diff.py` (ConfigDiffScreen is used only by integration_config, which goes away here).
- E2E snapshot tests for these 4 screens + their SVG goldens.
- `installer/app.py` if its only content is migrate utilities that could move to `installer/migrations/` or `installer/flow/` — decide case-by-case.

**Deps:** NO changes — Textual still a dep after P4 because removing it is P5's scope.

## Feature-parity guarantee

Every field, every toggle, every validator, every API-validation call that existed before P4 MUST survive. No silent defaults change, no skipped validation.

**Parity checklist (implementer MUST verify):**

| Feature | Before (Textual) | After (prompt_toolkit) |
|---|---|---|
| Wizard: all AnswerSpec-driven fields (bool/string/int/select) | Textual Input/Switch/Select | `run_form` FieldSpec equivalents |
| Wizard: field groups (Git Tracking, etc.) | compose groups | FieldSpec.group |
| Wizard: conditional field visibility (e.g. git_tracking children hide when parent off) | `_on_git_tracking_toggle` | FieldSpec conditional rendering or post-process (decide during impl) |
| Wizard: existing yaml values pre-filled | `partition_answers_by_bucket` + lookup | Same helper, passed as `FieldSpec.default` |
| Advanced config: all fields | Textual | `run_form` |
| Advanced config: existing-yaml defaults | Yes | Yes |
| Integration: API token, api_key, base_url, email fields | Textual Input | FieldSpec kind="password"/"text" |
| Integration: sync_enabled + auto_sync toggles | Textual Switch | FieldSpec kind="bool" |
| Integration: root_only (Todoist), on_delete (Trello), epic_link_field (Jira) — service-specific | Subclass compose_fields | FieldSpec extension per subclass |
| Integration: existing-yaml credentials pre-filled | Yes | Yes — ~/.claude/<service>.yaml + proj.yaml::sync.<service> |
| Integration: async credential validation via httpx | async httpx.AsyncClient | sync httpx.Client inside console.status() spinner |
| Integration: validation error → re-prompt with pre-filled values | Yes | Yes — pass `error_message` + current answers to `run_form` again |
| Cancel at any screen → abort install flow | Yes | run_form returns None → caller returns None → installer_flow handles |
| Ctrl-C anywhere → exit 130 | Yes | KeyboardInterrupt caught in main.py |
| Corrupt yaml on load → CorruptYamlScreen | Inside WizardScreen | pre_install_phase `_check_corrupt_yaml` gate (fixes todo 679) |

**Latent bugs fixed (from parent spec):**
- B1 (Jira base_url format): FieldSpec.validator checks `https?://`.
- B2 (empty-credentials guard): validator rejects empty strings when sync enabled.
- B3 (URL trailing slash): validator normalizes `rstrip("/")`.
- B4-B5 (bare except in integration_config `_gather_values`): no `query_one` → no widget-miss hazard.
- B6 (bare except in advanced_config): same.
- B7 (bare except in wizard): same.
- B8 (wizard strip whitespace): FieldSpec validator does `.strip()` on text fields.
- B11 (integration_config initial focus on wrong widget): `run_form` focuses first field.
- B13 (plugin-name regex validation timing): already done in P3; no-op here.

## Testing strategy

**Unit tests per new module:**

- `test_form.py` — mock `prompt_toolkit.Application.run()` via monkeypatch; verify:
  - FieldSpec validators fire and block submission on error
  - Tab/Enter/Escape key bindings dispatch correctly (via `key_bindings.get_bindings_for_keys()`)
  - Submit → returns dict of collected values
  - Cancel → returns None
  - Empty field list → returns empty dict

- `test_wizard.py`, `test_advanced_config.py`, `test_integration_config.py` — mock `run_form` return + verify:
  - Existing yaml values pre-loaded into FieldSpec defaults (**key parity requirement**)
  - Submit path writes correct yaml bucket shape
  - Cancel path returns None, writes nothing
  - Validation retry re-prompts with pre-filled values + error_message

**Syrupy snapshots:**
- Surrounding panels / error banners rendered via Rich.
- NOT the prompt_toolkit form itself (dialogs aren't snapshottable without full terminal emulation).

**Behavioral e2e tests updated:**
- `test_install_flow.py`, `test_integration_flow.py`, `test_wizard_full_config.py` — swap `pilot.press()` for `mock_run_form.return_value` assertions.

## Rollout — 16 tasks in 1 FF-merge

Single feature branch `feat/672-p4-prompt-toolkit-forms`. Tasks (detail per-task in plan):

0. Fix todo 679: `_check_corrupt_yaml` in `pre_install_phase`.
1. Create `installer/flow/form.py` (FieldSpec + run_form + tests).
2. Port WizardScreen → `flow/wizard.py::run_wizard` (existing-yaml defaults verified).
3. Port AdvancedConfigScreen → `flow/advanced_config.py`.
4. Port BaseIntegrationScreen + Todoist into `flow/integration_config.py`.
5. Port Trello into `flow/integration_config.py`.
6. Port Jira into `flow/integration_config.py`.
7. Async-to-sync validation conversion (part of tasks 4-6 but broken out if complex).
8. Wire `run_wizard` + `configure_todoist` / `trello` / `jira` into `installer_flow._run_install`.
9. Wire `run_advanced_config` into `installer_flow` (invocation path TBD — likely `--advanced` flag or prompt).
10. Delete `installer/screens/wizard.py`.
11. Delete `installer/screens/advanced_config.py`.
12. Delete `installer/screens/integration_config.py`.
13. Delete remaining Textual tests + SVG goldens for these 4 screens.
14. Update snapshot inventory docstring (all 8 original screens removed).
15. Syrupy snapshots for wrapper panels + error banners.
16. Full test + FF-merge + CI watch.

**Exit criteria:**

- `grep -rn "from textual" installer/` returns empty in non-test paths (may remain in deleted test snapshots until P5).
- `installer/screens/` directory does not exist.
- `installer/flow/` is the single install-time UI module.
- Every pre-P4 wizard/config field has an equivalent FieldSpec with correct default-loading.
- All 15 latent bugs from parent spec have test coverage.
- CI green (modulo tracked flakes on todo 675).

**Rollback:** single FF-merge atomic. `git revert <merge>` restores all 3 Textual screens + their tests.

## Non-goals

- Not removing Textual from deps (P5).
- No new wizard fields / no UX redesign.
- No changes to yaml bucket schema.
- No changes to `cpm-install` CLI flags.
- No breaking changes for users — every setting they have today still appears + still pre-fills.

## Open questions

None — all decisions captured in brainstorming.

## References

- Parent spec: `docs/superpowers/specs/2026-04-19-installer-ui-framework-migration-design.md`
- P3 spec: `docs/superpowers/specs/2026-04-19-installer-ui-672-p3-kill-installerapp-design.md`
- Todos: 672 (parent), 677 (P4 tracker), 678 (P5 tracker), 679 (corrupt-yaml wiring — subsumed here).

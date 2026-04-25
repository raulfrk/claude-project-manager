# Wizard Back/Forth Navigation — Design Spec

**Todo**: 745
**Status**: design approved 2026-04-25
**Author**: Claude (Opus 4.7) via `superpowers:brainstorming`

## Problem

The post-install wizard (`installer/wizard.py` Rich `--no-tui` path + `installer/flow/*.py` TUI default path) is a flat sequential prompt chain. Users cannot revisit a previous prompt to fix a mistyped value — the only options are (a) submit + edit yaml afterward, or (b) Ctrl+C + restart the entire wizard. Both paths use sequential dialog primitives (`Rich.Prompt.ask` / `prompt_toolkit` shortcut dialogs) that have no native back affordance.

## Goals

1. **Single-step bidirectional navigation** in both wizard paths — every prompt offers a "back" affordance returning to the previous prompt.
2. **Preserve all answers across navigation** — going back reveals the prior prompt with its previously-submitted value as default; going forward re-uses the user's prior answer for downstream prompts.
3. **Block-level validation preserved** — integration credential checks (httpx-based) still run; on failure, cursor jumps back to the first step of that integration block + error banner shown.
4. **Setup foundation for 744 + 746** — step list is filterable by selected plugins (744); single driver loop is wrappable in a SIGINT handler (746).

## Non-Goals

- Free-jump navigation (jump to any prior step from a hub UI). Defer.
- Whole-form TUI rewrite (single Application w/ Tab-focus cycling). Defer; would be a larger redesign.
- 744 (skip prompts for unselected plugins) and 746 (Ctrl+C clean abort) are out of scope here — but the architecture deliberately enables them.

## Architecture

### Module Layout

New package `installer/wizard_engine/`:

```
installer/wizard_engine/
├── __init__.py
├── step.py          # WizardStep, WizardBlock, AdvanceResult, BackResult dataclasses
├── machine.py       # StepMachine: cursor + answer dict + advance/back/jump_to_block
└── renderers/
    ├── __init__.py
    ├── base.py      # Renderer protocol + Outcome union
    ├── rich.py      # RichRenderer (Rich Prompt + :back sentinel + ← Back option)
    └── tui.py       # TuiRenderer (prompt_toolkit + Back button + :back sentinel)
```

### Existing modules — refactor

| File | Change |
|------|--------|
| `installer/wizard.py` | `_setup_proj_yaml` / `_setup_worktree_yaml` / `_setup_*_config` become `build_*_steps()` factories returning `list[WizardStep]`. `run_wizard()` composes step list + drives `StepMachine` w/ `RichRenderer`. `_atomic_write` + post-loop yaml writers retained. |
| `installer/flow/wizard.py` | `run_wizard(state, args, console)` reuses `installer/wizard.py::build_proj_steps` + `build_worktree_steps`. Drives `StepMachine` w/ `TuiRenderer`. |
| `installer/flow/integration_config.py` | `configure_todoist` / `configure_trello` / `configure_jira` / `configure_confluence` / `configure_wiki` become `build_*_steps()` factories. Existing validators (`_todoist_validator` etc.) become `WizardBlock.validator` callbacks. |
| `installer/flow/form.py` | Mostly absorbed into `wizard_engine.renderers.tui`. `FieldSpec` either retained as a renderer-side input type or removed entirely. |
| `installer/flow/installer_flow.py` | Per-integration `configure_*` calls collapse into a single `StepMachine.run()` driving all selected plugins' steps end-to-end. |

### Data Flow

```
selected_plugins
   ↓
build_all_steps(selected_plugins)  →  ([WizardStep, ...], {block_id: WizardBlock, ...})
   ↓
StepMachine(steps, blocks) + Renderer
   ↓
loop:
    step = machine.current()
    outcome = renderer.render(step, default=step.default_factory(machine.answers()), banner=last_block_error)
    match outcome:
        Submitted(value):  result = machine.advance(value)
                           if result.block_error: continue  # cursor already jumped back
        BackRequested:     machine.back()
        Cancelled:         return None
   ↓
on done: answers dict
   ↓
_write_results(answers)  (per-bucket yaml writes; retains existing _atomic_write + diff-prompt logic)
```

## Data Model

```python
# step.py
from dataclasses import dataclass
from typing import Any, Callable, Literal

StepKind = Literal["text", "password", "bool", "int", "select"]

@dataclass(frozen=True)
class WizardStep:
    key: str                                       # dotted_key e.g. "tracking_dir" or "todoist.api_token"
    label: str
    kind: StepKind
    default_factory: Callable[[dict[str, Any]], Any]   # receives full answer dict so far
    choices: tuple[str, ...] | None = None
    int_range: tuple[int, int] | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None
    block_id: str | None = None                    # None = standalone step
    group: str | None = None                       # display heading (e.g. "── Tracking ──")
    sensitive: bool = False
    help_text: str | None = None
    yaml_file: str | None = None                   # destination bucket: proj/worktree/todoist/...

@dataclass(frozen=True)
class WizardBlock:
    block_id: str
    label: str                                     # "Jira Configuration"
    validator: Callable[[dict[str, Any]], str | None] | None = None
    # validator receives the full answers dict; returns None (OK) or err message string.
    # Always runs (regardless of any "enabled" sub-key) — validator impls handle their own
    # "disabled + empty = no error" semantics.

@dataclass
class AdvanceResult:
    next_step: WizardStep | None                   # None when wizard complete
    block_error: str | None = None                 # populated when block validator failed at end-of-block

@dataclass
class BackResult:
    prev_step: WizardStep | None
    at_start: bool = False                         # True if cursor was already at first step
```

```python
# machine.py
class StepMachine:
    def __init__(
        self,
        steps: list[WizardStep],
        blocks: dict[str, WizardBlock],
    ) -> None: ...

    def current(self) -> WizardStep | None:
        """Return current step, or None if wizard complete. Skips conditional-false."""

    def advance(self, value: Any) -> AdvanceResult:
        """Record answer for current step, advance cursor (skipping conditional-false).
        If we just left the last step of a block w/ a validator, run it.
        On validator failure: jump cursor to first step of block, return AdvanceResult(block_error=...).
        On validator success or no validator: return AdvanceResult(next_step=...)."""

    def back(self) -> BackResult:
        """Move cursor backward (skipping conditional-false steps).
        Answers dict is NOT modified — values persist for "preserve all" semantics.
        From first step: returns BackResult(at_start=True), cursor unchanged."""

    def jump_to_block(self, block_id: str) -> None:
        """Set cursor to first conditional-true step of the given block. Used by validator failure path."""

    def answers(self) -> dict[str, Any]:
        """Return current full answer dict. Renderer uses this for default_factory + banner state."""
```

### Invariants

- Cursor never lands on a `condition(answers) is False` step. Skip applies to both `advance()` and `back()`.
- `answers` dict is **never wiped** by `back()` or by block validator jump-back. Values persist throughout the session.
- `back()` from the first step returns `at_start=True` w/o moving cursor; renderer surfaces "already at first step".
- Block validators run inside `advance()` when the current step is the last conditional-true step of its block AND the next step is in a different block (or wizard end).
- Validator failure: cursor jumps to the block's first conditional-true step, block_error returned; renderer shows banner; answers dict preserved (re-prompts use prior values as defaults).

## Renderers

### Renderer Protocol

```python
# renderers/base.py
from dataclasses import dataclass
from typing import Any, Protocol

@dataclass(frozen=True)
class Submitted:
    value: Any

@dataclass(frozen=True)
class BackRequested:
    pass

@dataclass(frozen=True)
class Cancelled:
    pass

Outcome = Submitted | BackRequested | Cancelled

class Renderer(Protocol):
    def render(
        self,
        step: WizardStep,
        default: Any,
        banner: str | None = None,    # block validator error msg, or None
        at_start: bool = False,        # if True, suppress back affordance
    ) -> Outcome: ...
```

### RichRenderer (Rich `--no-tui` path)

- `text` / `password` / `int` (free-input): use `Rich.Prompt.ask` w/ help suffix "(type `:back` to go back)". Detect `:back` in returned string → `BackRequested`. Detect EOF (Ctrl+D) → `Cancelled`.
- `bool`: use `Rich.prompt_choice` w/ options `[Yes, No, ← Back]`. ← Back → `BackRequested`.
- `select`: use existing `prompt_choice` w/ user choices + appended `← Back` option.
- `at_start=True` → omit `← Back` option / drop `:back` hint from help suffix.
- Banner: Rich `console.print(f"[red]{banner}[/red]")` printed before the prompt.

### TuiRenderer (default TUI path)

- `text` / `password` / `int`: use `prompt_toolkit.shortcuts.input_dialog`. Cancel button → check what user typed; if `:back` → `BackRequested`, else `Cancelled`. (Limitation: `input_dialog` only has OK/Cancel; sentinel is the back affordance.)
- `bool`: replace `yes_no_dialog` w/ `button_dialog` having three buttons: `Yes`, `No`, `Back`. Back → `BackRequested`.
- `select`: append `← Back` as a sentinel option in the radiolist (`("__BACK__", "← Back")`). On submit, sentinel value `"__BACK__"` → `BackRequested`. The sentinel string `"__BACK__"` is reserved — `WizardStep.choices` MUST NOT contain it; renderer asserts this at construction. Chosen over `button_dialog` (3rd-button approach) for prompt_toolkit version safety + uniformity w/ the radiolist UX.
- `at_start=True` → omit Back button / Back option.
- Banner: prepend `f"[Error: {banner}]\n"` to dialog text (already done in current `_FormRunner`).

### Sentinel String

`:back` — chosen for visibility, low collision risk w/ legitimate values, and consistency between renderers' free-input fields. Documented in step's help suffix.

## Step Composition

### Factory Hierarchy

```python
# installer/wizard.py
def build_proj_steps(existing: dict, selected_plugins: list[str]) -> list[WizardStep]: ...
def build_worktree_steps(existing: dict) -> list[WizardStep]: ...

# installer/flow/integration_config.py
def build_todoist_steps(existing: dict) -> tuple[list[WizardStep], WizardBlock]: ...
def build_trello_steps(existing: dict) -> tuple[list[WizardStep], WizardBlock]: ...
def build_jira_steps(existing: dict) -> tuple[list[WizardStep], WizardBlock]: ...
def build_confluence_steps(existing: dict) -> tuple[list[WizardStep], WizardBlock]: ...
def build_wiki_steps(existing: dict, proj_selected: bool) -> list[WizardStep]: ...
    # Wiki has no credential validator — returns just steps, no WizardBlock.
    # Other integration factories return (steps, block) because they have validators.

# installer/wizard_engine/__init__.py
def build_all_steps(
    selected_plugins: list[str],
    existing_buckets: dict[str, dict],
) -> tuple[list[WizardStep], dict[str, WizardBlock]]:
    """Compose ordered step list + block registry from selected plugins."""
```

### Order

Identical to current sequential ordering (preserves user mental model):

1. proj steps (basic tier; condition-gated by selected_plugins ∩ proj-relevant)
2. worktree steps (basic tier; if "worktree" selected)
3. todoist block (if "todoist" selected)
4. trello block (if "trello" selected)
5. jira block (if "jira" selected)
6. confluence block (if "confluence" selected)
7. wiki block (if "wiki" selected; conditional on proj_selected for proj-integration fields)

### Conditional Steps

`WizardStep.condition(answers)` evaluated on every cursor move. Identical to current `PromptSpec.condition` lambdas (signature already takes a dict). Migration: lift existing conditions verbatim; replace `proj_existing` argument w/ slice of `answers` dict.

## Block Validators

### Run Trigger

Validator runs in `advance()` when:

- Current step has `block_id == B`
- `B` has a non-None validator
- Next conditional-true step has `block_id != B` (or there is no next step)

### Failure Path

```
1. AdvanceResult(next_step=None, block_error="<msg>") returned to driver.
2. StepMachine.jump_to_block(B) called by driver.
3. Driver loop continues; renderer.render() called for first step of B w/ banner=block_error.
4. User can fix any field, advance again; on next end-of-block, validator re-runs.
```

### Validator Contract

```python
def validator(answers: dict[str, Any]) -> str | None: ...
```

- Receives the full answers dict (not just the block's keys) — validators read their own block's fields by dotted key.
- Returns None on success, a non-empty string error message on failure.
- **Always runs** when its block is exited — validator impls own the "disabled + empty creds = no error" semantics. (Decision 2026-04-25.)

### Migration of Existing Validators

| Current | New |
|---------|-----|
| `_todoist_validator(values: dict) → str \| None` | Wrapped: `validator=lambda a: _todoist_validator({"api_token": a.get("todoist.api_token", ""), "sync_enabled": a.get("todoist.enabled", False)})` |
| `_trello_validator` | Same wrapping pattern. |
| `_jira_validator` | Same. Confirms post-742 fix uses `/rest/api/2/myself`. |
| `_confluence_validator` (if present) | Same. |
| Wiki validator (none currently) | No-op. |

Wrapper functions live in `installer/flow/integration_config.py`.

## Back/Forward UX

### From the user's perspective

- Every prompt shows a `← Back` option (select/bool) or `:back` sentinel hint (text/password/int).
- First step has no back affordance (or shows it grayed-out w/ "(at start)").
- Going back: previous prompt re-displayed, default = the user's prior answer.
- Going forward after going back: subsequent prompts retain prior answers as defaults (user can press Enter to accept).
- Hitting back through a block re-enters that block; validator does not re-run until the user advances out of the block again.
- Cancel (Esc / Ctrl+C / Ctrl+D mid-prompt): wizard exits, no yaml writes. (Clean SIGINT handling = todo 746.)

### Edge Cases

| Case | Behavior |
|------|----------|
| Back from first step | "Already at first step" banner; cursor unchanged. |
| Back across condition-toggle | If a `bool` step's value flips, `condition` re-evaluates on subsequent moves; some downstream steps may newly appear or disappear. Cursor lands on the next conditional-true step in the chosen direction. |
| Forward through a condition-disabled step | Skipped silently; cursor lands on next conditional-true step. |
| Validator failure mid-wizard | Banner shown on first re-prompt of the block. User can navigate freely within the block; validator re-runs on next exit. User can also press back from the block's first step → goes to last step of previous block. Answers from failed-validation block are preserved across this nav. |
| Empty step list (no plugins selected) | StepMachine.current() returns None immediately; driver writes nothing, returns success. |

## Signal / Abort Handling

`StepMachine.run()` (or the driver loop in `installer/wizard.py::run_wizard`) wraps the loop in `try/except KeyboardInterrupt` returning `None` cleanly. **No yaml writes happen during the loop** — writes are post-loop in `_write_results`. Therefore SIGINT mid-wizard naturally leaves no partial writes, satisfying 746's safety requirement at the architectural level.

Detailed signal handling (terminal restoration, subprocess cleanup, lifecycle hooks for TUI) is **out of scope for 745** and tracked as 746.

## Testing Strategy

### Unit (new — `installer/tests/wizard_engine/`)

| File | Coverage |
|------|----------|
| `test_machine.py` | Cursor advance / back / skip on conditional-false / preservation of answers across back / jump_to_block correctness / at_start behavior / empty step list / single-step list / multi-block ordering. ~25-30 tests. |
| `test_step.py` | WizardStep + WizardBlock dataclass invariants, default_factory called w/ answers dict. ~5 tests. |
| `test_renderer_rich.py` | Rich renderer dispatched correctly for each StepKind, sentinel detection, ← Back option appending, banner display. Mock `Console` + monkeypatch `Prompt.ask`. ~10 tests. |
| `test_renderer_tui.py` | TuiRenderer dispatched correctly, Back button → BackRequested, sentinel detection in input_dialog, banner prepended. Mock prompt_toolkit dialogs. ~10 tests. |
| `test_block_validators.py` | Validator triggered at block exit, failure → AdvanceResult.block_error + cursor jump, success → next_step populated, validator runs even when "enabled=False" (validator impls handle empty case). ~8 tests. |

### E2E Rich (extend `installer/tests/e2e/test_wizard_full_config.py`)

- New test: `test_rich_wizard_back_navigates_to_prior_step` — stdin scripts: enter value 1, enter value 2, type `:back`, change value 1, advance through. Assert final yaml has revised value 1.
- New test: `test_rich_wizard_back_preserves_forward_answers` — back nav + advance shows prior forward answer as default.
- New test: `test_rich_wizard_back_at_first_step_no_op` — `:back` at step 0 doesn't crash, prompts again.

### E2E TUI (new — `installer/tests/e2e/test_wizard_tui_nav.py`)

- New dependency: `pexpect` (added to dev deps via uv).
- Tests spawn `python -m installer.main` (no `--no-tui`) under a pty via `pexpect.spawn`. Send keys to drive prompt_toolkit dialogs; expect screen output.
- Test set: same scenarios as Rich e2e — back nav, preserve forward, at-start no-op, block validator jump-back.
- Skipped when `TERM` is unset or `pexpect` import fails (CI must explicitly enable).

### Existing test ports

- `installer/tests/flow/test_wizard.py` (`test_defaults_from_existing_proj_yaml`): refactor to call `build_proj_steps()` + assert WizardStep defaults instead of FieldSpec defaults.
- `installer/tests/test_wizard_specs.py`: unaffected (tests PromptSpec table contents, not flow).

## Migration Plan

Single feature branch `feat/745-wizard-nav` off `dev`. 6 commits, each independently green:

1. **Add `wizard_engine/` skeleton + `StepMachine` + unit tests** — pure-Python module, no integration. ~400 LOC.
2. **Add Renderer protocol + RichRenderer + TuiRenderer + renderer unit tests** — wired against StepMachine but not yet integrated. ~500 LOC.
3. **Port `_setup_proj_yaml` + `_setup_worktree_yaml` → step factories**; `installer/wizard.py::run_wizard` switches to drive StepMachine for proj+worktree blocks. Existing `_setup_*_config` calls retained for now. Tests: existing `installer/tests/flow/test_wizard.py` re-pointed to factories.
4. **Port `configure_todoist` / `configure_trello` / `configure_jira` / `configure_confluence` / `configure_wiki` → step factories + block validators**; `installer/flow/installer_flow.py::run_wizard` collapses per-integration calls into single StepMachine pass.
5. **Wire `installer/wizard.py` end-to-end to drive StepMachine across all blocks**; delete dead `installer/flow/form.py::_FormRunner` code; remove old `_setup_*_config` Rich functions superseded by factories.
6. **E2E tests**: extend `tests/e2e/test_wizard_full_config.py` (Rich) + add `tests/e2e/test_wizard_tui_nav.py` (pexpect, TUI).

After commit 6: branch fast-forward-merge to `dev` (per `[[ff-merge-convention]]`), single push, single CI run.

## Risks

| Risk | Mitigation |
|------|------------|
| `pexpect` adds CI dependency surface; flaky pty interactions | Mark TUI e2e tests `@pytest.mark.tui` + skip in default CI; opt-in via env var. |
| `prompt_toolkit.button_dialog` API may vary across versions | Spec defaults to sentinel-option fallback; choose at impl time based on installed version. |
| Existing `flow/form.py` `_FormRunner` rewrite invalidates `tests/flow/test_wizard.py` | Re-port test in commit 3; included in migration plan. |
| Block validator semantics change (always runs) may break existing CI tests w/ disabled-sync stubs | Validator wrappers must explicitly return None for disabled + empty cases; covered in `test_block_validators.py`. |
| Sentinel `:back` collision w/ legitimate user input | Exceedingly rare for path-like fields. Document in help suffix. Accept the risk. |

## Open Questions

None at design freeze.

## Sets up (downstream todos)

- **744 (skip prompts for unselected plugins)**: `build_all_steps(selected_plugins)` already accepts the selected list; 744 just refines the per-block gating logic. Trivial layer atop this design.
- **746 (Ctrl+C clean abort)**: `StepMachine.run()` driver loop is the single point to install a `signal.signal(SIGINT, ...)` handler + terminal cleanup. Architecturally enabled.

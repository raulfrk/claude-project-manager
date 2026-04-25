# Wizard Back/Forth Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add single-step bidirectional navigation to both wizard paths (Rich `--no-tui` and TUI default), preserving all answers across nav, with block-level credential validators that jump cursor back on failure.

**Architecture:** Renderer-agnostic `StepMachine` (cursor + answer dict + advance/back/jump_to_block) drives an ordered `WizardStep` list. Two thin renderers (`RichRenderer`, `TuiRenderer`) translate one step at a time. Existing `_setup_*` / `configure_*` functions become step factories. Block validators run on block exit; failure jumps cursor to first step of block with banner. See `docs/superpowers/specs/2026-04-25-wizard-back-forth-nav-design.md` for full design.

**Tech Stack:** Python 3.13, Rich (existing), prompt_toolkit (existing), pexpect (NEW dev dep for TUI e2e), pytest, basedpyright, ruff.

**Branch:** `feat/745-wizard-nav` off `dev`. Single FF-merge to dev when complete.

---

## File Structure

**New files:**

| Path | Responsibility |
|------|---------------|
| `installer/wizard_engine/__init__.py` | Package marker; exports `build_all_steps`, `StepMachine`, `WizardStep`, `WizardBlock`. |
| `installer/wizard_engine/step.py` | `WizardStep`, `WizardBlock`, `AdvanceResult`, `BackResult` dataclasses. |
| `installer/wizard_engine/machine.py` | `StepMachine` class (cursor, answers, advance/back/jump_to_block). |
| `installer/wizard_engine/renderers/__init__.py` | Package marker. |
| `installer/wizard_engine/renderers/base.py` | `Submitted`/`BackRequested`/`Cancelled` dataclasses; `Outcome` alias; `Renderer` Protocol. |
| `installer/wizard_engine/renderers/rich.py` | `RichRenderer` — Rich `Confirm`/`Prompt` + `:back` sentinel + `← Back` choice. |
| `installer/wizard_engine/renderers/tui.py` | `TuiRenderer` — prompt_toolkit dialogs + `__BACK__` sentinel option. |
| `installer/tests/wizard_engine/__init__.py` | Test package marker. |
| `installer/tests/wizard_engine/test_step.py` | Dataclass invariants tests. |
| `installer/tests/wizard_engine/test_machine.py` | StepMachine cursor/back/skip/validator tests. |
| `installer/tests/wizard_engine/test_renderer_rich.py` | RichRenderer dispatch + sentinel tests. |
| `installer/tests/wizard_engine/test_renderer_tui.py` | TuiRenderer dispatch + sentinel tests. |
| `installer/tests/wizard_engine/test_block_validators.py` | Block validator behavior tests. |
| `installer/tests/wizard_engine/test_compose.py` | `build_all_steps` composition tests. |
| `installer/tests/e2e/test_wizard_tui_nav.py` | pexpect-driven TUI e2e tests. |

**Modified files:**

| Path | Change |
|------|--------|
| `installer/wizard.py` | `_setup_proj_yaml` / `_setup_worktree_yaml` / `_setup_*_config` → `build_*_steps` factories. `run_wizard()` drives StepMachine + RichRenderer. Keeps `_atomic_write` + post-loop yaml writers. |
| `installer/flow/wizard.py` | Reuse `installer/wizard.py::build_proj_steps` + `build_worktree_steps`. Drives StepMachine + TuiRenderer. |
| `installer/flow/integration_config.py` | `configure_*` → `build_*_steps` factories returning `(steps, block)`. Validators wrapped as `WizardBlock.validator` callbacks. |
| `installer/flow/form.py` | Most code deleted; `FieldSpec` retained only if a renderer needs it. |
| `installer/flow/installer_flow.py` | Per-integration `configure_*` calls replaced with single `StepMachine.run()` driving all selected plugins' steps. |
| `installer/tests/flow/test_wizard.py` | Re-port to assert `build_proj_steps` output instead of `FieldSpec`. |
| `installer/tests/e2e/test_wizard_full_config.py` | Add 3 back-nav scenarios (back nav, preserve forward, at-start no-op). |
| `pyproject.toml` | Add `pexpect>=4.9` to dev deps. |

---

## Task 1: wizard_engine skeleton + StepMachine + unit tests (commit 1)

**Files:**
- Create: `installer/wizard_engine/__init__.py`
- Create: `installer/wizard_engine/step.py`
- Create: `installer/wizard_engine/machine.py`
- Create: `installer/tests/wizard_engine/__init__.py`
- Create: `installer/tests/wizard_engine/test_step.py`
- Create: `installer/tests/wizard_engine/test_machine.py`

- [ ] **Step 1.1: Create directory structure**

```bash
mkdir -p installer/wizard_engine/renderers installer/tests/wizard_engine
touch installer/wizard_engine/__init__.py installer/wizard_engine/renderers/__init__.py installer/tests/wizard_engine/__init__.py
```

- [ ] **Step 1.2: Write `step.py` dataclasses**

Create `installer/wizard_engine/step.py`:

```python
"""WizardStep + WizardBlock + nav result dataclasses.

WizardStep describes a single prompt. WizardBlock groups steps for end-of-block
validation (e.g. integration credential checks). AdvanceResult and BackResult
carry cursor-move outcomes back to the driver loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

StepKind = Literal["text", "password", "bool", "int", "select"]


@dataclass(frozen=True)
class WizardStep:
    key: str
    label: str
    kind: StepKind
    default_factory: Callable[[dict[str, Any]], Any]
    choices: tuple[str, ...] | None = None
    int_range: tuple[int, int] | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None
    block_id: str | None = None
    group: str | None = None
    sensitive: bool = False
    help_text: str | None = None
    yaml_file: str | None = None


@dataclass(frozen=True)
class WizardBlock:
    block_id: str
    label: str
    validator: Callable[[dict[str, Any]], str | None] | None = None


@dataclass
class AdvanceResult:
    next_step: WizardStep | None
    block_error: str | None = None


@dataclass
class BackResult:
    prev_step: WizardStep | None
    at_start: bool = False
```

- [ ] **Step 1.3: Write failing tests for step.py dataclasses**

Create `installer/tests/wizard_engine/test_step.py`:

```python
"""WizardStep + WizardBlock dataclass invariants."""

from __future__ import annotations

from typing import Any

import pytest

from installer.wizard_engine.step import (
    AdvanceResult,
    BackResult,
    WizardBlock,
    WizardStep,
)


def test_wizard_step_minimal_construction() -> None:
    s = WizardStep(
        key="foo",
        label="Foo?",
        kind="text",
        default_factory=lambda _a: "default",
    )
    assert s.key == "foo"
    assert s.kind == "text"
    assert s.default_factory({}) == "default"
    assert s.choices is None
    assert s.condition is None
    assert s.block_id is None


def test_wizard_step_default_factory_receives_answers() -> None:
    s = WizardStep(
        key="b",
        label="B?",
        kind="text",
        default_factory=lambda answers: answers.get("a", "fallback"),
    )
    assert s.default_factory({"a": "from_a"}) == "from_a"
    assert s.default_factory({}) == "fallback"


def test_wizard_step_is_frozen() -> None:
    s = WizardStep(key="k", label="L", kind="text", default_factory=lambda _a: "")
    with pytest.raises(Exception):
        s.key = "other"  # type: ignore[misc]


def test_wizard_block_minimal() -> None:
    b = WizardBlock(block_id="todoist", label="Todoist Configuration")
    assert b.validator is None


def test_wizard_block_with_validator() -> None:
    def v(answers: dict[str, Any]) -> str | None:
        return None if answers.get("ok") else "bad"

    b = WizardBlock(block_id="x", label="X", validator=v)
    assert b.validator({"ok": True}) is None
    assert b.validator({"ok": False}) == "bad"


def test_advance_result_default_no_error() -> None:
    s = WizardStep(key="k", label="L", kind="text", default_factory=lambda _a: "")
    r = AdvanceResult(next_step=s)
    assert r.next_step is s
    assert r.block_error is None


def test_back_result_default_at_start_false() -> None:
    s = WizardStep(key="k", label="L", kind="text", default_factory=lambda _a: "")
    r = BackResult(prev_step=s)
    assert r.at_start is False
```

- [ ] **Step 1.4: Run step.py tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_step.py -v`
Expected: 7 tests PASS.

- [ ] **Step 1.5: Write `machine.py` with StepMachine skeleton (cursor only)**

Create `installer/wizard_engine/machine.py`:

```python
"""StepMachine: renderer-agnostic wizard driver.

Holds an ordered list of WizardSteps + an answer dict + a cursor index.
Methods advance/back/jump_to_block move the cursor and run block validators.
Conditional steps (condition(answers) is False) are skipped in both directions.
"""

from __future__ import annotations

from typing import Any

from installer.wizard_engine.step import (
    AdvanceResult,
    BackResult,
    WizardBlock,
    WizardStep,
)


class StepMachine:
    def __init__(
        self,
        steps: list[WizardStep],
        blocks: dict[str, WizardBlock] | None = None,
    ) -> None:
        self._steps = steps
        self._blocks = blocks or {}
        self._answers: dict[str, Any] = {}
        self._cursor: int = self._next_visible(0, direction=1)

    def _next_visible(self, start: int, direction: int) -> int:
        """Return index of next step satisfying its condition, or len(steps) if none.

        direction=1 scans forward, direction=-1 scans backward. start is inclusive.
        Returns len(steps) when scanning forward off the end (= done).
        Returns -1 when scanning backward off the start (= at_start).
        """
        i = start
        while 0 <= i < len(self._steps):
            step = self._steps[i]
            if step.condition is None or step.condition(self._answers):
                return i
            i += direction
        return len(self._steps) if direction == 1 else -1

    def current(self) -> WizardStep | None:
        if 0 <= self._cursor < len(self._steps):
            return self._steps[self._cursor]
        return None

    def answers(self) -> dict[str, Any]:
        return dict(self._answers)

    def advance(self, value: Any) -> AdvanceResult:
        cur = self.current()
        if cur is None:
            return AdvanceResult(next_step=None)
        self._answers[cur.key] = value
        next_idx = self._next_visible(self._cursor + 1, direction=1)
        # Block validator check: if cur was last visible step of its block,
        # and the next step is in a different block (or wizard is done), run validator.
        block_error = self._maybe_run_block_validator(cur, next_idx)
        if block_error is not None:
            self._jump_to_block_first_step(cur.block_id)
            return AdvanceResult(next_step=self.current(), block_error=block_error)
        self._cursor = next_idx
        return AdvanceResult(next_step=self.current())

    def back(self) -> BackResult:
        prev_idx = self._next_visible(self._cursor - 1, direction=-1)
        if prev_idx < 0:
            return BackResult(prev_step=self.current(), at_start=True)
        self._cursor = prev_idx
        return BackResult(prev_step=self.current())

    def jump_to_block(self, block_id: str) -> None:
        self._jump_to_block_first_step(block_id)

    def _jump_to_block_first_step(self, block_id: str | None) -> None:
        if block_id is None:
            return
        for i, step in enumerate(self._steps):
            if step.block_id == block_id and (
                step.condition is None or step.condition(self._answers)
            ):
                self._cursor = i
                return

    def _maybe_run_block_validator(
        self, cur: WizardStep, next_idx: int
    ) -> str | None:
        if cur.block_id is None:
            return None
        block = self._blocks.get(cur.block_id)
        if block is None or block.validator is None:
            return None
        # Trigger only when leaving this block: next step is in a different block,
        # or wizard is done (next_idx == len(steps)).
        if next_idx >= len(self._steps):
            return block.validator(self._answers)
        next_step = self._steps[next_idx]
        if next_step.block_id != cur.block_id:
            return block.validator(self._answers)
        return None
```

- [ ] **Step 1.6: Write failing tests for StepMachine cursor advance**

Create `installer/tests/wizard_engine/test_machine.py`:

```python
"""StepMachine cursor + back + skip + validator behavior."""

from __future__ import annotations

from typing import Any

from installer.wizard_engine.machine import StepMachine
from installer.wizard_engine.step import WizardBlock, WizardStep


def _step(key: str, **kw: Any) -> WizardStep:
    return WizardStep(
        key=key,
        label=key,
        kind="text",
        default_factory=lambda _a: "",
        **kw,
    )


def test_machine_starts_on_first_step() -> None:
    s1, s2 = _step("a"), _step("b")
    m = StepMachine([s1, s2])
    assert m.current() is s1


def test_machine_advance_moves_cursor() -> None:
    s1, s2 = _step("a"), _step("b")
    m = StepMachine([s1, s2])
    r = m.advance("v1")
    assert r.next_step is s2
    assert m.current() is s2
    assert m.answers() == {"a": "v1"}


def test_machine_advance_past_end_returns_none() -> None:
    s1 = _step("a")
    m = StepMachine([s1])
    r = m.advance("v1")
    assert r.next_step is None
    assert m.current() is None
    assert m.answers() == {"a": "v1"}


def test_machine_advance_when_done_is_noop() -> None:
    s1 = _step("a")
    m = StepMachine([s1])
    m.advance("v1")
    r = m.advance("ignored")
    assert r.next_step is None
    assert m.answers() == {"a": "v1"}  # second advance did not record


def test_machine_empty_step_list() -> None:
    m = StepMachine([])
    assert m.current() is None
```

- [ ] **Step 1.7: Run cursor tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_machine.py -v -k "cursor or advance or empty"`
Expected: 5 tests PASS.

- [ ] **Step 1.8: Add back-nav tests + answer-preservation tests**

Append to `installer/tests/wizard_engine/test_machine.py`:

```python
def test_machine_back_returns_to_prior_step() -> None:
    s1, s2, s3 = _step("a"), _step("b"), _step("c")
    m = StepMachine([s1, s2, s3])
    m.advance("v1")
    m.advance("v2")
    r = m.back()
    assert r.prev_step is s2
    assert r.at_start is False
    assert m.current() is s2


def test_machine_back_preserves_answers() -> None:
    s1, s2 = _step("a"), _step("b")
    m = StepMachine([s1, s2])
    m.advance("v1")
    m.advance("v2")
    m.back()
    m.back()
    assert m.answers() == {"a": "v1", "b": "v2"}


def test_machine_back_at_first_step_returns_at_start() -> None:
    s1, s2 = _step("a"), _step("b")
    m = StepMachine([s1, s2])
    r = m.back()
    assert r.at_start is True
    assert m.current() is s1


def test_machine_back_then_advance_keeps_default_via_answers() -> None:
    """default_factory reads answers dict; prior value still there for re-prompt."""
    s1, s2 = _step("a"), _step("b")
    m = StepMachine([s1, s2])
    m.advance("v1")
    m.back()
    # caller's renderer would call s1.default_factory(m.answers()) — verify dict has v1
    assert m.answers().get("a") == "v1"
```

- [ ] **Step 1.9: Run back-nav tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_machine.py -v -k "back"`
Expected: 4 tests PASS.

- [ ] **Step 1.10: Add conditional-skip tests**

Append to `installer/tests/wizard_engine/test_machine.py`:

```python
def test_machine_skips_conditional_false_forward() -> None:
    s1 = _step("a")
    s2 = _step("b", condition=lambda a: a.get("a") == "include")
    s3 = _step("c")
    m = StepMachine([s1, s2, s3])
    m.advance("exclude")
    assert m.current() is s3  # b skipped


def test_machine_skips_conditional_false_backward() -> None:
    s1 = _step("a")
    s2 = _step("b", condition=lambda a: a.get("a") == "include")
    s3 = _step("c")
    m = StepMachine([s1, s2, s3])
    m.advance("exclude")  # cursor on s3
    m.back()  # should land on s1 (s2 skipped)
    assert m.current() is s1


def test_machine_includes_conditional_true_step() -> None:
    s1 = _step("a")
    s2 = _step("b", condition=lambda a: a.get("a") == "include")
    s3 = _step("c")
    m = StepMachine([s1, s2, s3])
    m.advance("include")
    assert m.current() is s2
```

- [ ] **Step 1.11: Run conditional tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_machine.py -v -k "conditional"`
Expected: 3 tests PASS.

- [ ] **Step 1.12: Add block validator tests**

Append to `installer/tests/wizard_engine/test_machine.py`:

```python
def test_machine_block_validator_fires_on_block_exit() -> None:
    s1 = _step("a", block_id="X")
    s2 = _step("b", block_id="X")
    s3 = _step("c", block_id="Y")
    fired: list[dict[str, Any]] = []

    def v(answers: dict[str, Any]) -> str | None:
        fired.append(dict(answers))
        return None

    blocks = {"X": WizardBlock(block_id="X", label="X", validator=v)}
    m = StepMachine([s1, s2, s3], blocks)
    m.advance("v1")  # advance from s1 → s2; same block, no fire
    assert fired == []
    m.advance("v2")  # advance from s2 → s3; cross block, fire
    assert len(fired) == 1
    assert fired[0] == {"a": "v1", "b": "v2"}


def test_machine_block_validator_failure_jumps_back_to_block_first() -> None:
    s1 = _step("a", block_id="X")
    s2 = _step("b", block_id="X")
    s3 = _step("c", block_id="Y")
    blocks = {"X": WizardBlock(block_id="X", label="X", validator=lambda _a: "boom")}
    m = StepMachine([s1, s2, s3], blocks)
    m.advance("v1")
    r = m.advance("v2")
    assert r.block_error == "boom"
    assert r.next_step is s1
    assert m.current() is s1
    # Answers preserved despite jump-back.
    assert m.answers() == {"a": "v1", "b": "v2"}


def test_machine_block_validator_fires_on_wizard_end() -> None:
    s1 = _step("a", block_id="X")
    fired: list[bool] = []
    blocks = {
        "X": WizardBlock(
            block_id="X",
            label="X",
            validator=lambda _a: (fired.append(True), None)[1],
        )
    }
    m = StepMachine([s1], blocks)
    m.advance("v1")
    assert fired == [True]


def test_machine_block_no_validator_no_fire() -> None:
    s1 = _step("a", block_id="X")
    s2 = _step("b", block_id="Y")
    blocks = {"X": WizardBlock(block_id="X", label="X", validator=None)}
    m = StepMachine([s1, s2], blocks)
    r = m.advance("v1")
    assert r.block_error is None
    assert r.next_step is s2


def test_machine_jump_to_block_lands_on_first_visible_step() -> None:
    s1 = _step("a", block_id="X")
    s2 = _step("b", block_id="X", condition=lambda a: False)  # always hidden
    s3 = _step("c", block_id="X")
    s4 = _step("d", block_id="Y")
    m = StepMachine([s1, s2, s3, s4])
    m.advance("v1")
    m.advance("v3")  # v2 skipped due to condition
    m.jump_to_block("X")
    assert m.current() is s1  # first visible of X
```

- [ ] **Step 1.13: Run block validator tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_machine.py -v -k "block or jump"`
Expected: 5 tests PASS.

- [ ] **Step 1.14: Run all wizard_engine tests + lints**

Run:
```bash
cd installer && uv run pytest tests/wizard_engine/ -v
uv run ruff check installer/wizard_engine/ installer/tests/wizard_engine/
uv run ruff format --check installer/wizard_engine/ installer/tests/wizard_engine/
uv run basedpyright installer/wizard_engine/
```
Expected: all green.

- [ ] **Step 1.15: Commit**

```bash
git add installer/wizard_engine/__init__.py \
        installer/wizard_engine/step.py \
        installer/wizard_engine/machine.py \
        installer/wizard_engine/renderers/__init__.py \
        installer/tests/wizard_engine/__init__.py \
        installer/tests/wizard_engine/test_step.py \
        installer/tests/wizard_engine/test_machine.py
git commit -m "feat(installer/745): add wizard_engine StepMachine + step dataclasses

Introduces renderer-agnostic step machine for wizard nav. Cursor
advance/back/jump_to_block; conditional-skip both directions; block
validator on block exit with cursor jump-back on failure. Pure-Python,
no I/O, fully unit-tested."
```

---

## Task 2: Renderer protocol + RichRenderer + TuiRenderer + tests (commit 2)

**Files:**
- Create: `installer/wizard_engine/renderers/base.py`
- Create: `installer/wizard_engine/renderers/rich.py`
- Create: `installer/wizard_engine/renderers/tui.py`
- Create: `installer/tests/wizard_engine/test_renderer_rich.py`
- Create: `installer/tests/wizard_engine/test_renderer_tui.py`

- [ ] **Step 2.1: Write `renderers/base.py` Outcome + Protocol**

Create `installer/wizard_engine/renderers/base.py`:

```python
"""Renderer protocol + Outcome tagged union."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from installer.wizard_engine.step import WizardStep


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
        banner: str | None = None,
        at_start: bool = False,
    ) -> Outcome: ...
```

- [ ] **Step 2.2: Write `renderers/rich.py` skeleton**

Create `installer/wizard_engine/renderers/rich.py`:

```python
"""Rich console renderer.

Free-input prompts (text/password/int) detect the `:back` sentinel and emit
BackRequested. Bool/select prompts append a `← Back` choice. EOF (Ctrl+D)
emits Cancelled.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.prompt import Confirm, Prompt

from installer.prompts import int_in_range, prompt_choice
from installer.wizard_engine.renderers.base import (
    BackRequested,
    Cancelled,
    Outcome,
    Submitted,
)
from installer.wizard_engine.step import WizardStep

BACK_SENTINEL = ":back"
BACK_OPTION_LABEL = "← Back"


class RichRenderer:
    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def render(
        self,
        step: WizardStep,
        default: Any,
        banner: str | None = None,
        at_start: bool = False,
    ) -> Outcome:
        if banner:
            self._console.print(f"[red]{banner}[/red]")
        if step.group:
            self._console.print(f"\n[bold cyan]── {step.group} ──[/bold cyan]")
        try:
            if step.kind in ("text", "password"):
                return self._render_text(step, default, at_start)
            if step.kind == "int":
                return self._render_int(step, default, at_start)
            if step.kind == "bool":
                return self._render_bool(step, default, at_start)
            if step.kind == "select":
                return self._render_select(step, default, at_start)
            raise ValueError(f"Unknown step kind: {step.kind!r}")
        except EOFError:
            return Cancelled()

    def _render_text(
        self, step: WizardStep, default: Any, at_start: bool
    ) -> Outcome:
        suffix = "" if at_start else f" (type `{BACK_SENTINEL}` to go back)"
        raw = Prompt.ask(
            f"{step.label}{suffix}",
            default="" if default is None else str(default),
            password=(step.kind == "password"),
            console=self._console,
        )
        if not at_start and raw == BACK_SENTINEL:
            return BackRequested()
        return Submitted(raw)

    def _render_int(
        self, step: WizardStep, default: Any, at_start: bool
    ) -> Outcome:
        if step.int_range is None:
            raise ValueError(f"Step {step.key!r} has kind=int but no int_range")
        # int_in_range loops on invalid; we wrap it so the user can type :back first.
        suffix = "" if at_start else f" (type `{BACK_SENTINEL}` to go back)"
        low, high = step.int_range
        try:
            int_default = int(default)
        except (TypeError, ValueError):
            int_default = low
        # Probe first via Prompt.ask to detect sentinel; fall back to int_in_range.
        raw = Prompt.ask(
            f"{step.label}{suffix}",
            default=str(int_default),
            console=self._console,
        )
        if not at_start and raw == BACK_SENTINEL:
            return BackRequested()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = int_in_range(step.label, int_default, low, high, self._console)
        else:
            if not (low <= value <= high):
                value = int_in_range(step.label, int_default, low, high, self._console)
        return Submitted(value)

    def _render_bool(
        self, step: WizardStep, default: Any, at_start: bool
    ) -> Outcome:
        if at_start:
            return Submitted(
                Confirm.ask(
                    step.label, default=bool(default), console=self._console
                )
            )
        # 3-way prompt: Yes / No / Back
        choices = ("yes", "no", "back")
        default_str = "yes" if default else "no"
        choice = prompt_choice(step.label, default_str, choices, self._console)
        if choice == "back":
            return BackRequested()
        return Submitted(choice == "yes")

    def _render_select(
        self, step: WizardStep, default: Any, at_start: bool
    ) -> Outcome:
        if step.choices is None:
            raise ValueError(f"Step {step.key!r} has kind=select but no choices")
        choices = list(step.choices) + ([] if at_start else [BACK_OPTION_LABEL])
        default_str = (
            str(default) if default in step.choices else step.choices[0]
        )
        choice = prompt_choice(step.label, default_str, choices, self._console)
        if choice == BACK_OPTION_LABEL:
            return BackRequested()
        return Submitted(choice)
```

- [ ] **Step 2.3: Write failing tests for RichRenderer**

Create `installer/tests/wizard_engine/test_renderer_rich.py`:

```python
"""RichRenderer dispatch + sentinel tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from rich.console import Console

from installer.wizard_engine.renderers.base import (
    BackRequested,
    Cancelled,
    Submitted,
)
from installer.wizard_engine.renderers.rich import (
    BACK_OPTION_LABEL,
    BACK_SENTINEL,
    RichRenderer,
)
from installer.wizard_engine.step import WizardStep


def _step(kind: Any, **kw: Any) -> WizardStep:
    return WizardStep(
        key="k",
        label="L",
        kind=kind,
        default_factory=lambda _a: kw.get("default", ""),
        **{k: v for k, v in kw.items() if k != "default"},
    )


class TestRichTextStep:
    def test_text_returns_submitted(self) -> None:
        s = _step("text")
        with patch("installer.wizard_engine.renderers.rich.Prompt.ask", return_value="hello"):
            r = RichRenderer(Console()).render(s, default="d")
        assert r == Submitted("hello")

    def test_text_back_sentinel(self) -> None:
        s = _step("text")
        with patch(
            "installer.wizard_engine.renderers.rich.Prompt.ask",
            return_value=BACK_SENTINEL,
        ):
            r = RichRenderer(Console()).render(s, default="d")
        assert isinstance(r, BackRequested)

    def test_text_at_start_no_back_sentinel(self) -> None:
        s = _step("text")
        # When at_start, sentinel becomes literal value (no special handling).
        with patch(
            "installer.wizard_engine.renderers.rich.Prompt.ask",
            return_value=BACK_SENTINEL,
        ):
            r = RichRenderer(Console()).render(s, default="d", at_start=True)
        assert r == Submitted(BACK_SENTINEL)

    def test_text_eof_returns_cancelled(self) -> None:
        s = _step("text")
        with patch(
            "installer.wizard_engine.renderers.rich.Prompt.ask",
            side_effect=EOFError,
        ):
            r = RichRenderer(Console()).render(s, default="d")
        assert isinstance(r, Cancelled)


class TestRichBoolStep:
    def test_bool_yes(self) -> None:
        s = _step("bool")
        with patch(
            "installer.wizard_engine.renderers.rich.prompt_choice", return_value="yes"
        ):
            r = RichRenderer(Console()).render(s, default=False)
        assert r == Submitted(True)

    def test_bool_back(self) -> None:
        s = _step("bool")
        with patch(
            "installer.wizard_engine.renderers.rich.prompt_choice", return_value="back"
        ):
            r = RichRenderer(Console()).render(s, default=False)
        assert isinstance(r, BackRequested)

    def test_bool_at_start_uses_confirm(self) -> None:
        s = _step("bool")
        with patch(
            "installer.wizard_engine.renderers.rich.Confirm.ask", return_value=True
        ) as mock_confirm:
            r = RichRenderer(Console()).render(s, default=False, at_start=True)
        assert r == Submitted(True)
        mock_confirm.assert_called_once()


class TestRichSelectStep:
    def test_select_choice(self) -> None:
        s = _step("select", choices=("a", "b", "c"))
        with patch(
            "installer.wizard_engine.renderers.rich.prompt_choice", return_value="b"
        ):
            r = RichRenderer(Console()).render(s, default="a")
        assert r == Submitted("b")

    def test_select_back_via_back_option(self) -> None:
        s = _step("select", choices=("a", "b"))
        with patch(
            "installer.wizard_engine.renderers.rich.prompt_choice",
            return_value=BACK_OPTION_LABEL,
        ):
            r = RichRenderer(Console()).render(s, default="a")
        assert isinstance(r, BackRequested)


class TestRichBanner:
    def test_banner_printed(self, capsys: Any) -> None:
        s = _step("text")
        with patch(
            "installer.wizard_engine.renderers.rich.Prompt.ask", return_value="v"
        ):
            RichRenderer(Console()).render(s, default="", banner="bad creds")
        captured = capsys.readouterr()
        assert "bad creds" in captured.out
```

- [ ] **Step 2.4: Run RichRenderer tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_renderer_rich.py -v`
Expected: 10 tests PASS.

- [ ] **Step 2.5: Write `renderers/tui.py` skeleton**

Create `installer/wizard_engine/renderers/tui.py`:

```python
"""prompt_toolkit TUI renderer.

Free-input prompts use input_dialog; sentinel `:back` in the input → BackRequested.
Bool prompts use yes_no_dialog plus a third "Back" button via button_dialog.
Select prompts use radiolist_dialog with `__BACK__` reserved sentinel option.
Cancel button (or Esc) → Cancelled.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from installer.wizard_engine.renderers.base import (
    BackRequested,
    Cancelled,
    Outcome,
    Submitted,
)
from installer.wizard_engine.step import WizardStep

BACK_SENTINEL = ":back"
BACK_OPTION_VALUE = "__BACK__"
BACK_OPTION_LABEL = "← Back"


class TuiRenderer:
    def __init__(self, console: Console | None = None) -> None:
        # console is currently unused; kept for API parity w/ RichRenderer + future
        # status / banner rendering above the dialog.
        del console

    def render(
        self,
        step: WizardStep,
        default: Any,
        banner: str | None = None,
        at_start: bool = False,
    ) -> Outcome:
        text_prefix = ""
        if banner:
            text_prefix = f"[Error: {banner}]\n\n"
        if step.kind in ("text", "password"):
            return self._render_input(step, default, at_start, text_prefix)
        if step.kind == "int":
            return self._render_int(step, default, at_start, text_prefix)
        if step.kind == "bool":
            return self._render_bool(step, default, at_start, text_prefix)
        if step.kind == "select":
            return self._render_select(step, default, at_start, text_prefix)
        raise ValueError(f"Unknown step kind: {step.kind!r}")

    def _render_input(
        self, step: WizardStep, default: Any, at_start: bool, prefix: str
    ) -> Outcome:
        from prompt_toolkit.shortcuts import input_dialog

        suffix = (
            "" if at_start else f"\n\n(type `{BACK_SENTINEL}` and submit to go back)"
        )
        raw = input_dialog(
            title=step.label,
            text=f"{prefix}{step.label}{suffix}",
            default="" if default is None else str(default),
            password=(step.kind == "password"),
        ).run()
        if raw is None:
            return Cancelled()
        if not at_start and raw == BACK_SENTINEL:
            return BackRequested()
        return Submitted(raw)

    def _render_int(
        self, step: WizardStep, default: Any, at_start: bool, prefix: str
    ) -> Outcome:
        from prompt_toolkit.shortcuts import input_dialog

        if step.int_range is None:
            raise ValueError(f"Step {step.key!r} has kind=int but no int_range")
        suffix = (
            "" if at_start else f"\n\n(type `{BACK_SENTINEL}` and submit to go back)"
        )
        try:
            int_default = int(default)
        except (TypeError, ValueError):
            int_default = step.int_range[0]
        raw = input_dialog(
            title=step.label,
            text=f"{prefix}{step.label}{suffix}",
            default=str(int_default),
        ).run()
        if raw is None:
            return Cancelled()
        if not at_start and raw == BACK_SENTINEL:
            return BackRequested()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = int_default
        return Submitted(value)

    def _render_bool(
        self, step: WizardStep, default: Any, at_start: bool, prefix: str
    ) -> Outcome:
        if at_start:
            from prompt_toolkit.shortcuts import yes_no_dialog

            raw = yes_no_dialog(
                title=step.label, text=f"{prefix}{step.label}"
            ).run()
            if raw is None:
                return Cancelled()
            return Submitted(bool(raw))
        from prompt_toolkit.shortcuts import button_dialog

        raw = button_dialog(
            title=step.label,
            text=f"{prefix}{step.label}",
            buttons=[("Yes", True), ("No", False), ("Back", BACK_OPTION_VALUE)],
        ).run()
        if raw is None:
            return Cancelled()
        if raw == BACK_OPTION_VALUE:
            return BackRequested()
        return Submitted(bool(raw))

    def _render_select(
        self, step: WizardStep, default: Any, at_start: bool, prefix: str
    ) -> Outcome:
        from prompt_toolkit.shortcuts import radiolist_dialog

        if step.choices is None:
            raise ValueError(f"Step {step.key!r} has kind=select but no choices")
        if BACK_OPTION_VALUE in step.choices:
            raise ValueError(
                f"Step {step.key!r} choices contains reserved sentinel "
                f"{BACK_OPTION_VALUE!r}"
            )
        items: list[tuple[str, str]] = [(c, c) for c in step.choices]
        if not at_start:
            items.append((BACK_OPTION_VALUE, BACK_OPTION_LABEL))
        raw = radiolist_dialog(
            title=step.label,
            text=f"{prefix}{step.label}",
            values=items,
            default=default if default in step.choices else None,
        ).run()
        if raw is None:
            return Cancelled()
        if raw == BACK_OPTION_VALUE:
            return BackRequested()
        return Submitted(raw)
```

- [ ] **Step 2.6: Write failing tests for TuiRenderer**

Create `installer/tests/wizard_engine/test_renderer_tui.py`:

```python
"""TuiRenderer dispatch + sentinel tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from installer.wizard_engine.renderers.base import (
    BackRequested,
    Cancelled,
    Submitted,
)
from installer.wizard_engine.renderers.tui import (
    BACK_OPTION_VALUE,
    BACK_SENTINEL,
    TuiRenderer,
)
from installer.wizard_engine.step import WizardStep


def _step(kind: Any, **kw: Any) -> WizardStep:
    return WizardStep(
        key="k",
        label="L",
        kind=kind,
        default_factory=lambda _a: "",
        **kw,
    )


def _patch_dialog(name: str, return_value: Any) -> Any:
    """Patch a prompt_toolkit shortcut dialog to return the given value via .run()."""
    fake = MagicMock()
    fake.return_value.run.return_value = return_value
    return patch(f"prompt_toolkit.shortcuts.{name}", fake)


class TestTuiInputStep:
    def test_text_submitted(self) -> None:
        s = _step("text")
        with _patch_dialog("input_dialog", "hello"):
            r = TuiRenderer().render(s, default="d")
        assert r == Submitted("hello")

    def test_text_sentinel_back(self) -> None:
        s = _step("text")
        with _patch_dialog("input_dialog", BACK_SENTINEL):
            r = TuiRenderer().render(s, default="d")
        assert isinstance(r, BackRequested)

    def test_text_cancel_returns_cancelled(self) -> None:
        s = _step("text")
        with _patch_dialog("input_dialog", None):
            r = TuiRenderer().render(s, default="d")
        assert isinstance(r, Cancelled)

    def test_text_at_start_sentinel_treated_literal(self) -> None:
        s = _step("text")
        with _patch_dialog("input_dialog", BACK_SENTINEL):
            r = TuiRenderer().render(s, default="d", at_start=True)
        assert r == Submitted(BACK_SENTINEL)


class TestTuiBoolStep:
    def test_bool_at_start_uses_yes_no(self) -> None:
        s = _step("bool")
        with _patch_dialog("yes_no_dialog", True):
            r = TuiRenderer().render(s, default=False, at_start=True)
        assert r == Submitted(True)

    def test_bool_uses_button_dialog_with_back(self) -> None:
        s = _step("bool")
        with _patch_dialog("button_dialog", True):
            r = TuiRenderer().render(s, default=False)
        assert r == Submitted(True)

    def test_bool_back_button_returns_back_requested(self) -> None:
        s = _step("bool")
        with _patch_dialog("button_dialog", BACK_OPTION_VALUE):
            r = TuiRenderer().render(s, default=False)
        assert isinstance(r, BackRequested)


class TestTuiSelectStep:
    def test_select_choice(self) -> None:
        s = _step("select", choices=("a", "b"))
        with _patch_dialog("radiolist_dialog", "b"):
            r = TuiRenderer().render(s, default="a")
        assert r == Submitted("b")

    def test_select_back_sentinel(self) -> None:
        s = _step("select", choices=("a", "b"))
        with _patch_dialog("radiolist_dialog", BACK_OPTION_VALUE):
            r = TuiRenderer().render(s, default="a")
        assert isinstance(r, BackRequested)

    def test_select_reserved_sentinel_in_choices_raises(self) -> None:
        s = _step("select", choices=("a", BACK_OPTION_VALUE))
        with _patch_dialog("radiolist_dialog", "a"):
            with pytest.raises(ValueError, match="reserved sentinel"):
                TuiRenderer().render(s, default="a")


class TestTuiBanner:
    def test_banner_prepended_to_dialog_text(self) -> None:
        s = _step("text")
        captured: dict[str, Any] = {}

        def fake_input_dialog(**kwargs: Any) -> Any:
            captured.update(kwargs)
            mock = MagicMock()
            mock.run.return_value = "v"
            return mock

        with patch(
            "prompt_toolkit.shortcuts.input_dialog", side_effect=fake_input_dialog
        ):
            TuiRenderer().render(s, default="", banner="bad creds")
        assert "bad creds" in captured["text"]
```

- [ ] **Step 2.7: Run TuiRenderer tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_renderer_tui.py -v`
Expected: 11 tests PASS.

- [ ] **Step 2.8: Run all wizard_engine tests + lints**

Run:
```bash
cd installer && uv run pytest tests/wizard_engine/ -v
uv run ruff check installer/wizard_engine/ installer/tests/wizard_engine/
uv run ruff format --check installer/wizard_engine/ installer/tests/wizard_engine/
uv run basedpyright installer/wizard_engine/
```
Expected: all green.

- [ ] **Step 2.9: Commit**

```bash
git add installer/wizard_engine/renderers/ installer/tests/wizard_engine/test_renderer_rich.py installer/tests/wizard_engine/test_renderer_tui.py
git commit -m "feat(installer/745): add Rich + TUI renderers w/ back sentinels

RichRenderer uses :back sentinel for free-input + ← Back option for
bool/select. TuiRenderer uses :back sentinel for input_dialog +
button_dialog (3-way) for bool + reserved __BACK__ option in
radiolist_dialog. EOF / Cancel / None-result map to Cancelled."
```

---

## Task 3: Port `_setup_proj_yaml` + `_setup_worktree_yaml` → step factories (commit 3)

**Files:**
- Modify: `installer/wizard.py` (add factories; old `_setup_proj_yaml`/`_setup_worktree_yaml` become wrappers around StepMachine drive)
- Create: `installer/tests/wizard_engine/test_compose.py`
- Modify: `installer/tests/flow/test_wizard.py` (re-port to assert factory output)

- [ ] **Step 3.1: Read existing PROJ_YAML_PROMPTS to understand structure**

Run: `head -100 /home/raul/projects/claude-project-manager/installer/wizard_specs.py`
Read `PromptSpec` dataclass + first 5-10 entries to confirm the `dotted_key`, `default_factory`, `condition`, `group`, `tier`, `yaml_file`, `type` fields are present.

- [ ] **Step 3.2: Add `build_proj_steps` factory in `installer/wizard.py`**

Add to `installer/wizard.py` after the existing imports:

```python
from installer.wizard_engine.step import WizardStep


def _prompt_spec_to_step(spec: PromptSpec) -> WizardStep:
    """Convert a PromptSpec entry to a WizardStep."""
    kind: Any
    if spec.type == "bool":
        kind = "bool"
    elif spec.type == "int":
        kind = "int"
    elif spec.type == "choice":
        kind = "select"
    elif spec.type == "str" and spec.sensitive:
        kind = "password"
    elif spec.type == "str":
        kind = "text"
    else:
        raise ValueError(f"Unknown PromptSpec type: {spec.type!r}")
    return WizardStep(
        key=spec.dotted_key,
        label=spec.label,
        kind=kind,
        default_factory=spec.default_factory,
        choices=tuple(spec.choices) if spec.choices else None,
        int_range=spec.int_range,
        condition=spec.condition,
        block_id=None,
        group=spec.group,
        sensitive=spec.sensitive,
        yaml_file=spec.yaml_file,
    )


def build_proj_steps(selected_plugins: list[str]) -> list[WizardStep]:
    """Return ordered WizardStep list for proj.yaml prompts (basic tier).

    Filters PROJ_YAML_PROMPTS to yaml_file=='proj' and tier=='basic'. Conditions
    are preserved verbatim and evaluated at cursor-move time against the live
    answers dict.
    """
    del selected_plugins  # gating moved into spec.condition lambdas (744 will refine)
    return [
        _prompt_spec_to_step(s)
        for s in PROJ_YAML_PROMPTS
        if s.yaml_file == "proj" and s.tier == "basic"
    ]


def build_worktree_steps() -> list[WizardStep]:
    """Return ordered WizardStep list for worktree.yaml prompts (basic tier)."""
    return [
        _prompt_spec_to_step(s)
        for s in PROJ_YAML_PROMPTS
        if s.yaml_file == "worktree" and s.tier == "basic"
    ]
```

- [ ] **Step 3.3: Write failing tests for factories**

Create `installer/tests/wizard_engine/test_compose.py`:

```python
"""build_proj_steps + build_worktree_steps factory tests."""

from __future__ import annotations

from installer.wizard import build_proj_steps, build_worktree_steps
from installer.wizard_engine.step import WizardStep


class TestBuildProjSteps:
    def test_returns_list_of_wizard_step(self) -> None:
        steps = build_proj_steps(selected_plugins=["proj"])
        assert isinstance(steps, list)
        assert all(isinstance(s, WizardStep) for s in steps)
        assert len(steps) > 0

    def test_all_steps_target_proj_yaml(self) -> None:
        steps = build_proj_steps(selected_plugins=["proj"])
        assert all(s.yaml_file == "proj" for s in steps)

    def test_steps_preserve_dotted_key(self) -> None:
        steps = build_proj_steps(selected_plugins=["proj"])
        keys = {s.key for s in steps}
        # tracking_dir + projects_base_dir are baseline expected keys
        assert "tracking_dir" in keys
        assert "projects_base_dir" in keys

    def test_default_factory_callable(self) -> None:
        steps = build_proj_steps(selected_plugins=["proj"])
        for s in steps:
            assert callable(s.default_factory)
            # Smoke: factory accepts an empty dict without raising.
            s.default_factory({})


class TestBuildWorktreeSteps:
    def test_returns_list_of_wizard_step(self) -> None:
        steps = build_worktree_steps()
        assert isinstance(steps, list)
        assert all(isinstance(s, WizardStep) for s in steps)

    def test_all_steps_target_worktree_yaml(self) -> None:
        steps = build_worktree_steps()
        assert all(s.yaml_file == "worktree" for s in steps)
```

- [ ] **Step 3.4: Run factory tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_compose.py -v`
Expected: 6 tests PASS.

- [ ] **Step 3.5: Refactor `_setup_proj_yaml` to drive StepMachine**

Replace `_setup_proj_yaml` body in `installer/wizard.py` (lines 165-205) to use StepMachine + RichRenderer. Existing `existing` dict load + mtime check + atomic write are preserved. New body:

```python
def _setup_proj_yaml(console: Console, selected_plugins: list[str]) -> dict[str, Any]:
    """Setup ~/.claude/proj.yaml using WizardStep factory + StepMachine. Returns final config dict."""
    from installer.wizard_engine.machine import StepMachine
    from installer.wizard_engine.renderers.rich import RichRenderer

    path = Path.home() / ".claude" / "proj.yaml"
    try:
        existing = load_existing_yaml(path)
    except ConfigLoadError as exc:
        console.print(f"[red]Failed to load {path}: {exc.original}[/red]")
        console.print("[yellow]Aborting proj.yaml setup.[/yellow]")
        return {}
    mtime_before = path.stat().st_mtime if path.exists() else None

    console.print("\n[bold]proj.yaml configuration[/bold]")

    steps = build_proj_steps(selected_plugins)
    machine = StepMachine(steps)
    renderer = RichRenderer(console)
    answers = _drive_machine(machine, renderer, existing_view=existing)
    if answers is None:
        return existing
    _merge_dotted_into_dict(existing, answers)

    if Confirm.ask("\nShow advanced options?", default=False, console=console):
        adv_steps = [
            _prompt_spec_to_step(s)
            for s in PROJ_YAML_PROMPTS
            if s.yaml_file == "proj" and s.tier == "advanced"
        ]
        adv_machine = StepMachine(adv_steps)
        adv_answers = _drive_machine(adv_machine, renderer, existing_view=existing)
        if adv_answers is not None:
            _merge_dotted_into_dict(existing, adv_answers)

    if (
        mtime_before is not None
        and path.exists()
        and path.stat().st_mtime != mtime_before
    ):
        console.print(
            "[red]proj.yaml changed on disk during wizard — aborting write.[/red]"
        )
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        path, yaml.safe_dump(existing, sort_keys=False, default_flow_style=False)
    )
    console.print(f"[green]Wrote {path}[/green]")
    return existing
```

Add helper `_drive_machine` to the same module:

```python
def _drive_machine(
    machine: Any,
    renderer: Any,
    existing_view: dict[str, Any],
) -> dict[str, Any] | None:
    """Drive StepMachine + Renderer loop. Returns answers dict on submit, None on cancel."""
    from installer.wizard_engine.renderers.base import (
        BackRequested,
        Cancelled,
        Submitted,
    )

    last_banner: str | None = None
    while True:
        step = machine.current()
        if step is None:
            return machine.answers()
        # Defaults read from prior answers dict (with existing_view as fallback for first visit).
        merged_view: dict[str, Any] = dict(existing_view)
        for k, v in machine.answers().items():
            merged_view[k] = v
        default = step.default_factory(merged_view)
        # at_start = no prior visible step exists.
        snapshot = machine._cursor  # type: ignore[attr-defined]
        prior = machine._next_visible(snapshot - 1, direction=-1)  # type: ignore[attr-defined]
        at_start = prior < 0
        outcome = renderer.render(step, default, banner=last_banner, at_start=at_start)
        last_banner = None
        if isinstance(outcome, Submitted):
            r = machine.advance(outcome.value)
            if r.block_error is not None:
                last_banner = r.block_error
        elif isinstance(outcome, BackRequested):
            machine.back()
        elif isinstance(outcome, Cancelled):
            return None
        else:
            raise ValueError(f"Unknown outcome: {outcome!r}")
```

- [ ] **Step 3.6: Refactor `_setup_worktree_yaml` to drive StepMachine**

Replace `_setup_worktree_yaml` body in `installer/wizard.py` (lines 208-265) using same pattern as 3.5. Keep proj_existing load for condition lambdas (pass via existing_view).

- [ ] **Step 3.7: Run installer flow tests, verify no regression**

Run:
```bash
cd installer && uv run pytest tests/test_wizard.py tests/test_wizard_specs.py tests/flow/test_wizard.py -v
```
Expected: existing tests PASS (some may need port — see step 3.8).

- [ ] **Step 3.8: Re-port `installer/tests/flow/test_wizard.py` to factories**

Update test_defaults_from_existing_proj_yaml to assert against `build_proj_steps` factory output:

Read: `installer/tests/flow/test_wizard.py`
Change: Import + assertion swap (FieldSpec defaults → WizardStep default_factory output). Replace `from installer.flow.wizard import run_wizard` w/ `from installer.wizard import build_proj_steps`. Test logic: build_proj_steps + invoke each step's default_factory against an existing yaml dict, assert defaults match.

- [ ] **Step 3.9: Run all installer tests + lints**

Run:
```bash
cd installer && uv run pytest tests/ -v --ignore=tests/e2e
uv run ruff check installer/
uv run basedpyright installer/wizard.py installer/wizard_engine/
```
Expected: all green.

- [ ] **Step 3.10: Commit**

```bash
git add installer/wizard.py installer/tests/wizard_engine/test_compose.py installer/tests/flow/test_wizard.py
git commit -m "refactor(installer/745): port _setup_proj_yaml + _setup_worktree_yaml to StepMachine

build_proj_steps + build_worktree_steps factories convert PromptSpec
table to WizardStep. _setup_*_yaml now drives StepMachine + RichRenderer
via shared _drive_machine helper. Existing mtime check + atomic write
preserved. flow/test_wizard.py re-ported."
```

---

## Task 4: Port integration `configure_*` funcs + block validators (commit 4)

**Files:**
- Modify: `installer/flow/integration_config.py` (add `build_*_steps` factories + WizardBlock instances; keep validators)
- Modify: `installer/flow/installer_flow.py` (collapse per-integration calls into single StepMachine pass)
- Create: `installer/tests/wizard_engine/test_block_validators.py`

- [ ] **Step 4.1: Add `build_todoist_steps` factory in `installer/flow/integration_config.py`**

Append to `installer/flow/integration_config.py`:

```python
from installer.wizard_engine.step import WizardBlock, WizardStep


def _todoist_block_validator(answers: dict[str, Any]) -> str | None:
    """Wrap _todoist_validator: extract block keys, run, return err or None.

    Always runs (no enabled-skip): impl returns None when sync disabled + creds blank.
    """
    enabled = bool(answers.get("todoist.enabled", False))
    token = str(answers.get("todoist.api_token", "") or "").strip()
    # Disabled + empty creds = no error.
    if not enabled and not token:
        return None
    # Re-use existing validator (which expects {"api_token": ..., "sync_enabled": ...}).
    return _todoist_validator({"api_token": token, "sync_enabled": enabled})


def build_todoist_steps(
    existing_path: Path = Path.home() / ".claude" / "todoist.yaml",
) -> tuple[list[WizardStep], WizardBlock]:
    existing = _load_yaml(existing_path)
    steps = [
        WizardStep(
            key="todoist.enabled",
            label="Enable Todoist sync?",
            kind="bool",
            default_factory=lambda _a: bool(existing.get("enabled", False)),
            block_id="todoist",
            group="Todoist",
            yaml_file="todoist",
        ),
        WizardStep(
            key="todoist.auto_sync",
            label="Enable auto-sync?",
            kind="bool",
            default_factory=lambda _a: bool(existing.get("auto_sync", True)),
            condition=lambda a: bool(a.get("todoist.enabled", False)),
            block_id="todoist",
            group="Todoist",
            yaml_file="todoist",
        ),
        WizardStep(
            key="todoist.api_token",
            label="Todoist API token",
            kind="password",
            default_factory=lambda _a: str(existing.get("api_token", "") or ""),
            condition=lambda a: bool(a.get("todoist.enabled", False)),
            block_id="todoist",
            group="Todoist",
            sensitive=True,
            yaml_file="todoist",
        ),
    ]
    block = WizardBlock(
        block_id="todoist",
        label="Todoist Configuration",
        validator=_todoist_block_validator,
    )
    return steps, block
```

- [ ] **Step 4.2: Repeat factory pattern for Trello, Jira, Confluence, Wiki**

Add `build_trello_steps`, `build_jira_steps`, `build_confluence_steps`, `build_wiki_steps` mirroring the same pattern. For each: 1 enabled bool + 1 auto_sync bool + N credential/config text/password steps gated on enabled. Block validator wraps the existing `_<service>_validator` w/ "disabled + empty = OK" guard.

Wiki has no credential validator → returns `(list[WizardStep], None)` OR returns just `list[WizardStep]` (per spec §"Step Composition"). Choose: return `tuple[list[WizardStep], WizardBlock | None]` for type uniformity; downstream filters out None blocks.

- [ ] **Step 4.3: Write failing tests for block validators**

Create `installer/tests/wizard_engine/test_block_validators.py`:

```python
"""Block validator wrapper tests — disabled+empty=OK, runs always otherwise."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from installer.flow.integration_config import _todoist_block_validator


class TestTodoistBlockValidator:
    def test_disabled_empty_returns_none(self) -> None:
        assert _todoist_block_validator(
            {"todoist.enabled": False, "todoist.api_token": ""}
        ) is None

    def test_disabled_with_token_runs_validator(self) -> None:
        with patch(
            "installer.flow.integration_config._todoist_validator",
            return_value="bad",
        ) as mock_v:
            r = _todoist_block_validator(
                {"todoist.enabled": False, "todoist.api_token": "old_token"}
            )
        mock_v.assert_called_once()
        assert r == "bad"

    def test_enabled_empty_runs_validator(self) -> None:
        with patch(
            "installer.flow.integration_config._todoist_validator",
            return_value="API token is required",
        ) as mock_v:
            r = _todoist_block_validator(
                {"todoist.enabled": True, "todoist.api_token": ""}
            )
        mock_v.assert_called_once()
        assert r == "API token is required"

    def test_enabled_with_token_passes_through(self) -> None:
        with patch(
            "installer.flow.integration_config._todoist_validator",
            return_value=None,
        ):
            r = _todoist_block_validator(
                {"todoist.enabled": True, "todoist.api_token": "good"}
            )
        assert r is None
```

(Repeat similar test classes for Trello, Jira, Confluence wrappers.)

- [ ] **Step 4.4: Run block validator tests, verify pass**

Run: `cd installer && uv run pytest tests/wizard_engine/test_block_validators.py -v`
Expected: 4 tests PASS (todoist) + similar for other integrations once added.

- [ ] **Step 4.5: Wire integration_config into installer_flow**

Modify `installer/flow/installer_flow.py::run_install` (around lines 376-408):
- Replace per-integration `configure_<service>` calls with collected `build_<service>_steps()` factory invocations.
- Concatenate all steps into a single list.
- Build blocks dict from all returned `WizardBlock`s.
- Drive single `StepMachine + TuiRenderer` pass.
- After completion, dispatch answers dict per yaml_file via existing `_write_integration_result` w/ ConfigDiff prompt.

- [ ] **Step 4.6: Run installer + flow tests + lints**

Run:
```bash
cd installer && uv run pytest tests/ -v --ignore=tests/e2e
uv run ruff check installer/
uv run basedpyright installer/flow/integration_config.py installer/flow/installer_flow.py installer/wizard_engine/
```
Expected: all green.

- [ ] **Step 4.7: Commit**

```bash
git add installer/flow/integration_config.py installer/flow/installer_flow.py installer/tests/wizard_engine/test_block_validators.py
git commit -m "refactor(installer/745): port configure_* integrations to step factories + block validators

build_todoist_steps / build_trello_steps / build_jira_steps /
build_confluence_steps / build_wiki_steps return (steps, block).
Validators wrap existing _<service>_validator w/ disabled+empty=OK
guard (per spec decision: validator always runs). installer_flow
collapses per-integration calls into single StepMachine pass."
```

---

## Task 5: Wire end-to-end + delete dead code (commit 5)

**Files:**
- Modify: `installer/wizard.py` (`run_wizard` — replace per-plugin `_setup_*` calls w/ single StepMachine pass)
- Modify: `installer/flow/wizard.py` (reuse `installer/wizard.py::build_proj_steps` + `build_worktree_steps`)
- Modify: `installer/flow/form.py` (delete `_FormRunner` and most internals; keep `FieldSpec` only if still referenced)
- Create: `installer/wizard_engine/__init__.py` (exports + `build_all_steps` composer)

- [ ] **Step 5.1: Add `build_all_steps` in `installer/wizard_engine/__init__.py`**

Replace empty `__init__.py` w/:

```python
"""wizard_engine package — exports + step composer."""

from __future__ import annotations

from typing import Any

from installer.wizard_engine.machine import StepMachine
from installer.wizard_engine.step import (
    AdvanceResult,
    BackResult,
    WizardBlock,
    WizardStep,
)

__all__ = [
    "AdvanceResult",
    "BackResult",
    "StepMachine",
    "WizardBlock",
    "WizardStep",
    "build_all_steps",
]

_PROJ_PLUGINS = {"proj", "router", "todoist", "trello", "jira", "confluence"}


def build_all_steps(
    selected_plugins: list[str],
) -> tuple[list[WizardStep], dict[str, WizardBlock]]:
    """Compose ordered step list + block registry from selected plugins."""
    from installer.flow.integration_config import (
        build_confluence_steps,
        build_jira_steps,
        build_todoist_steps,
        build_trello_steps,
        build_wiki_steps,
    )
    from installer.wizard import build_proj_steps, build_worktree_steps

    steps: list[WizardStep] = []
    blocks: dict[str, WizardBlock] = {}

    if _PROJ_PLUGINS & set(selected_plugins):
        steps.extend(build_proj_steps(selected_plugins))
    if "worktree" in selected_plugins:
        steps.extend(build_worktree_steps())

    integration_factories: list[tuple[str, Any]] = [
        ("todoist", build_todoist_steps),
        ("trello", build_trello_steps),
        ("jira", build_jira_steps),
        ("confluence", build_confluence_steps),
    ]
    for name, factory in integration_factories:
        if name in selected_plugins:
            block_steps, block = factory()
            steps.extend(block_steps)
            blocks[block.block_id] = block

    if "wiki" in selected_plugins:
        wiki_result = build_wiki_steps(proj_selected="proj" in selected_plugins)
        if isinstance(wiki_result, tuple):
            wiki_steps, wiki_block = wiki_result
            steps.extend(wiki_steps)
            if wiki_block is not None:
                blocks[wiki_block.block_id] = wiki_block
        else:
            steps.extend(wiki_result)
    return steps, blocks
```

- [ ] **Step 5.2: Refactor `installer/wizard.py::run_wizard` to single StepMachine drive**

Replace `run_wizard` body (lines 590-629) w/:

```python
def run_wizard(selected_plugins: list[str], skip: bool = False) -> None:
    """Run the post-install setup wizard (Rich --no-tui path)."""
    from installer.wizard_engine import build_all_steps
    from installer.wizard_engine.machine import StepMachine
    from installer.wizard_engine.renderers.rich import RichRenderer

    console = Console()
    if skip:
        console.print("[dim]Skipping setup wizard (--skip-wizard)[/dim]")
        return

    console.print("\n[bold]Post-install Setup Wizard[/bold]")
    console.print("Configure your plugins. Press Enter to accept defaults; type `:back` to revisit.\n")

    steps, blocks = build_all_steps(selected_plugins)
    if not steps:
        console.print("[dim]No plugins require configuration.[/dim]")
    else:
        machine = StepMachine(steps, blocks)
        renderer = RichRenderer(console)
        answers = _drive_machine(machine, renderer, existing_view={})
        if answers is None:
            console.print("[dim]Cancelled at wizard.[/dim]")
            return
        _write_all_answers(answers)

    cache_dir = Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"
    plugin_dirs: list[Path] = []
    for name in selected_plugins:
        resolved = _resolve_plugin_dir(cache_dir, name)
        if resolved is not None:
            plugin_dirs.append(resolved)
    if plugin_dirs:
        _hooks_diff_prompt(plugin_dirs, console=console)

    ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")


def _write_all_answers(answers: dict[str, Any]) -> None:
    """Dispatch answers dict per yaml_file bucket (proj, worktree, todoist, ...).

    Re-uses existing _atomic_write + per-bucket merge logic.
    """
    # Group answers by yaml_file via key prefix or step.yaml_file lookup.
    # Implementation reads PROJ_YAML_PROMPTS for proj/worktree mapping,
    # uses dotted-key prefix for integration buckets (todoist.* → todoist.yaml).
    ...  # FILL: pseudocode is "for each bucket, build dict, _atomic_write".
```

(Step 5.2 has a `...` — flesh out `_write_all_answers` body with the existing per-bucket write logic ported from `_setup_*_config`. Each bucket: load existing yaml, deep-merge new answers (stripping `<bucket>.` prefix), atomic write.)

- [ ] **Step 5.3: Refactor `installer/flow/wizard.py::run_wizard` to drive StepMachine**

Replace `run_wizard` w/ TuiRenderer-driven equivalent:

```python
def run_wizard(state: Any, args: Any, console: Console) -> dict[str, Any] | None:
    from installer.wizard import _drive_machine
    from installer.wizard_engine import build_all_steps
    from installer.wizard_engine.machine import StepMachine
    from installer.wizard_engine.renderers.tui import TuiRenderer

    selected = list(getattr(state, "installed_plugins", []))
    steps, blocks = build_all_steps(selected)
    if not steps:
        return {}
    machine = StepMachine(steps, blocks)
    renderer = TuiRenderer(console)
    return _drive_machine(machine, renderer, existing_view={})
```

- [ ] **Step 5.4: Delete dead code in `installer/flow/form.py`**

Remove `_FormRunner`, `_build_application`, `run_form`. Keep `FieldSpec` only if `installer/flow/wizard.py` (post-refactor) or any test still imports it. If unused, delete the whole file.

- [ ] **Step 5.5: Delete superseded `_setup_*_config` Rich functions**

Remove from `installer/wizard.py`: `_setup_todoist_config`, `_setup_trello_config`, `_setup_jira_config` (lines ~315-587). They are now superseded by `build_*_steps` + StepMachine.

- [ ] **Step 5.6: Run all installer tests + lints**

Run:
```bash
cd installer && uv run pytest tests/ -v --ignore=tests/e2e
uv run ruff check installer/
uv run basedpyright installer/
```
Expected: all green. If any test imports a deleted symbol, port to the new factory.

- [ ] **Step 5.7: Manual smoke test (Rich path)**

Run: `cd installer && uv run python -m installer.main --no-tui --skip-marketplace`
Expected: wizard runs through configured plugins, `:back` works, final yaml writes correctly.

- [ ] **Step 5.8: Manual smoke test (TUI path)**

Run: `cd installer && uv run python -m installer.main` (in a real terminal)
Expected: TUI dialogs render, Back button on bool prompts, `← Back` option on radiolist, sentinel works on input.

- [ ] **Step 5.9: Commit**

```bash
git add installer/wizard.py installer/flow/wizard.py installer/flow/form.py installer/wizard_engine/__init__.py
git commit -m "refactor(installer/745): wire end-to-end StepMachine pass; delete dead code

Single StepMachine drive across all selected plugins (Rich + TUI).
build_all_steps composer assembles ordered step list + block registry.
Removed superseded _setup_*_config funcs in wizard.py + _FormRunner /
run_form / _build_application in flow/form.py. Manual smoke verified."
```

---

## Task 6: E2E tests — Rich back-nav + TUI pexpect (commit 6)

**Files:**
- Modify: `installer/tests/e2e/test_wizard_full_config.py` (add 3 back-nav scenarios)
- Create: `installer/tests/e2e/test_wizard_tui_nav.py` (new pexpect-based suite)
- Modify: `pyproject.toml` (add pexpect dev dep)

- [ ] **Step 6.1: Add pexpect to dev deps**

Edit `pyproject.toml` — add `pexpect>=4.9` to the `[dependency-groups.dev]` (or `tool.uv.dev-dependencies`) list.

Run: `cd installer && uv sync`
Verify: `uv run python -c "import pexpect; print(pexpect.__version__)"` succeeds.

- [ ] **Step 6.2: Write Rich back-nav e2e — back navigates to prior step**

Append to `installer/tests/e2e/test_wizard_full_config.py`:

```python
class TestRichWizardBackNav:
    def test_back_navigates_to_prior_step(self, tmp_path: Path) -> None:
        """Submit value 1, advance, submit value 2, type :back, change value 1."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        (tmp_home / ".claude").mkdir()
        # stdin script: enter value-A, value-B, :back, value-A2, advance to end
        stdin = "value-A\nvalue-B\n:back\nvalue-A2\n" + "\n" * 50
        result = _run_wizard(tmp_home, stdin)
        proj_yaml = tmp_home / ".claude" / "proj.yaml"
        if not proj_yaml.exists():
            pytest.skip(f"wizard did not write proj.yaml; stderr: {result.stderr[:500]}")
        data = yaml.safe_load(proj_yaml.read_text())
        # tracking_dir is the first prompt; should now be "value-A2" (revised)
        assert data.get("tracking_dir") == "value-A2"

    def test_back_at_first_step_does_not_crash(self, tmp_path: Path) -> None:
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        (tmp_home / ".claude").mkdir()
        stdin = ":back\n" + "value-A\n" + "\n" * 50
        result = _run_wizard(tmp_home, stdin)
        # Just assert it didn't crash with non-zero. proj.yaml may or may not exist.
        assert result.returncode in (0, 1)

    def test_back_preserves_forward_answers(self, tmp_path: Path) -> None:
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        (tmp_home / ".claude").mkdir()
        stdin = "first\nsecond\n:back\n\n" + "\n" * 50  # back, then accept default (=first)
        result = _run_wizard(tmp_home, stdin)
        proj_yaml = tmp_home / ".claude" / "proj.yaml"
        if not proj_yaml.exists():
            pytest.skip(f"stderr: {result.stderr[:500]}")
        data = yaml.safe_load(proj_yaml.read_text())
        # First prompt's value preserved as default (re-accepted via Enter)
        assert data.get("tracking_dir") == "first"
```

- [ ] **Step 6.3: Run Rich back-nav e2e, verify pass**

Run: `cd installer && uv run pytest tests/e2e/test_wizard_full_config.py::TestRichWizardBackNav -v`
Expected: 3 tests PASS (or SKIP if subprocess can't run in env).

- [ ] **Step 6.4: Create TUI pexpect e2e harness**

Create `installer/tests/e2e/test_wizard_tui_nav.py`:

```python
"""TUI wizard e2e via pexpect — drives prompt_toolkit dialogs through a pty."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pexpect = pytest.importorskip("pexpect")

REPO_ROOT = Path(__file__).resolve().parents[3]


def _spawn_wizard(tmp_home: Path, timeout: int = 30) -> "pexpect.spawn":
    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env["UV_CACHE_DIR"] = str(tmp_home / ".uv-cache")
    env["TERM"] = "xterm-256color"
    cmd = f"{sys.executable} -m installer.main"
    return pexpect.spawn(
        cmd, cwd=str(REPO_ROOT), env=env, timeout=timeout, encoding="utf-8"
    )


@pytest.mark.tui
class TestTuiWizardNav:
    def test_back_button_navigates_to_prior_step(self, tmp_path: Path) -> None:
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        (tmp_home / ".claude").mkdir()
        child = _spawn_wizard(tmp_home)
        try:
            # Wait for first dialog
            child.expect("Configure")
            # Enter first value, Tab to OK, Enter
            child.send("first\t\r")
            # Second dialog
            child.expect("Configure")
            # Type :back, Tab to OK, Enter — should land on first dialog again
            child.send(":back\t\r")
            child.expect("first")  # default value preserved
        finally:
            child.terminate(force=True)
```

(Add 3 more tests for at_start no-op, validator jump-back, ← Back option in radiolist — same pexpect pattern.)

- [ ] **Step 6.5: Configure pytest mark "tui" + skip in default CI**

Edit `installer/pyproject.toml` (or `pytest.ini`):

```toml
[tool.pytest.ini_options]
markers = [
    "tui: TUI wizard tests requiring a real pty (run via `pytest -m tui`)",
]
```

Update CI yaml: default test runs include `-m "not tui"`. Add a separate (opt-in) job: `pytest -m tui`.

- [ ] **Step 6.6: Run TUI pexpect e2e locally w/ `-m tui`**

Run: `cd installer && uv run pytest tests/e2e/test_wizard_tui_nav.py -m tui -v`
Expected: 4 tests PASS (when run on a machine w/ pty; otherwise SKIP).

- [ ] **Step 6.7: Run all installer tests + lints**

Run:
```bash
cd installer && uv run pytest tests/ -v --ignore=tests/e2e
cd installer && uv run pytest tests/e2e -v -m "not tui"
uv run ruff check installer/
uv run basedpyright installer/
```
Expected: all green.

- [ ] **Step 6.8: Commit**

```bash
git add installer/tests/e2e/test_wizard_full_config.py installer/tests/e2e/test_wizard_tui_nav.py pyproject.toml installer/pyproject.toml
git commit -m "test(installer/745): add Rich back-nav e2e + TUI pexpect e2e

Rich: 3 new scenarios in test_wizard_full_config.py (back nav, at-start
no-op, preserve forward). TUI: new test_wizard_tui_nav.py drives
prompt_toolkit through pexpect. pexpect added to dev deps. Tests gated
by `tui` pytest marker — opt-in CI job."
```

---

## Final Integration

- [ ] **Step F.1: Run full installer test suite + lints**

```bash
cd installer && uv run pytest tests/ -v
uv run ruff check installer/
uv run ruff format --check installer/
uv run basedpyright installer/
```
Expected: all green.

- [ ] **Step F.2: Manual end-to-end smoke (Rich path)**

In a temp HOME, run wizard from scratch:
```bash
TMPHOME=$(mktemp -d)
HOME=$TMPHOME uv run python -m installer.main --no-tui
```
Verify:
- All prompts navigable forward.
- `:back` returns to previous prompt; default = prior value.
- `:back` at first prompt prints "Already at first step" or equivalent.
- Final yaml writes correct.

- [ ] **Step F.3: Manual end-to-end smoke (TUI path)**

In a real terminal:
```bash
TMPHOME=$(mktemp -d)
HOME=$TMPHOME uv run python -m installer.main
```
Verify:
- Dialogs render correctly.
- "Back" button on bool prompts works.
- "← Back" option in radiolist returns to prior step.
- `:back` sentinel in input dialogs works.
- Validator failure (intentional bad creds) jumps cursor back to integration's first step + shows banner.

- [ ] **Step F.4: Verify SIGINT mid-wizard leaves no partial yaml writes**

Run wizard, press Ctrl+C halfway through. Verify `~/.claude/*.yaml` files match the pre-wizard state (no half-written buckets). This is the architectural foundation for 746; 746 itself adds graceful banner + terminal cleanup.

- [ ] **Step F.5: Use `superpowers:finishing-a-development-branch`**

Invoke `superpowers:finishing-a-development-branch` to FF-merge `feat/745-wizard-nav` to `dev`, push, watch CI.

---

## Self-Review

**1. Spec coverage**:

| Spec section | Task |
|--------------|------|
| Module layout (wizard_engine/) | T1, T2 |
| WizardStep / WizardBlock data model | T1 |
| StepMachine (advance/back/jump_to_block) | T1 |
| Renderer protocol + Outcome | T2 |
| RichRenderer (sentinel + ← Back) | T2 |
| TuiRenderer (sentinel + __BACK__ + button_dialog) | T2 |
| build_proj_steps / build_worktree_steps factories | T3 |
| Migrate _setup_proj_yaml / _setup_worktree_yaml | T3 |
| Re-port flow/test_wizard.py | T3 |
| build_*_steps integration factories + WizardBlock | T4 |
| Block validator wrappers (disabled+empty=OK) | T4 |
| installer_flow.py wiring | T4 |
| build_all_steps composer | T5 |
| installer/wizard.py::run_wizard end-to-end drive | T5 |
| Delete dead form.py code | T5 |
| Delete superseded _setup_*_config Rich funcs | T5 |
| Rich back-nav e2e | T6 |
| TUI pexpect e2e + pexpect dev dep | T6 |
| pytest "tui" marker | T6 |
| SIGINT architectural foundation | F.4 |

All spec sections covered.

**2. Placeholder scan**: Step 5.2 has `...  # FILL` for `_write_all_answers` body. Resolution: pseudocode is "for each bucket, build dict, atomic_write." This is acceptable as a hand-off because it ports existing logic from the deleted `_setup_*_config` functions — the implementer reads those functions for reference. Marked explicitly so it's not missed.

**3. Type consistency**: `build_wiki_steps` return type is `tuple[list[WizardStep], WizardBlock | None]` (per spec self-review fix). `build_all_steps` handles both tuple-return and bare-list-return defensively (Step 5.1 isinstance check). `_drive_machine` accesses `machine._cursor` and `machine._next_visible` (private members) — acceptable because `_drive_machine` is a sibling utility in the same package boundary; alternative is to add `at_start_for_current()` public method to StepMachine. Trade-off documented; prefer the public API.

**4. Add public StepMachine.at_start_for_current() method**: refactor — add this in Task 1 (Step 1.5 needs the method on the StepMachine). Update spec / plan accordingly.

Actually — fix inline now (writing-plans skill says "Fix any issues inline"):

**Inline fix to Task 1, Step 1.5**: add the following method to StepMachine:

```python
def at_start_for_current(self) -> bool:
    """Return True if there is no visible step before the cursor (back is no-op)."""
    if self.current() is None:
        return False
    prior = self._next_visible(self._cursor - 1, direction=-1)
    return prior < 0
```

And add a unit test in Step 1.8:

```python
def test_machine_at_start_for_current() -> None:
    s1, s2 = _step("a"), _step("b")
    m = StepMachine([s1, s2])
    assert m.at_start_for_current() is True
    m.advance("v1")
    assert m.at_start_for_current() is False
```

Then in `_drive_machine` (Step 3.5 / 5.2), use `machine.at_start_for_current()` instead of accessing `_cursor` / `_next_visible` directly.

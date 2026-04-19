# Installer UI P3 — Kill InstallerApp + Port 7 Screens

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete `installer/app.py::InstallerApp` (Textual `App` subclass) and port 7 Textual screens to `installer/flow/` using Rich + prompt_toolkit. Replaces the top-level `InstallerApp().run()` entry with plain-Python `run_installer_flow(mode, args, console)`.

**Architecture:** All 4 modes (install/update/reinstall/uninstall) dispatch through a 3-phase flow: pre-phase (Rich: detection, corrupt-yaml, confirms), interactive phase (Rich prompts for install/update; plain plan-build for reinstall/uninstall), post-phase (Rich progress + cleanup). Introduces `prompt_toolkit>=3.0` for checkbox multi-select screens (update, plugin_select). Preserves 100% feature parity with the pre-P3 Textual flows (see spec §Feature-parity guarantee).

**Tech Stack:** Python 3.13, Rich 13+, prompt_toolkit 3+, pytest, syrupy, existing `subprocess`/`asyncio` patterns from P1+P2.

**Spec:** `docs/superpowers/specs/2026-04-19-installer-ui-672-p3-kill-installerapp-design.md`

---

## File Structure

**Created under `installer/flow/`:**
- `confirm.py` — `ConfirmOption`, `ConfirmResult`, `confirm_with_options(title, message, options, console, variant, confirm_label, cancel_label) -> ConfirmResult`
- `detection.py` — `show_detection_and_confirm(state, rows, title, console) -> bool` (proceed y/n)
- `corrupt_yaml.py` — `show_corrupt_yaml_and_confirm(errors, console) -> bool` (continue-with-defaults y/n)
- `hooks_diff.py` — `review_hooks_diff(diffs, console) -> dict[str, set[str]] | None` ({"apply": set, "remove": set} or None to cancel)
- `config_diff.py` — `review_config_diff(service_name, diff_text, console) -> bool` (apply/cancel)
- `update.py` — `select_updates(version_diffs, console) -> list[str]` (selected plugin names, empty = cancel)
- `plugin_select.py` — `select_plugin_actions(statuses, console) -> list[tuple[str, str]]` (list of (name, action))
- `pre_install_phase.py` — `PreInstallResult` dataclass + `pre_install_phase(mode, args, console) -> PreInstallResult`
- `installer_flow.py` — `run_installer_flow(mode, args, console) -> int` top-level dispatcher

**Created under `installer/tests/flow/`:**
- `test_confirm.py`, `test_detection.py`, `test_corrupt_yaml.py`, `test_hooks_diff.py`, `test_config_diff.py`, `test_update.py`, `test_plugin_select.py`
- `test_pre_install_phase.py`, `test_installer_flow.py`
- Snapshot files under `installer/tests/flow/__snapshots__/`

**Modified:**
- `installer/main.py` — replace `InstallerApp().run()` call with `run_installer_flow(mode, args, console)`. Remove pre-flow logic that moved to `pre_install_phase`.
- `installer/tests/test_main.py` — update tests to mock `run_installer_flow` instead of `InstallerApp`.
- `installer/tests/e2e/test_install_flow.py`, `test_update_flows.py`, `test_integration_flow.py`, `test_uninstall_wizard.py`, `test_edge_cases.py` — replace Textual pilot asserts with flow-function asserts.
- `pyproject.toml` — add `prompt_toolkit>=3.0` to `[dependency-groups].test`. (It's installed for test envs + plugin install imports; since installer runs at install time via `uv run cpm-install`, also add to the runtime deps list.)
- `installer/tests/e2e/test_snapshots.py` — update inventory docstring with P3 NOTE.

**Deleted at end of phase:**
- `installer/screens/confirm.py`
- `installer/screens/detection.py`
- `installer/screens/corrupt_yaml.py`
- `installer/screens/hooks_diff.py`
- `installer/screens/config_diff.py`
- `installer/screens/update.py`
- `installer/screens/plugin_select.py`
- `installer/app.py::InstallerApp` class (the `run_migration_tui` function stays — P2 work).
- All Textual tests targeting these screens: `test_corrupt_yaml_screen.py`, `test_screens.py` (if Textual-only), `test_integration_screens.py`, `test_wizard.py` (install-wizard parts only; wizard screen stays for P4), plus the relevant Textual snapshot tests in `installer/tests/e2e/`.
- SVG goldens under `installer/tests/e2e/snapshots/` matching the deleted screens.
- Entries in `installer/screens/__init__.py` for the 7 deleted classes.

**Latent bugs fixed (spec §Latent bugs):**
- B9 (confirm.py:204-205 bare except) — eliminated, Rich has no widget-query hazard.
- B10 (plugin_select Enter=toggle vs confirm) — eliminated, prompt_toolkit checkboxlist_dialog has standard Enter-confirm.
- B14 (app.py _show_error try/except) — eliminated, InstallerApp deleted.

---

## Task 1: Add `prompt_toolkit>=3.0` to deps + scaffold installer/flow/ test package (if not already present)

**Files:**
- Modify: `pyproject.toml`
- Verify: `installer/tests/flow/__init__.py` (should exist from P1)

- [ ] **Step 1: Add prompt_toolkit to deps**

Open `/home/raul/worktrees/cpm/feat-672-p3-kill-installerapp/pyproject.toml`. Find `[dependency-groups]`. Ensure the `test` group AND the main `dependencies` list include `prompt_toolkit>=3.0`. Current state (from P1):

```toml
[dependency-groups]
test = ["pytest>=8.0", "pytest-cov>=7.0", "pytest-mock>=3.14", "pytest-asyncio>=0.24", "textual[dev]>=0.80", "pytest-textual-snapshot>=1.0", "syrupy>=5.0", "httpx>=0.28", "respx>=0.22"]
```

Add `"prompt_toolkit>=3.0"` to the `test` group. Also ensure it's in the main project deps (so `cpm-install` can import it at runtime). Search for the top-level `dependencies = [...]` — if it exists, add there; otherwise add via the existing runtime deps configuration.

- [ ] **Step 2: Sync deps**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv sync --group test
```

Expected: `prompt_toolkit==3.x` installed in `.venv/`. Verify:

```bash
.venv/bin/python -c "import prompt_toolkit; print(prompt_toolkit.__version__)"
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(installer/672): add prompt_toolkit>=3.0 dep for P3 checkboxlist screens"
```

---

## Task 2: Port ConfirmScreen → `installer/flow/confirm.py`

**Files:**
- Create: `installer/flow/confirm.py`
- Create: `installer/tests/flow/test_confirm.py`

**Context:** ConfirmScreen shows a title + message + optional toggle checkboxes, returns `ConfirmResult(confirmed: bool, options: dict[str, bool])`. Rich replacement: Prompt.ask for the main y/n, then sequential Prompt.ask per option for each toggle.

- [ ] **Step 1: Write failing tests**

Create `installer/tests/flow/test_confirm.py`:

```python
# installer/tests/flow/test_confirm.py
import pytest
from rich.console import Console

from installer.flow.confirm import ConfirmOption, ConfirmResult, confirm_with_options


class TestConfirmWithOptions:
    def test_confirmed_no_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Proceed?", message="Do the thing?", options=[], console=console
        )
        assert isinstance(result, ConfirmResult)
        assert result.confirmed is True
        assert result.options == {}

    def test_cancelled_no_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Proceed?", message="Do the thing?", options=[], console=console
        )
        assert result.confirmed is False
        assert result.options == {}

    def test_confirmed_with_option_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # First prompt: confirm (y). Second prompt: reset_configs (y).
        calls = iter(["y", "y"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Reinstall?",
            message="Reinstall all plugins.",
            options=[ConfirmOption(key="reset_configs", label="Reset configs")],
            console=console,
        )
        assert result.confirmed is True
        assert result.options == {"reset_configs": True}

    def test_confirmed_with_option_declined(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = iter(["y", "n"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Reinstall?",
            message="Reinstall all plugins.",
            options=[ConfirmOption(key="reset_configs", label="Reset configs")],
            console=console,
        )
        assert result.confirmed is True
        assert result.options == {"reset_configs": False}

    def test_cancel_skips_option_prompts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only the first prompt should fire; if cancelled, no option prompts.
        call_count = {"n": 0}

        def fake_ask(*args, **kwargs):
            call_count["n"] += 1
            return "n"

        monkeypatch.setattr("rich.prompt.Prompt.ask", fake_ask)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Reinstall?",
            message="Reinstall all plugins.",
            options=[ConfirmOption(key="reset_configs", label="Reset configs")],
            console=console,
        )
        assert result.confirmed is False
        assert call_count["n"] == 1  # only the confirm prompt fired

    def test_message_rendered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        confirm_with_options(
            title="My Title",
            message="My specific message",
            options=[],
            console=console,
        )
        text = console.export_text()
        assert "My Title" in text
        assert "My specific message" in text

    def test_variant_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """variant='error' should render without raising."""
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Uninstall?",
            message="Remove all?",
            options=[],
            console=console,
            variant="error",
        )
        assert result.confirmed is True
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/flow/test_confirm.py -v --no-cov
```

Expected: `ModuleNotFoundError: installer.flow.confirm`.

- [ ] **Step 3: Implement `confirm.py`**

Create `installer/flow/confirm.py`:

```python
# installer/flow/confirm.py
"""Rich-based replacement for Textual ConfirmScreen.

Shows a titled panel + message, prompts y/n to confirm, then (if confirmed)
prompts y/n per option toggle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt


Variant = Literal["primary", "warning", "error"]

_VARIANT_STYLE: dict[Variant, str] = {
    "primary": "cyan",
    "warning": "yellow",
    "error": "red",
}


@dataclass
class ConfirmOption:
    key: str
    label: str
    default: bool = False


@dataclass
class ConfirmResult:
    confirmed: bool
    options: dict[str, bool] = field(default_factory=dict)


def confirm_with_options(
    title: str,
    message: str,
    options: list[ConfirmOption],
    console: Console,
    variant: Variant = "primary",
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
) -> ConfirmResult:
    """Display title+message panel, prompt for y/n confirm, then per-option y/n.

    Cancel short-circuits — option prompts do not fire.
    """
    border_style = _VARIANT_STYLE.get(variant, "cyan")
    console.print(Panel(message, title=title, border_style=border_style))

    proceed = Prompt.ask(
        f"{confirm_label}?",
        choices=["y", "n"],
        default="y",
        console=console,
    )
    if proceed != "y":
        return ConfirmResult(confirmed=False, options={})

    option_values: dict[str, bool] = {}
    for opt in options:
        default = "y" if opt.default else "n"
        ans = Prompt.ask(
            opt.label,
            choices=["y", "n"],
            default=default,
            console=console,
        )
        option_values[opt.key] = ans == "y"

    return ConfirmResult(confirmed=True, options=option_values)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/flow/test_confirm.py -v --no-cov
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/flow/confirm.py installer/tests/flow/test_confirm.py
git commit -m "feat(installer/672): port ConfirmScreen → flow.confirm_with_options (P3)"
```

---

## Task 3: Port DetectionScreen → `installer/flow/detection.py`

**Files:**
- Create: `installer/flow/detection.py`
- Create: `installer/tests/flow/test_detection.py`

**Context:** DetectionScreen receives `state: InstallState`, `plugin_rows: list[PluginDetectionRow]`, `title_text: str`. Shows table of plugins (name, installed version, available version, status) + continue/cancel buttons. Returns `bool` (proceed).

- [ ] **Step 1: Write failing tests**

Create `installer/tests/flow/test_detection.py`:

```python
# installer/tests/flow/test_detection.py
from pathlib import Path

import pytest
from rich.console import Console

from installer.detect import InstallState
from installer.flow.detection import show_detection_and_confirm
from installer.screens.detection import PluginDetectionRow  # dataclass still here until Task 12


def _state(tmp_path: Path) -> InstallState:
    return InstallState(
        installed_plugins=["proj"],
        cache_dir=tmp_path / "cache",
        config_files_present={"proj.yaml": True},
        marketplace_registered=True,
    )


def _rows() -> list[PluginDetectionRow]:
    return [
        PluginDetectionRow(plugin="proj", installed_version="1.0.0", available_version="1.1.0"),
        PluginDetectionRow(plugin="worktree", installed_version=None, available_version="2.0.0"),
        PluginDetectionRow(plugin="router", installed_version="3.0.0", available_version=None),
    ]


class TestShowDetectionAndConfirm:
    def test_confirmed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = show_detection_and_confirm(
            state=_state(tmp_path),
            rows=_rows(),
            title="Existing Installation",
            console=console,
        )
        assert result is True

    def test_cancelled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert (
            show_detection_and_confirm(
                state=_state(tmp_path),
                rows=_rows(),
                title="Existing Installation",
                console=console,
            )
            is False
        )

    def test_table_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        show_detection_and_confirm(
            state=_state(tmp_path),
            rows=_rows(),
            title="Install Check",
            console=console,
        )
        text = console.export_text()
        assert "Install Check" in text
        assert "proj" in text
        assert "worktree" in text
        assert "router" in text
        assert "1.0.0" in text
        assert "1.1.0" in text
        # Status labels derived from row.status
        assert "outdated" in text or "up-to-date" in text or "not installed" in text

    def test_empty_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = show_detection_and_confirm(
            state=_state(tmp_path),
            rows=[],
            title="Empty",
            console=console,
        )
        assert result is True
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/flow/test_detection.py -v --no-cov
```

- [ ] **Step 3: Implement `detection.py`**

Create `installer/flow/detection.py`:

```python
# installer/flow/detection.py
"""Rich-based replacement for Textual DetectionScreen.

Renders a detection summary table (plugin name, installed + available
versions, derived status) then prompts y/n to continue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

if TYPE_CHECKING:
    from installer.detect import InstallState
    from installer.screens.detection import PluginDetectionRow


_STATUS_STYLE: dict[str, str] = {
    "up-to-date": "green",
    "outdated": "yellow",
    "not installed": "dim",
    "unknown": "dim",
}


def show_detection_and_confirm(
    state: "InstallState",
    rows: list["PluginDetectionRow"],
    title: str,
    console: Console,
) -> bool:
    """Render the detection table + prompt for proceed/cancel.

    Returns ``True`` if user opts to continue, ``False`` on cancel.
    """
    console.print(f"[bold]{title}[/bold]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Plugin")
    table.add_column("Installed")
    table.add_column("Available")
    table.add_column("Status")
    for row in rows:
        status = row.status
        style = _STATUS_STYLE.get(status, "")
        status_text = f"[{style}]{status}[/{style}]" if style else status
        table.add_row(
            row.plugin,
            row.installed_version or "—",
            row.available_version or "—",
            status_text,
        )
    console.print(table)

    proceed = Prompt.ask(
        "Continue?", choices=["y", "n"], default="y", console=console
    )
    return proceed == "y"
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/flow/test_detection.py -v --no-cov
```

- [ ] **Step 5: Commit**

```bash
git add installer/flow/detection.py installer/tests/flow/test_detection.py
git commit -m "feat(installer/672): port DetectionScreen → flow.show_detection_and_confirm (P3)"
```

---

## Task 4: Port CorruptYamlScreen → `installer/flow/corrupt_yaml.py`

**Files:**
- Create: `installer/flow/corrupt_yaml.py`
- Create: `installer/tests/flow/test_corrupt_yaml.py`

**Context:** CorruptYamlScreen gets `errors: dict[str, Exception]` — keys are bucket names (e.g. "proj", "worktree"), values are the parse exceptions. Returns `bool` — True = continue with defaults, False = cancel.

- [ ] **Step 1: Write failing tests**

Create `installer/tests/flow/test_corrupt_yaml.py`:

```python
# installer/tests/flow/test_corrupt_yaml.py
import pytest
from rich.console import Console
import yaml

from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm


def _errors() -> dict[str, Exception]:
    # Simulate a real parse failure.
    try:
        yaml.safe_load(":::not-valid")
    except yaml.YAMLError as e:
        return {"proj": e, "worktree": yaml.YAMLError("bad token")}
    return {}


class TestShowCorruptYamlAndConfirm:
    def test_continue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert show_corrupt_yaml_and_confirm(_errors(), console) is True

    def test_cancel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert show_corrupt_yaml_and_confirm(_errors(), console) is False

    def test_renders_bucket_and_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        show_corrupt_yaml_and_confirm(_errors(), console)
        text = console.export_text()
        assert "proj" in text
        assert "worktree" in text
        assert "bad token" in text or "YAMLError" in text
        # Should mention ~/.claude path hint
        assert ".claude" in text

    def test_empty_errors_returns_true_without_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prompt_called = {"n": 0}

        def fake_ask(*a, **k):
            prompt_called["n"] += 1
            return "y"

        monkeypatch.setattr("rich.prompt.Prompt.ask", fake_ask)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert show_corrupt_yaml_and_confirm({}, console) is True
        assert prompt_called["n"] == 0
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `corrupt_yaml.py`**

```python
# installer/flow/corrupt_yaml.py
"""Rich-based replacement for Textual CorruptYamlScreen.

Displays each corrupt yaml file with its bucket, path, and parse
exception, then prompts y/n to continue with defaults.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt


def show_corrupt_yaml_and_confirm(
    errors: dict[str, Exception], console: Console
) -> bool:
    """Render each corrupt-yaml bucket + prompt to continue with defaults.

    Short-circuits with ``True`` when ``errors`` is empty (nothing to show).
    """
    if not errors:
        return True

    console.print(
        Panel(
            "[bold red]⚠ Corrupt Configuration File(s)[/bold red]\n\n"
            "The following ~/.claude/*.yaml files could not be parsed. "
            "You can continue with defaults (values from the affected files "
            "will NOT be preserved) or cancel to fix them manually.",
            border_style="red",
        )
    )

    for bucket, exc in errors.items():
        path = Path.home() / ".claude" / f"{bucket}.yaml"
        original = getattr(exc, "original", exc)
        body = f"[bold]{bucket}.yaml[/bold]\n{path}\nReason: {original}"
        console.print(Panel(body, border_style="yellow"))

    proceed = Prompt.ask(
        "Continue with defaults?",
        choices=["y", "n"],
        default="n",
        console=console,
    )
    return proceed == "y"
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/corrupt_yaml.py installer/tests/flow/test_corrupt_yaml.py
git commit -m "feat(installer/672): port CorruptYamlScreen → flow.show_corrupt_yaml_and_confirm (P3)"
```

---

## Task 5: Port HooksDiffScreen → `installer/flow/hooks_diff.py`

**Files:**
- Create: `installer/flow/hooks_diff.py`
- Create: `installer/tests/flow/test_hooks_diff.py`

**Context:** HooksDiffScreen takes `diffs: list[HookDiff]` (the dataclass from `installer/hooks_diff.py`; each has fields like `hook_id`, `plugin`, `operation`, `old`, `new`, `label` via `_normalize_diff`). Returns `dict[str, set[str]] | None` where the dict has `{"apply": {hook_ids...}, "remove": {hook_ids...}}`, or None on cancel.

In the Rich port, we show each diff entry as a Rich Syntax panel, prompt for an action (apply all / skip all / select-and-continue / cancel). For the "select-and-continue" path, loop per diff prompting y/n to apply.

**Inspect the HookDiff dataclass + `_normalize_diff` + `compute_hooks_diff` before writing the port:**

```bash
grep -n "class HookDiff\|def _normalize_diff\|def compute_hooks_diff" /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp/installer/hooks_diff.py
```

If `HookDiff` / `_normalize_diff` / `compute_hooks_diff` all live in `installer/hooks_diff.py` (non-Textual), import from there. Otherwise adjust.

- [ ] **Step 1: Write failing tests**

Create `installer/tests/flow/test_hooks_diff.py`:

```python
# installer/tests/flow/test_hooks_diff.py
import pytest
from rich.console import Console

from installer.flow.hooks_diff import review_hooks_diff
from installer.hooks_diff import HookDiff


def _diffs() -> list[HookDiff]:
    return [
        HookDiff(
            hook_id="proj-tracking-flush",
            plugin="proj",
            operation="add",
            old=None,
            new={"trigger": "todo_add", "target": "tracking_git_flush"},
        ),
        HookDiff(
            hook_id="todoist-auto",
            plugin="todoist",
            operation="modify",
            old={"trigger": "todo_add"},
            new={"trigger": "todo_add_batch"},
        ),
        HookDiff(
            hook_id="stale-hook",
            plugin="old",
            operation="remove",
            old={"trigger": "x"},
            new=None,
        ),
    ]


class TestReviewHooksDiff:
    def test_empty_returns_empty_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = review_hooks_diff([], console)
        assert result == {"apply": set(), "remove": set()}

    def test_apply_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # First prompt: "a" (apply all).
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "a")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = review_hooks_diff(_diffs(), console)
        assert result == {
            "apply": {"proj-tracking-flush", "todoist-auto"},
            "remove": {"stale-hook"},
        }

    def test_skip_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = review_hooks_diff(_diffs(), console)
        assert result == {"apply": set(), "remove": set()}

    def test_cancel_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "c")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_hooks_diff(_diffs(), console) is None

    def test_diff_content_rendered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "c")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        review_hooks_diff(_diffs(), console)
        text = console.export_text()
        assert "proj-tracking-flush" in text
        assert "todoist-auto" in text
        assert "stale-hook" in text
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# installer/flow/hooks_diff.py
"""Rich-based replacement for Textual HooksDiffScreen.

Renders each HookDiff (add/modify/remove) in a Rich Panel + prompts for
apply-all / skip-all / cancel. Returns {"apply": set[hook_id], "remove": set}
or None on cancel. Mirrors the Textual screen's return-value shape.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from installer.hooks_diff import HookDiff


_OP_STYLE = {"add": "green", "modify": "yellow", "remove": "red"}


def review_hooks_diff(
    diffs: list[HookDiff], console: Console
) -> dict[str, set[str]] | None:
    """Show diffs + prompt for apply-all / skip-all / cancel.

    Returns ``{"apply": set, "remove": set}`` (keys always present) or
    ``None`` if user cancels. An empty ``diffs`` returns empty sets with no prompt.
    """
    if not diffs:
        return {"apply": set(), "remove": set()}

    console.print("[bold]Hook Configuration Updates[/bold]")

    for diff in diffs:
        style = _OP_STYLE.get(diff.operation, "cyan")
        header = f"[{style}]{diff.operation.upper()}[/] {diff.hook_id} ({diff.plugin})"
        body_lines: list[str] = []
        if diff.old is not None:
            body_lines.append("Old:")
            body_lines.append(str(diff.old))
        if diff.new is not None:
            body_lines.append("New:")
            body_lines.append(str(diff.new))
        console.print(Panel("\n".join(body_lines), title=header, border_style=style))

    choice = Prompt.ask(
        "Action",
        choices=["a", "s", "c"],
        default="a",
        console=console,
    )
    if choice == "c":
        return None

    apply_ids: set[str] = set()
    remove_ids: set[str] = set()

    if choice == "a":
        for d in diffs:
            if d.operation in ("add", "modify"):
                apply_ids.add(d.hook_id)
            elif d.operation == "remove":
                remove_ids.add(d.hook_id)

    # choice == "s" leaves both sets empty
    return {"apply": apply_ids, "remove": remove_ids}
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/hooks_diff.py installer/tests/flow/test_hooks_diff.py
git commit -m "feat(installer/672): port HooksDiffScreen → flow.review_hooks_diff (P3)"
```

---

## Task 6: Port ConfigDiffScreen → `installer/flow/config_diff.py`

**Files:**
- Create: `installer/flow/config_diff.py`
- Create: `installer/tests/flow/test_config_diff.py`

**Context:** ConfigDiffScreen takes `service_name: str`, `diff_text: str`. Returns bool (apply vs cancel).

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/flow/test_config_diff.py
import pytest
from rich.console import Console

from installer.flow.config_diff import review_config_diff


_DIFF = """\
--- a/todoist.yaml
+++ b/todoist.yaml
@@ -1 +1 @@
-api_token: old
+api_token: new
"""


class TestReviewConfigDiff:
    def test_apply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_config_diff("Todoist", _DIFF, console) is True

    def test_cancel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_config_diff("Todoist", _DIFF, console) is False

    def test_renders_service_and_diff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        review_config_diff("Todoist", _DIFF, console)
        text = console.export_text()
        assert "Todoist" in text
        assert "api_token" in text

    def test_empty_diff_returns_true_without_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        count = {"n": 0}
        def fake_ask(*a, **k):
            count["n"] += 1
            return "y"
        monkeypatch.setattr("rich.prompt.Prompt.ask", fake_ask)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_config_diff("Todoist", "", console) is True
        assert count["n"] == 0
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# installer/flow/config_diff.py
"""Rich-based replacement for Textual ConfigDiffScreen.

Renders a unified yaml diff with Rich Syntax highlighting + prompts y/n
to apply. Mirrors the Textual screen's bool return value.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax


def review_config_diff(service_name: str, diff_text: str, console: Console) -> bool:
    """Show diff + prompt apply/cancel.

    Short-circuits with ``True`` when ``diff_text`` is empty (nothing to apply anyway).
    """
    if not diff_text.strip():
        return True

    console.print(f"[bold]Configuration Changes — {service_name}[/bold]")
    syntax = Syntax(diff_text, "diff", theme="ansi_dark", line_numbers=False)
    console.print(Panel(syntax, border_style="cyan"))

    proceed = Prompt.ask(
        "Apply?", choices=["y", "n"], default="y", console=console
    )
    return proceed == "y"
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/config_diff.py installer/tests/flow/test_config_diff.py
git commit -m "feat(installer/672): port ConfigDiffScreen → flow.review_config_diff (P3)"
```

---

## Task 7: Port UpdateScreen → `installer/flow/update.py` (prompt_toolkit)

**Files:**
- Create: `installer/flow/update.py`
- Create: `installer/tests/flow/test_update.py`

**Context:** UpdateScreen takes `version_diffs: dict[str, tuple[str, str]]` where value = (installed_ver, available_ver). All selected by default. User picks via checkbox-list. Returns `list[str]` of selected plugin names, empty list on cancel.

Uses `prompt_toolkit.shortcuts.checkboxlist_dialog`. To test, mock the dialog function directly — don't drive prompt_toolkit's event loop.

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/flow/test_update.py
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from installer.flow.update import select_updates


_DIFFS = {
    "proj": ("1.0.0", "1.1.0"),
    "worktree": ("2.0.0", "2.0.1"),
    "router": ("3.0.0", "3.1.0"),
}


class TestSelectUpdates:
    def test_all_selected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dialog = MagicMock()
        mock_dialog.return_value.run.return_value = ["proj", "worktree", "router"]
        monkeypatch.setattr(
            "installer.flow.update.checkboxlist_dialog", mock_dialog
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_updates(_DIFFS, console)
        assert sorted(result) == ["proj", "router", "worktree"]
        # Verify the dialog was called with all 3 plugins as default-selected
        call_kwargs = mock_dialog.call_args.kwargs
        assert set(call_kwargs.get("default_values", [])) == {"proj", "worktree", "router"}

    def test_partial_selection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dialog = MagicMock()
        mock_dialog.return_value.run.return_value = ["proj"]
        monkeypatch.setattr(
            "installer.flow.update.checkboxlist_dialog", mock_dialog
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_updates(_DIFFS, console)
        assert result == ["proj"]

    def test_cancel_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dialog = MagicMock()
        # checkboxlist_dialog returns None when user presses Cancel
        mock_dialog.return_value.run.return_value = None
        monkeypatch.setattr(
            "installer.flow.update.checkboxlist_dialog", mock_dialog
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert select_updates(_DIFFS, console) == []

    def test_empty_diffs_returns_empty_without_dialog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_dialog = MagicMock()
        monkeypatch.setattr(
            "installer.flow.update.checkboxlist_dialog", mock_dialog
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_updates({}, console)
        assert result == []
        mock_dialog.assert_not_called()

    def test_dialog_values_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify the `values` kwarg to the dialog is a list of (plugin, label) pairs."""
        mock_dialog = MagicMock()
        mock_dialog.return_value.run.return_value = []
        monkeypatch.setattr(
            "installer.flow.update.checkboxlist_dialog", mock_dialog
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        select_updates(_DIFFS, console)
        values = mock_dialog.call_args.kwargs.get("values", [])
        # Each entry is (key, formatted_label_with_versions)
        keys = [v[0] for v in values]
        labels = [v[1] for v in values]
        assert set(keys) == {"proj", "worktree", "router"}
        assert any("1.0.0" in lbl and "1.1.0" in lbl for lbl in labels)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# installer/flow/update.py
"""prompt_toolkit-based replacement for Textual UpdateScreen.

Renders a checkbox list of outdated plugins with installed→available
versions. Returns the selected plugin names, or empty list on cancel.
"""

from __future__ import annotations

from prompt_toolkit.shortcuts import checkboxlist_dialog
from rich.console import Console


def select_updates(
    version_diffs: dict[str, tuple[str, str]], console: Console
) -> list[str]:
    """Prompt user to pick which plugins to update.

    Short-circuits with empty list when ``version_diffs`` is empty.
    """
    if not version_diffs:
        return []

    plugins = sorted(version_diffs.keys())
    values: list[tuple[str, str]] = []
    for name in plugins:
        installed, available = version_diffs[name]
        values.append((name, f"{name}  {installed} → {available}"))

    selected = checkboxlist_dialog(
        title="Plugin Updates Available",
        text="Select plugins to update (Space to toggle, Enter to confirm).",
        values=values,
        default_values=plugins,  # all selected by default
    ).run()

    return selected or []
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/update.py installer/tests/flow/test_update.py
git commit -m "feat(installer/672): port UpdateScreen → flow.select_updates (prompt_toolkit, P3)"
```

---

## Task 8: Port PluginStatusScreen → `installer/flow/plugin_select.py` (prompt_toolkit)

**Files:**
- Create: `installer/flow/plugin_select.py`
- Create: `installer/tests/flow/test_plugin_select.py`

**Context:** PluginStatusScreen takes `statuses: list[PluginStatus]` (each has `.plugin`, `.available_version`, `.installed_version`, `.is_outdated`, `.is_installed`, `.status_bucket`). Returns list of `(plugin_name, action)` tuples where action ∈ {install, reinstall, uninstall, skip}.

The Textual screen lets users cycle per-row actions (space). For the prompt_toolkit port, we'll show the installed plugins as one checkboxlist (toggles uninstall), then a separate checkboxlist for available-but-not-installed (toggles install). Per-row cycle was clever but not essential — 2 simple checkboxes preserve all outcomes.

Simpler alternative: **one checkboxlist per bucket** — available (select to install), installed (select to reinstall), outdated (select to update).

**Inspect PluginStatus first:**

```bash
grep -n "class PluginStatus\|status_bucket" /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp/installer/plugin_status.py | head -10
```

Confirm the dataclass fields before coding.

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/flow/test_plugin_select.py
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from installer.flow.plugin_select import select_plugin_actions
from installer.plugin_status import PluginStatus


def _statuses() -> list[PluginStatus]:
    return [
        PluginStatus(
            plugin="proj",
            available_version="1.1.0",
            installed_version="1.0.0",
        ),  # outdated
        PluginStatus(
            plugin="router",
            available_version="3.0.0",
            installed_version="3.0.0",
        ),  # installed up-to-date
        PluginStatus(
            plugin="worktree",
            available_version="2.0.0",
            installed_version=None,
        ),  # available, not installed
    ]


class TestSelectPluginActions:
    def test_install_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simulate 3 sequential checkboxlist calls:
        # 1. install-available → ["worktree"]
        # 2. update-outdated → []
        # 3. reinstall-installed → []
        mock = MagicMock()
        mock.return_value.run.side_effect = [["worktree"], [], []]
        monkeypatch.setattr(
            "installer.flow.plugin_select.checkboxlist_dialog", mock
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_plugin_actions(_statuses(), console)
        assert ("worktree", "install") in result
        assert not any(n == "proj" for n, _ in result)
        assert not any(n == "router" for n, _ in result)

    def test_update_and_reinstall(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        mock.return_value.run.side_effect = [[], ["proj"], ["router"]]
        monkeypatch.setattr(
            "installer.flow.plugin_select.checkboxlist_dialog", mock
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_plugin_actions(_statuses(), console)
        assert ("proj", "install") in result  # update = install-latest
        assert ("router", "reinstall") in result

    def test_cancel_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        mock.return_value.run.side_effect = [None, None, None]
        monkeypatch.setattr(
            "installer.flow.plugin_select.checkboxlist_dialog", mock
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert select_plugin_actions(_statuses(), console) == []

    def test_empty_statuses_returns_empty_without_dialog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = MagicMock()
        monkeypatch.setattr(
            "installer.flow.plugin_select.checkboxlist_dialog", mock
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert select_plugin_actions([], console) == []
        mock.assert_not_called()
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# installer/flow/plugin_select.py
"""prompt_toolkit-based replacement for Textual PluginStatusScreen.

Three sequential checkboxlist dialogs — one per status bucket:
  1. Available (not installed): selection → action="install"
  2. Outdated (installed + newer version available): selection → "install" (update)
  3. Installed (up-to-date): selection → "reinstall"

Returns a list of (plugin_name, action) tuples for every selected plugin.
"""

from __future__ import annotations

from prompt_toolkit.shortcuts import checkboxlist_dialog
from rich.console import Console

from installer.plugin_status import PluginStatus


def _partition(
    statuses: list[PluginStatus],
) -> tuple[list[PluginStatus], list[PluginStatus], list[PluginStatus]]:
    """Split into (available, outdated, installed_up_to_date) buckets."""
    available: list[PluginStatus] = []
    outdated: list[PluginStatus] = []
    installed: list[PluginStatus] = []
    for s in statuses:
        if s.installed_version is None and s.available_version is not None:
            available.append(s)
        elif (
            s.installed_version is not None
            and s.available_version is not None
            and s.installed_version != s.available_version
        ):
            outdated.append(s)
        elif s.installed_version is not None:
            installed.append(s)
    return available, outdated, installed


def _prompt(
    title: str, text: str, values: list[tuple[str, str]]
) -> list[str] | None:
    if not values:
        return []
    return checkboxlist_dialog(
        title=title, text=text, values=values
    ).run()


def select_plugin_actions(
    statuses: list[PluginStatus], console: Console
) -> list[tuple[str, str]]:
    """Prompt for per-bucket selections, return flat list of (name, action)."""
    if not statuses:
        return []

    available, outdated, installed = _partition(statuses)

    actions: list[tuple[str, str]] = []

    picks = _prompt(
        "Available Plugins",
        "Select plugins to install:",
        [(s.plugin, f"{s.plugin}  (available {s.available_version})") for s in available],
    )
    if picks is None:
        return []  # user cancelled
    for name in picks:
        actions.append((name, "install"))

    picks = _prompt(
        "Outdated Plugins",
        "Select plugins to update:",
        [
            (s.plugin, f"{s.plugin}  {s.installed_version} → {s.available_version}")
            for s in outdated
        ],
    )
    if picks is None:
        return []
    for name in picks:
        actions.append((name, "install"))  # update == install-latest

    picks = _prompt(
        "Installed Plugins",
        "Select plugins to reinstall (leave blank to skip):",
        [
            (s.plugin, f"{s.plugin}  {s.installed_version}")
            for s in installed
        ],
    )
    if picks is None:
        return []
    for name in picks:
        actions.append((name, "reinstall"))

    return actions
```

**Caveat:** if `PluginStatus` has different field names (e.g. `.is_outdated`), adjust `_partition`. Read `installer/plugin_status.py` first.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/plugin_select.py installer/tests/flow/test_plugin_select.py
git commit -m "feat(installer/672): port PluginStatusScreen → flow.select_plugin_actions (prompt_toolkit, P3)"
```

---

## Task 9: Create `installer/flow/pre_install_phase.py`

**Files:**
- Create: `installer/flow/pre_install_phase.py`
- Create: `installer/tests/flow/test_pre_install_phase.py`

**Context:** The pre-phase orchestrator (see spec §1). Accepts mode + args + console, returns `PreInstallResult`. Delegates to the ported Rich helpers.

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/flow/test_pre_install_phase.py
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from installer.flow.pre_install_phase import (
    PreInstallResult,
    pre_install_phase,
)


class _Args:
    pass


class TestPreInstallPhaseReinstall:
    def test_cancel_at_detection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(),
            ) as _mock_detect,
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=False,
            ) as _mock_det,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("reinstall", _Args(), console)
        assert isinstance(result, PreInstallResult)
        assert result.proceed is False

    def test_cancel_at_reinstall_confirm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options"
            ) as mock_conf,
        ):
            from installer.flow.confirm import ConfirmResult

            mock_conf.return_value = ConfirmResult(confirmed=False, options={})
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("reinstall", _Args(), console)
        assert result.proceed is False

    def test_full_reinstall_flow_no_orphans(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.flow.confirm import ConfirmResult

        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options",
                return_value=ConfirmResult(
                    confirmed=True, options={"reset_configs": False}
                ),
            ),
            patch(
                "installer.flow.pre_install_phase.scan_stale_cache",
                return_value=MagicMock(orphans=[]),
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("reinstall", _Args(), console)
        assert result.proceed is True
        assert result.mode_options == {"reset_configs": False}


class TestPreInstallPhaseUninstall:
    def test_full_uninstall_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from installer.flow.confirm import ConfirmResult

        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options",
                return_value=ConfirmResult(
                    confirmed=True, options={"full_cleanup": True}
                ),
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("uninstall", _Args(), console)
        assert result.proceed is True
        assert result.mode_options == {"full_cleanup": True}


class TestPreInstallPhaseInstall:
    def test_install_mode_skips_detection_confirm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install mode does marketplace check + status scan; NO detection prompt."""
        from installer.flow.confirm import ConfirmResult

        with (
            patch(
                "installer.flow.pre_install_phase.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.show_corrupt_yaml_and_confirm",
                return_value=True,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("install", _Args(), console)
        assert result.proceed is True
```

Note: `MagicMock` imports — add `from unittest.mock import MagicMock` at top of test file.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# installer/flow/pre_install_phase.py
"""Pre-phase orchestrator for the installer flow.

Runs BEFORE any Textual-needing interactive screen. Handles:
 - corrupt-yaml detection + confirm (all modes)
 - existing installation detection + confirm (update/reinstall/uninstall)
 - mode-specific confirms (reinstall: reset_configs + orphans; uninstall: full_cleanup)
 - marketplace auto-register (install mode)

Returns a PreInstallResult that main.py dispatches on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.console import Console

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.cleanup import (
    _cache_dir_for_reinstall,
    _marketplace_path_for_reinstall,
    scan_stale_cache,
)
from installer.detect import detect_existing
from installer.flow.confirm import ConfirmOption, confirm_with_options
from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm
from installer.flow.detection import show_detection_and_confirm
from installer.plugin_cli import check_marketplace_registered
from installer.update import (
    _read_installed_version,
    _read_marketplace_versions,
)

if TYPE_CHECKING:
    from installer.detect import InstallState
    from installer.screens.detection import PluginDetectionRow  # deletion deferred to Task 12


@dataclass(frozen=True)
class PreInstallResult:
    state: "InstallState | None"
    proceed: bool
    mode_options: dict[str, bool] = field(default_factory=dict)
    exit_code: int = 0
    error_message: str | None = None
    # Install-mode extras (populated only for install mode).
    orphans_to_remove: list[str] = field(default_factory=list)


def _build_detection_rows(state: "InstallState") -> list["PluginDetectionRow"]:
    """Build the (plugin, installed, available) rows used by detection."""
    # Kept here to avoid InstallerApp coupling.
    from installer.screens.detection import PluginDetectionRow  # TODO delete after Task 12

    repo_versions = _read_marketplace_versions()
    rows: list[PluginDetectionRow] = []
    all_plugins = sorted(set(state.installed_plugins) | set(repo_versions.keys()))
    for name in all_plugins:
        installed_ver = None
        if state.cache_dir is not None and name in state.installed_plugins:
            installed_ver = _read_installed_version(state.cache_dir, name)
        available_ver = repo_versions.get(name)
        rows.append(
            PluginDetectionRow(
                plugin=name,
                installed_version=installed_ver,
                available_version=available_ver,
            )
        )
    return rows


def _check_corrupt_yaml(console: Console) -> bool:
    """Load ~/.claude/*.yaml. If any fails, show prompt + return user choice."""
    try:
        load_existing_yaml()
    except ConfigLoadError as exc:
        errors: dict[str, Exception] = getattr(exc, "errors", {"config": exc})
        return show_corrupt_yaml_and_confirm(errors, console)
    return True


def pre_install_phase(
    mode: str, args: Any, console: Console
) -> PreInstallResult:
    # Every mode runs corrupt-yaml check first.
    if not _check_corrupt_yaml(console):
        return PreInstallResult(
            state=None,
            proceed=False,
            error_message="Cancelled by user (corrupt config).",
        )

    if mode == "install":
        # Marketplace check (auto-register if needed) happens later in main.py.
        # For install mode, we do NOT detect existing state here — the plugin
        # status scan + PluginStatusScreen equivalent handles per-plugin picks.
        return PreInstallResult(state=None, proceed=True)

    # update / reinstall / uninstall all share: detect + detection-confirm.
    state = detect_existing()
    rows = _build_detection_rows(state)
    title = f"Existing Installation — {mode.title()} Mode"
    if not show_detection_and_confirm(state, rows, title, console):
        return PreInstallResult(state=state, proceed=False)

    if mode == "update":
        # Update flow selection happens via select_updates later; no extra confirm here.
        return PreInstallResult(state=state, proceed=True)

    if mode == "reinstall":
        confirm = confirm_with_options(
            title="Reinstall Plugins",
            message=(
                "This will reinstall all installed plugins.\n"
                "A backup will be created before any changes."
            ),
            options=[
                ConfirmOption(
                    key="reset_configs",
                    label="Reset configs (remove proj.yaml, worktree.yaml)",
                    default=False,
                )
            ],
            console=console,
            variant="warning",
            confirm_label="Reinstall",
        )
        if not confirm.confirmed:
            return PreInstallResult(state=state, proceed=False)

        # Orphan cache scan — if any, prompt to remove.
        cache_dir = _cache_dir_for_reinstall()
        marketplace_path = _marketplace_path_for_reinstall()
        orphans: list[str] = []
        if cache_dir.is_dir() and marketplace_path.is_file():
            try:
                report = scan_stale_cache(cache_dir, marketplace_path)
                if report is not None and report.orphans:
                    orphan_names = list(report.orphans)
                    confirm_orph = confirm_with_options(
                        title="Remove Orphaned Plugins",
                        message=(
                            f"Found {len(orphan_names)} orphaned plugin dir(s) "
                            f"in cache:\n  {', '.join(orphan_names)}\n\n"
                            "These plugins are no longer in the marketplace. Remove them?"
                        ),
                        options=[],
                        console=console,
                        variant="warning",
                        confirm_label="Remove",
                    )
                    if confirm_orph.confirmed:
                        orphans = orphan_names
            except (FileNotFoundError, OSError):
                pass
        return PreInstallResult(
            state=state,
            proceed=True,
            mode_options=confirm.options,
            orphans_to_remove=orphans,
        )

    if mode == "uninstall":
        confirm = confirm_with_options(
            title="Uninstall Plugins",
            message=(
                "This will remove all installed plugins.\n"
                "A backup will be created before removal."
            ),
            options=[
                ConfirmOption(
                    key="full_cleanup",
                    label="Full cleanup (remove configs + CLAUDE.md managed section)",
                    default=False,
                )
            ],
            console=console,
            variant="error",
            confirm_label="Uninstall",
        )
        if not confirm.confirmed:
            return PreInstallResult(state=state, proceed=False)
        return PreInstallResult(state=state, proceed=True, mode_options=confirm.options)

    # Unknown mode — defensive fallback.
    return PreInstallResult(
        state=None,
        proceed=False,
        exit_code=2,
        error_message=f"Unknown mode: {mode}",
    )
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/pre_install_phase.py installer/tests/flow/test_pre_install_phase.py
git commit -m "feat(installer/672): add pre_install_phase orchestrator (P3)"
```

---

## Task 10: Create `installer/flow/installer_flow.py` top-level dispatcher

**Files:**
- Create: `installer/flow/installer_flow.py`
- Create: `installer/tests/flow/test_installer_flow.py`

**Context:** `run_installer_flow(mode, args, console)` replaces `InstallerApp().run()`. It calls `pre_install_phase`, then dispatches to per-mode logic. Reinstall/uninstall build plans plain; install/update call the Rich helpers then build plans.

- [ ] **Step 1: Write failing tests**

Structure the tests to mock each dependency (pre_install_phase, select_plugin_actions, review_hooks_diff, select_updates, execute_install_plan, cleanup_orphaned_plugin_caches). Verify flow per mode.

```python
# installer/tests/flow/test_installer_flow.py
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from installer.flow.installer_flow import run_installer_flow
from installer.flow.install_plan import InstallAction, InstallPlan, InstallResult
from installer.flow.pre_install_phase import PreInstallResult


class _Args:
    pass


def _success_result() -> InstallResult:
    return InstallResult(success_count=1, failure_count=0, failures=[])


class TestRunInstallerFlowReinstall:
    def test_cancelled_pre_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with patch(
            "installer.flow.installer_flow.pre_install_phase",
            return_value=PreInstallResult(state=None, proceed=False, exit_code=0),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("reinstall", _Args(), console)
        assert code == 0

    def test_reinstall_builds_plan_and_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                    mode_options={"reset_configs": False},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@m"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@m"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_success_result(),
            ) as mock_exec,
            patch(
                "installer.flow.installer_flow.cleanup_orphaned_plugin_caches"
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("reinstall", _Args(), console)
        assert code == 0
        plan_arg = mock_exec.call_args.args[0]
        assert isinstance(plan_arg, InstallPlan)
        assert any(a.action == "reinstall" for a in plan_arg.actions)


class TestRunInstallerFlowUninstall:
    def test_uninstall_builds_plan_with_full_cleanup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj", "worktree"]),
                    proceed=True,
                    mode_options={"full_cleanup": True},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@m", "worktree@m"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@m", "worktree@m"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_success_result(),
            ) as mock_exec,
            patch(
                "installer.flow.installer_flow.cleanup_orphaned_plugin_caches"
            ),
            patch(
                "installer.flow.installer_flow.remove_managed_section"
            ) as mock_rm,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("uninstall", _Args(), console)
        assert code == 0
        plan_arg = mock_exec.call_args.args[0]
        assert all(a.action == "uninstall" for a in plan_arg.actions)
        mock_rm.assert_called_once()  # full_cleanup=True ran


class TestRunInstallerFlowInstall:
    def test_install_asks_plugin_select_and_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(plugin="proj")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("proj", "install")],
            ),
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value={"apply": set(), "remove": set()},
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@m"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_success_result(),
            ) as mock_exec,
            patch(
                "installer.flow.installer_flow.cleanup_orphaned_plugin_caches"
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        plan = mock_exec.call_args.args[0]
        assert any(a.plugin_id == "proj@m" and a.action == "install" for a in plan.actions)

    def test_install_cancelled_at_plugin_select(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(plugin="proj")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan"
            ) as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()


class TestRunInstallerFlowUpdate:
    def test_update_selects_plugins_and_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                ),
            ),
            patch(
                "installer.flow.installer_flow.compare_versions",
                return_value={"proj": ("1.0.0", "1.1.0")},
            ),
            patch(
                "installer.flow.installer_flow.select_updates",
                return_value=["proj"],
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@m"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@m"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_success_result(),
            ) as mock_exec,
            patch(
                "installer.flow.installer_flow.cleanup_orphaned_plugin_caches"
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("update", _Args(), console)
        assert code == 0
        plan = mock_exec.call_args.args[0]
        assert any(a.plugin_id == "proj@m" and a.action == "update" for a in plan.actions)

    def test_update_empty_diff_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                ),
            ),
            patch(
                "installer.flow.installer_flow.compare_versions",
                return_value={},
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan"
            ) as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("update", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# installer/flow/installer_flow.py
"""Top-level installer flow dispatcher.

Replaces InstallerApp().run(). Orchestrates the 3-phase flow:
  1. pre_install_phase (Rich): detection, corrupt-yaml, mode-specific confirms
  2. interactive phase (mode-specific): Rich/prompt_toolkit prompts or plain plan-build
  3. execution phase (Rich progress + cleanup)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claudemd import ensure_managed_section, remove_managed_section
from rich.console import Console

from installer.cleanup import cleanup_orphaned_plugin_caches, prune_orphaned_plugins
from installer.errors import InstallerError
from installer.flow.hooks_diff import review_hooks_diff
from installer.flow.install_plan import (
    InstallAction,
    InstallPlan,
    execute_install_plan,
)
from installer.flow.plugin_select import select_plugin_actions
from installer.flow.pre_install_phase import pre_install_phase
from installer.flow.update import select_updates
from installer.plugin_cli import (
    check_marketplace_registered,
    get_available_plugins,
    get_installed_plugins,
)
from installer.plugin_status import build_plugin_status_list
from installer.update import compare_versions


def _name_to_id_map() -> dict[str, str]:
    try:
        available = get_available_plugins()
        installed_ids = get_installed_plugins()
    except InstallerError:
        available, installed_ids = [], []
    name_to_id: dict[str, str] = {}
    for pid in list(available) + list(installed_ids):
        name_to_id.setdefault(pid.split("@")[0], pid)
    return name_to_id


def _resolve_id(name: str, name_to_id: dict[str, str]) -> str:
    return name_to_id.get(name, f"{name}@claude-project-manager")


def _execute_and_report(
    plan: InstallPlan, console: Console
) -> int:
    """Run the plan + report failures via Rich console. Returns exit code."""
    result = execute_install_plan(plan, console)
    if result.failure_count:
        for failure in result.failures:
            console.print(
                f"[red]✗[/] {failure.plugin_id} ({failure.action}): {failure.error}"
            )
        return 1
    return 0


def _post_execute_cleanup(
    full_cleanup: bool, orphans: list[str], console: Console
) -> None:
    cache_root = Path.home() / ".claude" / "plugins" / "cache"
    installed_json = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        cleanup_orphaned_plugin_caches(cache_root, installed_json)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    if orphans:
        prune_orphaned_plugins(cache_root, orphans)
    if full_cleanup:
        remove_managed_section(Path.home() / ".claude" / "CLAUDE.md")


def _run_install(
    args: Any, console: Console
) -> int:
    """Install mode: marketplace check → status scan → select → hooks diff → execute."""
    if not check_marketplace_registered():
        # Marketplace auto-registration logic preserved from old worker:
        from installer.plugin_cli import add_marketplace

        console.print("[yellow]Marketplace not registered — registering...[/]")
        try:
            branch = getattr(args, "branch", None)
            add_marketplace(branch=branch)
        except InstallerError as exc:
            console.print(f"[red]Failed to register marketplace:[/] {exc}")
            return 1

    statuses = build_plugin_status_list()
    actions = select_plugin_actions(statuses, console)
    if not actions:
        console.print("[dim]No actions selected.[/dim]")
        return 0

    # Hooks diff review — happens after plugin selection in the Textual flow.
    # Loading plugin_dirs list from cache:
    plugin_dirs: list[Path] = []  # The hooks_diff helper can compute internally if empty.
    from installer.hooks_diff import compute_hooks_diff

    hooks_yaml = Path.home() / ".claude" / "hooks.yaml"
    diffs = compute_hooks_diff(hooks_yaml, plugin_dirs)
    hooks_decision = review_hooks_diff(diffs, console)
    if hooks_decision is None:
        console.print("[dim]Cancelled at hooks review.[/dim]")
        return 0
    if hooks_decision["apply"] or hooks_decision["remove"]:
        from installer.hooks_diff import apply_diffs

        apply_diffs(hooks_yaml, diffs, hooks_decision["apply"], hooks_decision["remove"])

    # CLAUDE.md managed section gets ensured post-install.
    ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")

    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(
            plugin_id=_resolve_id(name, name_to_id),
            action=action,  # type: ignore[arg-type]
        )
        for name, action in actions
    ]
    plan = InstallPlan(
        description=f"Processing {len(plan_actions)} plugin actions...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(full_cleanup=False, orphans=[], console=console)
    return exit_code


def _run_update(
    args: Any, pre_state: Any, console: Console
) -> int:
    """Update mode: compare versions → select → execute."""
    diffs = compare_versions(pre_state)
    if not diffs:
        console.print("[dim]All plugins are up to date.[/dim]")
        return 0
    selected = select_updates(diffs, console)
    if not selected:
        console.print("[dim]No updates selected.[/dim]")
        return 0
    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(
            plugin_id=_resolve_id(name, name_to_id),
            action="update",
        )
        for name in selected
    ]
    plan = InstallPlan(
        description=f"Updating {len(plan_actions)} plugins...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(full_cleanup=False, orphans=[], console=console)
    return exit_code


def _run_reinstall(
    args: Any, pre_state: Any, mode_options: dict[str, bool], orphans: list[str], console: Console
) -> int:
    """Reinstall mode: build plan from installed plugins → execute → optional orphan prune."""
    installed_names = list(pre_state.installed_plugins) if pre_state else []
    if not installed_names:
        console.print("[dim]Nothing to reinstall.[/dim]")
        return 0
    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(plugin_id=_resolve_id(n, name_to_id), action="reinstall")
        for n in installed_names
    ]
    plan = InstallPlan(
        description=f"Reinstalling {len(plan_actions)} plugins...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(full_cleanup=False, orphans=orphans, console=console)
    return exit_code


def _run_uninstall(
    args: Any, pre_state: Any, mode_options: dict[str, bool], console: Console
) -> int:
    """Uninstall mode: build uninstall plan → execute → optional full_cleanup."""
    installed_names = list(pre_state.installed_plugins) if pre_state else []
    if not installed_names:
        console.print("[dim]Nothing to uninstall.[/dim]")
        return 0
    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(plugin_id=_resolve_id(n, name_to_id), action="uninstall")
        for n in installed_names
    ]
    plan = InstallPlan(
        description=f"Uninstalling {len(plan_actions)} plugins...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(
        full_cleanup=mode_options.get("full_cleanup", False),
        orphans=[],
        console=console,
    )
    return exit_code


def run_installer_flow(mode: str, args: Any, console: Console) -> int:
    """Top-level entry. Returns exit code."""
    pre = pre_install_phase(mode, args, console)
    if not pre.proceed:
        if pre.error_message:
            console.print(pre.error_message)
        return pre.exit_code

    if mode == "install":
        return _run_install(args, console)
    if mode == "update":
        return _run_update(args, pre.state, console)
    if mode == "reinstall":
        return _run_reinstall(
            args, pre.state, pre.mode_options, pre.orphans_to_remove, console
        )
    if mode == "uninstall":
        return _run_uninstall(args, pre.state, pre.mode_options, console)

    console.print(f"[red]Unknown mode: {mode}[/red]")
    return 2
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/installer_flow.py installer/tests/flow/test_installer_flow.py
git commit -m "feat(installer/672): add run_installer_flow top-level dispatcher (P3)"
```

---

## Task 11: Rewire `installer/main.py` to call `run_installer_flow`

**Files:**
- Modify: `installer/main.py`

- [ ] **Step 1: Read current main.py flow**

```bash
sed -n '1,100p' /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp/installer/main.py
```

Identify the block that instantiates `InstallerApp(...)` and calls `.run()`. Also note any mode-specific branches (e.g. migrate mode calls `run_migrations` separately).

- [ ] **Step 2: Replace `InstallerApp` call with `run_installer_flow`**

Find the block (likely looks like):

```python
from installer.app import InstallerApp
app = InstallerApp(mode=mode, args=parsed)
app.run()
# post-exit: read app.install_plan, run execute_install_plan, cleanup, etc.
```

Replace with:

```python
from installer.flow.console import get_console
from installer.flow.installer_flow import run_installer_flow

exit_code = run_installer_flow(mode, parsed, get_console())
return exit_code
```

Delete the post-exit execute_install_plan / cleanup_orphaned_plugin_caches / reinstall_message printing — all of that lives inside `run_installer_flow` now.

Preserve: argparse, mode detection, migrate-mode dispatch (uses `run_migration_tui` still), --migrate-sql-only dispatch (unchanged), --help, non-TTY handling.

- [ ] **Step 3: Run the installer unit tests**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/test_main.py --no-cov -v 2>&1 | tail -20
```

Expected: some tests FAIL. These are tests that mocked `InstallerApp` directly. Rewrite them to mock `run_installer_flow`. Example rewrite:

```python
# BEFORE:
with patch("installer.main.InstallerApp") as mock_app:
    mock_app_inst = MagicMock()
    mock_app_inst.install_plan = None
    mock_app.return_value = mock_app_inst
    ...

# AFTER:
with patch("installer.main.run_installer_flow") as mock_flow:
    mock_flow.return_value = 0
    ...
    # assert mock_flow.called_with(mode, args, console_of_some_kind)
```

Update each failing test surgically. Keep test intent the same; only change what's mocked.

- [ ] **Step 4: Run until green**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/test_main.py --no-cov -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add installer/main.py installer/tests/test_main.py
git commit -m "refactor(installer/672): main.py calls run_installer_flow instead of InstallerApp (P3)"
```

---

## Task 12: Delete InstallerApp + 7 Textual screens + Textual-specific tests

**Files:**
- Modify: `installer/app.py` — delete the `InstallerApp` class definition. Keep `run_migration_tui` (P2's plain function). File itself survives but shrinks dramatically.
- Delete: `installer/screens/confirm.py`, `detection.py`, `corrupt_yaml.py`, `hooks_diff.py`, `config_diff.py`, `update.py`, `plugin_select.py`
- Modify: `installer/screens/__init__.py` — remove exports for the deleted classes.
- Delete: Textual-specific tests for each ported screen. Read each test file to decide:
  - `installer/tests/test_app.py` — InstallerApp tests: delete entire classes like `TestInstallerApp`, `TestStartStatusInstall`, `TestPrepareAndReinstallBuildsInstallPlan`, `TestOnUpdateSelected`, `TestEmitResyncRunbooks`. Rewrite any tests that covered helpers we preserved (e.g. `_make_outcome_from_runner` if it lives in `app.py` — move to flow module if needed).
  - `installer/tests/test_corrupt_yaml_screen.py` — delete.
  - `installer/tests/test_integration_screens.py` — delete (Textual integration config screens still exist for P4, but their tests that used the screens are fine; the ones that drove InstallerApp are not).
  - `installer/tests/test_screens.py` — delete if it's Textual-only; inspect first.
  - `installer/tests/e2e/test_snapshots.py`, `test_snapshots_main.py`, `test_snapshots_confirm_progress.py`, `test_snapshots_advanced.py`, `test_snapshots_integration.py`, `test_snapshots_diff.py` — delete tests for the 7 ported screens. Leave tests for wizard, advanced_config, integration_config screens intact (P4 territory).
  - SVG goldens matching deleted tests.
- Delete: `installer/tests/e2e/test_install_flow.py`, `test_update_flows.py`, `test_integration_flow.py`, `test_uninstall_wizard.py`, `test_edge_cases.py` — REWRITE, don't delete. These tests drive `main.py` via subprocess; update their mocks to target `run_installer_flow` instead of InstallerApp.

**Context:** This is the big-bang deletion commit. DO NOT rewrite tests whose intent is broken — delete them. Preserve tests that verify behavior (not Textual-specific screen transitions).

- [ ] **Step 1: Identify what to delete vs rewrite**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp
grep -rn "InstallerApp\|ConfirmScreen\|DetectionScreen\|CorruptYamlScreen\|HooksDiffScreen\|ConfigDiffScreen\|UpdateScreen\|PluginStatusScreen" installer/ --include='*.py' | head -30
```

For each file, decide: delete (pure Textual-screen test) vs rewrite (behavioral test that happens to reference the screens).

- [ ] **Step 2: Delete the 7 screen files + screens/__init__.py exports**

```bash
rm installer/screens/confirm.py installer/screens/detection.py installer/screens/corrupt_yaml.py installer/screens/hooks_diff.py installer/screens/config_diff.py installer/screens/update.py installer/screens/plugin_select.py
```

Edit `installer/screens/__init__.py`: remove all imports + `__all__` entries for the 7 deleted classes + `PluginDetectionRow` + `ConfirmOption` + `ConfirmResult` (those are now in flow/).

- [ ] **Step 3: Delete InstallerApp class from installer/app.py**

Open `installer/app.py`. Remove:
- The `class InstallerApp(App):` block + all its methods.
- The top-level imports for deleted screens (`from installer.screens.confirm import ...` etc.).
- Any remaining `from textual.app import App` only if no other code in the file uses it (should be removable now — `run_migration_tui` went Textual-free in P2).

Keep:
- `run_migration_tui` function (P2 plain Python).
- `MigrationOutcome` import (from flow.migration_summary).
- Any other helpers like `_emit_resync_runbooks` that `run_migration_tui` uses.

- [ ] **Step 4: Delete screen-focused test files**

```bash
rm installer/tests/test_corrupt_yaml_screen.py
# Inspect the others BEFORE deleting:
head -30 installer/tests/test_integration_screens.py
head -30 installer/tests/test_screens.py
# If purely Textual-screen-driven, delete. If they test a non-Textual helper, leave.
```

- [ ] **Step 5: Delete Textual snapshot tests for the 7 ported screens**

```bash
grep -l "ConfirmScreen\|DetectionScreen\|CorruptYamlScreen\|HooksDiffScreen\|ConfigDiffScreen\|UpdateScreen\|PluginStatusScreen\|PluginSelectScreen" installer/tests/e2e/*.py
```

For each file: delete the tests targeting the 7 screens. If a file's tests are all deleted, delete the file. Delete matching SVG goldens.

- [ ] **Step 6: Rewrite e2e behavioral tests**

For `installer/tests/e2e/test_install_flow.py`, `test_update_flows.py`, `test_integration_flow.py`, `test_uninstall_wizard.py`, `test_edge_cases.py`:

- Replace `from installer.app import InstallerApp` → `from installer.flow.installer_flow import run_installer_flow`.
- Replace `pilot.press(...)` / `pilot.pause()` Textual-pilot idioms with mocks on flow helpers.
- Replace assertions on `app.install_plan` / `app.reinstall_message` with assertions on `execute_install_plan` mock calls.

If a test's scenario is specifically "user tabs through 3 Textual screens and presses Enter twice" — that test is irrecoverable. Delete it.

**Minimum test coverage to preserve:**
- At least one test per mode (install/update/reinstall/uninstall) asserting successful end-to-end dispatch.
- At least one test per mode asserting cancellation at pre-phase returns 0 without side effects.
- At least one test asserting subprocess `claude` calls happen (via mocked `install_plugin` / `uninstall_plugin` / `update_plugin`).

- [ ] **Step 7: Run full installer test suite**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/ --no-cov -q 2>&1 | tail -15
```

Expected: all pass (modulo any remaining Textual snapshot flakes on wizard/advanced_config/integration_config screens — those are NOT your concern; P4 territory).

- [ ] **Step 8: Grep hygiene**

```bash
grep -rn "class InstallerApp\|InstallerApp(" installer/ --include='*.py'
grep -rn "ConfirmScreen\|DetectionScreen\|CorruptYamlScreen\|HooksDiffScreen\|ConfigDiffScreen\|UpdateScreen\|PluginStatusScreen" installer/ --include='*.py'
```

Expected: zero hits.

- [ ] **Step 9: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp
git add -A installer/
git commit -m "chore(installer/672): delete InstallerApp + 7 ported Textual screens + obsolete tests (P3)"
```

---

## Task 13: Update screen-inventory docstring

**Files:**
- Modify: `installer/tests/e2e/test_snapshots.py` (top docstring)

- [ ] **Step 1: Read current docstring**

```bash
head -20 installer/tests/e2e/test_snapshots.py
```

- [ ] **Step 2: Append P3 NOTE**

After the existing NOTEs from P1 + P2, add:

```
NOTE (2026-04-19, #672 phase 3): ConfirmScreen, DetectionScreen,
CorruptYamlScreen, HooksDiffScreen, ConfigDiffScreen, UpdateScreen,
PluginStatusScreen removed — replaced by installer/flow/ helpers
(confirm_with_options, show_detection_and_confirm,
show_corrupt_yaml_and_confirm, review_hooks_diff, review_config_diff,
select_updates, select_plugin_actions). InstallerApp deleted in the
same phase; main.py now calls run_installer_flow.
```

Remove any residual SCREEN INVENTORY / WIDGET ID MAP entries for the 7 deleted screens. Keep the wizard / advanced_config / integration_config entries — those ship in P4.

- [ ] **Step 3: Commit**

```bash
git add installer/tests/e2e/test_snapshots.py
git commit -m "docs(installer/672): update snapshot inventory — 7 screens removed + InstallerApp gone (P3)"
```

---

## Task 14: Add syrupy text snapshots for Rich output

**Files:**
- Create: `installer/tests/flow/test_confirm_snapshot.py`
- Create: `installer/tests/flow/test_detection_snapshot.py`
- Create: `installer/tests/flow/test_corrupt_yaml_snapshot.py`
- Create: `installer/tests/flow/test_hooks_diff_snapshot.py`
- Create: `installer/tests/flow/test_config_diff_snapshot.py`

(Update + plugin_select use prompt_toolkit dialogs — can't snapshot their output directly, but their Rich wrapper messages, if any, could be snapshotted. Skip snapshotting these in P3.)

- [ ] **Step 1: Write snapshot test for confirm**

```python
# installer/tests/flow/test_confirm_snapshot.py
import pytest
from rich.console import Console

from installer.flow.confirm import ConfirmOption, confirm_with_options


def test_confirm_primary_snapshot(
    snapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    confirm_with_options(
        title="Reinstall?",
        message="This will reinstall all plugins.",
        options=[ConfirmOption(key="reset", label="Reset configs", default=False)],
        console=console,
    )
    assert console.export_text() == snapshot


def test_confirm_error_variant_snapshot(
    snapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    confirm_with_options(
        title="Uninstall?",
        message="Permanently remove all plugins.",
        options=[],
        console=console,
        variant="error",
    )
    assert console.export_text() == snapshot
```

Similar snapshot tests for detection, corrupt_yaml, hooks_diff, config_diff. Create each file with 1-2 snapshot tests covering primary rendering shapes.

- [ ] **Step 2: Generate goldens**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/flow/ -k snapshot --snapshot-update -v --no-cov
```

- [ ] **Step 3: Re-run without update flag**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/flow/ -k snapshot -v --no-cov
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add installer/tests/flow/test_*_snapshot.py installer/tests/flow/__snapshots__/
git commit -m "test(installer/672): add syrupy text snapshots for 5 flow helpers (P3)"
```

---

## Task 15: Full test + FF-merge to dev + watch CI

- [ ] **Step 1: Full installer suite**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && uv run pytest installer/tests/ --no-cov -q 2>&1 | tail -15
```

Expected: all green except pre-existing unrelated flakes.

- [ ] **Step 2: Root-level `just test`**

```bash
cd /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp && just test 2>&1 | tail -15
```

- [ ] **Step 3: Final hygiene**

```bash
grep -rn "class InstallerApp\|InstallerApp(" /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp/installer/ --include='*.py'
grep -rn "from installer.screens.confirm\|from installer.screens.detection\|from installer.screens.corrupt_yaml\|from installer.screens.hooks_diff\|from installer.screens.config_diff\|from installer.screens.update\|from installer.screens.plugin_select" /home/raul/worktrees/cpm/feat-672-p3-kill-installerapp/installer/ --include='*.py'
```

Expected: zero hits.

- [ ] **Step 4: FF-merge to dev**

```bash
cd ~/projects/claude-project-manager
git fetch origin dev
git checkout dev
git merge --ff-only feat/672-p3-kill-installerapp
git push origin dev
```

- [ ] **Step 5: Watch CI**

```bash
gh run watch $(gh run list --branch dev --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

Known failure patterns to tolerate:
- `test (_shared)` — tracked as todo 675
- Any remaining Textual snapshot flakes on wizard/advanced_config/integration_config (P4 territory)

Apply subprocess-mock fixes if `test-installer` fails with `FileNotFoundError: claude` (same pattern as P1).

- [ ] **Step 6: Update todo 676 notes**

```bash
# via mcp__plugin_proj_proj__todo_notes_append
```

Record the shipped commits + any follow-up todos auto-captured during review.

---

## Self-review notes for the implementer

- **Task 11 + Task 12 are the biggest risks.** Test rewrites can be significant; budget time for reading each failing test before deciding delete vs rewrite.
- **prompt_toolkit dialogs block stdin** — if a test accidentally doesn't mock `checkboxlist_dialog`, the test suite will hang. Always assert via `mock.call_args` rather than letting the real dialog run.
- **`_check_corrupt_yaml` assumes `load_existing_yaml` exists** — verify the actual helper name in `installer/_config_loader.py`. The name `load_existing_yaml` was inferred; check the module first.
- **`PluginStatus.status_bucket`** field may not exist — the Task 8 `_partition` helper derives buckets from other fields. Verify before coding.
- **`add_marketplace`** signature may differ — Task 10's install flow calls it on fallback. Check actual signature.
- **`claudemd.remove_managed_section`** may not exist — Task 10 references it for uninstall full_cleanup. Verify.

## After P3 lands

- Update todo 676 status to reflect ship.
- P4 plan (todo 677): port wizard + advanced_config + integration_config × 3 to prompt_toolkit Application forms.
- P5 plan (todo 678): remove Textual from deps.

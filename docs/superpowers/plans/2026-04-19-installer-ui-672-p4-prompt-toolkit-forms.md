# Installer UI P4 — 5 Textual Form Screens → prompt_toolkit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the 5 remaining Textual form screens (wizard, advanced_config, 3 integration_configs) to prompt_toolkit via a shared `installer/flow/form.py::run_form` helper. Pre-fill every field from existing `~/.claude/*.yaml` values. Fold todo 679 (corrupt-yaml pre-phase wiring) in as task 0.

**Architecture:** One shared form builder + 5 per-screen ports + yaml preload gate. Each screen function loads existing yaml, builds `list[FieldSpec]` with defaults populated, calls `run_form`, transforms result, writes yaml. Integration screens add synchronous httpx validation inside `console.status("Validating...")` spinner.

**Tech Stack:** Python 3.13, prompt_toolkit 3 (already dep from P3), Rich 13+, httpx (already dep), pytest, syrupy.

**Spec:** `docs/superpowers/specs/2026-04-19-installer-ui-672-p4-prompt-toolkit-forms-design.md`

---

## File Structure

**Created:**
- `installer/flow/form.py` — `FieldSpec` dataclass + `run_form(fields, console, *, title, error_message) -> dict | None`.
- `installer/flow/wizard.py` — `run_wizard(state, args, console) -> dict | None`.
- `installer/flow/advanced_config.py` — `run_advanced_config(console) -> dict | None`.
- `installer/flow/integration_config.py` — `configure_todoist / configure_trello / configure_jira(console) -> dict | None` + shared `_run_integration_form`.
- Tests: `installer/tests/flow/test_form.py`, `test_wizard.py`, `test_advanced_config.py`, `test_integration_config.py`, `test_pre_install_phase.py` (updated for corrupt-yaml gate).

**Modified:**
- `installer/flow/pre_install_phase.py` — add `_check_corrupt_yaml` at top of every mode.
- `installer/flow/installer_flow.py::_run_install` — invoke `run_wizard` + `configure_<integration>` after plugin_select, before hooks_diff.

**Deleted at end:**
- `installer/screens/wizard.py`, `advanced_config.py`, `integration_config.py`
- `installer/screens/__init__.py` (empty → delete) + `installer/screens/` directory
- Tests: `test_wizard.py`, `test_integration_screens.py`, `test_config_diff.py` (config_diff screen goes away with integration_config), e2e snapshot tests + SVG goldens for these 4 screens.
- `installer/tests/e2e/test_snapshots*.py` files that only tested ported screens.

**Latent bugs addressed (parent spec):** B1-B8, B11, B13. See spec §Feature-parity guarantee.

---

## Task 0: Corrupt-yaml pre-phase gate (todo 679)

**Files:**
- Modify: `installer/flow/pre_install_phase.py`
- Modify: `installer/tests/flow/test_pre_install_phase.py`

**Context:** todo 679 follow-up — add yaml-preload step at top of pre_install_phase. Loads `~/.claude/{proj,worktree,todoist,trello,jira}.yaml` per-bucket, collects `ConfigLoadError.original` into errors dict, calls `show_corrupt_yaml_and_confirm` if any errors. User cancel → abort.

- [ ] **Step 1: Write failing test**

Append to `installer/tests/flow/test_pre_install_phase.py`:

```python
class TestPreInstallPhaseCorruptYaml:
    def test_corrupt_yaml_cancel_aborts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from installer._config_loader import ConfigLoadError

        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "proj.yaml").write_text(":::broken\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        with patch(
            "installer.flow.pre_install_phase.show_corrupt_yaml_and_confirm",
            return_value=False,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("install", _Args(), console)
        assert result.proceed is False

    def test_corrupt_yaml_continue_proceeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "proj.yaml").write_text(":::broken\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        with patch(
            "installer.flow.pre_install_phase.show_corrupt_yaml_and_confirm",
            return_value=True,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("install", _Args(), console)
        # install mode with no corrupt-yaml cancel → proceeds to return PreInstallResult(proceed=True)
        assert result.proceed is True

    def test_valid_yaml_no_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "proj.yaml").write_text("tracking_dir: /tmp\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        prompt_called = {"n": 0}

        def _not_called(*a, **k):
            prompt_called["n"] += 1
            return True

        with patch(
            "installer.flow.pre_install_phase.show_corrupt_yaml_and_confirm",
            side_effect=_not_called,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("install", _Args(), console)
        assert prompt_called["n"] == 0
        assert result.proceed is True
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd /home/raul/worktrees/cpm/feat-672-p4-prompt-toolkit-forms && uv run pytest installer/tests/flow/test_pre_install_phase.py::TestPreInstallPhaseCorruptYaml -v --no-cov
```

- [ ] **Step 3: Implement `_check_corrupt_yaml`**

Add to `installer/flow/pre_install_phase.py` at module level:

```python
from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm


_KNOWN_BUCKETS: tuple[str, ...] = ("proj", "worktree", "todoist", "trello", "jira")


def _check_corrupt_yaml(console: Console) -> bool:
    """Preload ~/.claude/{bucket}.yaml for known buckets. Prompt user on errors.

    Returns True if all yaml OK or user opts to continue with defaults.
    False if user cancels.
    """
    claude_home = Path.home() / ".claude"
    errors: dict[str, Exception] = {}
    for bucket in _KNOWN_BUCKETS:
        path = claude_home / f"{bucket}.yaml"
        if not path.exists():
            continue
        try:
            load_existing_yaml(path)
        except ConfigLoadError as exc:
            errors[bucket] = exc.original if hasattr(exc, "original") else exc
    if errors:
        return show_corrupt_yaml_and_confirm(errors, console)
    return True
```

Then at the top of `pre_install_phase(mode, args, console)`:

```python
def pre_install_phase(mode, args, console) -> PreInstallResult:
    if not _check_corrupt_yaml(console):
        return PreInstallResult(state=None, proceed=False)
    # ... existing dispatch ...
```

- [ ] **Step 4: Run — expect PASS (3/3 new + existing pass)**

```bash
cd /home/raul/worktrees/cpm/feat-672-p4-prompt-toolkit-forms && uv run pytest installer/tests/flow/test_pre_install_phase.py -v --no-cov
```

- [ ] **Step 5: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-672-p4-prompt-toolkit-forms
git add installer/flow/pre_install_phase.py installer/tests/flow/test_pre_install_phase.py
git commit -m "feat(installer/672): pre_install_phase corrupt-yaml gate (todo 679, P4 task 0)"
```

---

## Task 1: Create `installer/flow/form.py` + FieldSpec + run_form

**Files:**
- Create: `installer/flow/form.py`
- Create: `installer/tests/flow/test_form.py`

**Context:** This is the shared form builder. Every subsequent task uses it. prompt_toolkit `Application` with `TextArea`/`CheckboxList`/`RadioList` widgets per FieldSpec.kind. Validator runs on submit attempt; blocks + shows error inline if fails.

- [ ] **Step 1: Write failing tests**

Create `installer/tests/flow/test_form.py`:

```python
# installer/tests/flow/test_form.py
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from installer.flow.form import FieldSpec, run_form


class TestFieldSpec:
    def test_dataclass_fields(self) -> None:
        spec = FieldSpec(key="x", label="X", kind="text", default="foo")
        assert spec.key == "x"
        assert spec.label == "X"
        assert spec.kind == "text"
        assert spec.default == "foo"
        assert spec.choices is None
        assert spec.validator is None
        assert spec.help_text is None
        assert spec.group is None


class TestRunForm:
    def test_submit_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fields = [
            FieldSpec(key="name", label="Name", kind="text", default="alice"),
            FieldSpec(key="age", label="Age", kind="int", default=30),
            FieldSpec(key="sub", label="Subscribed", kind="bool", default=True),
        ]
        # Mock the prompt_toolkit Application to simulate submit with current defaults
        mock_app = MagicMock()
        mock_app.run.return_value = {"name": "alice", "age": 30, "sub": True}
        monkeypatch.setattr("installer.flow.form._build_application", lambda *a, **k: mock_app)

        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form(fields, console, title="Test")
        assert result == {"name": "alice", "age": 30, "sub": True}

    def test_cancel_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fields = [FieldSpec(key="name", label="Name", kind="text", default="alice")]
        mock_app = MagicMock()
        mock_app.run.return_value = None
        monkeypatch.setattr("installer.flow.form._build_application", lambda *a, **k: mock_app)

        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form(fields, console, title="Test")
        assert result is None

    def test_empty_fields_returns_empty_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_app = MagicMock()
        mock_app.run.return_value = {}
        monkeypatch.setattr("installer.flow.form._build_application", lambda *a, **k: mock_app)

        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form([], console, title="Empty")
        assert result == {}

    def test_validator_blocks_invalid_submit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FieldSpec.validator returning str should block submit + reshow form."""
        calls: list[dict | None] = []

        def fake_app_run(values):
            # First attempt: submit "" → validator rejects → re-prompt
            # Second attempt: submit "ok" → validator passes → submit
            if not calls:
                calls.append({"x": ""})
                return {"x": ""}
            calls.append({"x": "ok"})
            return {"x": "ok"}

        mock_app = MagicMock()
        mock_app.run.side_effect = [{"x": ""}, {"x": "ok"}]
        monkeypatch.setattr("installer.flow.form._build_application", lambda *a, **k: mock_app)

        def validator(v: str) -> str | None:
            return "required" if not v else None

        fields = [
            FieldSpec(
                key="x", label="X", kind="text", default="", validator=validator
            )
        ]
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form(fields, console, title="Test")
        assert result == {"x": "ok"}

    def test_error_message_preserved_on_rerun(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Caller passes error_message='previous attempt failed' → form shows it pre-submission."""
        mock_app = MagicMock()
        mock_app.run.return_value = {"x": "ok"}
        monkeypatch.setattr(
            "installer.flow.form._build_application",
            lambda fields, error_message=None, **k: _capture_err(error_message, mock_app),
        )
        captured: dict[str, str | None] = {}

        def _capture_err(err, app):
            captured["err"] = err
            return app

        fields = [FieldSpec(key="x", label="X", kind="text", default="old")]
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        run_form(fields, console, title="Test", error_message="auth failed")
        assert captured["err"] == "auth failed"
```

- [ ] **Step 2: Run — expect FAIL (ModuleNotFoundError)**

- [ ] **Step 3: Implement `installer/flow/form.py`**

```python
# installer/flow/form.py
"""Shared prompt_toolkit form builder.

FieldSpec describes one input field. run_form builds a prompt_toolkit
Application that renders all fields with Tab-focus cycling, per-field
validators, and Enter-to-submit / Escape-to-cancel.

Returns {key: value} dict on submit, None on cancel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from rich.console import Console


FieldKind = Literal["text", "password", "bool", "int", "select"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: FieldKind
    default: Any = None
    choices: list[str] | None = None
    validator: Callable[[Any], str | None] | None = None
    help_text: str | None = None
    group: str | None = None


def _build_application(
    fields: list[FieldSpec],
    *,
    title: str | None = None,
    error_message: str | None = None,
) -> Any:
    """Construct prompt_toolkit Application for given fields.

    Separate factory for test mockability. Returns an object with a `.run()`
    method that blocks until submit (returns dict) or cancel (returns None).
    """
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.widgets import Label, TextArea, Checkbox, RadioList, Frame

    # Build widget per field + preserve order for focus cycling.
    widgets: list[Any] = []
    field_widgets: dict[str, Any] = {}

    for spec in fields:
        if spec.kind in ("text", "password"):
            widget = TextArea(
                text=str(spec.default or ""),
                multiline=False,
                password=(spec.kind == "password"),
            )
        elif spec.kind == "int":
            widget = TextArea(
                text=str(spec.default or 0),
                multiline=False,
            )
        elif spec.kind == "bool":
            widget = Checkbox(text=spec.label, checked=bool(spec.default))
        elif spec.kind == "select":
            widget = RadioList(
                values=[(c, c) for c in (spec.choices or [])]
            )
            # Pre-select default
            if spec.default in (spec.choices or []):
                widget.current_value = spec.default
        else:
            raise ValueError(f"Unknown FieldKind: {spec.kind}")
        widgets.append(Frame(widget, title=spec.label))
        field_widgets[spec.key] = widget

    # Collect values helper — reads current widget state.
    def _collect() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for spec in fields:
            w = field_widgets[spec.key]
            if spec.kind in ("text", "password"):
                out[spec.key] = w.text
            elif spec.kind == "int":
                try:
                    out[spec.key] = int(w.text)
                except ValueError:
                    out[spec.key] = 0
            elif spec.kind == "bool":
                out[spec.key] = bool(w.checked)
            elif spec.kind == "select":
                out[spec.key] = w.current_value
        return out

    result: dict[str, Any] | None = None

    kb = KeyBindings()

    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    @kb.add("c-s")  # Ctrl-S to submit
    def _(event):
        values = _collect()
        # Validate each field
        for spec in fields:
            if spec.validator is None:
                continue
            err = spec.validator(values.get(spec.key))
            if err:
                # Surface error — for now exit with result dict that includes
                # error metadata; caller detects + re-runs.
                event.app.exit(result={"_form_error": err, "_values": values})
                return
        event.app.exit(result=values)

    # Simple header/error layout
    header_lines: list[str] = []
    if title:
        header_lines.append(f"[bold]{title}[/bold]")
    if error_message:
        header_lines.append(f"[red]{error_message}[/red]")
    header_text = "\n".join(header_lines) if header_lines else ""

    from prompt_toolkit.layout.containers import ScrollablePane

    body = HSplit(
        [
            Label(text=header_text) if header_text else Window(height=1),
            *widgets,
            Label(text="Ctrl-S: submit  |  Escape: cancel"),
        ]
    )
    layout = Layout(container=body)
    app = Application(layout=layout, key_bindings=kb, full_screen=True)
    return app


def run_form(
    fields: list[FieldSpec],
    console: Console,
    *,
    title: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    """Render form + return {key: value} dict on submit, None on cancel.

    Repeats on validator failure — re-renders with the error banner + preserved
    current values until the user either passes validation or cancels.
    """
    if not fields:
        return {}

    current_error = error_message
    current_defaults = {spec.key: spec.default for spec in fields}

    while True:
        # Build fresh FieldSpec list with current defaults (after prior invalid attempt).
        fields_with_defaults = [
            FieldSpec(
                key=spec.key,
                label=spec.label,
                kind=spec.kind,
                default=current_defaults.get(spec.key, spec.default),
                choices=spec.choices,
                validator=spec.validator,
                help_text=spec.help_text,
                group=spec.group,
            )
            for spec in fields
        ]
        app = _build_application(
            fields_with_defaults, title=title, error_message=current_error
        )
        raw = app.run()
        if raw is None:
            return None  # cancel
        if isinstance(raw, dict) and "_form_error" in raw:
            current_error = raw["_form_error"]
            current_defaults = raw["_values"]
            continue
        return raw  # type: ignore[return-value]
```

**Note for implementer:** prompt_toolkit's full Application API is complex. If the above is too complex or raises unexpected behavior, fall back to the simpler `prompt_toolkit.shortcuts.input_dialog` + `button_dialog` per field, looped. Document the fallback in a comment if you take it. The TEST structure (6 tests mocking `_build_application`) is unchanged — only the implementation detail differs.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/form.py installer/tests/flow/test_form.py
git commit -m "feat(installer/672): shared flow.form.run_form + FieldSpec for P4 (P4 T1)"
```

---

## Task 2: Port WizardScreen → `installer/flow/wizard.py`

**Files:**
- Create: `installer/flow/wizard.py`
- Create: `installer/tests/flow/test_wizard.py`

**Context:** Loads existing `~/.claude/*.yaml` buckets, iterates `PROJ_YAML_PROMPTS` to build FieldSpec list with defaults from existing values. Honors `spec.condition` (hides conditional fields based on parent value), `spec.group`, `spec.yaml_file`, `spec.tier="basic"` filter.

**CRITICAL:** every FieldSpec MUST have `default=` populated from existing yaml if present.

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/flow/test_wizard.py
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from rich.console import Console

from installer.flow.wizard import run_wizard


class _Args:
    branch = None


class TestRunWizard:
    def test_defaults_from_existing_proj_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wizard MUST pre-fill FieldSpec defaults from existing ~/.claude/proj.yaml."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump({"tracking_dir": "/my/existing/tracking"})
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured_fields: list = []

        def _capture_and_submit(fields, console, **kwargs):
            captured_fields.extend(fields)
            return {spec.key: spec.default for spec in fields}

        with patch("installer.flow.wizard.run_form", side_effect=_capture_and_submit):
            state = type("S", (), {"installed_plugins": ["proj"]})()
            console = Console(width=80, force_terminal=False, no_color=True)
            run_wizard(state, _Args(), console)

        # Find the tracking_dir FieldSpec — verify its default was pre-filled from yaml.
        tracking = [f for f in captured_fields if f.key == "tracking_dir"]
        assert len(tracking) == 1
        assert tracking[0].default == "/my/existing/tracking"

    def test_cancel_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with patch("installer.flow.wizard.run_form", return_value=None):
            state = type("S", (), {"installed_plugins": ["proj"]})()
            console = Console(width=80, force_terminal=False, no_color=True)
            result = run_wizard(state, _Args(), console)
        assert result is None

    def test_submit_returns_config_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with patch(
            "installer.flow.wizard.run_form",
            return_value={"tracking_dir": "/new"},
        ):
            state = type("S", (), {"installed_plugins": ["proj"]})()
            console = Console(width=80, force_terminal=False, no_color=True)
            result = run_wizard(state, _Args(), console)
        assert result is not None
        assert "tracking_dir" in result

    def test_needs_proj_only_includes_proj_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If user only installs worktree (not proj), wizard should not ask proj fields."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured_fields: list = []

        def _capture(fields, console, **k):
            captured_fields.extend(fields)
            return {spec.key: spec.default for spec in fields}

        with patch("installer.flow.wizard.run_form", side_effect=_capture):
            state = type("S", (), {"installed_plugins": ["worktree"]})()
            console = Console(width=80, force_terminal=False, no_color=True)
            run_wizard(state, _Args(), console)

        # proj-only fields should NOT be in captured_fields when proj plugin isn't selected
        keys = {f.key for f in captured_fields}
        assert "tracking_dir" not in keys  # proj-only field
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# installer/flow/wizard.py
"""prompt_toolkit replacement for Textual WizardScreen.

Loads existing ~/.claude/<bucket>.yaml values, builds FieldSpec list from
PROJ_YAML_PROMPTS (honoring spec.condition, .group, .yaml_file, .tier),
calls run_form, transforms result into bucket-partitioned config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.flow.form import FieldSpec, run_form
from installer.wizard_specs import PROJ_YAML_PROMPTS, get_distinct_yaml_files

_PROJ_PLUGINS = {"proj", "router", "todoist", "trello", "jira"}


def _spec_kind(spec) -> str:
    """Map wizard_specs.PromptSpec.type → FieldSpec.kind."""
    mapping = {"bool": "bool", "str": "text", "int": "int", "choice": "select"}
    return mapping.get(spec.type, "text")


def _load_bucket(bucket: str, claude_home: Path) -> dict[str, Any]:
    """Load a single bucket, return {} on missing or corrupt (caller handles errors)."""
    path = claude_home / f"{bucket}.yaml"
    if not path.exists():
        return {}
    try:
        return load_existing_yaml(path)
    except ConfigLoadError:
        return {}


def run_wizard(
    state, args, console: Console
) -> dict[str, Any] | None:
    """Render config wizard form, return result dict or None on cancel."""
    claude_home = Path.home() / ".claude"

    # Load existing buckets for default lookup
    buckets: dict[str, dict[str, Any]] = {}
    for bucket in get_distinct_yaml_files(PROJ_YAML_PROMPTS):
        buckets[bucket] = _load_bucket(bucket, claude_home)

    selected = set(getattr(state, "installed_plugins", []))
    needs_proj = bool(_PROJ_PLUGINS & selected)
    needs_worktree = "worktree" in selected

    # Build FieldSpec list
    fields: list[FieldSpec] = []
    proj_bucket = buckets.get("proj", {})
    for spec in PROJ_YAML_PROMPTS:
        if spec.tier != "basic":
            continue
        # Gate by plugin relevance — proj fields only if proj plugins selected
        if spec.yaml_file == "proj" and not needs_proj:
            continue
        if spec.yaml_file == "worktree" and not needs_worktree:
            continue
        # Honor spec.condition (depends on proj_bucket values)
        if spec.condition is not None and not spec.condition(proj_bucket):
            continue

        bucket = buckets.get(spec.yaml_file, {})
        default = spec.default_factory(bucket)
        fields.append(
            FieldSpec(
                key=spec.key,
                label=spec.label,
                kind=_spec_kind(spec),
                default=default,
                choices=list(spec.choices) if spec.choices else None,
                group=spec.group,
                # validator: rely on spec.type (int coercion handled in form.py)
            )
        )

    result = run_form(fields, console, title="Configuration Wizard")
    return result
```

- [ ] **Step 4: Run — expect PASS (4/4)**

- [ ] **Step 5: Commit**

```bash
git add installer/flow/wizard.py installer/tests/flow/test_wizard.py
git commit -m "feat(installer/672): port WizardScreen → flow.run_wizard (P4 T2)"
```

---

## Task 3: Port AdvancedConfigScreen → `installer/flow/advanced_config.py`

Same pattern as Task 2, but with `tier="advanced"` filter.

- [ ] **Step 1: Test file `test_advanced_config.py`** — mirror test_wizard.py's 4 tests targeting advanced-tier fields. Verify existing yaml pre-fills.

- [ ] **Step 2: Implement `run_advanced_config(console) -> dict | None`** — iterate PROJ_YAML_PROMPTS with `spec.tier == "advanced"` instead of "basic". No `state`/`args` params needed since advanced doesn't depend on selected plugins.

- [ ] **Step 3: Run tests → PASS**

- [ ] **Step 4: Commit**

```bash
git add installer/flow/advanced_config.py installer/tests/flow/test_advanced_config.py
git commit -m "feat(installer/672): port AdvancedConfigScreen → flow.run_advanced_config (P4 T3)"
```

---

## Task 4: Port Todoist integration screen → `installer/flow/integration_config.py`

**Files:**
- Create: `installer/flow/integration_config.py`
- Create: `installer/tests/flow/test_integration_config.py`

**Context:** First of 3 integration ports. Establishes shared `_run_integration_form(service_name, fields, validator, console) -> dict | None` pattern that Tasks 5+6 reuse.

Integration form fields (Todoist example):
- `api_token` (password, loaded from `~/.claude/todoist.yaml::api_token`)
- `sync_enabled` (bool, from `~/.claude/proj.yaml::sync.todoist.enabled`)
- `auto_sync` (bool, from `sync.todoist.auto_sync`)
- `root_only` (bool, from `sync.todoist.root_only`)

After submit: `_validate_credentials()` runs `httpx.Client().get(https://api.todoist.com/...)` inside `console.status("Validating...")`. On failure, re-prompt with pre-filled values + error banner.

- [ ] **Step 1: Write failing tests** — 5 tests: load_defaults_from_todoist_yaml, cancel_returns_none, submit_happy, validation_failure_reprompts, sync_disabled_skips_validation.

(Template test bodies follow P3 T7/T8 pattern — mock `run_form` + `httpx.Client`.)

- [ ] **Step 2: Implement `configure_todoist(console) -> dict | None`** with async→sync validation.

```python
# installer/flow/integration_config.py (partial)
import httpx
from rich.console import Console
from installer.flow.form import FieldSpec, run_form


def _run_integration_form(
    service_name: str,
    fields: list[FieldSpec],
    validator,  # Callable[[dict], str | None]
    console: Console,
) -> dict | None:
    """Run integration form with post-submit validation + retry on failure."""
    error: str | None = None
    while True:
        result = run_form(fields, console, title=f"{service_name} Configuration", error_message=error)
        if result is None:
            return None
        # Skip validation if sync not enabled (B2: empty creds OK when disabled)
        if not result.get("sync_enabled", True):
            return result
        with console.status(f"Validating {service_name} credentials..."):
            error = validator(result)
        if error is None:
            return result
        # Rebuild fields with new defaults from last submission
        fields = [
            FieldSpec(
                key=f.key,
                label=f.label,
                kind=f.kind,
                default=result.get(f.key, f.default),
                choices=f.choices,
                validator=f.validator,
                help_text=f.help_text,
                group=f.group,
            )
            for f in fields
        ]


def _todoist_validator(values: dict) -> str | None:
    token = (values.get("api_token") or "").strip()
    if not token:
        return "api_token required"
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                "https://api.todoist.com/rest/v2/projects",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code in (401, 403):
                return "invalid api_token"
            r.raise_for_status()
    except httpx.HTTPError as exc:
        return f"network error: {exc}"
    return None


def configure_todoist(console: Console) -> dict | None:
    # Load existing config
    from pathlib import Path
    from installer._config_loader import load_existing_yaml, ConfigLoadError
    claude_home = Path.home() / ".claude"
    todoist_cfg: dict = {}
    proj_cfg: dict = {}
    for bucket_name, target in (("todoist", todoist_cfg), ("proj", proj_cfg)):
        path = claude_home / f"{bucket_name}.yaml"
        if path.exists():
            try:
                target.update(load_existing_yaml(path) or {})
            except ConfigLoadError:
                pass
    sync_section = (proj_cfg.get("sync", {}) or {}).get("todoist", {}) or {}

    fields = [
        FieldSpec(
            key="api_token",
            label="API Token",
            kind="password",
            default=todoist_cfg.get("api_token", "") or sync_section.get("api_token", ""),
        ),
        FieldSpec(
            key="sync_enabled",
            label="Enable Todoist sync",
            kind="bool",
            default=sync_section.get("enabled", False),
        ),
        FieldSpec(
            key="auto_sync",
            label="Auto-sync on todo changes",
            kind="bool",
            default=sync_section.get("auto_sync", True),
        ),
        FieldSpec(
            key="root_only",
            label="Root-only mode (skip child tasks)",
            kind="bool",
            default=sync_section.get("root_only", False),
        ),
    ]
    return _run_integration_form("Todoist", fields, _todoist_validator, console)
```

- [ ] **Step 3: Run — PASS (5/5)**

- [ ] **Step 4: Commit**

```bash
git add installer/flow/integration_config.py installer/tests/flow/test_integration_config.py
git commit -m "feat(installer/672): port TodoistConfigScreen → flow.configure_todoist (P4 T4)"
```

---

## Task 5: Port Trello integration into same file

Fields: `api_key`, `token`, `sync_enabled`, `auto_sync`, `default_board_id` (optional), `on_delete` (select: "archive"/"delete"). Validator hits Trello API to verify key+token.

Extend `installer/flow/integration_config.py` + add 4 tests to `test_integration_config.py`. Commit message: `feat(installer/672): port TrelloConfigScreen → flow.configure_trello (P4 T5)`.

---

## Task 6: Port Jira integration into same file

Fields: `personal_access_token`, `base_url`, `email`, `sync_enabled`, `auto_sync`, `epic_link_field` (optional). Validator hits Jira API.

Latent bug **B1** fix: `base_url` FieldSpec.validator:

```python
def _jira_base_url_validator(v: str) -> str | None:
    v = (v or "").strip()
    if not v.startswith(("http://", "https://")):
        return "must start with http:// or https://"
    return None
```

Latent bug **B3** fix: normalize trailing `/` in post-process.

Extend integration_config.py + 4 tests. Commit: `feat(installer/672): port JiraConfigScreen → flow.configure_jira (P4 T6)`.

---

## Task 7: Wire into `run_installer_flow._run_install`

**File:** `installer/flow/installer_flow.py`

Insert after plugin_select, before hooks_diff:

```python
# After: actions = select_plugin_actions(...)

# Configure project (wizard)
wizard_result = run_wizard(state, args, console)
if wizard_result is None:
    console.print("[dim]Cancelled at wizard.[/dim]")
    return 0
# Write each bucket to yaml
_write_wizard_buckets(wizard_result)

# Configure integrations (only prompt for ones in selected plugins)
for service in ("todoist", "trello", "jira"):
    if service not in [name for name, _ in actions]:
        continue
    configure_fn = {"todoist": configure_todoist, "trello": configure_trello, "jira": configure_jira}[service]
    result = configure_fn(console)
    if result is None:
        console.print(f"[dim]Cancelled at {service} config.[/dim]")
        return 0
    _write_integration_bucket(service, result)

# Existing: hooks diff review, then execute
```

Update `test_installer_flow.py` install-mode test to mock `run_wizard` + 3 integration functions. Commit: `feat(installer/672): wire wizard + integration configs into run_installer_flow (P4 T7)`.

---

## Tasks 8-11: Deletion + cleanup

- **T8:** delete `installer/screens/wizard.py` + `installer/tests/test_wizard.py` + matching SVG goldens.
- **T9:** delete `installer/screens/advanced_config.py` + its tests + goldens.
- **T10:** delete `installer/screens/integration_config.py` + `installer/screens/config_diff.py` (ConfigDiffScreen was only used by integration wizard) + `installer/tests/test_integration_screens.py` + `installer/tests/test_config_diff.py` + goldens.
- **T11:** delete `installer/screens/` directory entirely (empty after above). Grep hygiene: `grep -rn "from installer.screens" installer/ --include='*.py'` → zero hits.

Each subtask:
1. rm files
2. remove imports from any callers
3. run full installer tests → green
4. commit

Commit template: `chore(installer/672): delete <screen>.py + tests + goldens (P4 T<N>)`.

---

## Task 12: Update snapshot inventory docstring

`installer/tests/e2e/test_snapshots.py` — append P4 NOTE:

```
NOTE (2026-04-19, #672 phase 4): WizardScreen, AdvancedConfigScreen,
TodoistConfigScreen, TrelloConfigScreen, JiraConfigScreen removed —
replaced by installer/flow/ helpers (run_wizard, run_advanced_config,
configure_todoist/trello/jira). installer/screens/ directory removed.
All install-time UI now in installer/flow/. Textual dep still present
(removal is P5).
```

Remove all remaining SCREEN INVENTORY entries. If the file is now empty of meaningful content, delete it; otherwise keep as empty module w/ module docstring noting the P5 cleanup.

Commit: `docs(installer/672): update snapshot inventory — all 13 screens removed (P4 T12)`.

---

## Task 13: Syrupy snapshots for wrapper output

Add snapshot tests for the Rich-rendered surrounding panels (title, error banner, status spinner contexts). Not the prompt_toolkit form itself — dialogs aren't snapshottable.

Files:
- `installer/tests/flow/test_wizard_snapshot.py`
- `installer/tests/flow/test_advanced_config_snapshot.py`
- `installer/tests/flow/test_integration_config_snapshot.py`

Each has 1-2 snapshots covering the visible-to-user panels. Commit: `test(installer/672): syrupy snapshots for 5 P4 flow helpers (P4 T13)`.

---

## Task 14: Full test + FF-merge + CI watch

- [ ] **Step 1: Full installer suite**

```bash
cd /home/raul/worktrees/cpm/feat-672-p4-prompt-toolkit-forms && uv run pytest installer/tests/ --no-cov -q 2>&1 | tail -15
```

- [ ] **Step 2: Grep hygiene**

```bash
grep -rn "from installer.screens\|class WizardScreen\|class AdvancedConfigScreen\|class Todoist.*Screen\|class Trello.*Screen\|class Jira.*Screen" installer/ --include='*.py'
```

Expected: zero hits.

- [ ] **Step 3: FF-merge + push**

```bash
cd ~/projects/claude-project-manager
git fetch origin dev
git merge --ff-only feat/672-p4-prompt-toolkit-forms
git push origin dev
```

- [ ] **Step 4: Watch CI**

```bash
gh run watch $(gh run list --branch dev --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

Known tracked flakes:
- `test (_shared)` — todo 675
- `test-installer-e2e` — if any remaining Textual snapshots fail, we've probably missed deletion

Apply subprocess-mock fixes if `test-installer` fails with `FileNotFoundError: claude` (P1 pattern).

- [ ] **Step 5: Update todo 677 notes + archive todo 679**

Record shipped commits + fix-ups. Mark 679 complete (corrupt-yaml wired).

---

## Self-review notes

- **Task 1 complexity:** prompt_toolkit `Application` is the bulk. If the provided implementation is too complex, fall back to simpler shortcut dialogs + document the fallback inline. Tests are implementation-agnostic (mock `_build_application`).
- **Task 2-6 depend on `_spec_kind` mapping + `PromptSpec` fields.** Verify the actual `PromptSpec` shape in `installer/wizard_specs.py` before coding — fields may include `validator`, `placeholder`, etc.
- **Task 7 wiring:** if `_write_wizard_buckets` + `_write_integration_bucket` don't exist, implement them using existing `partition_answers_by_bucket` + `write_bucket` from `installer/_config_writer.py`.
- **Task 8-11 deletion risk:** verify no remaining imports via grep before each delete.
- **Branch-switch logic in `_run_install`**: P1 had `add_marketplace(branch=args.branch)` — preserve that call path. Wizard does NOT re-run marketplace registration.

## After P4 lands

P5 (todo 678):
- Remove `textual` + `textual[dev]` + `pytest-textual-snapshot` from deps.
- Delete any remaining SVG goldens.
- Delete `installer/tests/e2e/test_snapshots.py` if empty of Textual tests.
- Full CI green.

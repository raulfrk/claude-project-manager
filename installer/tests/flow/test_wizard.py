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

        tracking = [f for f in captured_fields if f.key == "tracking_dir"]
        assert len(tracking) >= 1
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

    def test_submit_returns_dict(
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
        assert result == {"tracking_dir": "/new"}

    def test_worktree_only_excludes_proj_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If user only installs worktree (not any proj-requiring plugin), wizard should
        not include proj-yaml fields like tracking_dir."""
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

        keys = {f.key for f in captured_fields}
        # proj-only field tracking_dir should NOT appear for worktree-only install
        assert "tracking_dir" not in keys

    def test_sensitive_field_maps_to_password_kind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PromptSpec.sensitive=True → FieldSpec.kind='password'."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured_fields: list = []

        def _capture(fields, console, **k):
            captured_fields.extend(fields)
            return {spec.key: spec.default for spec in fields}

        with patch("installer.flow.wizard.run_form", side_effect=_capture):
            state = type("S", (), {"installed_plugins": ["proj"]})()
            console = Console(width=80, force_terminal=False, no_color=True)
            run_wizard(state, _Args(), console)

        # If any sensitive field exists in PROJ_YAML_PROMPTS (tier="basic") it should be kind="password"
        # This test is tolerant — PROJ_YAML_PROMPTS may not have any sensitive basic fields today.
        from installer.wizard_specs import PROJ_YAML_PROMPTS

        basic_sensitive_keys = {
            s.dotted_key for s in PROJ_YAML_PROMPTS if s.tier == "basic" and s.sensitive
        }
        if basic_sensitive_keys:
            # All should be kind="password"
            for f in captured_fields:
                if f.key in basic_sensitive_keys:
                    assert f.kind == "password"

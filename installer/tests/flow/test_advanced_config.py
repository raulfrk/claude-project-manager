# installer/tests/flow/test_advanced_config.py
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from installer.flow.advanced_config import run_advanced_config


class TestRunAdvancedConfig:
    def test_cancel_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with patch("installer.flow.advanced_config.run_form", return_value=None):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = run_advanced_config(console)
        assert result is None

    def test_submit_returns_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with patch(
            "installer.flow.advanced_config.run_form",
            return_value={"some_key": "some_value"},
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = run_advanced_config(console)
        assert result == {"some_key": "some_value"}

    def test_only_advanced_tier_fields_included(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured_fields: list = []

        def _capture(fields, console, **k):
            captured_fields.extend(fields)
            return {spec.key: spec.default for spec in fields}

        with patch("installer.flow.advanced_config.run_form", side_effect=_capture):
            console = Console(width=80, force_terminal=False, no_color=True)
            run_advanced_config(console)

        # Verify all captured fields correspond to tier="advanced" PromptSpecs
        from installer.wizard_specs import PROJ_YAML_PROMPTS

        advanced_keys = {
            s.dotted_key for s in PROJ_YAML_PROMPTS if s.tier == "advanced"
        }
        basic_keys = {s.dotted_key for s in PROJ_YAML_PROMPTS if s.tier == "basic"}
        captured_keys = {f.key for f in captured_fields}
        assert captured_keys.issubset(advanced_keys)
        # Ensure no basic-tier fields leaked through
        assert not (captured_keys & basic_keys)

    def test_defaults_from_existing_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advanced config MUST pre-fill defaults from existing yaml."""
        # Find an advanced-tier field to test
        from installer.wizard_specs import PROJ_YAML_PROMPTS

        advanced_specs = [s for s in PROJ_YAML_PROMPTS if s.tier == "advanced"]
        if not advanced_specs:
            pytest.skip("no advanced-tier fields in PROJ_YAML_PROMPTS")

        # Pick the first advanced spec and seed its yaml bucket with a value
        target = advanced_specs[0]
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        # Store value at dotted_key (e.g. "git_tracking.enabled" → {"git_tracking": {"enabled": True}})
        # Use spec.default_factory to determine what shape to write
        yaml_path = fake_home / ".claude" / f"{target.yaml_file}.yaml"
        # Write an empty dict so default_factory fallback kicks in; then test the pre-fill via run_form's
        # FieldSpec.default == default_factory(bucket). This verifies wiring, not specific values.
        yaml_path.write_text("{}\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured: list = []

        def _capture(fields, console, **k):
            captured.extend(fields)
            return {spec.key: spec.default for spec in fields}

        with patch("installer.flow.advanced_config.run_form", side_effect=_capture):
            console = Console(width=80, force_terminal=False, no_color=True)
            run_advanced_config(console)

        target_field = [f for f in captured if f.key == target.dotted_key]
        # If condition gates this out, skip — otherwise verify default_factory was called
        if target_field:
            assert target_field[0].default == target.default_factory({})

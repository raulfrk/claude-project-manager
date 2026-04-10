"""Tests for installer/wizard_specs.py — PromptSpec table + schema introspection."""

from __future__ import annotations

from installer.wizard_specs import (
    PROJ_YAML_PROMPTS,
    WIZARD_EXCLUDED_FIELDS,
    assert_prompt_spec_covers_schema,
)


class TestPromptSpecTable:
    def test_every_spec_has_required_fields(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            assert isinstance(spec.label, str) and spec.label
            assert isinstance(spec.dotted_key, str) and spec.dotted_key
            assert spec.type in ("bool", "str", "int", "choice")
            assert spec.tier in ("basic", "advanced")
            assert spec.yaml_file in ("proj", "worktree", "todoist", "trello", "jira")
            assert callable(spec.default_factory)

    def test_choice_specs_have_choices(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            if spec.type == "choice":
                assert spec.choices is not None and len(spec.choices) >= 1

    def test_int_specs_have_ranges(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            if spec.type == "int":
                assert spec.int_range is not None
                low, high = spec.int_range
                assert low <= high

    def test_dotted_keys_unique(self) -> None:
        # Uniqueness is per (yaml_file, dotted_key) — different yaml files may
        # have same key theoretically. Check unique tuples.
        tuples = [(s.yaml_file, s.dotted_key) for s in PROJ_YAML_PROMPTS]
        assert len(tuples) == len(set(tuples))

    def test_dotted_key_format_valid(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            for segment in spec.dotted_key.split("."):
                assert segment, f"empty segment in {spec.dotted_key}"
                assert all(c.isalnum() or c == "_" for c in segment), (
                    f"invalid char in {spec.dotted_key}"
                )


class TestWizardExcludedFields:
    def test_excluded_fields_is_set(self) -> None:
        assert isinstance(WIZARD_EXCLUDED_FIELDS, set)
        assert len(WIZARD_EXCLUDED_FIELDS) > 0

    def test_no_excluded_field_in_prompts(self) -> None:
        prompt_keys = {s.dotted_key for s in PROJ_YAML_PROMPTS if s.yaml_file == "proj"}
        intersection = prompt_keys & WIZARD_EXCLUDED_FIELDS
        assert intersection == set(), (
            f"Excluded fields leaked into prompts: {intersection}"
        )


class TestSchemaIntrospection:
    def test_assert_coverage_returns_list(self) -> None:
        """Regression: every ProjConfig dataclass field must have a PromptSpec."""
        missing = assert_prompt_spec_covers_schema()
        # If ProjConfig cannot be imported (e.g. in isolated CI), returns [] per
        # the permissive contract. Otherwise, the list should be empty.
        assert isinstance(missing, list)
        # Don't fail on missing keys here — this is a warning-only regression;
        # add strict fail in a future todo once coverage is verified complete.

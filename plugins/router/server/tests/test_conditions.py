"""Tests for server.lib.conditions — config-driven condition evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib.conditions import (
    evaluate_condition,
    resolve_condition_status,
    validate_condition_syntax,
)

# ── evaluate_condition ────────────────────────────────────────────────────────


class TestEvaluateCondition:
    def test_none_condition_always_true(self):
        assert evaluate_condition(None) is True

    @pytest.mark.parametrize("cond", ["", "   "])
    def test_empty_or_whitespace_always_true(self, cond: str):
        assert evaluate_condition(cond) is True

    def test_truthy_config_value(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": True}}}))
        assert evaluate_condition("sync.todoist.enabled", config_path=proj_yaml) is True

    def test_falsy_config_value(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": False}}}))
        assert evaluate_condition("sync.todoist.enabled", config_path=proj_yaml) is False

    def test_missing_key_is_false(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"other": "value"}))
        assert evaluate_condition("sync.todoist.enabled", config_path=proj_yaml) is False

    def test_missing_file_is_false(self, tmp_path: Path):
        nonexistent = tmp_path / "does-not-exist.yaml"
        assert evaluate_condition("some.flag", config_path=nonexistent) is False

    def test_negation(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"feature": True}))
        assert evaluate_condition("!feature", config_path=proj_yaml) is False

    def test_negation_of_false(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"feature": False}))
        assert evaluate_condition("!feature", config_path=proj_yaml) is True

    def test_negation_of_missing(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"other": True}))
        assert evaluate_condition("!missing_key", config_path=proj_yaml) is True

    def test_negation_with_spaces(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"flag": True}))
        assert evaluate_condition("  ! flag  ", config_path=proj_yaml) is False

    def test_null_value_is_false(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"key": None}))
        assert evaluate_condition("key", config_path=proj_yaml) is False

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("non-empty", True), (0, False), (42, True)],
        ids=["truthy-string", "falsy-zero", "truthy-int"],
    )
    def test_truthiness_of_values(self, proj_yaml: Path, value: object, expected: bool):
        proj_yaml.write_text(yaml.dump({"key": value}))
        assert evaluate_condition("key", config_path=proj_yaml) is expected

    def test_list_index_in_condition(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"items": [False, True]}))
        assert evaluate_condition("items.0", config_path=proj_yaml) is False
        assert evaluate_condition("items.1", config_path=proj_yaml) is True

    def test_empty_yaml_file(self, proj_yaml: Path):
        proj_yaml.write_text("")
        assert evaluate_condition("any.path", config_path=proj_yaml) is False

    def test_non_dict_yaml_file(self, proj_yaml: Path):
        proj_yaml.write_text("- item1\n- item2\n")
        assert evaluate_condition("any.path", config_path=proj_yaml) is False

    # ── compound conditions (and/or) ──────────────────────────────────────

    def test_and_both_true(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"a": True, "b": True}))
        assert evaluate_condition("a and b", config_path=proj_yaml) is True

    def test_and_one_false(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"a": True, "b": False}))
        assert evaluate_condition("a and b", config_path=proj_yaml) is False

    def test_or_one_true(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"a": False, "b": True}))
        assert evaluate_condition("a or b", config_path=proj_yaml) is True

    def test_or_both_false(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"a": False, "b": False}))
        assert evaluate_condition("a or b", config_path=proj_yaml) is False

    def test_and_with_dot_paths(self, proj_yaml: Path):
        proj_yaml.write_text(
            yaml.dump(
                {
                    "sync": {"todoist": {"enabled": True, "auto_sync": True}},
                    "project": {"todoist_project_id": "abc123"},
                }
            )
        )
        assert (
            evaluate_condition(
                "sync.todoist.enabled and sync.todoist.auto_sync and project.todoist_project_id",
                config_path=proj_yaml,
            )
            is True
        )

    def test_or_with_and_precedence(self, proj_yaml: Path):
        """'a and b or c' means '(a and b) or c'."""
        # a=False, b=True, c=True → (F and T)=F or T = True
        proj_yaml.write_text(yaml.dump({"a": False, "b": True, "c": True}))
        assert evaluate_condition("a and b or c", config_path=proj_yaml) is True
        # a=False, b=True, c=False → (F and T)=F or F = False
        proj_yaml.write_text(yaml.dump({"a": False, "b": True, "c": False}))
        assert evaluate_condition("a and b or c", config_path=proj_yaml) is False

    def test_or_with_and_precedence_reverse(self, proj_yaml: Path):
        """'a or b and c' means 'a or (b and c)', not '(a or b) and c'."""
        # a=False, b=True, c=True → F or (T and T) = True
        proj_yaml.write_text(yaml.dump({"a": False, "b": True, "c": True}))
        assert evaluate_condition("a or b and c", config_path=proj_yaml) is True
        # a=False, b=True, c=False → F or (T and F) = False
        proj_yaml.write_text(yaml.dump({"a": False, "b": True, "c": False}))
        assert evaluate_condition("a or b and c", config_path=proj_yaml) is False
        # a=True, b=False, c=False → T or (F and F) = True
        # If incorrectly parsed as (a or b) and c, this would be False
        proj_yaml.write_text(yaml.dump({"a": True, "b": False, "c": False}))
        assert evaluate_condition("a or b and c", config_path=proj_yaml) is True

    def test_negation_in_compound(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"a": True, "b": False}))
        assert evaluate_condition("a and !b", config_path=proj_yaml) is True


# ── resolve_condition_status ─────────────────────────────────────────────────


class TestResolveConditionStatus:
    @pytest.mark.parametrize("cond", [None, ""])
    def test_no_or_empty_condition_returns_always(self, cond: str | None):
        assert resolve_condition_status(cond) == "always"

    def test_active_condition(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"flag": True}))
        assert resolve_condition_status("flag", config_path=proj_yaml) == "active"

    def test_inactive_condition(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"flag": False}))
        assert resolve_condition_status("flag", config_path=proj_yaml) == "inactive"

    def test_negated_active(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"flag": False}))
        assert resolve_condition_status("!flag", config_path=proj_yaml) == "active"

    def test_negated_inactive(self, proj_yaml: Path):
        proj_yaml.write_text(yaml.dump({"flag": True}))
        assert resolve_condition_status("!flag", config_path=proj_yaml) == "inactive"

    # ── runtime partial evaluation ───────────────────────────────────────

    def test_runtime_only_term(self, proj_yaml: Path):
        """Pure runtime condition (project.* or todo.*) returns 'runtime'."""
        proj_yaml.write_text(yaml.dump({}))
        assert (
            resolve_condition_status("project.todoist_project_id", config_path=proj_yaml)
            == "runtime"
        )

    def test_config_active_and_runtime(self, proj_yaml: Path):
        """Config term passes + runtime term present -> 'runtime'."""
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": True}}}))
        assert (
            resolve_condition_status(
                "sync.todoist.enabled and project.todoist_project_id",
                config_path=proj_yaml,
            )
            == "runtime"
        )

    def test_config_inactive_and_runtime(self, proj_yaml: Path):
        """Config term fails + runtime term present -> 'inactive' (short-circuits)."""
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": False}}}))
        assert (
            resolve_condition_status(
                "sync.todoist.enabled and project.todoist_project_id",
                config_path=proj_yaml,
            )
            == "inactive"
        )

    def test_compound_and_all_config_active(self, proj_yaml: Path):
        """All config terms, no runtime -> 'active'."""
        proj_yaml.write_text(
            yaml.dump(
                {
                    "sync": {"todoist": {"enabled": True, "auto_sync": True}},
                }
            )
        )
        assert (
            resolve_condition_status(
                "sync.todoist.enabled and sync.todoist.auto_sync",
                config_path=proj_yaml,
            )
            == "active"
        )

    def test_or_with_runtime_and_active_branch(self, proj_yaml: Path):
        """Or: one branch is fully active (no runtime) -> 'active'."""
        proj_yaml.write_text(yaml.dump({"flag": True}))
        assert (
            resolve_condition_status(
                "project.todoist_project_id or flag",
                config_path=proj_yaml,
            )
            == "active"
        )

    def test_or_with_runtime_only_branches(self, proj_yaml: Path):
        """Or: all branches have runtime terms, config terms pass -> 'runtime'."""
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": True}}}))
        assert (
            resolve_condition_status(
                "sync.todoist.enabled and project.todoist_project_id or todo.todoist_task_id",
                config_path=proj_yaml,
            )
            == "runtime"
        )

    def test_negated_runtime_term(self, proj_yaml: Path):
        """Negated runtime term is still recognized as runtime."""
        proj_yaml.write_text(yaml.dump({}))
        assert resolve_condition_status("!todo.todoist_task_id", config_path=proj_yaml) == "runtime"

    def test_whitespace_condition_returns_always(self):
        """Whitespace-only condition is treated as no condition."""
        assert resolve_condition_status("   ") == "always"


# ── runtime config (optional config param) ────────────────────────────────────────


class TestRuntimeConfig:
    """Tests for the optional `config` parameter added to evaluate_condition()."""

    def test_explicit_config_true(self):
        assert (
            evaluate_condition(
                "todo.todoist_task_id",
                config={"todo": {"todoist_task_id": "abc123"}},
            )
            is True
        )

    def test_explicit_config_false(self):
        assert (
            evaluate_condition(
                "todo.todoist_task_id",
                config={"todo": {}},
            )
            is False
        )

    def test_compound_with_runtime(self):
        assert (
            evaluate_condition(
                "sync.todoist.enabled and todo.todoist_task_id",
                config={"sync": {"todoist": {"enabled": True}}, "todo": {"todoist_task_id": "abc"}},
            )
            is True
        )

    def test_compound_runtime_missing(self):
        assert (
            evaluate_condition(
                "sync.todoist.enabled and todo.todoist_task_id",
                config={"sync": {"todoist": {"enabled": True}}, "todo": {}},
            )
            is False
        )

    def test_backward_compat_no_config(self, tmp_path: Path):
        nonexistent = tmp_path / "does-not-exist.yaml"
        assert evaluate_condition("nonexistent.path", config_path=nonexistent) is False

    def test_negation_with_config(self):
        assert (
            evaluate_condition("!todo.todoist_task_id", config={"todo": {"todoist_task_id": "abc"}})
            is False
        )
        assert evaluate_condition("!todo.todoist_task_id", config={"todo": {}}) is True

    def test_or_with_config(self):
        """Or compound with config dict param."""
        assert (
            evaluate_condition(
                "a or b",
                config={"a": False, "b": True},
            )
            is True
        )
        assert (
            evaluate_condition(
                "a or b",
                config={"a": False, "b": False},
            )
            is False
        )


# ── validate_condition_syntax ───────────────────────────────────────────────


class TestValidateConditionSyntax:
    def test_valid_simple_condition(self):
        valid, err = validate_condition_syntax("sync.todoist.enabled")
        assert valid is True
        assert err is None

    def test_valid_compound_condition(self):
        valid, err = validate_condition_syntax(
            "sync.todoist.enabled and sync.todoist.auto_sync or sandbox_integration"
        )
        assert valid is True
        assert err is None

    def test_valid_negation(self):
        valid, err = validate_condition_syntax("!sync.todoist.enabled")
        assert valid is True
        assert err is None

    def test_valid_negation_in_compound(self):
        valid, err = validate_condition_syntax("a and !b")
        assert valid is True
        assert err is None

    @pytest.mark.parametrize("cond", ["", "   "])
    def test_empty_or_whitespace_invalid(self, cond: str):
        valid, err = validate_condition_syntax(cond)
        assert valid is False
        assert err is not None

    def test_bare_negation_without_operand(self):
        valid, err = validate_condition_syntax("!")
        assert valid is False
        assert "operand" in err.lower()

    def test_bare_or_without_operand(self):
        valid, err = validate_condition_syntax("a or  or b")
        assert valid is False
        assert "operand" in err.lower()

    def test_bare_and_without_operand(self):
        valid, err = validate_condition_syntax("a and  and b")
        assert valid is False
        assert "operand" in err.lower()

    def test_unbalanced_parens(self):
        valid, err = validate_condition_syntax("(a and b")
        assert valid is False
        assert "parenthes" in err.lower()

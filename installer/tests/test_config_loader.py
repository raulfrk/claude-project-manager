"""Tests for installer/_config_loader.py — shared yaml loader + nested dict walker."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer._config_loader import ConfigLoadError, get_nested, load_existing_yaml


class TestLoadExistingYaml:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_existing_yaml(tmp_path / "missing.yaml") == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.yaml"
        p.write_text("")
        assert load_existing_yaml(p) == {}

    def test_whitespace_only_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "whitespace.yaml"
        p.write_text("   \n\n  ")
        assert load_existing_yaml(p) == {}

    def test_valid_yaml_returns_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "valid.yaml"
        p.write_text("foo: bar\nbaz: 42\n")
        assert load_existing_yaml(p) == {"foo": "bar", "baz": 42}

    def test_null_document_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "null.yaml"
        p.write_text("null\n")
        assert load_existing_yaml(p) == {}

    def test_list_top_level_returns_empty(self, tmp_path: Path) -> None:
        """Non-dict top-level values are treated as empty."""
        p = tmp_path / "list.yaml"
        p.write_text("- a\n- b\n")
        assert load_existing_yaml(p) == {}

    def test_invalid_yaml_raises_config_load_error(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("foo: bar\n  baz: 42\n invalid: - - -\n}}")
        with pytest.raises(ConfigLoadError) as excinfo:
            load_existing_yaml(p)
        assert excinfo.value.path == p
        assert excinfo.value.original is not None


class TestGetNested:
    def test_simple_lookup(self) -> None:
        assert get_nested({"a": 1}, "a") == 1

    def test_nested_lookup(self) -> None:
        d = {"a": {"b": {"c": 42}}}
        assert get_nested(d, "a.b.c") == 42

    def test_missing_key_returns_default(self) -> None:
        assert get_nested({"a": 1}, "b", "default") == "default"

    def test_missing_nested_returns_default(self) -> None:
        d = {"a": {"b": 1}}
        assert get_nested(d, "a.c.d", "fallback") == "fallback"

    def test_intermediate_none_returns_default(self) -> None:
        d = {"a": {"b": None}}
        assert get_nested(d, "a.b.c", "fallback") == "fallback"

    def test_intermediate_non_dict_returns_default(self) -> None:
        d = {"a": 42}
        assert get_nested(d, "a.b", "fallback") == "fallback"

    def test_final_none_returns_default(self) -> None:
        d = {"a": {"b": None}}
        assert get_nested(d, "a.b", "fallback") == "fallback"

    def test_empty_key_returns_default(self) -> None:
        assert get_nested({"a": 1}, "", "fallback") == "fallback"

    def test_no_default_returns_none(self) -> None:
        assert get_nested({}, "a.b") is None

"""Tests for server.lib.template — ${} resolver."""

from __future__ import annotations

from server.lib.template import resolve_mapping, resolve_template


# ── resolve_template ─────────────────────────────────────────────────────────


class TestResolveTemplate:
    def test_no_placeholder(self):
        assert resolve_template("hello world", {}) == "hello world"

    def test_simple_string_value(self):
        source = {"name": "Alice"}
        assert resolve_template("${name}", source) == "Alice"

    def test_nested_path(self):
        source = {"result": {"path": "/tmp/project"}}
        assert resolve_template("${result.path}", source) == "/tmp/project"

    def test_deep_nested_path(self):
        source = {"a": {"b": {"c": {"d": "deep"}}}}
        assert resolve_template("${a.b.c.d}", source) == "deep"

    def test_missing_path_returns_empty(self):
        assert resolve_template("${missing.key}", {"other": "val"}) == ""

    def test_missing_path_in_none(self):
        assert resolve_template("${a.b}", {"a": None}) == ""

    def test_list_index(self):
        source = {"items": ["zero", "one", "two"]}
        assert resolve_template("${items.1}", source) == "one"

    def test_list_index_out_of_range(self):
        source = {"items": ["zero"]}
        assert resolve_template("${items.5}", source) == ""

    def test_list_index_non_numeric(self):
        source = {"items": ["zero"]}
        assert resolve_template("${items.abc}", source) == ""

    def test_integer_value_json_encoded(self):
        source = {"count": 42}
        assert resolve_template("${count}", source) == "42"

    def test_dict_value_json_encoded(self):
        source = {"data": {"key": "val"}}
        result = resolve_template("${data}", source)
        assert '"key"' in result
        assert '"val"' in result

    def test_list_value_json_encoded(self):
        source = {"arr": [1, 2, 3]}
        result = resolve_template("${arr}", source)
        assert result == "[1, 2, 3]"

    def test_bool_value_json_encoded(self):
        source = {"flag": True}
        assert resolve_template("${flag}", source) == "true"

    def test_multiple_placeholders(self):
        source = {"a": "hello", "b": "world"}
        assert resolve_template("${a} ${b}", source) == "hello world"

    def test_mixed_text_and_placeholder(self):
        source = {"name": "project"}
        assert resolve_template("path: ${name}/src", source) == "path: project/src"

    def test_multiple_placeholders_some_missing(self):
        source = {"a": "found"}
        assert resolve_template("${a} ${missing}", source) == "found "

    def test_empty_source(self):
        assert resolve_template("${anything}", {}) == ""

    def test_empty_template(self):
        assert resolve_template("", {"key": "val"}) == ""

    def test_non_string_in_mixed_template_stringified(self):
        """When placeholder is mixed with text, non-string values are JSON-encoded."""
        source = {"n": 42}
        assert resolve_template("count=${n}", source) == "count=42"

    def test_nested_list_in_dict(self):
        source = {"result": {"items": [{"name": "first"}, {"name": "second"}]}}
        assert resolve_template("${result.items.0.name}", source) == "first"
        assert resolve_template("${result.items.1.name}", source) == "second"


# ── resolve_mapping ──────────────────────────────────────────────────────────


class TestResolveMapping:
    def test_empty_mapping(self):
        assert resolve_mapping({}, {"key": "val"}) == {}

    def test_single_key(self):
        source = {"result": {"path": "/tmp"}}
        result = resolve_mapping({"path": "${result.path}"}, source)
        assert result == {"path": "/tmp"}

    def test_multiple_keys(self):
        source = {"title": "My Project", "id": "proj-001"}
        result = resolve_mapping(
            {"name": "${title}", "project_id": "${id}"},
            source,
        )
        assert result == {"name": "My Project", "project_id": "proj-001"}

    def test_literal_values_preserved(self):
        result = resolve_mapping({"static": "hello"}, {"anything": "val"})
        assert result == {"static": "hello"}

    def test_mixed_literal_and_template(self):
        source = {"name": "world"}
        result = resolve_mapping(
            {"greeting": "hello ${name}", "literal": "constant"},
            source,
        )
        assert result == {"greeting": "hello world", "literal": "constant"}

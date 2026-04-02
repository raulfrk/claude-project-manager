"""Tests for server.lib.template — ${} resolver."""

from __future__ import annotations

from server.lib.template import resolve_mapping, resolve_template, resolve_value


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

    def test_integer_value_native(self):
        source = {"count": 42}
        assert resolve_template("${count}", source) == 42

    def test_dict_value_native(self):
        source = {"data": {"key": "val"}}
        result = resolve_template("${data}", source)
        assert result == {"key": "val"}

    def test_list_value_native(self):
        source = {"arr": [1, 2, 3]}
        result = resolve_template("${arr}", source)
        assert result == [1, 2, 3]

    def test_bool_value_native(self):
        source = {"flag": True}
        assert resolve_template("${flag}", source) is True

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

    def test_nested_mapping(self):
        mapping = {"tasks": [{"content": "${title}"}]}
        result = resolve_mapping(mapping, {"title": "hello"})
        assert result == {"tasks": [{"content": "hello"}]}

    def test_mixed_nested_and_flat(self):
        mapping = {
            "name": "${title}",
            "tasks": [{"content": "${title}", "projectId": "${pid}"}],
        }
        source = {"title": "My Task", "pid": "proj123"}
        result = resolve_mapping(mapping, source)
        assert result == {
            "name": "My Task",
            "tasks": [{"content": "My Task", "projectId": "proj123"}],
        }

    def test_nested_dict_with_templates(self):
        mapping = {"tasks": [{"content": "${title}", "projectId": "${pid}"}]}
        source = {"title": "My Task", "pid": "proj123"}
        result = resolve_mapping(mapping, source)
        assert result == {"tasks": [{"content": "My Task", "projectId": "proj123"}]}


# ── resolve_value ───────────────────────────────────────────────────────────


class TestResolveValue:
    def test_nested_dict(self):
        mapping = {"tasks": [{"content": "${title}", "projectId": "${project_id}"}]}
        source = {"title": "My Task", "project_id": "proj123"}
        result = resolve_value(mapping["tasks"], source)
        assert result == [{"content": "My Task", "projectId": "proj123"}]

    def test_passthrough_int(self):
        assert resolve_value(42, {}) == 42

    def test_passthrough_none(self):
        assert resolve_value(None, {}) is None

    def test_passthrough_bool(self):
        assert resolve_value(True, {}) is True

    def test_passthrough_float(self):
        assert resolve_value(3.14, {}) == 3.14

    def test_string_template(self):
        assert resolve_value("${name}", {"name": "Alice"}) == "Alice"

    def test_nested_list_of_strings(self):
        result = resolve_value(["${a}", "${b}"], {"a": "x", "b": "y"})
        assert result == ["x", "y"]

    def test_list_of_dicts(self):
        value = [
            {"content": "${title}", "pid": "${pid}"},
            {"content": "${subtitle}", "pid": "${pid}"},
        ]
        source = {"title": "A", "subtitle": "B", "pid": "p1"}
        result = resolve_value(value, source)
        assert result == [
            {"content": "A", "pid": "p1"},
            {"content": "B", "pid": "p1"},
        ]

    def test_two_levels_deep(self):
        value = {"outer": {"inner": "${value}"}}
        result = resolve_value(value, {"value": "deep"})
        assert result == {"outer": {"inner": "deep"}}

    def test_missing_key_in_nested_dict(self):
        value = {"tasks": [{"content": "${missing.key}"}]}
        result = resolve_value(value, {"other": "val"})
        assert result == {"tasks": [{"content": ""}]}

    def test_empty_list(self):
        result = resolve_value([], {"key": "val"})
        assert result == []

    def test_passthrough_int_bool_in_nested(self):
        value = {"count": 5, "enabled": True, "name": "${name}"}
        result = resolve_value(value, {"name": "test"})
        assert result == {"count": 5, "enabled": True, "name": "test"}

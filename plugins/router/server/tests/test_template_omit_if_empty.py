from __future__ import annotations

from server.lib.template import resolve_mapping


def test_plain_template_still_resolves():
    mapping = {"name": "${title}", "priority": "${priority}"}
    source = {"title": "hi", "priority": "high"}
    assert resolve_mapping(mapping, source) == {"name": "hi", "priority": "high"}


def test_omit_if_empty_removes_key_when_value_empty():
    mapping = {
        "name": "${title}",
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {"title": "hi", "parent": ""}
    result = resolve_mapping(mapping, source)
    assert "parent_key" not in result
    assert result["name"] == "hi"


def test_omit_if_empty_removes_key_when_value_missing():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {}  # parent absent entirely
    assert resolve_mapping(mapping, source) == {}


def test_omit_if_empty_removes_key_when_value_none():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {"parent": None}
    assert resolve_mapping(mapping, source) == {}


def test_omit_if_empty_keeps_key_when_value_present():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {"parent": "CPM-100"}
    assert resolve_mapping(mapping, source) == {"parent_key": "CPM-100"}


def test_omit_if_empty_false_keeps_empty_value():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": False},
    }
    source = {"parent": ""}
    assert resolve_mapping(mapping, source) == {"parent_key": ""}


def test_dict_without_omit_if_empty_treated_as_plain_dict():
    # Backward compat: nested dicts without the omit_if_empty key still work
    mapping = {"outer": {"inner": "${x}"}}
    source = {"x": "y"}
    assert resolve_mapping(mapping, source) == {"outer": {"inner": "y"}}


def test_omit_if_empty_keeps_key_when_value_is_false():
    # False is a valid boolean value, not "empty" — key should be kept.
    mapping = {"flag": {"value": "${active}", "omit_if_empty": True}}
    source = {"active": False}
    assert resolve_mapping(mapping, source) == {"flag": False}


def test_omit_if_empty_keeps_key_when_value_is_true():
    mapping = {"flag": {"value": "${active}", "omit_if_empty": True}}
    source = {"active": True}
    assert resolve_mapping(mapping, source) == {"flag": True}


def test_omit_if_empty_removes_key_when_value_is_zero():
    mapping = {"count": {"value": "${n}", "omit_if_empty": True}}
    source = {"n": 0}
    assert resolve_mapping(mapping, source) == {}

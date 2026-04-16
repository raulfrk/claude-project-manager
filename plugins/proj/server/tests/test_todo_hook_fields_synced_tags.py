from __future__ import annotations

from server.lib.models import ProjectMeta, Todo
from server.tools.todos import _todo_hook_fields


def _todo(**kwargs) -> Todo:
    defaults = {"id": "1", "title": "x"}
    defaults.update(kwargs)
    return Todo(**defaults)


def _meta() -> ProjectMeta:
    return ProjectMeta(name="demo")


def test_synced_tags_strips_group_prefix():
    todo = _todo(tags=["manual", "group:5", "auto-added"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["manual", "auto-added"]


def test_synced_tags_preserves_order():
    todo = _todo(tags=["z", "group:5", "a", "m"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["z", "a", "m"]


def test_synced_tags_empty_when_only_group_tags():
    todo = _todo(tags=["group:5"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == []


def test_synced_tags_unchanged_when_no_group_prefix():
    todo = _todo(tags=["a", "b"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["a", "b"]


def test_raw_tags_field_still_includes_group_tag():
    todo = _todo(tags=["manual", "group:5"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["tags"] == ["manual", "group:5"]  # raw list preserved


def test_synced_tags_empty_list_for_todo_with_no_tags():
    todo = _todo(tags=[])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == []


def test_synced_tags_keeps_bare_group_tag():
    # `group:` (no id) is NOT a parent pointer per _GROUP_TAG_RE — keep it in synced_tags.
    todo = _todo(tags=["manual", "group:"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["manual", "group:"]


def test_synced_tags_strips_multiple_group_entries():
    todo = _todo(tags=["group:5", "real", "group:7"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["real"]

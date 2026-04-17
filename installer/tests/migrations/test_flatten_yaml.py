# installer/tests/migrations/test_flatten_yaml.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.transform import flatten_todos_yaml


def _load(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text()) or []


def test_parent_and_children_become_group_tag(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    src.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "parent",
                    "parent": None,
                    "children": ["1.1", "1.2"],
                    "tags": [],
                },
                {
                    "id": "1.1",
                    "title": "child a",
                    "parent": "1",
                    "children": [],
                    "tags": [],
                },
                {
                    "id": "1.2",
                    "title": "child b",
                    "parent": "1",
                    "children": [],
                    "tags": ["existing"],
                },
                {
                    "id": "2",
                    "title": "solo",
                    "parent": None,
                    "children": [],
                    "tags": [],
                },
            ]
        ),
    )
    flatten_todos_yaml(src)
    out = _load(src)
    by_id = {t["id"]: t for t in out}
    assert "parent" not in by_id["1"]
    assert "children" not in by_id["1"]
    assert "next_child_id" not in by_id["1"]
    assert "group:1" in by_id["1.1"]["tags"]
    assert "group:1" in by_id["1.2"]["tags"]
    assert "existing" in by_id["1.2"]["tags"]  # existing tags preserved
    assert by_id["1"]["tags"] == []  # parent itself has no group tag (it IS the group)
    assert by_id["2"]["tags"] == []  # standalone untouched


def test_idempotent_on_flat_data(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    data = [
        {"id": "1", "title": "parent", "tags": []},
        {"id": "1.1", "title": "child", "tags": ["group:1"]},
    ]
    src.write_text(yaml.safe_dump(data))
    flatten_todos_yaml(src)
    assert _load(src) == data


def test_orphan_child_gets_warning_and_no_group_tag(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    src = tmp_path / "todos.yaml"
    src.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "7",
                    "title": "orphan",
                    "parent": "missing",
                    "children": [],
                    "tags": [],
                },
            ]
        ),
    )
    flatten_todos_yaml(src)
    out = _load(src)
    assert "parent" not in out[0]
    assert not any(t.startswith("group:") for t in out[0]["tags"])
    assert any("orphan" in r.message for r in caplog.records)


def test_child_with_tags_already_containing_group_no_dup(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    src.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "parent",
                    "parent": None,
                    "children": ["1.1"],
                    "tags": [],
                },
                {
                    "id": "1.1",
                    "title": "c",
                    "parent": "1",
                    "children": [],
                    "tags": ["group:1"],
                },
            ]
        ),
    )
    flatten_todos_yaml(src)
    out = _load(src)
    assert out[1]["tags"].count("group:1") == 1


def test_preserves_other_fields(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    original = [
        {
            "id": "1",
            "title": "p",
            "parent": None,
            "children": ["1.1"],
            "tags": [],
            "priority": "high",
            "status": "pending",
            "todoist_task_id": "abc",
        },
        {
            "id": "1.1",
            "title": "c",
            "parent": "1",
            "children": [],
            "tags": [],
            "priority": "medium",
            "jira_issue_key": "CPM-5",
        },
    ]
    src.write_text(yaml.safe_dump(original))
    flatten_todos_yaml(src)
    out = _load(src)
    assert out[0]["todoist_task_id"] == "abc"
    assert out[1]["jira_issue_key"] == "CPM-5"
    assert out[0]["priority"] == "high"
    assert out[1]["priority"] == "medium"

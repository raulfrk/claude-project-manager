"""Tests for Todoist data models and priority mapping."""

from __future__ import annotations

import pytest

from server.lib.models import (
    TodoistProject,
    TodoistTask,
    local_to_todoist_priority,
    todoist_to_local_priority,
)


# -- local_to_todoist_priority ------------------------------------------------


class TestLocalToTodoistPriority:
    def test_high(self) -> None:
        assert local_to_todoist_priority("high") == "p2"

    def test_medium(self) -> None:
        assert local_to_todoist_priority("medium") == "p3"

    def test_low(self) -> None:
        assert local_to_todoist_priority("low") == "p4"

    def test_unknown_defaults_to_p4(self) -> None:
        assert local_to_todoist_priority("unknown") == "p4"

    def test_empty_string_defaults_to_p4(self) -> None:
        assert local_to_todoist_priority("") == "p4"


# -- todoist_to_local_priority ------------------------------------------------


class TestTodoistToLocalPriority:
    # String inputs
    def test_p1_string(self) -> None:
        assert todoist_to_local_priority("p1") == "high"

    def test_p2_string(self) -> None:
        assert todoist_to_local_priority("p2") == "high"

    def test_p3_string(self) -> None:
        assert todoist_to_local_priority("p3") == "medium"

    def test_p4_string(self) -> None:
        assert todoist_to_local_priority("p4") == "low"

    # Int inputs
    def test_p1_int(self) -> None:
        assert todoist_to_local_priority(1) == "high"

    def test_p2_int(self) -> None:
        assert todoist_to_local_priority(2) == "high"

    def test_p3_int(self) -> None:
        assert todoist_to_local_priority(3) == "medium"

    def test_p4_int(self) -> None:
        assert todoist_to_local_priority(4) == "low"

    # Edge cases
    def test_unknown_string_defaults_to_low(self) -> None:
        assert todoist_to_local_priority("p9") == "low"

    def test_non_p_string_defaults_to_low(self) -> None:
        assert todoist_to_local_priority("high") == "low"


# -- TodoistTask.from_api -----------------------------------------------------


class TestTodoistTaskFromApi:
    def test_complete_response(self) -> None:
        data = {
            "id": "123456",
            "content": "Buy groceries",
            "description": "Milk, eggs, bread",
            "priority": 2,
            "labels": ["shopping", "errands"],
            "due": {"date": "2024-01-15", "string": "Jan 15"},
            "projectId": "proj123",
            "parentId": "parent789",
            "isCompleted": False,
        }
        task = TodoistTask.from_api(data)

        assert task.id == "123456"
        assert task.content == "Buy groceries"
        assert task.description == "Milk, eggs, bread"
        assert task.priority == "high"
        assert task.labels == ["shopping", "errands"]
        assert task.due == {"date": "2024-01-15", "string": "Jan 15"}
        assert task.project_id == "proj123"
        assert task.parent_id == "parent789"
        assert task.is_completed is False

    def test_minimal_response(self) -> None:
        data = {"id": "1", "content": "Simple task"}
        task = TodoistTask.from_api(data)

        assert task.id == "1"
        assert task.content == "Simple task"
        assert task.description == ""
        assert task.priority == "low"
        assert task.labels == []
        assert task.due is None
        assert task.project_id == ""
        assert task.parent_id is None
        assert task.is_completed is False

    def test_string_priority(self) -> None:
        data = {"id": "1", "content": "Task", "priority": "p3"}
        task = TodoistTask.from_api(data)
        assert task.priority == "medium"

    def test_snake_case_keys(self) -> None:
        """API may return snake_case keys instead of camelCase."""
        data = {
            "id": "1",
            "content": "Task",
            "project_id": "proj1",
            "parent_id": "parent1",
            "is_completed": True,
        }
        task = TodoistTask.from_api(data)
        assert task.project_id == "proj1"
        assert task.parent_id == "parent1"
        assert task.is_completed is True

    def test_none_priority_defaults_to_low(self) -> None:
        data = {"id": "1", "content": "Task", "priority": None}
        task = TodoistTask.from_api(data)
        assert task.priority == "low"

    def test_invalid_labels_ignored(self) -> None:
        data = {"id": "1", "content": "Task", "labels": "not-a-list"}
        task = TodoistTask.from_api(data)
        assert task.labels == []

    def test_invalid_due_ignored(self) -> None:
        data = {"id": "1", "content": "Task", "due": "not-a-dict"}
        task = TodoistTask.from_api(data)
        assert task.due is None


# -- TodoistTask.to_dict ------------------------------------------------------


class TestTodoistTaskToDict:
    def test_round_trip(self) -> None:
        task = TodoistTask(
            id="1",
            content="Task",
            description="Desc",
            priority="medium",
            labels=["a"],
            due={"date": "2024-01-01"},
            project_id="p1",
            parent_id="pp1",
            is_completed=True,
        )
        d = task.to_dict()
        assert d == {
            "id": "1",
            "content": "Task",
            "description": "Desc",
            "priority": "medium",
            "labels": ["a"],
            "due": {"date": "2024-01-01"},
            "project_id": "p1",
            "parent_id": "pp1",
            "is_completed": True,
            "updatedAt": "",
        }


# -- TodoistProject.from_api --------------------------------------------------


class TestTodoistProjectFromApi:
    def test_complete_response(self) -> None:
        data = {
            "id": "proj123",
            "name": "Work",
            "color": "blue",
            "isFavorite": True,
        }
        project = TodoistProject.from_api(data)

        assert project.id == "proj123"
        assert project.name == "Work"
        assert project.color == "blue"
        assert project.is_favorite is True

    def test_minimal_response(self) -> None:
        data = {"id": "1", "name": "Inbox"}
        project = TodoistProject.from_api(data)

        assert project.id == "1"
        assert project.name == "Inbox"
        assert project.color is None
        assert project.is_favorite is False

    def test_snake_case_keys(self) -> None:
        data = {"id": "1", "name": "P", "is_favorite": True}
        project = TodoistProject.from_api(data)
        assert project.is_favorite is True


# -- TodoistProject.to_dict ---------------------------------------------------


class TestTodoistProjectToDict:
    def test_round_trip(self) -> None:
        project = TodoistProject(id="1", name="P", color="red", is_favorite=True)
        d = project.to_dict()
        assert d == {
            "id": "1",
            "name": "P",
            "color": "red",
            "is_favorite": True,
        }


# -- Round-trip priority consistency ------------------------------------------


class TestPriorityRoundTrip:
    @pytest.mark.parametrize(
        ("local", "expected_todoist", "expected_back"),
        [
            ("high", "p2", "high"),
            ("medium", "p3", "medium"),
            ("low", "p4", "low"),
        ],
    )
    def test_local_to_todoist_and_back(
        self, local: str, expected_todoist: str, expected_back: str
    ) -> None:
        todoist = local_to_todoist_priority(local)
        assert todoist == expected_todoist
        back = todoist_to_local_priority(todoist)
        assert back == expected_back

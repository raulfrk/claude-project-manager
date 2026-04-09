"""Tests filling coverage gaps: unexpected response types, batch edge cases,
model parsing edge cases, rate-limit propagation, and todoist_init tool.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from server.lib.client import TodoistClient
from server.tools.tasks import _build_task_payload, _resolve_priority, _to_json_value

# -- Shared fixtures ---------------------------------------------------------

_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "FTP_PROXY",
    "ftp_proxy",
)


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock(spec=TodoistClient)
    monkeypatch.setattr("server.tools.tasks.get_client", lambda: client)
    monkeypatch.setattr("server.tools.projects.get_client", lambda: client)
    return client


def _api_task(
    id: str = "1",
    content: str = "Task",
    priority: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    return {"id": id, "content": content, "priority": priority, **extra}


def _make_task_app():
    from mcp.server.fastmcp import FastMCP

    from server.tools.tasks import register

    app = FastMCP("test")
    register(app)
    return app


def _make_project_app():
    from mcp.server.fastmcp import FastMCP

    from server.tools.projects import register

    app = FastMCP("test")
    register(app)
    return app


# -- _to_json_value ----------------------------------------------------------


class TestToJsonValue:
    def test_list_input(self) -> None:
        result = _to_json_value(["a", "b"])
        assert result == ["a", "b"]

    def test_string_input(self) -> None:
        assert _to_json_value("hello") == "hello"

    def test_int_input(self) -> None:
        assert _to_json_value(42) == 42

    def test_bool_input(self) -> None:
        assert _to_json_value(True) is True

    def test_none_input(self) -> None:
        assert _to_json_value(None) is None

    def test_float_input(self) -> None:
        assert _to_json_value(3.14) == 3.14


# -- _build_task_payload edge cases ------------------------------------------


class TestBuildTaskPayloadEdgeCases:
    def test_priority_bool_passes_through(self) -> None:
        """Bool is a subclass of int in Python, so isinstance(True, int) is True.
        True (1) passes through _resolve_priority as int 1."""
        payload = _build_task_payload({"content": "Task", "priority": True})
        # bool True == int 1, so _resolve_priority returns 1
        assert payload["priority"] == 1

    def test_priority_float_excluded(self) -> None:
        """Priority that is float should be excluded."""
        payload = _build_task_payload({"content": "Task", "priority": 2.5})
        assert "priority" not in payload

    def test_camel_case_takes_precedence_over_snake(self) -> None:
        """When both dueString and due_string present, camelCase wins."""
        payload = _build_task_payload(
            {"content": "Task", "dueString": "tomorrow", "due_string": "next week"}
        )
        assert payload["due_string"] == "tomorrow"


# -- _resolve_priority edge cases --------------------------------------------


class TestResolvePriorityEdgeCases:
    def test_whitespace_padded_string(self) -> None:
        assert _resolve_priority("  p3  ") == 3

    def test_mixed_case_local(self) -> None:
        assert _resolve_priority("Medium") == 3

    def test_empty_string_defaults_to_1(self) -> None:
        """Empty string is unknown, defaults to 1."""
        assert _resolve_priority("") == 1


# -- todoist_add_tasks: unexpected response type -----------------------------


class TestAddTasksUnexpectedResponse:
    def test_non_dict_response_records_failure(self, mock_client: MagicMock) -> None:
        """When API returns a non-dict (e.g. a string), it should be a failure."""
        mock_client.post.return_value = "unexpected string"

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[{"content": "Task"}]))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["error"] == "Unexpected response type"

    def test_list_response_records_failure(self, mock_client: MagicMock) -> None:
        """When API returns a list instead of dict, it should be a failure."""
        mock_client.post.return_value = [{"id": "1"}]

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[{"content": "Task"}]))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["error"] == "Unexpected response type"

    def test_mixed_success_and_unexpected(self, mock_client: MagicMock) -> None:
        """First task returns dict, second returns non-dict."""
        mock_client.post.side_effect = [
            _api_task(id="1", content="Good"),
            "not a dict",
        ]

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[{"content": "Good"}, {"content": "Bad"}]))

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["index"] == 1


# -- todoist_update_tasks: unexpected response type --------------------------


class TestUpdateTasksUnexpectedResponse:
    def test_non_dict_response_records_failure(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = 42

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[{"id": "1", "content": "X"}]))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["error"] == "Unexpected response type"

    def test_all_updates_fail_with_exception(self, mock_client: MagicMock) -> None:
        """Every update raises — all should be captured in failures."""
        mock_client.post.side_effect = RuntimeError("boom")

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(
            tool.fn(
                tasks=[
                    {"id": "1", "content": "A"},
                    {"id": "2", "content": "B"},
                ]
            )
        )

        assert result["successes"] == []
        assert len(result["failures"]) == 2
        assert result["failures"][0]["id"] == "1"
        assert result["failures"][1]["id"] == "2"


# -- todoist_update_task_hook: unexpected response type ----------------------


class TestUpdateTaskHookUnexpectedResponse:
    def test_non_dict_response(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = "oops"

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_update_task_hook"]
        result = json.loads(tool.fn(id="u1", content="X"))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["id"] == "u1"
        assert result["failures"][0]["error"] == "Unexpected response type"


# -- todoist_add_child_task_hook: unexpected response type -------------------


class TestAddChildTaskHookUnexpectedResponse:
    def test_non_dict_response(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = None

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_add_child_task_hook"]
        result = json.loads(tool.fn(content="Child", projectId="p1", parentId="par1"))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["error"] == "Unexpected response type"


# -- todoist_find_tasks: edge cases ------------------------------------------


class TestFindTasksEdgeCases:
    def test_non_dict_items_filtered(self, mock_client: MagicMock) -> None:
        """Response list may contain non-dict items (e.g. nulls). They should be filtered."""
        mock_client.get_paginated.return_value = [
            _api_task(id="1", content="Real"),
            "not a dict",
            42,
            None,
            _api_task(id="2", content="Also real"),
        ]

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn())

        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "2"

    def test_both_project_id_and_filter(self, mock_client: MagicMock) -> None:
        """Both params should be passed together."""
        mock_client.get_paginated.return_value = []

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_find_tasks"]
        tool.fn(project_id="proj1", filter="today")

        mock_client.get_paginated.assert_called_once_with(
            "/tasks", params={"project_id": "proj1", "filter": "today"}, limit=None
        )


# -- todoist_uncomplete_tasks: all fail --------------------------------------


class TestUncompleteTasksAllFail:
    def test_all_fail(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.side_effect = RuntimeError("gone")

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=["a", "b"]))

        assert result["successes"] == []
        assert len(result["failures"]) == 2


# -- todoist_complete_tasks: all fail ----------------------------------------


class TestCompleteTasksAllFail:
    def test_all_fail(self, mock_client: MagicMock) -> None:
        mock_client.close_task.side_effect = RuntimeError("gone")

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=["x", "y", "z"]))

        assert result["successes"] == []
        assert len(result["failures"]) == 3
        for i, f in enumerate(result["failures"]):
            assert f["id"] == ["x", "y", "z"][i]
            assert "gone" in f["error"]


# -- todoist_verify_complete: missing is_completed field ---------------------


class TestVerifyCompleteMissingField:
    def test_dict_without_checked_field(self, mock_client: MagicMock) -> None:
        """API returns a dict without checked — should default to False."""
        mock_client.get.return_value = {"id": "v4", "content": "task"}

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_verify_complete"]
        result = json.loads(tool.fn(todoist_task_id="v4"))

        assert result["verified"] is False
        assert result["status"] == "open"


# -- Rate-limit propagation through tools ------------------------------------


class TestRateLimitPropagation:
    def test_add_tasks_rate_limit(self, mock_client: MagicMock) -> None:
        """Rate limit error should be captured in failures, not crash."""
        mock_client.post.side_effect = RuntimeError("Todoist rate limited. Retry after 30 seconds.")

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[{"content": "Task"}]))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "rate limited" in result["failures"][0]["error"].lower()

    def test_complete_tasks_rate_limit(self, mock_client: MagicMock) -> None:
        mock_client.close_task.side_effect = RuntimeError(
            "Todoist rate limited. Retry after 60 seconds."
        )

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=["t1"]))

        assert result["successes"] == []
        assert "rate limited" in result["failures"][0]["error"].lower()

    def test_update_tasks_rate_limit(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("Todoist rate limited. Retry after 60 seconds.")

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[{"id": "1", "content": "X"}]))

        assert result["successes"] == []
        assert "rate limited" in result["failures"][0]["error"].lower()

    def test_uncomplete_tasks_rate_limit(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.side_effect = RuntimeError(
            "Todoist rate limited. Retry after 60 seconds."
        )

        app = _make_task_app()
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=["t1"]))

        assert result["successes"] == []
        assert "rate limited" in result["failures"][0]["error"].lower()


# -- todoist_find_projects: non-dict items in response -----------------------


class TestFindProjectsEdgeCases:
    def test_non_dict_items_filtered_during_name_search(self, mock_client: MagicMock) -> None:
        """Non-dict items in the response list should be filtered by name search."""
        mock_client.get_paginated.return_value = [
            {"id": "1", "name": "Work"},
            "not a dict",
            None,
            {"id": "2", "name": "Personal"},
        ]

        app = _make_project_app()
        tool = app._tool_manager._tools["todoist_find_projects"]
        result = json.loads(tool.fn(name="work"))

        assert len(result) == 1
        assert result[0]["name"] == "Work"


# -- todoist_init tool -------------------------------------------------------


class TestTodoistInit:
    @pytest.fixture(autouse=True)
    def _clear_caches(self) -> None:
        import server.lib.client as client_mod
        import server.lib.config as config_mod

        config_mod._cached_config = None
        client_mod._cached_client = None

    def _get_tool(self) -> Any:
        from mcp.server.fastmcp import FastMCP

        from server.tools.init import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["todoist_init"]

    def test_success(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Successful init validates token and writes config."""

        def mock_get(*args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200, json={"results": [{"id": "p1"}, {"id": "p2"}], "next_cursor": None}
            )

        monkeypatch.setattr(httpx, "get", mock_get)
        config_path = tmp_path / "todoist.yaml"
        monkeypatch.setattr(
            "server.tools.init.Path",
            lambda p: config_path if "todoist.yaml" in p else Path(p),
        )
        # Patch expanduser on the config_path
        monkeypatch.setattr(Path, "expanduser", lambda self: self)

        tool = self._get_tool()
        result = json.loads(tool.fn(api_token="tok-valid"))

        assert result["ok"] is True
        assert result["project_count"] == 2

    def test_invalid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid token returns error JSON, not exception."""

        def mock_get(*args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        monkeypatch.setattr(httpx, "get", mock_get)

        tool = self._get_tool()
        result = json.loads(tool.fn(api_token="bad-token"))

        assert "error" in result
        assert "401" in result["error"]

    def test_server_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Server error returns error JSON."""

        def mock_get(*args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        monkeypatch.setattr(httpx, "get", mock_get)

        tool = self._get_tool()
        result = json.loads(tool.fn(api_token="tok-test"))

        assert "error" in result
        assert "500" in result["error"]


# -- TodoistTask.from_api: more edge cases -----------------------------------


class TestTaskModelEdgeCases:
    def test_empty_dict(self) -> None:
        """from_api with empty dict should return defaults."""
        from server.lib.models import TodoistTask

        task = TodoistTask.from_api({})
        assert task.id == ""
        assert task.content == ""
        assert task.priority == "low"
        assert task.labels == []
        assert task.due is None
        assert task.parent_id is None

    def test_integer_id_coerced_to_string(self) -> None:
        """Todoist API may return integer IDs."""
        from server.lib.models import TodoistTask

        task = TodoistTask.from_api({"id": 12345, "content": "Task"})
        assert task.id == "12345"
        assert isinstance(task.id, str)

    def test_integer_parent_id_coerced_to_string(self) -> None:
        from server.lib.models import TodoistTask

        task = TodoistTask.from_api({"id": "1", "content": "Task", "parent_id": 999})
        assert task.parent_id == "999"
        assert isinstance(task.parent_id, str)

    def test_labels_with_non_string_elements(self) -> None:
        """Labels list with non-string elements should still stringify."""
        from server.lib.models import TodoistTask

        task = TodoistTask.from_api({"id": "1", "content": "Task", "labels": [1, True, "ok"]})
        assert task.labels == ["1", "True", "ok"]

    def test_priority_out_of_range_int(self) -> None:
        """Priority int outside 1-4 range maps to unknown -> low."""
        from server.lib.models import TodoistTask

        task = TodoistTask.from_api({"id": "1", "content": "Task", "priority": 99})
        assert task.priority == "low"

    def test_project_id_from_snake_case(self) -> None:
        """API v1 uses snake_case project_id."""
        from server.lib.models import TodoistTask

        task = TodoistTask.from_api({"id": "1", "content": "Task", "project_id": "snake"})
        assert task.project_id == "snake"

    def test_parent_id_from_snake_case(self) -> None:
        """API v1 uses snake_case parent_id."""
        from server.lib.models import TodoistTask

        task = TodoistTask.from_api({"id": "1", "content": "Task", "parent_id": "snake"})
        assert task.parent_id == "snake"


# -- TodoistProject.from_api edge cases --------------------------------------


class TestProjectModelEdgeCases:
    def test_empty_dict(self) -> None:
        from server.lib.models import TodoistProject

        project = TodoistProject.from_api({})
        assert project.id == ""
        assert project.name == ""
        assert project.color is None
        assert project.is_favorite is False

    def test_integer_id_coerced(self) -> None:
        from server.lib.models import TodoistProject

        project = TodoistProject.from_api({"id": 42, "name": "Test"})
        assert project.id == "42"
        assert isinstance(project.id, str)

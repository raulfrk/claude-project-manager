# installer/tests/migrations/test_todoist_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.todoist import TodoistResync, _load_api_token
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_todoist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> PendingProject:
    # Global integration config lives in ~/.claude/proj.yaml — point HOME at tmp.
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump({"sync": {"todoist": {"enabled": True, "api_token": "tok"}}}),
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    root = tmp_path / "demo"
    root.mkdir()
    (root / "todos.yaml").write_text("[]\n")
    return PendingProject(
        name="demo",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=1,
    )


def _make_children(n: int) -> list[TodoRef]:
    return [
        TodoRef(id=f"1.{i}", title=f"c{i}", todoist_task_id=f"task-{i}", parent="1")
        for i in range(n)
    ]


def test_enabled_for_requires_config_and_links(
    project_with_todoist: PendingProject,
) -> None:
    r = TodoistResync()
    assert r.enabled_for(project_with_todoist) is False  # no migrated todos yet
    # With at least one migrated child with a todoist_task_id
    # (enabled_for in this impl takes project + migrated list)
    actions = r.plan(project_with_todoist, _make_children(1))
    assert len(actions) == 1


def test_enabled_for_unwraps_todos_dict(
    project_with_todoist: PendingProject,
) -> None:
    """Real proj-plugin todos.yaml is {"todos": [...]}; enabled_for must unwrap."""
    (project_with_todoist.path / "todos.yaml").write_text(
        yaml.safe_dump({"todos": [{"id": "1", "todoist_task_id": "tsk-1"}]}),
    )
    assert TodoistResync().enabled_for(project_with_todoist) is True


def test_enabled_for_accepts_bare_list(
    project_with_todoist: PendingProject,
) -> None:
    """Legacy bare-list todos.yaml still accepted."""
    (project_with_todoist.path / "todos.yaml").write_text(
        yaml.safe_dump([{"id": "1", "todoist_task_id": "tsk-1"}]),
    )
    assert TodoistResync().enabled_for(project_with_todoist) is True


def test_enabled_for_returns_false_when_no_todoist_ids(
    project_with_todoist: PendingProject,
) -> None:
    """Wrapped todos.yaml w/ no todoist_task_id → enabled_for False."""
    (project_with_todoist.path / "todos.yaml").write_text(
        yaml.safe_dump({"todos": [{"id": "1", "title": "t"}]}),
    )
    assert TodoistResync().enabled_for(project_with_todoist) is False


def test_plan_emits_clear_parent_per_child(
    project_with_todoist: PendingProject,
) -> None:
    r = TodoistResync()
    actions = r.plan(project_with_todoist, _make_children(3))
    assert len(actions) == 3
    assert all(a.kind == "clear_parent" for a in actions)
    assert {a.target_id for a in actions} == {"task-0", "task-1", "task-2"}


def test_plan_skips_children_without_todoist_id(
    project_with_todoist: PendingProject,
) -> None:
    children = [
        TodoRef(id="1.1", title="c", todoist_task_id=None, parent="1"),
        TodoRef(id="1.2", title="c", todoist_task_id="t", parent="1"),
    ]
    actions = TodoistResync().plan(project_with_todoist, children)
    assert [a.target_id for a in actions] == ["t"]


@respx.mock
def test_execute_batches_successfully(project_with_todoist: PendingProject) -> None:
    actions = TodoistResync().plan(project_with_todoist, _make_children(3))
    respx.post("https://api.todoist.com/api/v1/sync").mock(
        return_value=Response(200, json={"sync_status": {}})
    )
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is False
    assert len(result.ok) == 3
    assert not result.failed


@respx.mock
def test_execute_logs_partial_batch_failure(
    project_with_todoist: PendingProject,
) -> None:
    actions = TodoistResync().plan(
        project_with_todoist, _make_children(60)
    )  # 2 batches
    # First batch ok, second 429
    route = respx.post("https://api.todoist.com/api/v1/sync")
    route.side_effect = [
        Response(200, json={}),
        Response(429, json={"error": "rate limited"}),
    ]
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is False
    assert len(result.ok) == 50
    assert len(result.failed) == 10
    assert result.failed[0].error_class == "HTTPStatusError"


@respx.mock
def test_execute_auth_failure_aborts(project_with_todoist: PendingProject) -> None:
    actions = TodoistResync().plan(project_with_todoist, _make_children(2))
    respx.post("https://api.todoist.com/api/v1/sync").mock(
        return_value=Response(401, json={})
    )
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is True
    assert len(result.failed) == 2


class TestLoadApiToken:
    """Priority: ~/.claude/todoist.yaml → proj.yaml → None."""

    def test_load_from_todoist_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "todoist.yaml").write_text(
            "api_token: tok-from-todoist\n"
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        # Proj cfg should be ignored when todoist.yaml wins.
        cfg = {"sync": {"todoist": {"api_token": "tok-from-proj"}}}
        assert _load_api_token(cfg) == "tok-from-todoist"

    def test_fallback_to_proj_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        # No todoist.yaml file.
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        cfg = {"sync": {"todoist": {"api_token": "tok-from-proj"}}}
        assert _load_api_token(cfg) == "tok-from-proj"

    def test_returns_none_when_both_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        assert _load_api_token({}) is None
        assert _load_api_token(None) is None
        assert _load_api_token({"sync": {"todoist": {}}}) is None

    def test_yaml_error_in_todoist_yaml_fallbacks_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "todoist.yaml").write_text(":::broken\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        cfg = {"sync": {"todoist": {"api_token": "tok-from-proj"}}}
        assert _load_api_token(cfg) == "tok-from-proj"

    def test_empty_token_treated_as_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "todoist.yaml").write_text("api_token: '   '\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        # Should fall through to proj.yaml.
        cfg = {"sync": {"todoist": {"api_token": "tok-from-proj"}}}
        assert _load_api_token(cfg) == "tok-from-proj"


class TestExecuteTokenResolution:
    """``execute`` must use ``_load_api_token`` and emit a single runbook-bearing
    ``FailedAction`` when no token is available."""

    def test_aborts_with_runbook_when_no_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.migrations.integrations.base import Action

        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        # No todoist.yaml.
        (fake_home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump({"sync": {"todoist": {"enabled": True}}})
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        root = tmp_path / "demo"
        root.mkdir()
        (root / "todos.yaml").write_text("[]\n")
        project = PendingProject(
            name="demo",
            path=root,
            schema_version_path=root / ".schema-version",
            current_version=1,
        )

        actions = [
            Action(kind="clear_parent", target_id="t-1", payload={"parent_id": None}),
            Action(kind="clear_parent", target_id="t-2", payload={"parent_id": None}),
            Action(kind="clear_parent", target_id="t-3", payload={"parent_id": None}),
        ]

        result = TodoistResync().execute(project, actions)

        assert result.aborted is True
        # Exactly one synthetic FailedAction — not one-per-action spam.
        assert len(result.failed) == 1
        fa = result.failed[0]
        assert fa.error_class == "ConfigError"
        assert "api_token not found" in fa.message
        assert "/proj:todoist-sync" in fa.message

    @respx.mock
    def test_proceeds_when_todoist_yaml_has_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.migrations.integrations.base import Action

        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "todoist.yaml").write_text(
            "api_token: tok-from-todoist\n"
        )
        # Enable flag lives in proj.yaml.
        (fake_home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump({"sync": {"todoist": {"enabled": True}}})
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        root = tmp_path / "demo"
        root.mkdir()
        (root / "todos.yaml").write_text("[]\n")
        project = PendingProject(
            name="demo",
            path=root,
            schema_version_path=root / ".schema-version",
            current_version=1,
        )

        respx.post("https://api.todoist.com/api/v1/sync").mock(
            return_value=Response(200, json={"sync_status": {}})
        )

        actions = [
            Action(
                kind="clear_parent",
                target_id="t-1",
                payload={"parent_id": None},
            ),
        ]
        result = TodoistResync().execute(project, actions)

        assert result.aborted is False
        assert len(result.ok) == 1
        assert result.ok[0].target_id == "t-1"

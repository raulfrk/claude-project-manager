# installer/tests/migrations/test_jira_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.jira import JiraResync, _load_jira_cfg
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_jira(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> PendingProject:
    # Global integration config lives in ~/.claude/proj.yaml — point HOME at tmp.
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump(
            {
                "sync": {
                    "jira": {
                        "enabled": True,
                        "base_url": "https://example.atlassian.net",
                        "email": "u@example.com",
                        "api_token": "tok",
                        "epic_link_field": "customfield_10014",
                    },
                },
            }
        ),
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


def _parent_epic() -> TodoRef:
    return TodoRef(id="1", title="epic", jira_issue_key="CPM-100")


def _parent_story() -> TodoRef:
    return TodoRef(id="1", title="story", jira_issue_key="CPM-50")


def _child_subtask(idx: int) -> TodoRef:
    return TodoRef(
        id=f"1.{idx}", title=f"st {idx}", parent="1", jira_issue_key=f"CPM-{100 + idx}"
    )


def test_plan_under_epic_preserves_epic_link(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1), _child_subtask(2)]
    actions = JiraResync().plan(project_with_jira, migrated)
    assert len(actions) == 2
    assert all(a.payload["epic_link"] == "CPM-100" for a in actions)


@respx.mock
def test_execute_type_conversion(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1)]
    actions = JiraResync().plan(project_with_jira, migrated)
    # PUT /rest/api/3/issue/<key>
    respx.put(
        url__regex=r"https://example\.atlassian\.net/rest/api/3/issue/CPM-101"
    ).mock(
        return_value=Response(204),
    )
    result = JiraResync().execute(project_with_jira, actions)
    assert not result.failed
    assert len(result.ok) == 1


@respx.mock
def test_execute_project_rejects_type_change(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1)]
    actions = JiraResync().plan(project_with_jira, migrated)
    respx.put(url__regex=r".*rest/api/3/issue/CPM-101").mock(
        return_value=Response(400, json={"errorMessages": ["type change not allowed"]}),
    )
    result = JiraResync().execute(project_with_jira, actions)
    assert len(result.failed) == 1
    assert result.failed[0].retryable is False


# ── 661: safe-get + runbook for missing config fields ─────────────────────────


def _actions_stub() -> list:
    """Return a minimal 2-action list — execute must abort before touching network."""
    from installer.migrations.integrations.base import Action

    return [
        Action(
            kind="demote_subtask",
            target_id="CPM-101",
            payload={"new_issue_type": "Story", "epic_link": "CPM-100"},
        ),
        Action(
            kind="demote_subtask",
            target_id="CPM-102",
            payload={"new_issue_type": "Story", "epic_link": "CPM-100"},
        ),
    ]


def _write_proj_yaml(home: Path, jira_cfg: dict | None) -> None:
    body: dict = {"sync": {}}
    if jira_cfg is not None:
        body["sync"]["jira"] = jira_cfg
    (home / ".claude" / "proj.yaml").write_text(yaml.safe_dump(body))


def test_execute_aborts_when_api_token_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    _write_proj_yaml(
        fake_home,
        {
            "enabled": True,
            "base_url": "https://ex.atlassian.net",
            "email": "u@example.com",
            # api_token intentionally missing
        },
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    project = PendingProject(
        name="demo",
        path=tmp_path / "demo",
        schema_version_path=tmp_path / "demo" / ".schema-version",
        current_version=1,
    )
    (tmp_path / "demo").mkdir()

    result = JiraResync().execute(project, _actions_stub())

    assert result.aborted is True
    # Single synthetic FailedAction — not one-per-action spam.
    assert len(result.failed) == 1
    fa = result.failed[0]
    assert fa.error_class == "ConfigError"
    assert "api_token" in fa.message
    assert "/proj:jira-sync" in fa.message


def test_execute_aborts_when_base_url_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    _write_proj_yaml(
        fake_home,
        {
            "enabled": True,
            "email": "u@example.com",
            "api_token": "tok",
            # base_url intentionally missing
        },
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    project = PendingProject(
        name="demo",
        path=tmp_path / "demo",
        schema_version_path=tmp_path / "demo" / ".schema-version",
        current_version=1,
    )
    (tmp_path / "demo").mkdir()

    result = JiraResync().execute(project, _actions_stub())

    assert result.aborted is True
    assert len(result.failed) == 1
    assert result.failed[0].error_class == "ConfigError"
    assert "base_url" in result.failed[0].message


def test_execute_aborts_when_sync_jira_block_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `sync.jira` block at all — must not KeyError on `cfg['sync']['jira']`."""
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "proj.yaml").write_text(yaml.safe_dump({}))
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    project = PendingProject(
        name="demo",
        path=tmp_path / "demo",
        schema_version_path=tmp_path / "demo" / ".schema-version",
        current_version=1,
    )
    (tmp_path / "demo").mkdir()

    result = JiraResync().execute(project, _actions_stub())

    assert result.aborted is True
    assert len(result.failed) == 1
    assert result.failed[0].error_class == "ConfigError"


# ── 662: jira.yaml priority + proj.yaml fallback ──────────────────────────────


class TestLoadJiraCfg:
    """Priority: ~/.claude/jira.yaml → proj.yaml sync.jira → {}."""

    def test_load_from_jira_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "jira.yaml").write_text(
            yaml.safe_dump(
                {
                    "personal_access_token": "tok-from-jira-yaml",
                    "base_url": "https://ex.atlassian.net",
                    "email": "u@ex.com",
                }
            )
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        # proj.yaml sync.jira values should be ignored when jira.yaml wins.
        proj_cfg = {
            "sync": {
                "jira": {
                    "api_token": "tok-from-proj",
                    "base_url": "https://should-be-ignored",
                    "email": "ignored@ex.com",
                }
            }
        }
        cfg = _load_jira_cfg(proj_cfg)
        assert cfg["api_token"] == "tok-from-jira-yaml"
        assert cfg["base_url"] == "https://ex.atlassian.net"
        assert cfg["email"] == "u@ex.com"

    def test_jira_yaml_maps_personal_access_token_to_api_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "jira.yaml").write_text(
            yaml.safe_dump(
                {
                    "personal_access_token": "pat-xyz",
                    "base_url": "https://ex.atlassian.net",
                    "email": "u@ex.com",
                }
            )
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        cfg = _load_jira_cfg({})
        # jira.yaml uses `personal_access_token`; helper normalises to api_token.
        assert cfg.get("api_token") == "pat-xyz"

    def test_fallback_to_proj_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        # No jira.yaml.
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        proj_cfg = {
            "sync": {
                "jira": {
                    "api_token": "tok-from-proj",
                    "base_url": "https://ex.atlassian.net",
                    "email": "u@ex.com",
                    "enabled": True,
                }
            }
        }
        cfg = _load_jira_cfg(proj_cfg)
        assert cfg["api_token"] == "tok-from-proj"
        assert cfg["base_url"] == "https://ex.atlassian.net"
        assert cfg["email"] == "u@ex.com"

    def test_returns_empty_when_both_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        assert _load_jira_cfg({}) == {}
        assert _load_jira_cfg(None) == {}

    def test_yaml_error_falls_back_to_proj_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "jira.yaml").write_text(":::broken\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        proj_cfg = {
            "sync": {
                "jira": {
                    "api_token": "tok-from-proj",
                    "base_url": "https://ex.atlassian.net",
                    "email": "u@ex.com",
                }
            }
        }
        cfg = _load_jira_cfg(proj_cfg)
        assert cfg["api_token"] == "tok-from-proj"


@respx.mock
def test_execute_uses_jira_yaml_token_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: no proj.yaml sync.jira credentials, but jira.yaml has them."""
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump({"sync": {"jira": {"enabled": True}}})
    )
    (fake_home / ".claude" / "jira.yaml").write_text(
        yaml.safe_dump(
            {
                "personal_access_token": "pat-from-yaml",
                "base_url": "https://ex.atlassian.net",
                "email": "u@ex.com",
            }
        )
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    project = PendingProject(
        name="demo",
        path=tmp_path / "demo",
        schema_version_path=tmp_path / "demo" / ".schema-version",
        current_version=1,
    )
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "todos.yaml").write_text("[]\n")

    respx.put(url__regex=r"https://ex\.atlassian\.net/rest/api/3/issue/CPM-101").mock(
        return_value=Response(204)
    )

    result = JiraResync().execute(project, _actions_stub()[:1])

    assert result.aborted is False
    assert len(result.ok) == 1

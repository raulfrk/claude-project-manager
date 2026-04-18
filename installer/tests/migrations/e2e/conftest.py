# installer/tests/migrations/e2e/conftest.py
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def home_with_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake $HOME with 3 projects: cpm (T+R+J), side (T only), legacy (no integrations).

    Uses real-shape file layout:
    - ~/.claude/proj.yaml has tracking_dir + global integration config (sync section)
    - <tracking_dir>/active-projects.yaml has projects: map
    - Per-project dir has .schema-version (absent = v1) + todos.yaml/archive.yaml/data.db
    - Per-project integration "enablement" derived from todos having integration IDs (not
      from a per-project proj.yaml — that file does not exist in real environments).
    """
    home = tmp_path / "home"
    tracking_dir = home / "projects" / "tracking"
    (home / ".claude").mkdir(parents=True)

    cpm_dir = tracking_dir / "cpm"
    side_dir = tracking_dir / "side"
    legacy_dir = tracking_dir / "legacy"
    for d, name, integ in (
        (cpm_dir, "cpm", {"todoist": True, "trello": True, "jira": True}),
        (side_dir, "side", {"todoist": True}),
        (legacy_dir, "legacy", {}),
    ):
        d.mkdir(parents=True)
        # v1: no .schema-version file (absent = version 1)
        # No per-project proj.yaml — integration config lives at global ~/.claude/proj.yaml
        tdata = [
            {
                "id": "1",
                "title": "parent",
                "parent": None,
                "children": ["1.1"],
                "tags": [],
                "todoist_task_id": "p-" + name,
                "trello_card_id": "pc-" + name if integ.get("trello") else None,
                "trello_checklist_id": "cl-" + name if integ.get("trello") else None,
                "jira_issue_key": "J-" + name if integ.get("jira") else None,
            },
            {
                "id": "1.1",
                "title": "child",
                "parent": "1",
                "children": [],
                "tags": [],
                "todoist_task_id": "c-" + name,
                "trello_checklist_item_id": "it-" + name
                if integ.get("trello")
                else None,
                "jira_issue_key": "J2-" + name if integ.get("jira") else None,
            },
        ]
        (d / "todos.yaml").write_text(yaml.safe_dump(tdata))
        (d / "archive.yaml").write_text("[]\n")
        conn = sqlite3.connect(d / "data.db")
        conn.executescript(
            "CREATE TABLE todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);"
            "CREATE TABLE archive_todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);",
        )
        conn.commit()
        conn.close()

    # Global config — tracking_dir + integration auth/enable for all 3 SaaS.
    # Per-project enabled_for() derives actual usage from the project's todo data.
    (home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump(
            {
                "tracking_dir": str(tracking_dir),
                "sync": {
                    "todoist": {"enabled": True, "api_token": "tok"},
                    "trello": {
                        "enabled": True,
                        "api_key": "k",
                        "api_token": "t",
                        "board_id": "b",
                        "list_mappings": {"tasks": "l"},
                    },
                    "jira": {
                        "enabled": True,
                        "base_url": "https://ex.atlassian.net",
                        "email": "e@x.com",
                        "api_token": "tok",
                        "epic_link_field": "customfield_10014",
                    },
                },
            }
        )
    )

    # Registry — real-shape active-projects.yaml
    registry = {
        "projects": {
            "cpm": {"tracking_dir": str(cpm_dir), "archived": False},
            "side": {"tracking_dir": str(side_dir), "archived": False},
            "legacy": {"tracking_dir": str(legacy_dir), "archived": False},
        }
    }
    (tracking_dir / "active-projects.yaml").write_text(yaml.safe_dump(registry))

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    return home

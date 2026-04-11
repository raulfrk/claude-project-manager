"""Shared fixtures for installer tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console


@pytest.fixture()
def mock_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fake HOME with ~/.claude/ structure and patch Path.home()."""
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture()
def mock_subprocess(mocker):
    """Patch subprocess.run and return the mock."""
    return mocker.patch("subprocess.run")


@pytest.fixture()
def mock_console() -> Console:
    """Create a Rich Console that writes to a string buffer."""
    return Console(file=MagicMock(), highlight=False, width=120)


@pytest.fixture()
def marketplace_json(tmp_path: Path) -> Path:
    """Write a minimal marketplace.json and return its path."""
    data = {
        "plugins": [
            {
                "name": "sandbox",
                "description": "Sandbox management",
                "version": "0.2.0",
                "category": "core",
                "keywords": ["sandbox"],
            },
            {
                "name": "router",
                "description": "Central MCP-to-MCP hook registry",
                "version": "0.3.0",
                "category": "core",
                "keywords": ["router", "hooks"],
            },
            {
                "name": "proj",
                "description": "Project management",
                "version": "1.0.0",
                "category": "productivity",
                "keywords": ["project"],
            },
            {
                "name": "worktree",
                "description": "Git worktrees",
                "version": "0.7.0",
                "category": "utilities",
                "keywords": ["git"],
            },
            {
                "name": "trello",
                "description": "Trello integration",
                "version": "0.5.0",
                "category": "integrations",
                "keywords": ["trello"],
            },
        ]
    }
    path = tmp_path / "marketplace.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path

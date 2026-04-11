"""Shared fixtures for installer end-to-end tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from installer.app import InstallerApp
from installer.detect import InstallState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assert_all_visible(
    screen, selector: str = "Widget", *, skip_hidden: bool = True
) -> None:
    """Assert all matching widgets are visible and within viewport.

    Widgets that are intentionally hidden (``display: none``) are skipped
    by default since many screens conditionally hide elements (e.g.,
    warning bars, optional fields).  Pass ``skip_hidden=False`` to enforce
    that *every* widget must be visible.
    """
    for widget in screen.query(selector):
        if widget.id and widget.id.startswith("_"):
            continue  # skip internal widgets
        if skip_hidden and widget.styles.display == "none":
            continue  # intentionally hidden widget
        region = widget.region
        assert region.width > 0, f"{widget!r} has zero width"
        assert region.height > 0, f"{widget!r} has zero height"


# ---------------------------------------------------------------------------
# Full marketplace data (all 9 plugins)
# ---------------------------------------------------------------------------

_ALL_PLUGINS = [
    {
        "name": "sandbox",
        "description": "Manage sandbox-mode settings.json",
        "version": "1.0.0",
        "category": "utilities",
        "keywords": ["sandbox", "permissions"],
    },
    {
        "name": "worktree",
        "description": "Git worktree management",
        "version": "3.0.0",
        "category": "utilities",
        "keywords": ["git", "worktree"],
    },
    {
        "name": "proj",
        "description": "Project lifecycle management",
        "version": "4.0.0",
        "category": "productivity",
        "keywords": ["project", "tracking"],
    },
    {
        "name": "trello",
        "description": "Trello board and card management",
        "version": "3.0.0",
        "category": "integrations",
        "keywords": ["trello", "boards"],
    },
    {
        "name": "jira",
        "description": "Jira issue and project access",
        "version": "3.0.0",
        "category": "integrations",
        "keywords": ["jira", "issues"],
    },
    {
        "name": "router",
        "description": "Central MCP-to-MCP hook registry",
        "version": "2.0.0",
        "category": "utilities",
        "keywords": ["router", "hooks"],
    },
    {
        "name": "zoxide",
        "description": "Zoxide frecency database integration",
        "version": "2.0.0",
        "category": "utilities",
        "keywords": ["zoxide", "frecency"],
    },
    {
        "name": "todoist",
        "description": "Todoist task and project management",
        "version": "2.0.0",
        "category": "integrations",
        "keywords": ["todoist", "tasks"],
    },
    {
        "name": "analyse",
        "description": "Guided code review skill",
        "version": "2.0.0",
        "category": "utilities",
        "keywords": ["analyse", "code-review"],
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_args(**overrides) -> SimpleNamespace:
    """Build a fake args namespace matching the CLI parser output."""
    defaults = {
        "update": False,
        "reinstall": False,
        "uninstall": False,
        "full_cleanup": False,
        "plugins": None,
        "skip_wizard": False,
        "verbose": False,
        "no_tui": False,
        "branch": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


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
def marketplace_json(tmp_path: Path) -> Path:
    """Write a test marketplace.json with all 9 plugins and return its path."""
    data = {"plugins": _ALL_PLUGINS}
    path = tmp_path / "marketplace.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture()
def mock_detect(monkeypatch: pytest.MonkeyPatch) -> InstallState:
    """Mock ``installer.detect.detect_existing`` at both source and import site."""
    state = InstallState(
        installed_plugins=["proj", "router", "sandbox"],
        mcp_entries=[
            "plugin_proj_proj",
            "plugin_router_router",
            "plugin_sandbox_sandbox",
        ],
    )
    monkeypatch.setattr("installer.detect.detect_existing", lambda: state)
    # Also patch the local reference in app.py
    monkeypatch.setattr("installer.app.detect_existing", lambda: state)
    return state


@pytest.fixture()
def mock_plugin_cli(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Monkeypatch all functions in ``installer.plugin_cli`` with reasonable defaults.

    Patches at BOTH ``installer.plugin_cli.<fn>`` and ``installer.app.<fn>``
    because app.py imports functions directly (``from installer.plugin_cli import ...``).
    """
    mocks: dict[str, MagicMock] = {}

    def _patch(name: str, mock: MagicMock) -> None:
        monkeypatch.setattr(f"installer.plugin_cli.{name}", mock)
        # Also patch the local reference in app.py (direct import)
        try:
            monkeypatch.setattr(f"installer.app.{name}", mock)
        except AttributeError:
            pass  # function not imported in app.py
        mocks[name] = mock

    _patch("check_marketplace_registered", MagicMock(return_value=True))
    _patch("add_marketplace", MagicMock(return_value=None))
    _patch("remove_marketplace", MagicMock(return_value=None))
    _patch(
        "get_installed_plugins",
        MagicMock(
            return_value=[
                "proj@claude-project-manager",
                "router@claude-project-manager",
                "sandbox@claude-project-manager",
            ]
        ),
    )
    _patch(
        "get_available_plugins",
        MagicMock(
            return_value=[f"{p['name']}@claude-project-manager" for p in _ALL_PLUGINS]
        ),
    )
    _patch("install_plugin", MagicMock(return_value=None))
    _patch("update_plugin", MagicMock(return_value=None))
    _patch("uninstall_plugin", MagicMock(return_value=None))

    return mocks


@pytest.fixture()
def stub_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub httpx.get / httpx.Client.get / httpx.AsyncClient.get.

    Used by snapshot tests for integration config screens so tests NEVER
    reach a real Todoist/Trello/Jira API. Any call raises ConnectError,
    which would be caught by the screen's validator — but snapshot tests
    trigger error states directly via ``_show_error()``, so this fixture
    just acts as a safety net.
    """

    def _raise(*args, **kwargs):  # noqa: ANN002, ANN003
        raise httpx.ConnectError("stubbed — no network in tests")

    monkeypatch.setattr("httpx.get", _raise)
    monkeypatch.setattr("httpx.Client.get", _raise)
    monkeypatch.setattr("httpx.AsyncClient.get", _raise)


@pytest.fixture()
def e2e_app(
    mock_home: Path,
    marketplace_json: Path,
    mock_subprocess,
    mock_plugin_cli: dict[str, MagicMock],
):
    """Factory fixture that creates an InstallerApp with mocked dependencies."""

    def _factory(mode: str = "install", **kwargs) -> InstallerApp:
        return InstallerApp(mode=mode, args=_mock_args(**kwargs))

    return _factory

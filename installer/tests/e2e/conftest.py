"""Shared fixtures for installer end-to-end tests.

Note: InstallerApp-specific fixtures (e2e_app, mock_detect, mock_plugin_cli,
marketplace_json, mock_subprocess) were deleted in P3 (#672) together with
the InstallerApp class and the Textual pilot behavioral tests. Only fixtures
still used by snapshot tests are retained here.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest


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
# Fixtures
# ---------------------------------------------------------------------------


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

"""Unit tests for sandbox.reconcile.reconcile_settings.

The reconciler syncs ~/.claude/settings.json MCP allow rules with an
expected list of MCP server names. Removes stale entries (mcp__*__* rules
not in expected) and adds missing ones. Atomic write — partial state
should never reach disk.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _settings_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def _write_settings(path: Path, allow: list[str]) -> None:
    path.write_text(json.dumps({"permissions": {"allow": allow}}, indent=2))


def _read_allow(path: Path) -> list[str]:
    return list(json.loads(path.read_text())["permissions"]["allow"])


@pytest.fixture()
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SETTINGS_PATH into tmp_path."""
    from sandbox import storage

    target = _settings_path(tmp_path)
    monkeypatch.setattr(storage, "SETTINGS_PATH", target)
    return target


class TestReconcileSettings:
    def test_empty_settings_adds_all_expected(self, isolated_settings: Path) -> None:
        from sandbox.reconcile import reconcile_settings

        result = reconcile_settings(
            expected_servers=["plugin_proj_proj", "plugin_wiki_wiki"],
        )

        assert result.added == 2
        assert result.removed == 0
        on_disk = _read_allow(isolated_settings)
        assert "mcp__plugin_proj_proj__*" in on_disk
        assert "mcp__plugin_wiki_wiki__*" in on_disk

    def test_existing_stale_removed(self, isolated_settings: Path) -> None:
        from sandbox.reconcile import reconcile_settings

        _write_settings(
            isolated_settings,
            allow=[
                "mcp__plugin_old__*",
                "mcp__plugin_sandbox_sandbox__*",
                "mcp__plugin_proj_proj__*",
            ],
        )

        result = reconcile_settings(expected_servers=["plugin_proj_proj"])

        assert result.removed == 2
        assert sorted(result.stale_removed) == sorted(["plugin_old", "plugin_sandbox_sandbox"])
        on_disk = _read_allow(isolated_settings)
        assert "mcp__plugin_old__*" not in on_disk
        assert "mcp__plugin_sandbox_sandbox__*" not in on_disk
        assert "mcp__plugin_proj_proj__*" in on_disk

    def test_existing_correct_is_noop(self, isolated_settings: Path) -> None:
        from sandbox.reconcile import reconcile_settings

        _write_settings(
            isolated_settings,
            allow=["mcp__plugin_proj_proj__*", "mcp__plugin_wiki_wiki__*"],
        )

        result = reconcile_settings(
            expected_servers=["plugin_proj_proj", "plugin_wiki_wiki"],
        )

        assert result.added == 0
        assert result.removed == 0
        on_disk = sorted(_read_allow(isolated_settings))
        assert on_disk == sorted(["mcp__plugin_proj_proj__*", "mcp__plugin_wiki_wiki__*"])

    def test_idempotent(self, isolated_settings: Path) -> None:
        from sandbox.reconcile import reconcile_settings

        first = reconcile_settings(expected_servers=["plugin_proj_proj"])
        second = reconcile_settings(expected_servers=["plugin_proj_proj"])

        assert first.added == 1 and first.removed == 0
        assert second.added == 0 and second.removed == 0

    def test_atomic_write_failure_leaves_settings_unchanged(self, isolated_settings: Path) -> None:
        """If save() fails mid-write, original settings.json must be intact."""
        from sandbox import storage
        from sandbox.reconcile import reconcile_settings

        _write_settings(isolated_settings, allow=["mcp__plugin_proj_proj__*"])
        original = isolated_settings.read_text()

        with (
            patch.object(storage, "save", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            reconcile_settings(expected_servers=["plugin_wiki_wiki"])

        assert isolated_settings.read_text() == original

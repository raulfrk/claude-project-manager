"""Tests for zoxide integration helpers and wiring."""

from __future__ import annotations

from unittest.mock import patch, call

import pytest

from server.lib.models import ProjConfig, ProjectMeta, RepoEntry
from server.lib.zoxide import resolve_enabled, zoxide_boost, zoxide_remove


class TestResolveEnabled:
    """Test resolve_enabled() with global/per-project flag resolution."""

    def test_global_false_meta_none(self) -> None:
        cfg = ProjConfig(zoxide_integration=False)
        meta = ProjectMeta(name="test", zoxide_integration=None)
        assert resolve_enabled(cfg, meta) is False

    def test_global_true_meta_none(self) -> None:
        cfg = ProjConfig(zoxide_integration=True)
        meta = ProjectMeta(name="test", zoxide_integration=None)
        assert resolve_enabled(cfg, meta) is True

    def test_meta_overrides_global_true(self) -> None:
        cfg = ProjConfig(zoxide_integration=True)
        meta = ProjectMeta(name="test", zoxide_integration=False)
        assert resolve_enabled(cfg, meta) is False

    def test_meta_overrides_global_false(self) -> None:
        cfg = ProjConfig(zoxide_integration=False)
        meta = ProjectMeta(name="test", zoxide_integration=True)
        assert resolve_enabled(cfg, meta) is True


class TestZoxideBoost:
    """Test zoxide_boost() subprocess calls."""

    @patch("server.lib.zoxide.subprocess.run")
    def test_calls_zoxide_add_n_times(self, mock_run: object) -> None:
        zoxide_boost("/some/path", times=3)
        assert mock_run.call_count == 3  # type: ignore[union-attr]
        mock_run.assert_called_with(["zoxide", "add", "/some/path"], check=False)  # type: ignore[union-attr]

    @patch("server.lib.zoxide.subprocess.run")
    def test_default_10_times(self, mock_run: object) -> None:
        zoxide_boost("/some/path")
        assert mock_run.call_count == 10  # type: ignore[union-attr]

    @patch("server.lib.zoxide.subprocess.run", side_effect=FileNotFoundError)
    def test_skips_silently_when_not_installed(self, mock_run: object) -> None:
        # Should not raise
        zoxide_boost("/some/path", times=5)
        # Only called once — first call raises, then returns early
        assert mock_run.call_count == 1  # type: ignore[union-attr]


class TestZoxideRemove:
    """Test zoxide_remove() subprocess calls."""

    @patch("server.lib.zoxide.subprocess.run")
    def test_calls_zoxide_remove(self, mock_run: object) -> None:
        zoxide_remove("/some/path")
        mock_run.assert_called_once_with(["zoxide", "remove", "/some/path"], check=False)  # type: ignore[union-attr]

    @patch("server.lib.zoxide.subprocess.run", side_effect=FileNotFoundError)
    def test_skips_silently_when_not_installed(self, mock_run: object) -> None:
        # Should not raise
        zoxide_remove("/some/path")


class TestZoxideModelRoundTrip:
    """Test that zoxide_integration fields serialize/deserialize correctly."""

    def test_proj_config_roundtrip(self) -> None:
        cfg = ProjConfig(zoxide_integration=True)
        d = cfg.to_dict()
        assert d["zoxide_integration"] is True
        restored = ProjConfig.from_dict(d)
        assert restored.zoxide_integration is True

    def test_proj_config_default_false(self) -> None:
        cfg = ProjConfig()
        assert cfg.zoxide_integration is False

    def test_proj_config_from_dict_missing_key(self) -> None:
        cfg = ProjConfig.from_dict({})
        assert cfg.zoxide_integration is False

    def test_project_meta_roundtrip_none(self) -> None:
        meta = ProjectMeta(name="test")
        d = meta.to_dict()
        assert d["zoxide_integration"] is None
        restored = ProjectMeta.from_dict(d)
        assert restored.zoxide_integration is None

    def test_project_meta_roundtrip_true(self) -> None:
        meta = ProjectMeta(name="test", zoxide_integration=True)
        d = meta.to_dict()
        assert d["zoxide_integration"] is True
        restored = ProjectMeta.from_dict(d)
        assert restored.zoxide_integration is True

    def test_project_meta_roundtrip_false(self) -> None:
        meta = ProjectMeta(name="test", zoxide_integration=False)
        d = meta.to_dict()
        assert d["zoxide_integration"] is False
        restored = ProjectMeta.from_dict(d)
        # Note: False is falsy, so from_dict with walrus operator returns None
        # This is the same behavior as claudemd_management
        # bool(False) if False is not None else None → but False is not None is True → bool(False) = False
        assert restored.zoxide_integration is False

    def test_project_meta_from_dict_missing_key(self) -> None:
        meta = ProjectMeta.from_dict({"name": "test"})
        assert meta.zoxide_integration is None

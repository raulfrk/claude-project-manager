"""Tests for schema_version.require_flat and LegacyProjectError."""

import pytest

from server.lib import schema_version
from server.lib.models import ProjConfig
from server.lib.schema_version import LegacyProjectError


def test_require_flat_raises_for_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / ".schema-version").write_text("1\n")
    with pytest.raises(LegacyProjectError, match="cpm-install --migrate"):
        schema_version.require_flat(cfg, "demo")


def test_require_flat_passes_for_v2(tmp_path):
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / ".schema-version").write_text("2\n")
    schema_version.require_flat(cfg, "demo")  # no raise


def test_require_flat_passes_when_schema_version_file_absent(tmp_path):
    """Missing .schema-version is treated as a new project — allowed through."""
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    # No .schema-version file
    schema_version.require_flat(cfg, "demo")  # no raise

"""Tests for schema_version.require_current and LegacyProjectError (v3 target)."""

import pytest

from server.lib import schema_version
from server.lib.models import ProjConfig
from server.lib.schema_version import LegacyProjectError


def test_require_current_raises_for_v2(tmp_path):
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / ".schema-version").write_text("2\n")
    with pytest.raises(LegacyProjectError, match="cpm-install --migrate"):
        schema_version.require_current(cfg, "demo")


def test_require_current_passes_for_v3(tmp_path):
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / ".schema-version").write_text("3\n")
    schema_version.require_current(cfg, "demo")  # no raise


def test_require_current_passes_when_schema_version_file_absent(tmp_path):
    """Missing .schema-version is treated as a new project — allowed through."""
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    # No .schema-version file
    schema_version.require_current(cfg, "demo")  # no raise

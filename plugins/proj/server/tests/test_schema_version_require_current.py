"""Tests for schema_version.require_current and LegacyProjectError (v3 target)."""

import pytest

from server.lib import schema_version
from server.lib.models import ProjConfig
from server.lib.schema_version import LegacyProjectError


def test_require_current_raises_for_v2(tmp_path):
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / "proj.yaml").write_text("name: demo\nschema_version: 2\n")
    with pytest.raises(LegacyProjectError, match="cpm-install --migrate"):
        schema_version.require_current(cfg, "demo")


def test_require_current_passes_for_v3(tmp_path):
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / "proj.yaml").write_text("name: demo\nschema_version: 3\n")
    schema_version.require_current(cfg, "demo")  # no raise

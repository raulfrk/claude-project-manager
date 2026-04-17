"""Tests for schema_version.require_flat and LegacyProjectError."""

from server.lib import schema_version
from server.lib.models import ProjConfig
from server.lib.schema_version import LegacyProjectError


def test_require_flat_raises_for_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / "proj.yaml").write_text("name: demo\n")  # no schema_version
    import pytest

    with pytest.raises(LegacyProjectError, match="cpm-install --migrate-flat"):
        schema_version.require_flat(cfg, "demo")


def test_require_flat_passes_for_v2(tmp_path):
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / "proj.yaml").write_text("name: demo\nschema_version: 2\n")
    schema_version.require_flat(cfg, "demo")  # no raise

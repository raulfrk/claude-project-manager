from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib import schema_version


@pytest.fixture
def fake_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Minimal ProjConfig shim with a tracking_dir pointing at tmp_path."""
    from server.lib.models import ProjConfig

    # NOTE: adjust ProjConfig args to the real constructor signature.
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    return cfg


def _write_proj_yaml(tracking_dir: Path, project: str, data: dict) -> None:
    proj_dir = tracking_dir / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "proj.yaml").write_text(yaml.safe_dump(data))


def test_target_constant_is_2():
    assert schema_version.TARGET == 2


def test_current_returns_1_when_field_absent(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"name": "demo"})
    assert schema_version.current(fake_cfg, "demo") == 1


def test_current_returns_int_value(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"name": "demo", "schema_version": 2})
    assert schema_version.current(fake_cfg, "demo") == 2


def test_current_returns_1_when_proj_yaml_missing(fake_cfg):
    assert schema_version.current(fake_cfg, "nope") == 1


def test_current_returns_1_when_field_malformed(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": "not-a-number"})
    assert schema_version.current(fake_cfg, "demo") == 1


def test_current_returns_1_when_yaml_corrupted(fake_cfg, tmp_path):
    proj_dir = tmp_path / "demo"
    proj_dir.mkdir()
    (proj_dir / "proj.yaml").write_text("not: [valid")
    assert schema_version.current(fake_cfg, "demo") == 1


def test_flat_only_false_when_below_target(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 1})
    assert schema_version.flat_only(fake_cfg, "demo") is False


def test_flat_only_true_when_at_target(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 2})
    assert schema_version.flat_only(fake_cfg, "demo") is True


def test_flat_only_true_when_above_target(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 99})
    assert schema_version.flat_only(fake_cfg, "demo") is True


def test_no_caching_between_calls(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 1})
    assert schema_version.flat_only(fake_cfg, "demo") is False
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 2})
    # Second call must pick up the new value — no cache.
    assert schema_version.flat_only(fake_cfg, "demo") is True

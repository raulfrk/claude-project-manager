from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import schema_version


@pytest.fixture
def fake_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Minimal ProjConfig shim with a tracking_dir pointing at tmp_path."""
    from server.lib.models import ProjConfig

    # NOTE: adjust ProjConfig args to the real constructor signature.
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    return cfg


def _write_schema_version(tracking_dir: Path, project: str, version: int) -> None:
    proj_dir = tracking_dir / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / ".schema-version").write_text(f"{version}\n")


def test_target_constant_is_3():
    assert schema_version.TARGET == 3


def test_current_returns_1_when_file_missing(fake_cfg):
    assert schema_version.current(fake_cfg, "nope") == 1


def test_current_returns_int_value(fake_cfg, tmp_path):
    _write_schema_version(tmp_path, "demo", 2)
    assert schema_version.current(fake_cfg, "demo") == 2


def test_current_returns_1_when_field_malformed(fake_cfg, tmp_path):
    proj_dir = tmp_path / "demo"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / ".schema-version").write_text("not-a-number\n")
    assert schema_version.current(fake_cfg, "demo") == 1


def test_flat_only_false_when_below_target(fake_cfg, tmp_path):
    # flat_only now checks >= TARGET (3); v1 and v2 are both below
    _write_schema_version(tmp_path, "demo", 1)
    assert schema_version.flat_only(fake_cfg, "demo") is False


def test_flat_only_false_when_at_v2(fake_cfg, tmp_path):
    # v2 is below TARGET=3
    _write_schema_version(tmp_path, "demo", 2)
    assert schema_version.flat_only(fake_cfg, "demo") is False


def test_flat_only_true_when_at_target(fake_cfg, tmp_path):
    _write_schema_version(tmp_path, "demo", 3)
    assert schema_version.flat_only(fake_cfg, "demo") is True


def test_flat_only_true_when_above_target(fake_cfg, tmp_path):
    _write_schema_version(tmp_path, "demo", 99)
    assert schema_version.flat_only(fake_cfg, "demo") is True


def test_no_caching_between_calls(fake_cfg, tmp_path):
    _write_schema_version(tmp_path, "demo", 2)
    assert schema_version.flat_only(fake_cfg, "demo") is False
    _write_schema_version(tmp_path, "demo", 3)
    # Second call must pick up the new value — no cache.
    assert schema_version.flat_only(fake_cfg, "demo") is True


def test_current_expands_tilde_in_tracking_dir(tmp_path, monkeypatch):
    # Regression guard: tracking_dir may contain ~ (e.g. ~/projects/tracking).
    # Path() alone does NOT expand it — must call .expanduser().
    from server.lib.models import ProjConfig

    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ProjConfig(tracking_dir="~/tracking")
    _write_schema_version(tmp_path / "tracking", "demo", 2)
    assert schema_version.current(cfg, "demo") == 2


def test_bump_schema_version_writes_file(tmp_path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    schema_version.bump_schema_version(proj_dir, 2)
    assert (proj_dir / ".schema-version").read_text().strip() == "2"


def test_bump_schema_version_overwrites(tmp_path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    schema_version.bump_schema_version(proj_dir, 2)
    schema_version.bump_schema_version(proj_dir, 3)
    assert (proj_dir / ".schema-version").read_text().strip() == "3"

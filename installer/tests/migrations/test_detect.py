from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import (
    bump_schema_version,
    discover_pending,
    read_schema_version,
)


def write_proj_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def test_read_schema_version_missing_field_returns_1(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    write_proj_yaml(p, {"name": "x"})
    assert read_schema_version(p) == 1


def test_read_schema_version_reads_int(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    write_proj_yaml(p, {"name": "x", "schema_version": 2})
    assert read_schema_version(p) == 2


def test_read_schema_version_corrupted_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    p.write_text("not: [valid: yaml")
    assert read_schema_version(p) is None


def test_read_schema_version_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_schema_version(tmp_path / "nope.yaml") is None


def test_discover_pending_yields_legacy_projects(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    current_dir = tmp_path / "current"
    future_dir = tmp_path / "future"
    write_proj_yaml(legacy_dir / "proj.yaml", {"name": "legacy"})
    write_proj_yaml(current_dir / "proj.yaml", {"name": "current", "schema_version": 2})
    write_proj_yaml(future_dir / "proj.yaml", {"name": "future", "schema_version": 9})

    projects = [
        {"name": "legacy", "path": str(legacy_dir)},
        {"name": "current", "path": str(current_dir)},
        {"name": "future", "path": str(future_dir)},
    ]

    result = list(discover_pending(projects))
    assert len(result) == 1
    assert result[0].name == "legacy"
    assert result[0].current_version == 1


def test_discover_pending_skips_corrupted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad_dir = tmp_path / "bad"
    (bad_dir).mkdir()
    (bad_dir / "proj.yaml").write_text("not: [valid")

    projects = [{"name": "bad", "path": str(bad_dir)}]
    result = list(discover_pending(projects))
    assert result == []
    assert any("proj.yaml unreadable" in r.message for r in caplog.records)


def test_bump_schema_version_writes_atomically(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    write_proj_yaml(p, {"name": "x"})
    bump_schema_version(p, 2)
    data = yaml.safe_load(p.read_text())
    assert data["schema_version"] == 2
    assert data["name"] == "x"  # other keys preserved

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
    v1_dir = tmp_path / "v1proj"
    v2_dir = tmp_path / "v2proj"
    v3_dir = tmp_path / "v3proj"
    write_proj_yaml(v1_dir / "proj.yaml", {"name": "v1proj"})
    write_proj_yaml(v2_dir / "proj.yaml", {"name": "v2proj", "schema_version": 2})
    write_proj_yaml(v3_dir / "proj.yaml", {"name": "v3proj", "schema_version": 3})

    projects = [
        {"name": "v1proj", "path": str(v1_dir)},
        {"name": "v2proj", "path": str(v2_dir)},
        {"name": "v3proj", "path": str(v3_dir)},
    ]

    result = list(discover_pending(projects))
    # Both v1 and v2 are pending (TARGET is now 3); v3 is current
    assert len(result) == 2
    names = {r.name for r in result}
    assert "v1proj" in names
    assert "v2proj" in names
    assert "v3proj" not in names


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

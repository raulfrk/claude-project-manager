from __future__ import annotations

from pathlib import Path

import pytest

from installer.migrations.detect import (
    bump_schema_version,
    discover_pending,
    read_schema_version,
)


def test_read_schema_version_returns_1_when_file_absent(tmp_path: Path) -> None:
    assert read_schema_version(tmp_path / ".schema-version") == 1


def test_read_schema_version_reads_int(tmp_path: Path) -> None:
    p = tmp_path / ".schema-version"
    p.write_text("2\n")
    assert read_schema_version(p) == 2


def test_read_schema_version_malformed_returns_none(tmp_path: Path) -> None:
    p = tmp_path / ".schema-version"
    p.write_text("not-a-number\n")
    assert read_schema_version(p) is None


def test_discover_pending_yields_legacy_projects(tmp_path: Path) -> None:
    v1_dir = tmp_path / "v1proj"
    v2_dir = tmp_path / "v2proj"
    v3_dir = tmp_path / "v3proj"
    v1_dir.mkdir()
    v2_dir.mkdir()
    v3_dir.mkdir()
    # v1: no .schema-version file → treated as v1
    # v2: .schema-version = 2
    (v2_dir / ".schema-version").write_text("2\n")
    # v3: .schema-version = 3
    (v3_dir / ".schema-version").write_text("3\n")

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


def test_discover_pending_skips_malformed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / ".schema-version").write_text("not-a-number\n")

    projects = [{"name": "bad", "path": str(bad_dir)}]
    result = list(discover_pending(projects))
    assert result == []
    assert any(".schema-version unreadable" in r.message for r in caplog.records)


def test_bump_schema_version_writes_atomically(tmp_path: Path) -> None:
    bump_schema_version(tmp_path, 2)
    assert (tmp_path / ".schema-version").read_text().strip() == "2"


def test_bump_schema_version_overwrites(tmp_path: Path) -> None:
    bump_schema_version(tmp_path, 2)
    bump_schema_version(tmp_path, 3)
    assert (tmp_path / ".schema-version").read_text().strip() == "3"


def test_discover_pending_sets_schema_version_path(tmp_path: Path) -> None:
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    (proj_dir / ".schema-version").write_text("1\n")
    projects = [{"name": "myproj", "path": str(proj_dir)}]
    result = list(discover_pending(projects))
    assert len(result) == 1
    assert result[0].schema_version_path == proj_dir / ".schema-version"

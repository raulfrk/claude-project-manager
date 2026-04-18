# installer/tests/migrations/test_backup.py
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from installer.migrations.backup import BackupSnapshot, VerificationError


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_db(path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()


@pytest.fixture
def src_project(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    root.mkdir()
    (root / "todos.yaml").write_text("- id: '1'\n  title: hi\n")
    (root / "archive.yaml").write_text("[]\n")
    (root / "meta.yaml").write_text("name: x\n")
    _make_db(root / "data.db")
    return root


def test_create_writes_all_artifacts(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create(
        "demo", "2026-04-16T12-00-00", src_project, backup_root
    )
    assert (snap.dir / "todos.yaml").exists()
    assert (snap.dir / "archive.yaml").exists()
    assert (snap.dir / "meta.yaml").exists()
    assert (snap.dir / "data.db").exists()
    manifest = json.loads((snap.dir / "manifest.json").read_text())
    assert manifest["project"] == "demo"
    assert manifest["run_ts"] == "2026-04-16T12-00-00"
    for name, digest in manifest["checksums"].items():
        assert digest == _sha256(snap.dir / name)


def test_create_is_atomic_no_tmp_dir_left(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    BackupSnapshot.create("demo", "ts", src_project, backup_root)
    leftover = list(backup_root.glob("*.tmp"))
    assert leftover == []


def test_restore_overwrites_source(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", src_project, backup_root)
    # mutate source after backup
    (src_project / "todos.yaml").write_text("- id: '2'\n  title: changed\n")
    snap.restore()
    assert (src_project / "todos.yaml").read_text() == "- id: '1'\n  title: hi\n"


def test_restore_rejects_tampered_manifest(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", src_project, backup_root)
    # tamper: flip one byte in todos.yaml inside backup
    (snap.dir / "todos.yaml").write_text("tampered\n")
    with pytest.raises(VerificationError):
        snap.restore()


def test_create_handles_missing_optional_files(tmp_path: Path) -> None:
    # archive.yaml is optional; data.db is optional (git_enabled=false)
    root = tmp_path / "src"
    root.mkdir()
    (root / "todos.yaml").write_text("[]\n")
    (root / "meta.yaml").write_text("name: x\n")
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", root, backup_root)
    assert (snap.dir / "todos.yaml").exists()
    assert not (snap.dir / "archive.yaml").exists()
    assert not (snap.dir / "data.db").exists()
    manifest = json.loads((snap.dir / "manifest.json").read_text())
    assert "archive.yaml" not in manifest["checksums"]


def test_create_includes_decisions_yaml_when_present(
    src_project: Path, tmp_path: Path
) -> None:
    """decisions.yaml is included in backup when it exists."""
    (src_project / "decisions.yaml").write_text("[]\n")
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", src_project, backup_root)
    assert (snap.dir / "decisions.yaml").exists()
    manifest = json.loads((snap.dir / "manifest.json").read_text())
    assert "decisions.yaml" in manifest["checksums"]


def test_create_skips_decisions_yaml_when_absent(
    src_project: Path, tmp_path: Path
) -> None:
    """decisions.yaml is not required; backup succeeds when it's missing."""
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", src_project, backup_root)
    assert not (snap.dir / "decisions.yaml").exists()
    manifest = json.loads((snap.dir / "manifest.json").read_text())
    assert "decisions.yaml" not in manifest["checksums"]

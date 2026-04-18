# installer/migrations/backup.py
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


class VerificationError(RuntimeError):
    """Raised when a backup's manifest checksums don't match its files."""


OPTIONAL_FILES = (
    "archive.yaml",
    "data.db",
    "decisions.yaml",
    "meta.yaml",
    ".schema-version",
)
REQUIRED_FILES = ("todos.yaml",)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _checkpoint_wal(db_path: Path) -> None:
    """Flush WAL to main .db file so the file copy is point-in-time consistent."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except sqlite3.Error as e:
        log.warning("WAL checkpoint failed for %s: %s", db_path, e)


@dataclass
class BackupSnapshot:
    project: str
    run_ts: str
    source_dir: Path
    dir: Path
    checksums: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        project: str,
        run_ts: str,
        source_dir: Path,
        backup_root: Path,
    ) -> BackupSnapshot:
        """Snapshot source_dir into backup_root/<run_ts>/<project>/ atomically."""
        final_dir = backup_root / run_ts / project
        tmp_dir = backup_root / run_ts / f"{project}.tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        snap = cls(
            project=project,
            run_ts=run_ts,
            source_dir=source_dir,
            dir=final_dir,
        )

        try:
            for name in REQUIRED_FILES:
                src = source_dir / name
                if not src.exists():
                    raise FileNotFoundError(f"required file missing: {src}")
                shutil.copy2(src, tmp_dir / name)
                snap.checksums[name] = _sha256(tmp_dir / name)

            for name in OPTIONAL_FILES:
                src = source_dir / name
                if not src.exists():
                    continue
                if name == "data.db":
                    _checkpoint_wal(src)
                shutil.copy2(src, tmp_dir / name)
                snap.checksums[name] = _sha256(tmp_dir / name)

            manifest = {
                "project": project,
                "run_ts": run_ts,
                "source_dir": str(source_dir),
                "checksums": dict(snap.checksums),
            }
            (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
            # manifest excluded from its own checksum map
            os.replace(tmp_dir, final_dir)
            snap.dir = final_dir
            return snap
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def verify(self) -> None:
        """Raise VerificationError if any file's digest mismatches the manifest."""
        manifest = json.loads((self.dir / "manifest.json").read_text())
        for name, expected in manifest["checksums"].items():
            actual = _sha256(self.dir / name)
            if actual != expected:
                raise VerificationError(
                    f"checksum mismatch for {name}: expected {expected}, got {actual}",
                )

    def restore(self) -> None:
        """Copy backup files back over source_dir after verify()."""
        self.verify()
        manifest = json.loads((self.dir / "manifest.json").read_text())
        for name in manifest["checksums"]:
            shutil.copy2(self.dir / name, self.source_dir / name)

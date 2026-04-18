from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.lib.models import ProjConfig

log = logging.getLogger(__name__)

TARGET = 3
SCHEMA_VERSION_FILE = ".schema-version"


def _schema_version_path(cfg: ProjConfig, project_name: str) -> Path:
    return Path(cfg.tracking_dir).expanduser() / project_name / SCHEMA_VERSION_FILE


def current(cfg: ProjConfig, project_name: str) -> int:
    """Return the per-project schema_version. File absent / unreadable → 1."""
    path = _schema_version_path(cfg, project_name)
    try:
        raw = path.read_text().strip()
    except (FileNotFoundError, OSError):
        return 1
    try:
        return int(raw)
    except (TypeError, ValueError):
        log.warning("%s contains malformed value %r; treating as 1", path, raw)
        return 1


def bump_schema_version(project_dir: Path, version: int) -> None:
    """Write the schema_version file atomically (temp+rename)."""
    path = project_dir / SCHEMA_VERSION_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{version}\n")
    tmp.replace(path)


def flat_only(cfg: ProjConfig, project_name: str) -> bool:
    return current(cfg, project_name) >= TARGET


def _schema_version_file_exists(cfg: ProjConfig, project_name: str) -> bool:
    """Return True if the project's .schema-version file exists on disk."""
    return _schema_version_path(cfg, project_name).exists()


class LegacyProjectError(RuntimeError):
    """Raised when a project is still on the nested (pre-flat-model) schema."""


def require_flat(cfg: ProjConfig, project_name: str) -> None:
    """Raise LegacyProjectError when a project has an explicit legacy schema.

    Only raises when .schema-version EXISTS and reports schema_version < 2.
    Missing .schema-version is treated as a new (not yet initialized) project
    and allowed through — storage will raise FileNotFoundError on data.db absence.
    """
    if not _schema_version_file_exists(cfg, project_name):
        return
    v = current(cfg, project_name)
    if v < 2:
        raise LegacyProjectError(
            f"Project {project_name!r} is still on the nested todo schema "
            f"(schema_version={v}). Run `cpm-install --migrate` "
            f"to upgrade this project before using todo tools.",
        )


def require_current(cfg: ProjConfig, project_name: str) -> None:
    """Raise LegacyProjectError when a project is not at schema_version=TARGET (3).

    Only raises when .schema-version EXISTS and reports schema_version < TARGET.
    Missing .schema-version is treated as a new (not yet initialized) project
    and allowed through — storage will raise FileNotFoundError on data.db absence.
    """
    if not _schema_version_file_exists(cfg, project_name):
        return
    v = current(cfg, project_name)
    if v < TARGET:
        raise LegacyProjectError(
            f"Project {project_name!r} is on schema_version={v} "
            f"(target is {TARGET}). Run `cpm-install --migrate` "
            f"to upgrade this project before using todo tools.",
        )

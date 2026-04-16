from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from server.lib.models import ProjConfig

log = logging.getLogger(__name__)

TARGET = 2


def current(cfg: ProjConfig, project_name: str) -> int:
    """Return the per-project schema_version. Missing / unreadable → 1.

    Reads `proj.yaml` directly rather than going through the SQL-backed
    meta loader because `schema_version` is the migration gate that the
    installer wizard writes before any other storage operations succeed
    for migrated projects. Keeping it out of SQL also avoids needing a
    SQL schema migration for this one field.
    """
    path = Path(cfg.tracking_dir).expanduser() / project_name / "proj.yaml"
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return 1
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        log.warning("proj.yaml for %s is corrupted; treating as schema_version=1", project_name)
        return 1
    if not isinstance(data, dict):
        log.warning(
            "proj.yaml for %s has non-dict root; treating as schema_version=1",
            project_name,
        )
        return 1
    v = data.get("schema_version")
    if v is None:
        return 1
    try:
        return int(v)
    except (TypeError, ValueError):
        log.warning(
            "proj.yaml for %s has malformed schema_version=%r; treating as 1",
            project_name,
            v,
        )
        return 1


def flat_only(cfg: ProjConfig, project_name: str) -> bool:
    return current(cfg, project_name) >= TARGET

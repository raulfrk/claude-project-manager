from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import yaml

from installer.migrations.types import TARGET_SCHEMA_VERSION, PendingProject

log = logging.getLogger(__name__)


def read_schema_version(proj_yaml_path: Path) -> int | None:
    """Return schema_version (1 when absent), or None when unreadable."""
    try:
        raw = proj_yaml_path.read_text()
    except FileNotFoundError:
        return None
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("schema_version")
    if v is None:
        return 1
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def bump_schema_version(proj_yaml_path: Path, version: int) -> None:
    """Merge schema_version into proj.yaml atomically (temp+rename).

    Cleans up the temp file on any failure between creation and rename so
    a permission error on os.replace doesn't leak `.proj.yaml.*.tmp` files
    into the project directory across migration runs.
    """
    data: dict = yaml.safe_load(proj_yaml_path.read_text()) or {}
    data["schema_version"] = version
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=proj_yaml_path.parent,
        prefix=".proj.yaml.",
        suffix=".tmp",
        delete=False,
    )
    tmp_name = tmp.name
    try:
        try:
            yaml.safe_dump(data, tmp, sort_keys=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.replace(tmp_name, proj_yaml_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def discover_pending(projects: Iterable[dict]) -> Iterator[PendingProject]:
    """Yield PendingProject entries for projects with schema_version < target."""
    for entry in projects:
        name = entry["name"]
        proj_path = Path(entry["path"])
        proj_yaml = proj_path / "proj.yaml"
        v = read_schema_version(proj_yaml)
        if v is None:
            log.warning("proj.yaml unreadable for %s, skipping migration detect", name)
            continue
        if v >= TARGET_SCHEMA_VERSION:
            continue
        yield PendingProject(
            name=name,
            path=proj_path,
            proj_yaml_path=proj_yaml,
            current_version=v,
        )


def detect_already_flat(todos_yaml_path: Path) -> bool:
    """Return True when no todo has a non-null `parent` field."""
    try:
        data = yaml.safe_load(todos_yaml_path.read_text()) or []
    except (FileNotFoundError, yaml.YAMLError):
        return False
    if not isinstance(data, list):
        return False
    # Require every entry to be a dict — a non-dict element is ambiguous and
    # should not be treated as "flat" (would otherwise raise AttributeError).
    return all(
        isinstance(t, dict) and t.get("parent") is None and not t.get("children")
        for t in data
    )

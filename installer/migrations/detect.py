from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from pathlib import Path

from installer.migrations.types import TARGET_SCHEMA_VERSION, PendingProject

log = logging.getLogger(__name__)

SCHEMA_VERSION_FILE = ".schema-version"


def read_schema_version(path: Path) -> int | None:
    """Return schema_version from a .schema-version file, or None when unreadable.

    `path` is the file itself (not a directory).
    Returns 1 when file is absent (legacy default).
    Returns None when file is present but unreadable/malformed.
    """
    try:
        raw = path.read_text().strip()
    except FileNotFoundError:
        return 1
    except OSError:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def bump_schema_version(project_dir: Path, version: int) -> None:
    """Write the schema_version file atomically (temp+rename).

    `project_dir` is the project directory; writes <project_dir>/.schema-version.
    """
    path = project_dir / SCHEMA_VERSION_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{version}\n")
    tmp.replace(path)


def discover_pending(projects: Iterable[dict]) -> Iterator[PendingProject]:
    """Yield PendingProject entries for projects with schema_version < target."""
    for entry in projects:
        name = entry["name"]
        proj_path = Path(entry["path"])
        schema_version_file = proj_path / SCHEMA_VERSION_FILE
        v = read_schema_version(schema_version_file)
        if v is None:
            log.warning(
                ".schema-version unreadable for %s, skipping migration detect", name
            )
            continue
        if v >= TARGET_SCHEMA_VERSION:
            continue
        yield PendingProject(
            name=name,
            path=proj_path,
            schema_version_path=schema_version_file,
            current_version=v,
        )


def detect_already_flat(todos_yaml_path: Path) -> bool:
    """Return True when no todo has a non-null `parent` field."""
    import yaml

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

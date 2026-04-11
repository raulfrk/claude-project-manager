"""Per-bucket wizard-answer writer with advisory locking and TOCTOU guard.

Contract:
- partition_answers_by_bucket: explicit dotted_key → yaml_file mapping via
  PROJ_YAML_PROMPTS. Answers whose dotted_key is not in any spec go to "proj"
  (conservative default for legacy keys).
- write_bucket: atomic tmp+rename with fcntl.flock(LOCK_EX | NB) advisory lock,
  mtime re-check after lock acquisition. Logs a WARNING if the file was
  modified by another process between the wizard's read and this write.
- _NORMALIZERS: optional per-bucket post-merge hooks (e.g. ProjConfig round
  trip). A normalizer that raises falls through — the raw merged dict is
  written, and a WARNING is logged.
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml

from installer.wizard_specs import PROJ_YAML_PROMPTS, get_distinct_yaml_files

_log = logging.getLogger("installer.config_writer")


def partition_answers_by_bucket(
    answers: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Partition flat dotted-key answers into per-yaml_file buckets.

    Uses PROJ_YAML_PROMPTS as the source of truth for dotted_key → yaml_file
    mapping. Keys not present in any spec default to the "proj" bucket.
    """
    yaml_file_by_key = {s.dotted_key: s.yaml_file for s in PROJ_YAML_PROMPTS}
    buckets: dict[str, dict[str, Any]] = {
        b: {} for b in get_distinct_yaml_files(PROJ_YAML_PROMPTS)
    }
    buckets.setdefault("proj", {})
    for dotted_key, value in answers.items():
        target = yaml_file_by_key.get(dotted_key, "proj")
        buckets.setdefault(target, {})[dotted_key] = value
    return buckets


def _merge_dotted_into_dict(
    existing: dict[str, Any], answers: dict[str, Any]
) -> dict[str, Any]:
    """Merge flat dotted-key answers into a nested existing dict (in-place)."""
    for dotted, value in answers.items():
        parts = dotted.split(".")
        cursor = existing
        for segment in parts[:-1]:
            nxt = cursor.get(segment)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[segment] = nxt
            cursor = nxt
        cursor[parts[-1]] = value
    return existing


def _normalize_proj(data: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through ProjConfig to normalize keys/defaults.

    Falls through (returns data unchanged) if ProjConfig cannot be imported or
    the round-trip raises — we never want normalization to block a write.
    """
    try:
        from plugins.proj.server.server.lib.models import ProjConfig  # type: ignore

        return ProjConfig.from_dict(data).to_dict()
    except Exception as exc:
        _log.warning("proj normalizer failed, writing raw dict: %s", exc)
        return data


_NORMALIZERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "proj": _normalize_proj,
}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        raise


class DriftDetected(Exception):
    """Raised when the target file changed between wizard read and write."""


def write_bucket(
    path: Path,
    existing: dict[str, Any],
    answers: dict[str, Any],
    *,
    bucket: str,
    expected_mtime: float | None = None,
) -> None:
    """Merge answers into existing, normalize, and atomically write to path.

    TOCTOU flow:
    1. Acquire fcntl.flock(LOCK_EX | LOCK_NB) on a sibling lockfile.
    2. If expected_mtime is non-None, re-stat path. If mtime differs by more
       than 1 millisecond, log a WARNING (drift detected by another writer).
       We still proceed — the wizard is the authoritative source for the
       fields it owns; unknown fields in `existing` were preserved at read
       time and survive the merge.
    3. Apply per-bucket normalizer (if any).
    4. atomic tmp + replace.
    5. Release lock.

    The lock is advisory only; it coordinates with other installer processes
    but does not protect against external writers that ignore the lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")

    merged = _merge_dotted_into_dict(dict(existing), answers)
    normalizer = _NORMALIZERS.get(bucket)
    if normalizer is not None:
        merged = normalizer(merged)

    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DriftDetected(
                f"advisory lock on {lock_path} held by another process"
            ) from exc

        if expected_mtime is not None and expected_mtime > 0:
            try:
                actual_mtime = path.stat().st_mtime
            except FileNotFoundError:
                actual_mtime = 0.0
            if abs(actual_mtime - expected_mtime) > 0.001:
                _log.warning(
                    "drift detected on %s: expected mtime %s, got %s "
                    "(another writer modified the file between wizard read "
                    "and write; wizard fields still win)",
                    path,
                    expected_mtime,
                    actual_mtime,
                )

        _atomic_write(
            path,
            yaml.safe_dump(merged, sort_keys=False, default_flow_style=False),
        )
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)

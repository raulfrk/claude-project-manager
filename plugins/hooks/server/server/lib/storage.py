"""YAML load/save for ~/.claude/hooks.yaml and failure logging."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from server.lib._types import JsonValue

from server.lib.models import HookRegistry

logger = logging.getLogger(__name__)

_HOOKS_FILE = Path.home() / ".claude" / "hooks.yaml"
_FAILURES_FILE = Path.home() / ".claude" / "hooks-failures.yaml"
_VERIFICATIONS_FILE = Path.home() / ".claude" / "hooks-verifications.yaml"
_MAX_FAILURES = 200  # rolling cap — oldest entries are trimmed
_MAX_VERIFICATIONS = 500  # rolling cap — oldest entries are trimmed
_INVOCATIONS_FILE = Path.home() / ".claude" / "hooks-invocations.yaml"
_MAX_INVOCATIONS = 2000  # rolling cap — oldest entries are trimmed


def hooks_path() -> Path:
    """Return the path to the hooks.yaml file."""
    return _HOOKS_FILE


def failures_path() -> Path:
    """Return the path to the hooks-failures.yaml file."""
    return _FAILURES_FILE


def verifications_path() -> Path:
    """Return the path to the hooks-verifications.yaml file."""
    return _VERIFICATIONS_FILE


def invocations_path() -> Path:
    """Return the path to the hooks-invocations.yaml file."""
    return _INVOCATIONS_FILE


def load(path: Path | None = None) -> HookRegistry:
    """Load the hook registry from YAML. Returns empty registry if file doesn't exist."""
    target = path or _HOOKS_FILE
    if not target.exists():
        return HookRegistry()

    with target.open() as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return HookRegistry()

    return HookRegistry.from_dict(raw)


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write content to path via a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode: int | None = None
    if path.exists():
        original_mode = path.stat().st_mode
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        tmp.replace(path)
        if original_mode is not None:
            path.chmod(original_mode & 0o7777)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def save(registry: HookRegistry, path: Path | None = None) -> Path:
    """Atomically write the hook registry to YAML. Creates file and parent dirs if needed.

    Returns the path written to.
    """
    target = path or _HOOKS_FILE
    data = registry.to_dict()
    content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    _atomic_write(target, content)
    return target


# ── Failure logging ──────────────────────────────────────────────────────────


def _load_failures(path: Path | None = None) -> list[dict[str, JsonValue]]:
    """Load existing failure entries from YAML. Returns empty list on any error."""
    target = path or _FAILURES_FILE
    if not target.exists():
        return []
    try:
        with target.open() as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, list):
            return raw
    except Exception:  # noqa: BLE001
        logger.warning("Could not read %s — starting fresh", target)
    return []


def log_failure(
    *,
    hook_id: str,
    trigger_tool: str,
    target_tool: str,
    server: str,
    error: str,
    source_result: str | None = None,
    retry_count: int = 0,
    path: Path | None = None,
) -> Path:
    """Append a failure entry to ``~/.claude/hooks-failures.yaml``.

    The file is a YAML list capped at ``_MAX_FAILURES`` entries (oldest dropped).
    Returns the path written to.
    """
    target = path or _FAILURES_FILE
    entries = _load_failures(target)

    entry: dict[str, JsonValue] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "hook_id": hook_id,
        "trigger_tool": trigger_tool,
        "target_tool": target_tool,
        "server": server,
        "error": error,
        "retry_count": retry_count,
    }
    if source_result is not None:
        entry["source_result"] = source_result
    entries.append(entry)

    # Trim to rolling cap
    if len(entries) > _MAX_FAILURES:
        entries = entries[-_MAX_FAILURES:]

    content = yaml.dump(entries, default_flow_style=False, sort_keys=False)
    _atomic_write(target, content)
    return target


def load_failures(path: Path | None = None) -> list[dict[str, JsonValue]]:
    """Public accessor for failure entries."""
    return _load_failures(path)


def save_failures(entries: list[dict[str, JsonValue]], path: Path | None = None) -> Path:
    """Atomically write failure entries to ``~/.claude/hooks-failures.yaml``.

    Returns the path written to.
    """
    target = path or _FAILURES_FILE
    content = yaml.dump(entries, default_flow_style=False, sort_keys=False) if entries else ""
    _atomic_write(target, content)
    return target


def clear_failures(path: Path | None = None) -> int:
    """Remove all failure entries. Returns the count cleared."""
    target = path or _FAILURES_FILE
    entries = _load_failures(target)
    count = len(entries)
    if count:
        _atomic_write(target, "")
    return count


# ── Verification results ─────────────────────────────────────────────────────


def _load_verifications(path: Path | None = None) -> list[dict[str, JsonValue]]:
    """Load existing verification entries from YAML. Returns empty list on any error."""
    target = path or _VERIFICATIONS_FILE
    if not target.exists():
        return []
    try:
        with target.open() as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, list):
            return raw
    except Exception:  # noqa: BLE001
        logger.warning("Could not read %s — starting fresh", target)
    return []


def store_verification_result(
    trigger_tool: str,
    hook_id: str,
    status: str,
    details: str,
    *,
    path: Path | None = None,
) -> Path:
    """Append a verification result to ``~/.claude/hooks-verifications.yaml``.

    The file is a YAML list capped at ``_MAX_VERIFICATIONS`` entries (oldest dropped).
    Returns the path written to.
    """
    target = path or _VERIFICATIONS_FILE
    entries = _load_verifications(target)

    entry: dict[str, JsonValue] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "trigger_tool": trigger_tool,
        "hook_id": hook_id,
        "status": status,
        "details": details,
    }
    entries.append(entry)

    # Trim to rolling cap
    if len(entries) > _MAX_VERIFICATIONS:
        entries = entries[-_MAX_VERIFICATIONS:]

    content = yaml.dump(entries, default_flow_style=False, sort_keys=False)
    _atomic_write(target, content)
    return target


def load_verification_results(
    limit: int = 50,
    path: Path | None = None,
) -> list[dict[str, JsonValue]]:
    """Load recent verification results. Returns up to *limit* most recent entries."""
    entries = _load_verifications(path)
    if limit and len(entries) > limit:
        return entries[-limit:]
    return entries


# ── Invocation logging ───────────────────────────────────────────────────────


def _load_invocations(path: Path | None = None) -> list[dict[str, JsonValue]]:
    """Load existing invocation entries from YAML. Returns empty list on any error."""
    target = path or _INVOCATIONS_FILE
    if not target.exists():
        return []
    try:
        with target.open() as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, list):
            return raw
    except Exception:  # noqa: BLE001
        logger.warning("Could not read %s — starting fresh", target)
    return []


def log_invocation(
    *,
    hook_id: str,
    trigger_tool: str,
    target_tool: str,
    server: str,
    source_result: str | None = None,
    payload: dict[str, JsonValue] | None = None,
    path: Path | None = None,
) -> Path:
    """Append a success invocation entry to ``~/.claude/hooks-invocations.yaml``.

    The file is a YAML list capped at ``_MAX_INVOCATIONS`` entries (oldest dropped).
    ``source_result`` and ``payload`` are truncated to 500 chars to keep the log compact.
    Returns the path written to.
    """
    target = path or _INVOCATIONS_FILE
    entries = _load_invocations(target)

    entry: dict[str, JsonValue] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "hook_id": hook_id,
        "trigger_tool": trigger_tool,
        "target_tool": target_tool,
        "server": server,
    }
    if source_result is not None:
        entry["source_result"] = source_result[:500]
    if payload is not None:
        payload_str = json.dumps(payload) if not isinstance(payload, str) else payload
        entry["payload"] = payload_str[:500]

    entries.append(entry)

    # Trim to rolling cap
    if len(entries) > _MAX_INVOCATIONS:
        entries = entries[-_MAX_INVOCATIONS:]

    content = yaml.dump(entries, default_flow_style=False, sort_keys=False)
    _atomic_write(target, content)
    return target


def load_invocations(limit: int = 50, path: Path | None = None) -> list[dict[str, JsonValue]]:
    """Load recent invocation entries. Returns up to *limit* most recent entries."""
    entries = _load_invocations(path)
    if limit and len(entries) > limit:
        return entries[-limit:]
    return entries

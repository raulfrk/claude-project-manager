from __future__ import annotations

import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import yaml

T = TypeVar("T")


def retry_link(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    backoff: float = 0.5,
    orphan_context: dict[str, Any] | None = None,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(backoff * attempt)

    if orphan_context is not None and last_exc is not None:
        log_orphaned_resource(
            orphan_context.get("tracking_dir", ""),
            {
                "external_id": orphan_context.get("external_id", ""),
                "todo_id": orphan_context.get("todo_id", ""),
                "service": orphan_context.get("service", ""),
                "error": str(last_exc),
            },
        )

    warnings.warn(
        f"retry_link exhausted {max_retries} retries: {last_exc}",
        stacklevel=2,
    )
    raise last_exc  # type: ignore[misc]


def log_orphaned_resource(tracking_dir: str, context: dict[str, Any]) -> None:
    path = Path(tracking_dir).expanduser() / ".orphaned-resources.yaml"
    entries: list[dict[str, Any]] = []
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text()) or []
        except yaml.YAMLError:
            raw = []
        if isinstance(raw, list):
            entries = raw
    entries.append({**context, "timestamp": datetime.now(timezone.utc).isoformat()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(entries, default_flow_style=False))

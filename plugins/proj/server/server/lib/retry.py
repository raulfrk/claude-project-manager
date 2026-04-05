from __future__ import annotations

import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

import yaml

from server.lib.backoff import exponential_backoff
from server.lib.resilience import CircuitBreakerManager

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open and the call is skipped."""

    def __init__(self, service: str) -> None:
        self.service = service
        super().__init__(f"Circuit breaker OPEN for {service} — call skipped (graceful degradation)")


def retry_link(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    backoff: float = 0.5,
    orphan_context: dict[str, str] | None = None,
    circuit_breaker_manager: CircuitBreakerManager | None = None,
    service: str | None = None,
) -> T:
    # If circuit breaker is active and circuit is open, skip the call
    if circuit_breaker_manager is not None and service is not None:
        if not circuit_breaker_manager.check(service):
            raise CircuitOpenError(service)

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            result = fn()
            # Record success if circuit breaker is active
            if circuit_breaker_manager is not None and service is not None:
                circuit_breaker_manager.record_success(service)
            return result
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = exponential_backoff(attempt - 1, base=backoff)
                time.sleep(delay)

    # Record failure if circuit breaker is active
    if circuit_breaker_manager is not None and service is not None and last_exc is not None:
        circuit_breaker_manager.record_failure(service, str(last_exc))

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
    assert last_exc is not None  # guaranteed: loop ran at least once
    raise last_exc


def log_orphaned_resource(tracking_dir: str, context: dict[str, str]) -> None:
    path = Path(tracking_dir).expanduser() / ".orphaned-resources.yaml"
    entries: list[dict[str, str]] = []
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

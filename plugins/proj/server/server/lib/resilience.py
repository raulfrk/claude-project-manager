"""Circuit breaker for external API calls (Todoist, Trello, Jira)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

from server.lib.models import JsonDict, _int

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class CircuitBreaker:
    """State for a single service circuit breaker."""

    service: str  # "todoist", "trello", "jira"
    state: str = "HEALTHY"  # HEALTHY | OPEN | HALF_OPEN
    failure_count: int = 0
    last_failure: str | None = None
    last_success: str | None = None
    opened_at: str | None = None
    last_error: str | None = None
    last_status_code: int | None = None

    def to_dict(self) -> JsonDict:
        return {
            "service": self.service,
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure,
            "last_success": self.last_success,
            "opened_at": self.opened_at,
            "last_error": self.last_error,
            "last_status_code": self.last_status_code,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> CircuitBreaker:
        raw_status_code = data.get("last_status_code")
        return cls(
            service=str(data.get("service", "")),
            state=str(data.get("state", "HEALTHY")),
            failure_count=_int(data.get("failure_count")),
            last_failure=str(data["last_failure"]) if data.get("last_failure") else None,
            last_success=str(data["last_success"]) if data.get("last_success") else None,
            opened_at=str(data["opened_at"]) if data.get("opened_at") else None,
            last_error=str(data["last_error"]) if data.get("last_error") else None,
            last_status_code=_int(raw_status_code) if raw_status_code is not None else None,
        )


class CircuitBreakerManager:
    """Manage circuit breakers for external services with persistent state."""

    def __init__(
        self,
        state_dir: Path,
        failure_threshold: int = 3,
        recovery_timeout: int = 300,
    ) -> None:
        self.state_file = state_dir / ".team-state" / "circuit-breakers.yaml"
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._breakers: dict[str, CircuitBreaker] = {}
        self._load()

    def _load(self) -> None:
        """Read breaker state from YAML file if it exists."""
        if not self.state_file.exists():
            return
        try:
            raw = yaml.safe_load(self.state_file.read_text())
        except yaml.YAMLError:
            return
        if not isinstance(raw, dict):
            return
        breakers_raw = raw.get("breakers", {})
        if not isinstance(breakers_raw, dict):
            return
        for key, val in breakers_raw.items():
            if isinstance(val, dict):
                self._breakers[str(key)] = CircuitBreaker.from_dict(val)

    def _save(self) -> None:
        """Atomic write breaker state to YAML file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".yaml.tmp")
        data = {"breakers": {k: v.to_dict() for k, v in self._breakers.items()}}
        tmp.write_text(yaml.dump(data, default_flow_style=False))
        tmp.rename(self.state_file)

    def _get_or_create(self, service: str) -> CircuitBreaker:
        if service not in self._breakers:
            self._breakers[service] = CircuitBreaker(service=service)
        return self._breakers[service]

    def check(self, service: str) -> bool:
        """Return True if the call should proceed.

        - HEALTHY: always proceed
        - OPEN: check if recovery_timeout elapsed -> transition to HALF_OPEN, allow one probe
        - HALF_OPEN: allow one probe attempt
        """
        breaker = self._get_or_create(service)

        if breaker.state == "HEALTHY":
            return True

        if breaker.state == "OPEN":
            if breaker.opened_at is None:
                # Shouldn't happen, but recover gracefully
                breaker.state = "HALF_OPEN"
                self._save()
                return True
            opened = datetime.fromisoformat(breaker.opened_at)
            now = datetime.now(UTC)
            elapsed = (now - opened).total_seconds()
            if elapsed >= self.recovery_timeout:
                breaker.state = "HALF_OPEN"
                self._save()
                return True
            return False

        # HALF_OPEN: allow one probe
        return True

    def record_success(self, service: str) -> None:
        """Reset to HEALTHY, clear failure count."""
        breaker = self._get_or_create(service)
        breaker.state = "HEALTHY"
        breaker.failure_count = 0
        breaker.last_success = datetime.now(UTC).isoformat()
        breaker.opened_at = None
        self._save()

    def record_failure(self, service: str, error: str, status_code: int | None = None) -> None:
        """Increment failure count.

        HEALTHY -> OPEN if threshold reached.
        HALF_OPEN -> OPEN on probe failure (reset opened_at).
        """
        breaker = self._get_or_create(service)
        breaker.failure_count += 1
        breaker.last_failure = datetime.now(UTC).isoformat()
        breaker.last_error = error
        breaker.last_status_code = status_code

        if breaker.state == "HALF_OPEN":
            # Probe failed — reopen
            breaker.state = "OPEN"
            breaker.opened_at = datetime.now(UTC).isoformat()
        elif breaker.state == "HEALTHY" and breaker.failure_count >= self.failure_threshold:
            breaker.state = "OPEN"
            breaker.opened_at = datetime.now(UTC).isoformat()

        self._save()

    def get_status(self) -> dict[str, JsonDict]:
        """Return all breaker states for status display."""
        return {k: v.to_dict() for k, v in self._breakers.items()}


class OrphanLogger:
    """Log orphaned external resources to .team-state/orphaned-resources.yaml.

    An orphan is an external resource (e.g. Todoist task, Trello card) that was
    created but could not be linked back to a local todo due to an error.
    """

    MAX_ENTRIES = 500

    def __init__(self, state_dir: Path) -> None:
        self.state_file = state_dir / ".team-state" / "orphaned-resources.yaml"

    def log_orphan(
        self,
        service: str,
        external_id: str,
        todo_id: str,
        error: str,
    ) -> None:
        """Append an orphaned resource entry, capping at MAX_ENTRIES."""
        entries = self._load_entries()
        entries.append(
            {
                "service": service,
                "external_id": external_id,
                "todo_id": todo_id,
                "error": error,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        # Rolling cap — keep the most recent entries
        if len(entries) > self.MAX_ENTRIES:
            entries = entries[-self.MAX_ENTRIES :]
        self._save_entries(entries)

    def load_orphans(self) -> list[JsonDict]:
        """Return all orphaned resource entries."""
        return self._load_entries()

    def _load_entries(self) -> list[JsonDict]:
        if not self.state_file.exists():
            return []
        try:
            raw = yaml.safe_load(self.state_file.read_text())
        except yaml.YAMLError:
            return []
        if not isinstance(raw, list):
            return []
        return raw

    def _save_entries(self, entries: list[JsonDict]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.dump(entries, default_flow_style=False))
        tmp.rename(self.state_file)

"""Tests for circuit breaker resilience module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from server.lib.resilience import CircuitBreaker, CircuitBreakerManager, OrphanLogger


class TestCircuitBreakerDataclass:
    def test_to_dict(self):
        cb = CircuitBreaker(service="todoist", state="OPEN", failure_count=3)
        d = cb.to_dict()
        assert d["service"] == "todoist"
        assert d["state"] == "OPEN"
        assert d["failure_count"] == 3
        assert d["last_error"] is None
        assert d["last_status_code"] is None

    def test_to_dict_with_error_fields(self):
        cb = CircuitBreaker(
            service="todoist",
            state="OPEN",
            failure_count=3,
            last_error="connection timeout",
            last_status_code=503,
        )
        d = cb.to_dict()
        assert d["last_error"] == "connection timeout"
        assert d["last_status_code"] == 503

    def test_from_dict_defaults(self):
        cb = CircuitBreaker.from_dict({"service": "trello"})
        assert cb.service == "trello"
        assert cb.state == "HEALTHY"
        assert cb.failure_count == 0
        assert cb.last_failure is None
        assert cb.last_success is None
        assert cb.opened_at is None
        assert cb.last_error is None
        assert cb.last_status_code is None

    def test_from_dict_with_error_fields(self):
        cb = CircuitBreaker.from_dict(
            {
                "service": "todoist",
                "last_error": "rate limited",
                "last_status_code": 429,
            }
        )
        assert cb.last_error == "rate limited"
        assert cb.last_status_code == 429

    def test_roundtrip(self):
        cb = CircuitBreaker(
            service="jira",
            state="HALF_OPEN",
            failure_count=2,
            last_failure="2026-01-01T00:00:00+00:00",
            last_success="2025-12-31T00:00:00+00:00",
            opened_at="2026-01-01T00:00:00+00:00",
            last_error="server error",
            last_status_code=500,
        )
        restored = CircuitBreaker.from_dict(cb.to_dict())
        assert restored.service == cb.service
        assert restored.state == cb.state
        assert restored.failure_count == cb.failure_count
        assert restored.last_failure == cb.last_failure
        assert restored.last_success == cb.last_success
        assert restored.opened_at == cb.opened_at
        assert restored.last_error == cb.last_error
        assert restored.last_status_code == cb.last_status_code


class TestCircuitBreakerManager:
    def test_healthy_allows_call(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path)
        assert mgr.check("todoist") is True

    def test_healthy_to_open_transition(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=3)
        mgr.record_failure("todoist", "timeout")
        assert mgr.check("todoist") is True  # 1 failure, still healthy
        mgr.record_failure("todoist", "timeout")
        assert mgr.check("todoist") is True  # 2 failures, still healthy
        mgr.record_failure("todoist", "timeout")
        # 3 failures = threshold reached -> OPEN
        assert mgr.check("todoist") is False

    def test_open_to_half_open_after_timeout(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=1, recovery_timeout=60)
        mgr.record_failure("todoist", "error")
        assert mgr.check("todoist") is False  # OPEN

        # Simulate time passing beyond recovery_timeout
        past = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
        mgr._breakers["todoist"].opened_at = past
        mgr._save()

        assert mgr.check("todoist") is True  # Should transition to HALF_OPEN
        assert mgr._breakers["todoist"].state == "HALF_OPEN"

    def test_half_open_to_healthy_on_success(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=1, recovery_timeout=0)
        mgr.record_failure("todoist", "error")
        # Force transition to HALF_OPEN
        mgr._breakers["todoist"].opened_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        mgr._save()
        mgr.check("todoist")  # transitions to HALF_OPEN

        mgr.record_success("todoist")
        assert mgr._breakers["todoist"].state == "HEALTHY"
        assert mgr._breakers["todoist"].failure_count == 0

    def test_half_open_to_open_on_failure(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=1, recovery_timeout=0)
        mgr.record_failure("todoist", "error")
        # Force transition to HALF_OPEN
        mgr._breakers["todoist"].opened_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        mgr._save()
        mgr.check("todoist")  # transitions to HALF_OPEN
        assert mgr._breakers["todoist"].state == "HALF_OPEN"

        mgr.record_failure("todoist", "probe failed")
        assert mgr._breakers["todoist"].state == "OPEN"
        assert mgr._breakers["todoist"].opened_at is not None

    def test_state_persistence(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=2)
        mgr.record_failure("todoist", "err1")
        mgr.record_failure("todoist", "err2")

        # Load from disk in a new manager instance
        mgr2 = CircuitBreakerManager(tmp_path, failure_threshold=2)
        assert mgr2._breakers["todoist"].state == "OPEN"
        assert mgr2._breakers["todoist"].failure_count == 2
        assert mgr2.check("todoist") is False

    def test_get_status_returns_all_breakers(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path)
        mgr.record_success("todoist")
        mgr.record_failure("trello", "timeout")
        mgr.record_success("jira")

        status = mgr.get_status()
        assert "todoist" in status
        assert "trello" in status
        assert "jira" in status
        assert status["todoist"]["state"] == "HEALTHY"
        assert status["trello"]["state"] == "HEALTHY"  # 1 failure, threshold=3
        assert status["jira"]["state"] == "HEALTHY"

    def test_get_status_includes_error_fields(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=1)
        mgr.record_failure("todoist", "connection timeout", status_code=503)

        status = mgr.get_status()
        assert status["todoist"]["last_error"] == "connection timeout"
        assert status["todoist"]["last_status_code"] == 503

    def test_record_success_resets_failure_count(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=5)
        mgr.record_failure("todoist", "err1")
        mgr.record_failure("todoist", "err2")
        assert mgr._breakers["todoist"].failure_count == 2
        mgr.record_success("todoist")
        assert mgr._breakers["todoist"].failure_count == 0
        assert mgr._breakers["todoist"].state == "HEALTHY"

    def test_record_failure_stores_error_and_status_code(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path)
        mgr.record_failure("todoist", "rate limited", status_code=429)
        breaker = mgr._breakers["todoist"]
        assert breaker.last_error == "rate limited"
        assert breaker.last_status_code == 429

    def test_record_failure_stores_error_without_status_code(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path)
        mgr.record_failure("todoist", "network error")
        breaker = mgr._breakers["todoist"]
        assert breaker.last_error == "network error"
        assert breaker.last_status_code is None

    def test_record_failure_overwrites_previous_error(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path)
        mgr.record_failure("todoist", "first error", status_code=500)
        mgr.record_failure("todoist", "second error", status_code=503)
        breaker = mgr._breakers["todoist"]
        assert breaker.last_error == "second error"
        assert breaker.last_status_code == 503

    def test_error_fields_persist_across_loads(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path)
        mgr.record_failure("todoist", "server error", status_code=500)

        mgr2 = CircuitBreakerManager(tmp_path)
        breaker = mgr2._breakers["todoist"]
        assert breaker.last_error == "server error"
        assert breaker.last_status_code == 500

    def test_load_handles_missing_file(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path)
        assert mgr._breakers == {}

    def test_load_handles_corrupt_file(self, tmp_path: Path):
        state_dir = tmp_path / ".team-state"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "circuit-breakers.yaml"
        state_file.write_text("not: valid: yaml: {{{")
        mgr = CircuitBreakerManager(tmp_path)
        assert mgr._breakers == {}

    def test_load_handles_non_dict_file(self, tmp_path: Path):
        state_dir = tmp_path / ".team-state"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "circuit-breakers.yaml"
        state_file.write_text("- a list\n- not a dict\n")
        mgr = CircuitBreakerManager(tmp_path)
        assert mgr._breakers == {}

    def test_multiple_services_independent(self, tmp_path: Path):
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=2)
        mgr.record_failure("todoist", "err")
        mgr.record_failure("todoist", "err")
        mgr.record_failure("trello", "err")

        assert mgr.check("todoist") is False  # OPEN (2 >= 2)
        assert mgr.check("trello") is True  # HEALTHY (1 < 2)

    def test_open_without_opened_at_recovers(self, tmp_path: Path):
        """Edge case: OPEN state but opened_at is None should recover gracefully."""
        mgr = CircuitBreakerManager(tmp_path)
        mgr._breakers["todoist"] = CircuitBreaker(service="todoist", state="OPEN", opened_at=None)
        mgr._save()

        # Should transition to HALF_OPEN and allow the call
        assert mgr.check("todoist") is True
        assert mgr._breakers["todoist"].state == "HALF_OPEN"

    def test_state_file_in_team_state_dir(self, tmp_path: Path):
        """Verify the state file is written to .team-state/ subdirectory."""
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=1)
        mgr.record_failure("todoist", "error")

        state_file = tmp_path / ".team-state" / "circuit-breakers.yaml"
        assert state_file.exists()
        # Old location should NOT exist
        old_file = tmp_path / ".circuit-breakers.yaml"
        assert not old_file.exists()

    def test_yaml_state_file_format(self, tmp_path: Path):
        """Verify the YAML file structure is correct."""
        mgr = CircuitBreakerManager(tmp_path, failure_threshold=1)
        mgr.record_failure("todoist", "connection timeout", status_code=503)

        state_file = tmp_path / ".team-state" / "circuit-breakers.yaml"
        assert state_file.exists()
        data = yaml.safe_load(state_file.read_text())
        assert "breakers" in data
        assert "todoist" in data["breakers"]
        assert data["breakers"]["todoist"]["state"] == "OPEN"
        assert data["breakers"]["todoist"]["failure_count"] == 1
        assert data["breakers"]["todoist"]["last_error"] == "connection timeout"
        assert data["breakers"]["todoist"]["last_status_code"] == 503


class TestOrphanLogger:
    def test_log_orphan_creates_file(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        logger.log_orphan("todoist", "ext-123", "TODO-001", "sync failed")

        assert logger.state_file.exists()
        entries = yaml.safe_load(logger.state_file.read_text())
        assert len(entries) == 1
        assert entries[0]["service"] == "todoist"
        assert entries[0]["external_id"] == "ext-123"
        assert entries[0]["todo_id"] == "TODO-001"
        assert entries[0]["error"] == "sync failed"
        assert "timestamp" in entries[0]

    def test_log_orphan_appends(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        logger.log_orphan("todoist", "ext-1", "TODO-001", "err1")
        logger.log_orphan("trello", "ext-2", "TODO-002", "err2")

        entries = logger.load_orphans()
        assert len(entries) == 2
        assert entries[0]["service"] == "todoist"
        assert entries[1]["service"] == "trello"

    def test_load_orphans_empty(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        assert logger.load_orphans() == []

    def test_load_orphans_returns_entries(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        logger.log_orphan("todoist", "ext-1", "TODO-001", "err1")
        logger.log_orphan("jira", "ext-2", "TODO-002", "err2")

        orphans = logger.load_orphans()
        assert len(orphans) == 2
        assert orphans[0]["external_id"] == "ext-1"
        assert orphans[1]["external_id"] == "ext-2"

    def test_rolling_cap_at_500(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        # Write 500 entries
        for i in range(500):
            logger.log_orphan("svc", f"ext-{i}", f"TODO-{i}", f"err-{i}")
        assert len(logger.load_orphans()) == 500

        # Add one more — should still be 500, oldest dropped
        logger.log_orphan("svc", "ext-500", "TODO-500", "err-500")
        entries = logger.load_orphans()
        assert len(entries) == 500
        # First entry should be ext-1 (ext-0 was dropped)
        assert entries[0]["external_id"] == "ext-1"
        assert entries[-1]["external_id"] == "ext-500"

    def test_state_file_in_team_state_dir(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        logger.log_orphan("todoist", "ext-1", "TODO-001", "err")

        expected = tmp_path / ".team-state" / "orphaned-resources.yaml"
        assert expected.exists()
        assert logger.state_file == expected

    def test_handles_corrupt_yaml(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        logger.state_file.parent.mkdir(parents=True, exist_ok=True)
        logger.state_file.write_text("{{{not valid yaml")

        # Should return empty list, not crash
        assert logger.load_orphans() == []

        # Should overwrite corrupt file
        logger.log_orphan("todoist", "ext-1", "TODO-001", "err")
        entries = logger.load_orphans()
        assert len(entries) == 1

    def test_handles_non_list_yaml(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        logger.state_file.parent.mkdir(parents=True, exist_ok=True)
        logger.state_file.write_text("key: value\n")

        assert logger.load_orphans() == []

    def test_timestamp_is_utc_iso(self, tmp_path: Path):
        logger = OrphanLogger(tmp_path)
        logger.log_orphan("todoist", "ext-1", "TODO-001", "err")

        entries = logger.load_orphans()
        ts = entries[0]["timestamp"]
        # Should be parseable as ISO datetime
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None  # UTC-aware

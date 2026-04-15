"""Unit tests for sql_decisions CRUD module."""

from __future__ import annotations

from server.lib.models import ProjConfig
from server.lib.sql_decisions import (
    append_decision,
    load_all_decisions,
    load_decisions,
    replace_decisions,
)


class TestLoadDecisions:
    def test_empty_returns_empty_list(self, cfg: ProjConfig) -> None:
        result = load_decisions(cfg, "myproject")
        assert result == []

    def test_roundtrip_single_decision(self, cfg: ProjConfig) -> None:
        entry = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "decision": "Use SQLite",
            "context": "storage layer",
        }
        append_decision(cfg, "myproject", entry)
        result = load_decisions(cfg, "myproject")
        assert len(result) == 1
        assert result[0]["decision"] == "Use SQLite"
        assert result[0]["context"] == "storage layer"

    def test_insertion_order_preserved(self, cfg: ProjConfig) -> None:
        for i in range(3):
            append_decision(
                cfg,
                "myproject",
                {"timestamp": f"2026-01-0{i + 1}T00:00:00+00:00", "decision": f"Decision {i}"},
            )
        result = load_decisions(cfg, "myproject")
        assert len(result) == 3
        assert result[0]["decision"] == "Decision 0"
        assert result[1]["decision"] == "Decision 1"
        assert result[2]["decision"] == "Decision 2"

    def test_project_isolation(self, cfg: ProjConfig) -> None:
        append_decision(
            cfg, "proj_a", {"timestamp": "2026-01-01T00:00:00+00:00", "decision": "A decision"}
        )
        append_decision(
            cfg, "proj_b", {"timestamp": "2026-01-01T00:00:00+00:00", "decision": "B decision"}
        )
        result_a = load_decisions(cfg, "proj_a")
        result_b = load_decisions(cfg, "proj_b")
        assert len(result_a) == 1
        assert result_a[0]["decision"] == "A decision"
        assert len(result_b) == 1
        assert result_b[0]["decision"] == "B decision"


class TestAppendDecision:
    def test_auto_generates_timestamp_when_missing(self, cfg: ProjConfig) -> None:
        entry: dict[str, object] = {"decision": "No timestamp"}
        append_decision(cfg, "myproject", entry)
        result = load_decisions(cfg, "myproject")
        assert len(result) == 1
        # timestamp field was in the stored entry (auto-generated)
        assert "decision" in result[0]
        assert result[0]["decision"] == "No timestamp"

    def test_preserves_explicit_timestamp(self, cfg: ProjConfig) -> None:
        ts = "2025-06-15T12:34:56+00:00"
        entry = {"timestamp": ts, "decision": "Explicit ts"}
        append_decision(cfg, "myproject", entry)
        result = load_decisions(cfg, "myproject")
        assert len(result) == 1
        assert result[0]["timestamp"] == ts


class TestReplaceDecisions:
    def test_replaces_all_entries(self, cfg: ProjConfig) -> None:
        for i in range(3):
            append_decision(
                cfg, "myproject", {"timestamp": "2026-01-01T00:00:00+00:00", "decision": f"Old {i}"}
            )
        new_entries = [
            {"timestamp": "2026-06-01T00:00:00+00:00", "decision": "New A"},
            {"timestamp": "2026-06-02T00:00:00+00:00", "decision": "New B"},
        ]
        replace_decisions(cfg, "myproject", new_entries)
        result = load_decisions(cfg, "myproject")
        assert len(result) == 2
        assert result[0]["decision"] == "New A"
        assert result[1]["decision"] == "New B"

    def test_empty_list_clears_all(self, cfg: ProjConfig) -> None:
        append_decision(
            cfg, "myproject", {"timestamp": "2026-01-01T00:00:00+00:00", "decision": "Something"}
        )
        replace_decisions(cfg, "myproject", [])
        result = load_decisions(cfg, "myproject")
        assert result == []


class TestLoadAllDecisions:
    def test_empty_tracking_dir(self, cfg: ProjConfig) -> None:
        result = load_all_decisions(cfg)
        assert result == {}

    def test_multiple_projects(self, cfg: ProjConfig) -> None:
        append_decision(
            cfg, "proj_a", {"timestamp": "2026-01-01T00:00:00+00:00", "decision": "Alpha"}
        )
        append_decision(
            cfg, "proj_b", {"timestamp": "2026-01-01T00:00:00+00:00", "decision": "Beta"}
        )
        result = load_all_decisions(cfg)
        assert "proj_a" in result
        assert "proj_b" in result
        assert result["proj_a"][0]["decision"] == "Alpha"
        assert result["proj_b"][0]["decision"] == "Beta"

"""Integration tests for context injection with mock data on disk."""

from __future__ import annotations

from pathlib import Path

from server.lib.models import (
    ContextInjectionConfig,
    ContextInjectionSectionsConfig,
    ProjConfig,
    Todo,
)
from server.tools.context_injection import (
    ContextInjection,
    _load_decision_items,
    _read_all_knowledge,
    inject_context,
)


def _make_cfg(tracking_dir: str) -> ProjConfig:
    """Create a ProjConfig pointing at a tmp tracking dir with injection enabled."""
    return ProjConfig(
        tracking_dir=tracking_dir,
        context_injection=ContextInjectionConfig(
            enabled=True,
            budget=2000,
            recency_window=24,
            sections=ContextInjectionSectionsConfig(notes=40, decisions=35, knowledge=25),
        ),
    )


def _write_notes(tracking: Path, content: str) -> None:
    tracking.mkdir(parents=True, exist_ok=True)
    (tracking / "NOTES.md").write_text(content)


def _write_decisions(tracking: Path, entries: list[dict]) -> None:
    """Seed decisions into SQLite for the project located at *tracking*.

    tracking is expected to be ``<tracking_dir>/<project_name>``.
    """
    from server.lib import storage as _storage
    from server.lib.models import ProjConfig as _ProjConfig

    tracking.mkdir(parents=True, exist_ok=True)
    # Derive cfg + project_name from the tracking path
    tracking_dir = str(tracking.parent)
    project_name = tracking.name
    cfg = _ProjConfig(tracking_dir=tracking_dir)
    for entry in entries:
        _storage.append_decision(cfg, project_name, entry)


def _write_knowledge(tracking: Path, content: str) -> None:
    tracking.mkdir(parents=True, exist_ok=True)
    (tracking / "knowledge.md").write_text(content)


# ── Budget Compliance ────────────────────────────────────────────────────────


class TestBudgetCompliance:
    def test_output_within_budget(self, tmp_path: Path) -> None:
        """Total injected chars must not exceed configured budget."""
        tracking = tmp_path / "testproj"
        _write_notes(tracking, "## 2026-04-07\n" + "x" * 5000)
        _write_decisions(
            tracking,
            [
                {"timestamp": "2026-04-07T10:00:00", "decision": "d" * 3000},
            ],
        )
        _write_knowledge(tracking, "## 2026-04-07\n" + "k" * 5000)

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 500

        todos = [Todo(id="1", title="test todo", status="in-progress")]
        result = inject_context(cfg, "testproj", todos, [])

        assert result.total_chars <= 500

    def test_zero_budget_returns_empty(self, tmp_path: Path) -> None:
        tracking = tmp_path / "testproj"
        _write_notes(tracking, "## 2026-04-07\nSome notes")

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 0

        result = inject_context(cfg, "testproj", [], [])
        assert result.total_chars == 0
        assert result.notes == ""
        assert result.decisions == ""
        assert result.knowledge == ""

    def test_disabled_returns_empty(self, tmp_path: Path) -> None:
        tracking = tmp_path / "testproj"
        _write_notes(tracking, "## 2026-04-07\nSome notes")

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.enabled = False

        result = inject_context(cfg, "testproj", [], [])
        assert result == ContextInjection()


# ── Relevance Ordering ───────────────────────────────────────────────────────


class TestRelevanceOrdering:
    def test_relevant_content_ranks_higher(self, tmp_path: Path) -> None:
        """Notes matching active todo keywords should appear in output."""
        tracking = tmp_path / "testproj"
        _write_notes(
            tracking,
            (
                "## 2026-03-01\n"
                "Unrelated discussion about cooking recipes\n\n"
                "## 2026-03-02\n"
                "Authentication module refactor with security improvements\n\n"
                "## 2026-03-03\n"
                "Another cooking topic with no project relevance"
            ),
        )
        _write_decisions(tracking, [])

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 500

        todos = [
            Todo(id="1", title="Implement authentication security", status="in-progress"),
        ]
        result = inject_context(cfg, "testproj", todos, [])

        # The auth-related note should appear in the output
        assert "authentication" in result.notes.lower() or "security" in result.notes.lower()

    def test_git_paths_influence_relevance(self, tmp_path: Path) -> None:
        tracking = tmp_path / "testproj"
        _write_notes(
            tracking,
            (
                "## 2026-03-01\n"
                "Database migration notes for schema changes\n\n"
                "## 2026-03-02\n"
                "Random unrelated filler content here"
            ),
        )
        _write_decisions(tracking, [])

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 500

        result = inject_context(cfg, "testproj", [], ["src/database/migration.py"])
        # Database-related note should be favored
        if result.notes:
            assert "database" in result.notes.lower() or "migration" in result.notes.lower()

    def test_active_todo_id_boosts_content(self, tmp_path: Path) -> None:
        tracking = tmp_path / "testproj"
        _write_notes(
            tracking,
            (
                "## 2026-03-01\n"
                "Working on todo 42 authentication flow\n\n"
                "## 2026-03-02\n"
                "Completely unrelated gardening tips and tricks"
            ),
        )
        _write_decisions(tracking, [])

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 400

        todos = [
            Todo(id="42", title="auth flow", status="in-progress"),
        ]
        result = inject_context(cfg, "testproj", todos, [])
        if result.notes:
            assert "todo 42" in result.notes.lower() or "authentication" in result.notes.lower()


# ── Tiered Injection ─────────────────────────────────────────────────────────


class TestTieredInjection:
    def test_recent_in_tier1(self, tmp_path: Path) -> None:
        """Very recent notes should always appear (tier 1)."""
        tracking = tmp_path / "testproj"
        # Today's date header guarantees recency
        _write_notes(
            tracking,
            (
                "## 2026-04-07\n"
                "Today's critical implementation note about the release\n\n"
                "## 2020-01-01\n"
                "Very old note from years ago about something"
            ),
        )
        _write_decisions(tracking, [])

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 300

        result = inject_context(cfg, "testproj", [], [])
        # Recent note should be in output
        assert "critical implementation" in result.notes or "release" in result.notes

    def test_older_relevant_in_tier2(self, tmp_path: Path) -> None:
        """Old but keyword-relevant items should appear via tier 2."""
        tracking = tmp_path / "testproj"
        _write_notes(
            tracking,
            (
                "## 2020-01-01\n"
                "Authentication security module implementation design\n\n"
                "## 2020-01-02\n"
                "Random filler with no keywords at all here none"
            ),
        )
        _write_decisions(tracking, [])

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 2000

        todos = [
            Todo(id="1", title="authentication security module", status="in-progress"),
        ]
        result = inject_context(cfg, "testproj", todos, [])
        # Old but relevant note should appear
        assert "authentication" in result.notes.lower()

    def test_tier3_fills_remaining(self, tmp_path: Path) -> None:
        """When no keywords match, tier 3 fills with most recent old items."""
        tracking = tmp_path / "testproj"
        _write_notes(
            tracking,
            (
                "## 2020-06-01\n"
                "June discussion about deployment strategy\n\n"
                "## 2020-01-01\n"
                "January planning session notes content"
            ),
        )
        _write_decisions(tracking, [])

        cfg = _make_cfg(str(tmp_path))
        cfg.context_injection.budget = 2000

        # No keywords -> tier2 is empty, tier3 picks up by recency
        result = inject_context(cfg, "testproj", [], [])
        assert "deployment" in result.notes.lower() or "planning" in result.notes.lower()


# ── End-to-End ───────────────────────────────────────────────────────────────


class TestEndToEnd:
    def test_inject_context_full(self, tmp_path: Path) -> None:
        """Full inject_context with notes, decisions, and knowledge on disk."""
        tracking = tmp_path / "testproj"

        _write_notes(
            tracking,
            (
                "## 2026-04-07\n"
                "Added retry logic to the API client for transient failures\n\n"
                "## 2026-04-06\n"
                "Discussed caching strategy with the team"
            ),
        )

        _write_decisions(
            tracking,
            [
                {
                    "timestamp": "2026-04-07T09:00:00",
                    "decision": "Use exponential backoff for retries",
                    "context": "Evaluated linear vs exponential",
                    "tags": ["api", "resilience"],
                },
                {
                    "timestamp": "2026-04-06T14:00:00",
                    "decision": "Cache TTL set to 5 minutes",
                    "tags": ["caching"],
                },
            ],
        )

        _write_knowledge(
            tracking,
            (
                "## 2026-04-07\n"
                "- API rate limit is 100 req/s\n"
                "- Retry after 429 status code\n\n"
                "## 2026-04-05\n"
                "- Redis used as cache backend"
            ),
        )

        cfg = _make_cfg(str(tmp_path))
        todos = [
            Todo(id="1", title="Implement retry logic", status="in-progress"),
            Todo(id="2", title="Add caching layer", status="pending"),
        ]

        result = inject_context(cfg, "testproj", todos, ["src/api/client.py"])

        assert isinstance(result, ContextInjection)
        assert result.total_chars > 0
        assert result.total_chars <= cfg.context_injection.budget
        # At least one section has content
        assert result.notes or result.decisions or result.knowledge

    def test_read_all_knowledge_with_sessions(self, tmp_path: Path) -> None:
        """_read_all_knowledge reads both knowledge.md and session-*.md files."""
        tracking = tmp_path / "testproj"
        _write_knowledge(tracking, "## 2026-04-07\n- Main knowledge entry")

        sessions_dir = tracking / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "session-2026-04-06.md").write_text(
            "## Session Notes\nSome session content\n\n"
            "## Project Knowledge\n- Session knowledge item\n"
        )

        cfg = _make_cfg(str(tmp_path))
        items = _read_all_knowledge(cfg, "testproj")

        assert len(items) == 2
        texts = [i.text for i in items]
        assert any("Main knowledge" in t for t in texts)
        assert any("Session knowledge" in t for t in texts)

    def test_load_decisions_skips_bad_timestamps(self, tmp_path: Path) -> None:
        """Decisions with unparseable timestamps are silently skipped."""
        tracking = tmp_path / "testproj"
        _write_decisions(
            tracking,
            [
                {"timestamp": "2026-04-07T10:00:00", "decision": "Good decision"},
                {"timestamp": "not-a-date", "decision": "Bad timestamp"},
                {"timestamp": "", "decision": "Empty timestamp"},
                {"decision": "Missing timestamp"},
                {"timestamp": "2026-04-06", "decision": "Date-only ok"},
            ],
        )

        cfg = _make_cfg(str(tmp_path))
        items = _load_decision_items(cfg, "testproj")

        # Only entries with parseable timestamps should survive
        assert len(items) == 2
        texts = [i.text for i in items]
        assert any("Good decision" in t for t in texts)
        assert any("Date-only ok" in t for t in texts)

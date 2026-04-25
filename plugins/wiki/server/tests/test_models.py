"""Tests for lib/models.py."""

from pathlib import Path

import pytest

from server.lib.models import Page, Profile, SessionIngestGate, WikiConfig


class TestSessionIngestGate:
    def test_defaults(self) -> None:
        gate = SessionIngestGate()
        assert gate.decisions_min == 1
        assert gate.insights_min == 1
        assert gate.word_count_min == 300

    def test_from_dict_defaults(self) -> None:
        gate = SessionIngestGate.from_dict({})
        assert gate.decisions_min == 1
        assert gate.insights_min == 1
        assert gate.word_count_min == 300

    def test_from_dict_custom(self) -> None:
        gate = SessionIngestGate.from_dict(
            {"decisions_min": 2, "insights_min": 3, "word_count_min": 500}
        )
        assert gate.decisions_min == 2
        assert gate.insights_min == 3
        assert gate.word_count_min == 500

    def test_from_dict_partial_override(self) -> None:
        gate = SessionIngestGate.from_dict({"decisions_min": 2})
        assert gate.decisions_min == 2
        assert gate.insights_min == 1  # default preserved
        assert gate.word_count_min == 300  # default preserved

    def test_to_dict_roundtrip(self) -> None:
        gate = SessionIngestGate(decisions_min=2, insights_min=0, word_count_min=100)
        restored = SessionIngestGate.from_dict(gate.to_dict())
        assert restored == gate


class TestWikiConfig:
    def test_from_dict_defaults(self) -> None:
        cfg = WikiConfig.from_dict({})
        assert cfg.enabled is False
        assert cfg.wiki_dir == Path.home() / ".claude" / "wiki"
        assert cfg.reingest_cooldown_hours == 24
        assert cfg.bootstrap_pending is False
        assert cfg.session_ingest_section_map == {}

    def test_from_dict_overrides(self) -> None:
        cfg = WikiConfig.from_dict(
            {
                "enabled": True,
                "wiki_dir": "/tmp/w",
                "reingest_cooldown_hours": 1,
                "bootstrap_pending": True,
                "session_ingest": {"section_map": {"Key Decisions": "decisions"}},
            }
        )
        assert cfg.enabled is True
        assert cfg.wiki_dir == Path("/tmp/w")
        assert cfg.reingest_cooldown_hours == 1
        assert cfg.bootstrap_pending is True
        assert cfg.session_ingest_section_map == {"Key Decisions": "decisions"}

    def test_to_dict_roundtrip(self) -> None:
        cfg = WikiConfig(
            enabled=True,
            wiki_dir=Path("/tmp/w"),
            reingest_cooldown_hours=12,
            bootstrap_pending=False,
            session_ingest_section_map={"X": "y"},
        )
        restored = WikiConfig.from_dict(cfg.to_dict())
        assert restored == cfg

    def test_from_dict_gate_defaults(self) -> None:
        cfg = WikiConfig.from_dict({})
        assert cfg.session_ingest_gate.decisions_min == 1
        assert cfg.session_ingest_gate.insights_min == 1
        assert cfg.session_ingest_gate.word_count_min == 300

    def test_from_dict_gate_custom(self) -> None:
        cfg = WikiConfig.from_dict(
            {
                "session_ingest": {
                    "section_map": {},
                    "gate": {"decisions_min": 2, "insights_min": 0, "word_count_min": 150},
                }
            }
        )
        assert cfg.session_ingest_gate.decisions_min == 2
        assert cfg.session_ingest_gate.insights_min == 0
        assert cfg.session_ingest_gate.word_count_min == 150

    def test_to_dict_includes_gate(self) -> None:
        cfg = WikiConfig(
            session_ingest_gate=SessionIngestGate(
                decisions_min=3, insights_min=2, word_count_min=400
            )
        )
        d = cfg.to_dict()
        assert d["session_ingest"]["gate"] == {
            "decisions_min": 3,
            "insights_min": 2,
            "word_count_min": 400,
        }

    def test_to_dict_roundtrip_with_gate(self) -> None:
        cfg = WikiConfig(
            enabled=True,
            wiki_dir=Path("/tmp/w"),
            reingest_cooldown_hours=12,
            bootstrap_pending=False,
            session_ingest_section_map={"X": "y"},
            session_ingest_gate=SessionIngestGate(
                decisions_min=2, insights_min=1, word_count_min=500
            ),
        )
        restored = WikiConfig.from_dict(cfg.to_dict())
        assert restored == cfg


class TestProfile:
    def test_builtin_software_shape(self) -> None:
        # software profile must have exactly these 5 categories
        p = Profile(
            name="software",
            categories=["concepts", "decisions", "references", "pitfalls", "entities"],
            session_section_map_default={"Key Decisions": "decisions"},
        )
        assert "decisions" in p.categories
        assert p.name == "software"

    def test_categories_must_be_nonempty_unless_minimal(self) -> None:
        with pytest.raises(ValueError, match="categories cannot be empty"):
            Profile(name="custom", categories=[], session_section_map_default={})

    def test_minimal_profile_empty_categories_allowed(self) -> None:
        # minimal profile explicitly allows empty categories (flat pages/)
        p = Profile(name="minimal", categories=[], session_section_map_default={})
        assert p.categories == []


class TestPage:
    def test_from_frontmatter_body(self) -> None:
        fm = {
            "title": "Hooks architecture",
            "tags": ["hooks", "plugin"],
            "links_to": ["router"],
            "scope": ["project:cpm"],
            "sources": [
                {
                    "type": "file",
                    "ref": "/tmp/x.md",
                    "ingested_at": "2026-04-23T10:00:00Z",
                }
            ],
            "last_ingested": "2026-04-23T10:00:00Z",
        }
        body = "# Hooks\n\nContent."
        p = Page(path=Path("/tmp/hooks.md"), frontmatter=fm, body=body)
        assert p.title == "Hooks architecture"
        assert "hooks" in p.tags
        assert p.scope == ["project:cpm"]

    def test_slug_from_filename(self) -> None:
        p = Page(
            path=Path("/tmp/pages/concepts/hooks-architecture.md"),
            frontmatter={"title": "X"},
            body="",
        )
        assert p.slug == "hooks-architecture"

    def test_category_from_path(self) -> None:
        p = Page(
            path=Path("/tmp/pages/concepts/hooks-architecture.md"),
            frontmatter={"title": "X"},
            body="",
        )
        assert p.category == "concepts"

    def test_category_none_for_flat(self) -> None:
        p = Page(path=Path("/tmp/pages/hooks.md"), frontmatter={"title": "X"}, body="")
        assert p.category is None


class TestPageScopeStringBranch:
    def test_scope_accepts_plain_string(self, tmp_path: Path) -> None:
        page = Page(
            path=tmp_path / "pages" / "concepts" / "foo.md",
            frontmatter={"scope": "global", "tags": [], "title": "Foo"},
            body="",
        )
        assert page.scope == ["global"]


class TestPageCategoryBranch:
    def test_category_returns_none_when_path_has_no_pages_segment(self, tmp_path: Path) -> None:
        # Flat layout: path has no 'pages' dir between wiki root and file.
        page = Page(
            path=tmp_path / "foo.md",
            frontmatter={"title": "Foo"},
            body="",
        )
        assert page.category is None

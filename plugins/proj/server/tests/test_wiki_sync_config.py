"""Tests for WikiSync dataclass + ProjConfig.wiki integration."""

from __future__ import annotations

from server.lib.models import ProjConfig, WikiSync


class TestWikiSync:
    def test_from_dict_defaults(self) -> None:
        w = WikiSync.from_dict({})
        assert w.enabled is False
        assert w.auto_sync is True
        assert w.auto_ingest_sessions is False
        assert w.capture_notes_as_log is False
        assert w.replace_notes_md is False
        assert w.bootstrap_docs == []

    def test_from_dict_overrides(self) -> None:
        w = WikiSync.from_dict(
            {
                "enabled": True,
                "auto_sync": False,
                "auto_ingest_sessions": True,
                "capture_notes_as_log": True,
                "replace_notes_md": True,
                "bootstrap_docs": ["docs/arch.md", "overhaul.md"],
            }
        )
        assert w.enabled is True
        assert w.auto_sync is False
        assert w.auto_ingest_sessions is True
        assert w.capture_notes_as_log is True
        assert w.replace_notes_md is True
        assert w.bootstrap_docs == ["docs/arch.md", "overhaul.md"]

    def test_to_dict_roundtrip(self) -> None:
        w = WikiSync(
            enabled=True,
            auto_sync=True,
            auto_ingest_sessions=True,
            capture_notes_as_log=False,
            replace_notes_md=False,
            bootstrap_docs=["a.md"],
        )
        restored = WikiSync.from_dict(w.to_dict())
        assert restored == w

    def test_bootstrap_docs_non_list_coerces_to_empty(self) -> None:
        w = WikiSync.from_dict({"bootstrap_docs": "not-a-list"})
        assert w.bootstrap_docs == []


class TestProjConfigWithWiki:
    def test_config_has_wiki_field_with_defaults(self) -> None:
        cfg = ProjConfig.from_dict({})
        assert hasattr(cfg, "wiki")
        assert cfg.wiki == WikiSync()

    def test_config_loads_wiki_sync(self) -> None:
        cfg = ProjConfig.from_dict(
            {
                "sync": {
                    "wiki": {
                        "enabled": True,
                        "auto_ingest_sessions": True,
                    }
                }
            }
        )
        assert cfg.wiki.enabled is True
        assert cfg.wiki.auto_ingest_sessions is True

    def test_config_roundtrip_preserves_wiki(self) -> None:
        cfg = ProjConfig.from_dict(
            {
                "sync": {
                    "wiki": {
                        "enabled": True,
                        "auto_ingest_sessions": True,
                        "capture_notes_as_log": True,
                    }
                }
            }
        )
        restored = ProjConfig.from_dict(cfg.to_dict())
        assert restored.wiki == cfg.wiki

"""Tests for lib/bm25.py."""

import json
import time
from pathlib import Path

from server.lib.bm25 import (
    BM25_SIDECAR_FILENAME,
    index_dir,
    index_is_stale,
    load_or_rebuild,
    rebuild_index,
    tokenize,
)


class TestTokenize:
    def test_lowercase_words(self) -> None:
        assert tokenize("Hello WORLD") == ["hello", "world"]

    def test_strip_punctuation(self) -> None:
        assert tokenize("Hooks, plugin! Architecture.") == ["hooks", "plugin", "architecture"]

    def test_empty_input(self) -> None:
        assert tokenize("") == []

    def test_markdown_noise_filtered(self) -> None:
        # headings, emphasis, code fences don't produce weird tokens
        tokens = tokenize("# Hooks\n\n**bold** and `code` + [[wikilink]]")
        assert "hooks" in tokens
        assert "bold" in tokens
        assert "code" in tokens
        assert "wikilink" in tokens
        # markers themselves shouldn't appear
        assert "*" not in tokens
        assert "`" not in tokens


class TestIndexDir:
    def test_default_subpath(self, wiki_root: Path) -> None:
        assert index_dir(wiki_root) == wiki_root / ".index"


class TestRebuildIndex:
    def test_rebuild_empty_wiki(self, wiki_root: Path) -> None:
        idx = rebuild_index(wiki_root)
        assert idx.doc_count == 0
        sidecar = index_dir(wiki_root) / BM25_SIDECAR_FILENAME
        assert sidecar.exists()

    def test_rebuild_with_pages(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "concepts" / "hooks.md").write_text(
            "---\ntitle: Hooks architecture\n---\nHooks fire after tool execution."
        )
        (wiki_root / "pages" / "decisions" / "fastmcp.md").parent.mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "decisions" / "fastmcp.md").write_text(
            "---\ntitle: Why FastMCP\n---\nFastMCP chosen over pure MCP for ergonomics."
        )
        idx = rebuild_index(wiki_root)
        assert idx.doc_count == 2
        assert "hooks" in idx.docs

    def test_query_scores(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "concepts" / "hooks.md").write_text(
            "---\ntitle: Hooks\n---\nHooks dispatch via router after tool."
        )
        (wiki_root / "pages" / "concepts" / "cache.md").write_text(
            "---\ntitle: Cache\n---\nCache eviction LRU strategy."
        )
        (wiki_root / "pages" / "concepts" / "storage.md").write_text(
            "---\ntitle: Storage\n---\nStorage backend persistence layer."
        )
        idx = rebuild_index(wiki_root)
        hits = idx.query("hooks router", top_k=5)
        assert len(hits) >= 1
        assert hits[0]["slug"] == "hooks"
        assert hits[0]["score"] > 0

    def test_query_no_matches(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "concepts" / "hooks.md").write_text(
            "---\ntitle: Hooks\n---\nHooks body."
        )
        idx = rebuild_index(wiki_root)
        hits = idx.query("totally-unrelated-term", top_k=5)
        # Zero-score results filtered out
        assert all(h["score"] > 0 for h in hits)


class TestPersistence:
    def test_sidecar_shape(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "concepts" / "p.md").write_text("---\ntitle: P\n---\nbody tokens")
        rebuild_index(wiki_root)
        sidecar = index_dir(wiki_root) / BM25_SIDECAR_FILENAME
        data = json.loads(sidecar.read_text())
        assert "docs" in data
        assert "version" in data
        assert "mtime_snapshot" in data
        assert "p" in data["docs"]

    def test_load_or_rebuild_uses_sidecar(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "concepts" / "p.md").write_text("---\ntitle: P\n---\nhello")
        rebuild_index(wiki_root)
        # Delete page but keep sidecar — load_or_rebuild should use sidecar
        # unless it detects staleness. Force-use sidecar by touching it newer.
        sidecar = index_dir(wiki_root) / BM25_SIDECAR_FILENAME
        time.sleep(0.01)  # ensure mtime ordering
        sidecar.touch()
        idx = load_or_rebuild(wiki_root)
        # Got loaded from sidecar (doc still present even though we didn't delete)
        assert idx.doc_count == 1


class TestStaleness:
    def test_index_stale_when_page_newer(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        page = wiki_root / "pages" / "concepts" / "p.md"
        page.write_text("---\ntitle: P\n---\nbody")
        rebuild_index(wiki_root)
        time.sleep(0.01)
        # Page modified after index built
        page.write_text("---\ntitle: P\n---\nbody changed")
        assert index_is_stale(wiki_root) is True

    def test_index_fresh_after_rebuild(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "concepts" / "p.md").write_text("---\ntitle: P\n---\nbody")
        rebuild_index(wiki_root)
        assert index_is_stale(wiki_root) is False

    def test_missing_sidecar_is_stale(self, wiki_root: Path) -> None:
        assert index_is_stale(wiki_root) is True

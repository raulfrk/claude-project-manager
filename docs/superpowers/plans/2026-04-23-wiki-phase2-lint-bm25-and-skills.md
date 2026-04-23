# Wiki Plugin Phase 2: Lint + BM25 Search + Standalone Skills — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 7 Tier-1 lint MCP tools + the BM25 search layer (2 MCP tools) + 3 user-facing standalone skills (`/wiki:init`, `/wiki:query`, `/wiki:lint`). At end of Phase 2, a user can install the wiki plugin, run `/wiki:init` interactively to create the wiki, query it with `/wiki:query`, and lint it with `/wiki:lint`. No ingest, no bootstrap, no proj integration yet — those are Phase 3/4.

**Architecture:** Adds two new tool modules to `plugins/wiki/server/server/tools/` (`lint.py`, `search.py`) + one new lib module (`lib/bm25.py`) wrapping `rank-bm25`. BM25 index is a sidecar at `~/.claude/wiki/.index/bm25.json` (git-ignored). Lazy-rebuild: `wiki_search_bm25` checks if any page is newer than the index mtime and rebuilds if stale. Skills live at `plugins/wiki/skills/<skill>/SKILL.md`, written in caveman-ultra per cpm convention, calling MCP tools by full name (`mcp__plugin_wiki_wiki__*`). No router hook registration in Phase 2.

**Tech Stack:** Python 3.12, `rank-bm25` (new dep), FastMCP, `mcp.server.fastmcp`, PyYAML (existing), pytest + pytest-asyncio + pytest-cov (existing).

**Spec reference:** `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` — Phase 2 = §15 "Phase 2: Lint + BM25 + standalone skills". Prior plan: `docs/superpowers/plans/2026-04-23-wiki-phase1-core-tools-and-storage.md` (Phase 1 complete at commit `101e2e0`).

---

## Scope (what's IN Phase 2, what's OUT)

**IN:**
- `lib/bm25.py` — BM25 index builder (wraps `rank-bm25`), tokenizer, sidecar persistence at `.index/bm25.json`, staleness check
- `tools/search.py` — `wiki_search_bm25`, `wiki_search_index_refresh` (MCP tools)
- `tools/lint.py` — 7 lint MCP tools: `wiki_lint_orphans`, `wiki_lint_broken_links`, `wiki_lint_broken_section_refs`, `wiki_lint_category_violations`, `wiki_lint_stale`, `wiki_lint_schema`, `wiki_lint_duplicates`
- `plugins/wiki/skills/init/SKILL.md` — interactive wiki init (profile prompt + creates wiki.yaml + wiki/config.yaml + empty index.md + empty log.md)
- `plugins/wiki/skills/query/SKILL.md` — LLM-driven query w/ BM25 seed + LLM-reads, citations, optional `--raw` / `--file-back` / `--scope` flags
- `plugins/wiki/skills/lint/SKILL.md` — interactive Tier-1 lint: runs all 7 lint tools, presents findings, prompts user to fix / skip per item
- `rank-bm25` dependency added to `pyproject.toml`
- Unit tests for all 9 new MCP tools (target ≥85% coverage across plugin)
- Register new tools in `main.py`

**OUT (later phases):**
- `/wiki:ingest` + source readers — Phase 3
- `/wiki:bootstrap` + `/wiki:promote` — Phase 3
- Tier-2 semantic lint (contradictions, deprecation, cross-ref suggestions, category-cluster suggestions) — Phase 4
- `/proj:save` integration, router hooks, wizard — Phase 4
- `file-todo` fix option in `/wiki:lint` (needs proj integration) — Phase 4 (skill gracefully hides it when proj unavailable)
- Vector DB — deferred, tracked in todo 701

---

## File Structure

All paths relative to repo root (work happens in worktree `/home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin`).

```
plugins/wiki/
├── server/
│   ├── pyproject.toml            # Modify: add rank-bm25 dep
│   └── server/
│       ├── lib/
│       │   └── bm25.py           # NEW — BM25 index + tokenizer + persistence
│       ├── tools/
│       │   ├── search.py         # NEW — wiki_search_bm25 + wiki_search_index_refresh
│       │   └── lint.py           # NEW — 7 lint tools
│       └── main.py               # Modify: register search + lint modules
│   └── tests/
│       ├── test_bm25.py          # NEW — lib/bm25.py unit tests
│       ├── test_search.py        # NEW — search tools tests
│       ├── test_lint_orphans.py  # NEW
│       ├── test_lint_broken_links.py  # NEW (covers page + section)
│       ├── test_lint_category_violations.py  # NEW
│       ├── test_lint_stale.py    # NEW
│       ├── test_lint_schema.py   # NEW
│       └── test_lint_duplicates.py  # NEW
└── skills/                       # NEW directory
    ├── init/SKILL.md             # /wiki:init
    ├── query/SKILL.md            # /wiki:query
    └── lint/SKILL.md             # /wiki:lint
```

**Responsibilities:**
- `lib/bm25.py` — tokenize markdown bodies (simple regex-based lowercase word split), build `BM25Okapi` from token lists, persist (doc_id, tokens) pairs to `.index/bm25.json`, load from sidecar + rebuild when stale.
- `tools/search.py::wiki_search_bm25` — accepts query, tokenizes, runs `bm25.get_scores(query_tokens)`, returns top-k hits with scores + snippets. Rebuilds index if stale.
- `tools/search.py::wiki_search_index_refresh` — forces full rebuild (scans pages/, re-tokenizes, overwrites sidecar).
- `tools/lint.py` — one function per lint check. Each is pure-data (no LLM). All return JSON-serializable findings.
- Skills — caveman-ultra prose guiding the LLM; invoke MCP tools by full mcp__plugin_wiki_wiki__* name.

---

## Task Breakdown

17 tasks total.

---

### Task 1: Add `rank-bm25` dependency

**Goal:** Add the BM25 library + re-sync lockfile.

**Files:**
- Modify: `plugins/wiki/server/pyproject.toml` — add `rank-bm25>=0.2.2` to `dependencies`
- Modify: `plugins/wiki/server/uv.lock` (regenerated)

- [ ] **Step 1.1: Edit pyproject.toml**

In `plugins/wiki/server/pyproject.toml`, locate the `[project] dependencies` block and add `rank-bm25>=0.2.2`:

```toml
dependencies = [
    "mcp>=1.0.0",
    "pyyaml>=6.0",
    "rank-bm25>=0.2.2",
    "claude-hook-transport",
]
```

- [ ] **Step 1.2: Re-sync lockfile**

```bash
cd plugins/wiki/server && uv sync --all-groups
```
Expected: adds rank-bm25 + numpy transitive dep; `uv.lock` updated.

- [ ] **Step 1.3: Verify import works**

```bash
cd plugins/wiki/server && uv run python -c "from rank_bm25 import BM25Okapi; print(BM25Okapi)"
```
Expected: prints `<class 'rank_bm25.BM25Okapi'>`.

- [ ] **Step 1.4: just check clean**

```bash
cd plugins/wiki/server && just check
```
Expected: 0 errors.

- [ ] **Step 1.5: Commit**

```bash
git add plugins/wiki/server/pyproject.toml plugins/wiki/server/uv.lock
git commit -m "feat(wiki/688): add rank-bm25 dep for Phase 2 BM25 search"
```

---

### Task 2: `lib/bm25.py` — BM25 index builder

**Goal:** Build, persist, and query a BM25 index over the wiki's markdown pages. Lazy rebuild when stale.

**Files:**
- Create: `plugins/wiki/server/server/lib/bm25.py`
- Create: `plugins/wiki/server/tests/test_bm25.py`

- [ ] **Step 2.1: Write failing tests**

File: `plugins/wiki/server/tests/test_bm25.py`
```python
"""Tests for lib/bm25.py."""
import json
import time
from pathlib import Path

import pytest

from server.lib.bm25 import (
    BM25Index,
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
        (wiki_root / "pages" / "decisions" / "fastmcp.md").parent.mkdir(
            parents=True, exist_ok=True
        )
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
            "---\ntitle: Cache\n---\nCache eviction LRU."
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
        (wiki_root / "pages" / "concepts" / "p.md").write_text(
            "---\ntitle: P\n---\nbody tokens"
        )
        rebuild_index(wiki_root)
        sidecar = index_dir(wiki_root) / BM25_SIDECAR_FILENAME
        data = json.loads(sidecar.read_text())
        assert "docs" in data
        assert "version" in data
        assert "mtime_snapshot" in data
        assert "p" in data["docs"]

    def test_load_or_rebuild_uses_sidecar(self, wiki_root: Path) -> None:
        (wiki_root / "pages" / "concepts").mkdir(parents=True, exist_ok=True)
        (wiki_root / "pages" / "concepts" / "p.md").write_text(
            "---\ntitle: P\n---\nhello"
        )
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
        (wiki_root / "pages" / "concepts" / "p.md").write_text(
            "---\ntitle: P\n---\nbody"
        )
        rebuild_index(wiki_root)
        assert index_is_stale(wiki_root) is False

    def test_missing_sidecar_is_stale(self, wiki_root: Path) -> None:
        assert index_is_stale(wiki_root) is True
```

- [ ] **Step 2.2: Run tests; verify fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_bm25.py -v
```
Expected: ImportError.

- [ ] **Step 2.3: Write bm25.py**

File: `plugins/wiki/server/server/lib/bm25.py`
```python
"""BM25 index over wiki pages. Sidecar persistence at .index/bm25.json.

Lazy-rebuild via load_or_rebuild + is_stale. Uses rank-bm25 (pure Python).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from rank_bm25 import BM25Okapi

from server.lib import frontmatter as fm_mod
from server.lib import storage

BM25_SIDECAR_FILENAME = "bm25.json"
_SCHEMA_VERSION = 1

# Lowercase alphanumeric word tokens; drops markdown markers + punctuation.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def index_dir(wiki_dir: Path) -> Path:
    return wiki_dir / ".index"


def sidecar_path(wiki_dir: Path) -> Path:
    return index_dir(wiki_dir) / BM25_SIDECAR_FILENAME


def tokenize(text: str) -> list[str]:
    """Lowercase tokenizer. Strips punctuation + markdown markers. Returns word tokens."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class BM25Index:
    """In-memory BM25 index. Use rebuild_index / load_or_rebuild to construct."""

    docs: dict[str, list[str]] = field(default_factory=dict)  # slug → tokens
    _bm25: BM25Okapi | None = None
    _slugs: list[str] = field(default_factory=list)

    @property
    def doc_count(self) -> int:
        return len(self.docs)

    def build(self) -> None:
        """Rebuild the BM25Okapi instance from self.docs."""
        self._slugs = sorted(self.docs.keys())
        corpus = [self.docs[slug] for slug in self._slugs] if self._slugs else [[""]]
        self._bm25 = BM25Okapi(corpus)

    def query(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        """Return top-k hits as [{slug, score, snippet}]. Zero-score hits excluded."""
        if self._bm25 is None or not self._slugs:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            [(slug, float(score)) for slug, score in zip(self._slugs, scores, strict=True)],
            key=lambda x: x[1],
            reverse=True,
        )
        hits: list[dict[str, Any]] = []
        for slug, score in ranked[:top_k]:
            if score <= 0:
                continue
            hits.append({"slug": slug, "score": score, "snippet": ""})
        return hits


def _collect_page_tokens(wiki_dir: Path) -> dict[str, list[str]]:
    """Walk pages/, tokenize each page's title + body. Returns slug → tokens."""
    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        return {}
    docs: dict[str, list[str]] = {}
    for md in pages_root.rglob("*.md"):
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        title = str(fm.get("title", ""))
        text = f"{title}\n\n{body}"
        docs[md.stem] = tokenize(text)
    return docs


def _pages_latest_mtime(wiki_dir: Path) -> float:
    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        return 0.0
    latest = 0.0
    for md in pages_root.rglob("*.md"):
        latest = max(latest, md.stat().st_mtime)
    return latest


def rebuild_index(wiki_dir: Path) -> BM25Index:
    """Full rebuild: scan pages/, tokenize, write sidecar, return in-memory index."""
    idx_dir = index_dir(wiki_dir)
    idx_dir.mkdir(parents=True, exist_ok=True)
    docs = _collect_page_tokens(wiki_dir)
    snapshot = _pages_latest_mtime(wiki_dir)
    data: dict[str, Any] = {
        "version": _SCHEMA_VERSION,
        "mtime_snapshot": snapshot,
        "docs": docs,
    }
    sidecar = sidecar_path(wiki_dir)
    with storage.wiki_lock(wiki_dir):
        storage.atomic_write(sidecar, json.dumps(data, separators=(",", ":")))

    idx = BM25Index(docs=docs)
    idx.build()
    return idx


def load_or_rebuild(wiki_dir: Path) -> BM25Index:
    """Load sidecar into an index; rebuild if missing or stale."""
    sidecar = sidecar_path(wiki_dir)
    if index_is_stale(wiki_dir):
        return rebuild_index(wiki_dir)
    try:
        data = json.loads(sidecar.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return rebuild_index(wiki_dir)
    docs = cast("dict[str, list[str]]", data.get("docs", {}))
    idx = BM25Index(docs=docs)
    idx.build()
    return idx


def index_is_stale(wiki_dir: Path) -> bool:
    """True when sidecar is missing or any page is newer than the recorded snapshot."""
    sidecar = sidecar_path(wiki_dir)
    if not sidecar.exists():
        return True
    try:
        data = json.loads(sidecar.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return True
    snapshot = float(data.get("mtime_snapshot", 0.0))
    latest = _pages_latest_mtime(wiki_dir)
    # Use 0.001s tolerance to avoid spurious staleness on identical timestamps.
    return latest > snapshot + 0.001
```

- [ ] **Step 2.4: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_bm25.py -v
```
Expected: all tests pass (12 tests).

- [ ] **Step 2.5: Commit**

```bash
git add plugins/wiki/server/server/lib/bm25.py plugins/wiki/server/tests/test_bm25.py
git commit -m "feat(wiki/688): add BM25 index lib with sidecar persistence + staleness check"
```

---

### Task 3: `tools/search.py::wiki_search_bm25`

**Goal:** MCP tool wrapping `bm25.load_or_rebuild` + `BM25Index.query`. Filters by category/tags/scope_filter applied post-ranking.

**Files:**
- Create: `plugins/wiki/server/server/tools/search.py`
- Create: `plugins/wiki/server/tests/test_search.py`
- Modify: `plugins/wiki/server/tests/conftest.py` — register `search` in `mcp_app`

- [ ] **Step 3.1: Register search in conftest mcp_app**

Edit `plugins/wiki/server/tests/conftest.py`. Update the `mcp_app` fixture:

```python
@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    from server.tools import index, links, log, page, scope, search

    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    log.register(mcp)
    index.register(mcp)
    links.register(mcp)
    scope.register(mcp)
    search.register(mcp)
    return mcp
```

- [ ] **Step 3.2: Write failing tests**

File: `plugins/wiki/server/tests/test_search.py`
```python
"""Tests for wiki_search_bm25 + wiki_search_index_refresh."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


def _write_page(wiki_dir: Path, category: str, slug: str, body: str, **fm_extras) -> None:
    import yaml
    fm: dict = {
        "title": slug.replace("-", " ").title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    fm.update(fm_extras)
    path = wiki_dir / "pages" / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{yaml.safe_dump(fm)}---\n{body}")


@pytest.mark.asyncio
class TestWikiSearchBM25:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="anything"))
        assert result["hits"] == []

    async def test_basic_keyword_search(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks", "Hooks dispatch via router.")
        _write_page(wiki_setup["wiki_dir"], "concepts", "cache", "Cache uses LRU eviction.")
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="router"))
        assert len(result["hits"]) >= 1
        assert result["hits"][0]["slug"] == "hooks"

    async def test_limit_respected(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        for i in range(5):
            _write_page(wiki_setup["wiki_dir"], "concepts", f"p{i}", f"content-word p{i}")
        result = json.loads(await call_tool(
            mcp_app, "wiki_search_bm25", query="content-word", limit=2
        ))
        assert len(result["hits"]) <= 2

    async def test_filter_by_category(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks-c", "router hooks here")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks-d", "router decisions about hooks")
        result = json.loads(await call_tool(
            mcp_app, "wiki_search_bm25", query="hooks", category="concepts"
        ))
        slugs = [h["slug"] for h in result["hits"]]
        assert "hooks-c" in slugs
        assert "hooks-d" not in slugs

    async def test_filter_by_tags(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "shared-token body", tags=["x"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "shared-token body", tags=["y"])
        result = json.loads(await call_tool(
            mcp_app, "wiki_search_bm25", query="shared-token", tags=["x"]
        ))
        slugs = [h["slug"] for h in result["hits"]]
        assert slugs == ["a"]

    async def test_filter_by_scope(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "scope-token", scope=["project:cpm"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "scope-token", scope=["global"])
        result = json.loads(await call_tool(
            mcp_app, "wiki_search_bm25", query="scope-token", scope_filter="project:cpm"
        ))
        assert [h["slug"] for h in result["hits"]] == ["a"]

    async def test_snippet_populated(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks",
                    "Hooks plugin architecture is centralized.")
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="centralized"))
        assert len(result["hits"]) == 1
        assert "centralized" in result["hits"][0]["snippet"].lower()

    async def test_rebuilds_on_staleness(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # First search builds + caches index
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "alpha beta")
        await call_tool(mcp_app, "wiki_search_bm25", query="alpha")
        # Add a new page; search should auto-rebuild and find it
        import time
        time.sleep(0.01)
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "beta gamma")
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="gamma"))
        assert any(h["slug"] == "b" for h in result["hits"])
```

- [ ] **Step 3.3: Run tests; verify fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_search.py -v
```
Expected: tool-not-registered / ImportError.

- [ ] **Step 3.4: Write search.py (with both tools — will flesh refresh in next task)**

File: `plugins/wiki/server/server/tools/search.py`
```python
"""BM25 search MCP tools: wiki_search_bm25 + wiki_search_index_refresh."""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

from server.lib import bm25 as bm25_mod
from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
else:
    from mcp.server.fastmcp import FastMCP  # noqa: TC002


_SNIPPET_CTX_CHARS = 80


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_search_bm25)
    mcp.tool()(wiki_search_index_refresh)


def _extract_snippet(body: str, query_tokens: list[str]) -> str:
    """Grab a small window around the first query-token occurrence."""
    low = body.lower()
    for tok in query_tokens:
        idx = low.find(tok)
        if idx >= 0:
            start = max(0, idx - _SNIPPET_CTX_CHARS)
            end = min(len(body), idx + len(tok) + _SNIPPET_CTX_CHARS)
            return body[start:end].replace("\n", " ").strip()
    return body[:160].replace("\n", " ").strip()


def _page_metadata(
    wiki_dir,
    slug: str,
) -> tuple[str | None, dict[str, Any], str]:
    """Return (category, frontmatter, body) for a given slug, or (None, {}, '') if missing."""
    pages_root = storage.pages_dir(wiki_dir)
    for md in pages_root.rglob(f"{slug}.md"):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else None
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            return None, {}, ""
        return cat, fm, body
    return None, {}, ""


def wiki_search_bm25(
    query: str,
    limit: int = 20,
    category: str | None = None,
    tags: list[str] | None = None,
    scope_filter: str | None = None,
) -> str:
    """BM25 keyword search over wiki pages. Filters applied post-ranking.

    Returns JSON {hits: [{slug, score, snippet, category, tags, scope}]}.
    """
    cfg = config_mod.load_config()
    idx = bm25_mod.load_or_rebuild(cfg.wiki_dir)
    raw_hits = idx.query(query, top_k=limit * 3 if (category or tags or scope_filter) else limit)

    query_tokens = bm25_mod.tokenize(query)
    tag_set = set(tags or [])
    results: list[dict[str, Any]] = []
    for hit in raw_hits:
        cat, fm, body = _page_metadata(cfg.wiki_dir, hit["slug"])
        if cat is None:
            continue
        if category and cat != category:
            continue
        page_tags = set(fm.get("tags", []) or [])
        if tag_set and not tag_set.issubset(page_tags):
            continue
        page_scope = fm.get("scope", []) or []
        if scope_filter and scope_filter not in page_scope:
            continue
        results.append({
            "slug": hit["slug"],
            "score": hit["score"],
            "snippet": _extract_snippet(body, query_tokens),
            "category": cat,
            "tags": list(page_tags),
            "scope": page_scope,
        })
        if len(results) >= limit:
            break
    return json.dumps({"hits": results})


def wiki_search_index_refresh() -> str:
    """Force full rebuild of the BM25 sidecar index."""
    cfg = config_mod.load_config()
    start = time.monotonic()
    idx = bm25_mod.rebuild_index(cfg.wiki_dir)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return json.dumps({"pages_indexed": idx.doc_count, "elapsed_ms": elapsed_ms})
```

- [ ] **Step 3.5: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_search.py -v
```
Expected: 8 tests pass.

- [ ] **Step 3.6: Commit**

```bash
git add plugins/wiki/server/server/tools/search.py plugins/wiki/server/tests/test_search.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): add wiki_search_bm25 + wiki_search_index_refresh MCP tools"
```

---

### Task 4: `wiki_search_index_refresh` explicit tests

**Goal:** The refresh tool was added in Task 3's search.py, but needs its own targeted tests (doc count return, timing, sidecar regeneration).

**Files:**
- Modify: `plugins/wiki/server/tests/test_search.py` — add `TestWikiSearchIndexRefresh` class

- [ ] **Step 4.1: Add tests for index_refresh**

Append to `plugins/wiki/server/tests/test_search.py`:

```python
@pytest.mark.asyncio
class TestWikiSearchIndexRefresh:
    async def test_empty_wiki_returns_zero(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_search_index_refresh"))
        assert result["pages_indexed"] == 0
        assert "elapsed_ms" in result

    async def test_counts_pages(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "alpha")
        _write_page(wiki_setup["wiki_dir"], "decisions", "b", "beta")
        result = json.loads(await call_tool(mcp_app, "wiki_search_index_refresh"))
        assert result["pages_indexed"] == 2

    async def test_regenerates_sidecar(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "alpha")
        sidecar = wiki_setup["wiki_dir"] / ".index" / "bm25.json"
        await call_tool(mcp_app, "wiki_search_index_refresh")
        assert sidecar.exists()
        # Delete and re-refresh: sidecar should regenerate
        sidecar.unlink()
        await call_tool(mcp_app, "wiki_search_index_refresh")
        assert sidecar.exists()
```

- [ ] **Step 4.2: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_search.py -v
```
Expected: 11 tests pass (8 BM25 + 3 refresh).

- [ ] **Step 4.3: Commit**

```bash
git add plugins/wiki/server/tests/test_search.py
git commit -m "test(wiki/688): add explicit wiki_search_index_refresh tests"
```

---

### Task 5: `tools/lint.py` — orphans + module scaffold

**Goal:** Start the lint module with `wiki_lint_orphans` (pages with 0 inbound + 0 outbound links).

**Files:**
- Create: `plugins/wiki/server/server/tools/lint.py`
- Create: `plugins/wiki/server/tests/test_lint_orphans.py`
- Modify: `plugins/wiki/server/tests/conftest.py` — register `lint` in `mcp_app`

- [ ] **Step 5.1: Register lint in conftest mcp_app**

Update `mcp_app` fixture in `plugins/wiki/server/tests/conftest.py`:

```python
@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    from server.tools import index, lint, links, log, page, scope, search

    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    log.register(mcp)
    index.register(mcp)
    links.register(mcp)
    scope.register(mcp)
    search.register(mcp)
    lint.register(mcp)
    return mcp
```

- [ ] **Step 5.2: Write failing tests**

File: `plugins/wiki/server/tests/test_lint_orphans.py`
```python
"""Tests for wiki_lint_orphans."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintOrphans:
    async def test_empty_wiki_no_orphans(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        assert result["orphans"] == []

    async def test_single_page_is_orphan(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "alone")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        # With default orphan_min_page_count=3, a single-page wiki doesn't report orphans.
        assert result["orphans"] == []

    async def test_orphan_detected_above_threshold(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Write 3 pages: 2 linked together, 1 orphan
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b")
        _write_page(wiki_setup["wiki_dir"], "concepts", "alone")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        slugs = sorted(p["slug"] for p in result["orphans"])
        assert slugs == ["alone"]

    async def test_page_with_only_inbound_not_orphan(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b")  # no outlinks, has inlink from a
        _write_page(wiki_setup["wiki_dir"], "concepts", "c")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        slugs = [p["slug"] for p in result["orphans"]]
        assert "b" not in slugs
        assert "c" in slugs

    async def test_threshold_configurable_via_config_yaml(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Lower orphan threshold to 1 via wiki/config.yaml
        import yaml
        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        data = yaml.safe_load(cfg_path.read_text())
        data.setdefault("lint", {})["orphan_min_page_count"] = 1
        cfg_path.write_text(yaml.safe_dump(data))

        _write_page(wiki_setup["wiki_dir"], "concepts", "alone")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        assert len(result["orphans"]) == 1
```

- [ ] **Step 5.3: Run tests; verify fail**

- [ ] **Step 5.4: Write lint.py with wiki_lint_orphans**

File: `plugins/wiki/server/server/tools/lint.py`
```python
"""Tier-1 lint MCP tools (pure-data, no LLM).

Each tool returns JSON-serializable findings. Tier-2 semantic checks live in
skill prompts (Phase 4), not here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
else:
    from mcp.server.fastmcp import FastMCP  # noqa: TC002


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)


def _load_lint_config(wiki_dir: Path) -> dict[str, Any]:
    """Load wiki/config.yaml's lint section. Returns defaults if missing."""
    cfg_path = wiki_dir / "config.yaml"
    defaults: dict[str, Any] = {
        "stale_after_days": 90,
        "orphan_min_page_count": 3,
    }
    if not cfg_path.exists():
        return defaults
    try:
        data = yaml.safe_load(cfg_path.read_text()) or {}
    except yaml.YAMLError:
        return defaults
    lint_section = data.get("lint", {}) if isinstance(data, dict) else {}
    merged = {**defaults, **(lint_section if isinstance(lint_section, dict) else {})}
    return merged


def _iter_pages(wiki_dir: Path):
    """Yield (path, frontmatter, body) for every parseable page under pages/."""
    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        return
    for md in sorted(pages_root.rglob("*.md")):
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        yield md, fm, body


def wiki_lint_orphans() -> str:
    """Pages with 0 inbound + 0 outbound links_to refs.

    Skipped when total page count < lint.orphan_min_page_count (default 3).
    Returns JSON {orphans: [{slug, category, path}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    lint_cfg = _load_lint_config(wiki_dir)
    min_pages = int(lint_cfg.get("orphan_min_page_count", 3))

    pages: list[tuple[Path, dict[str, Any], str]] = list(_iter_pages(wiki_dir))
    if len(pages) < min_pages:
        return json.dumps({"orphans": []})

    inbound: dict[str, int] = {}
    for _, fm, _ in pages:
        for target in (fm.get("links_to", []) or []):
            inbound[str(target)] = inbound.get(str(target), 0) + 1

    pages_root = storage.pages_dir(wiki_dir)
    orphans: list[dict[str, Any]] = []
    for md, fm, _ in pages:
        slug = md.stem
        outlinks = fm.get("links_to", []) or []
        if not outlinks and inbound.get(slug, 0) == 0:
            rel = md.relative_to(pages_root)
            cat = rel.parts[0] if len(rel.parts) > 1 else None
            orphans.append({"slug": slug, "category": cat, "path": str(md)})
    return json.dumps({"orphans": orphans})
```

- [ ] **Step 5.5: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_lint_orphans.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5.6: Commit**

```bash
git add plugins/wiki/server/server/tools/lint.py plugins/wiki/server/tests/test_lint_orphans.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): add wiki_lint_orphans with config-driven threshold"
```

---

### Task 6: `wiki_lint_broken_links` + `wiki_lint_broken_section_refs`

**Goal:** Two related lint tools: (1) `[[page]]` refs where target doesn't exist; (2) `[[page#section]]` refs where page exists but section heading doesn't.

**Files:**
- Modify: `plugins/wiki/server/server/tools/lint.py` — add both functions + update register()
- Create: `plugins/wiki/server/tests/test_lint_broken_links.py`

- [ ] **Step 6.1: Write failing tests**

File: `plugins/wiki/server/tests/test_lint_broken_links.py`
```python
"""Tests for wiki_lint_broken_links + wiki_lint_broken_section_refs."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


def _write_page_with_body(
    wiki_dir: Path, category: str, slug: str, body: str, **fm_extras
) -> None:
    """Like _write_page but sets body text (needed for inline [[wikilinks]] + section tests)."""
    import yaml
    fm = {
        "title": slug.title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    fm.update(fm_extras)
    path = wiki_dir / "pages" / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{yaml.safe_dump(fm)}---\n{body}")


@pytest.mark.asyncio
class TestWikiLintBrokenLinks:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        assert result["broken"] == []

    async def test_no_broken_links(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        assert result["broken"] == []

    async def test_frontmatter_links_to_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["ghost"])
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        broken = result["broken"]
        assert len(broken) == 1
        assert broken[0]["from"] == "a"
        assert broken[0]["link"] == "ghost"

    async def test_inline_wikilink_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "a", "See [[nonexistent]] for more."
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        assert any(b["link"] == "nonexistent" for b in result["broken"])

    async def test_alias_resolves_not_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(
            wiki_setup["wiki_dir"], "concepts", "hooks-plugin", aliases=["hooks"]
        )
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "b", "See [[hooks]] for details."
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        # [[hooks]] resolves via alias → not broken
        assert not any(b["link"] == "hooks" for b in result["broken"])


@pytest.mark.asyncio
class TestWikiLintBrokenSectionRefs:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []

    async def test_section_present(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "target",
            "# Target\n\n## Overview\n\nbody",
        )
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "a",
            "See [[target#Overview]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []

    async def test_section_missing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "target",
            "# Target\n\n## Overview\n\nbody",
        )
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "a",
            "See [[target#Missing]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        broken = result["broken"]
        assert len(broken) == 1
        assert broken[0]["from"] == "a"
        assert broken[0]["link"] == "target#Missing"
        assert broken[0]["resolved_page"].endswith("target.md")

    async def test_page_missing_excluded(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # When the page itself is missing, broken_links catches it — not broken_section_refs
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "a",
            "See [[ghost#Overview]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []
```

- [ ] **Step 6.2: Run tests; verify fail**

- [ ] **Step 6.3: Add both functions to lint.py**

Add to `plugins/wiki/server/server/tools/lint.py` (before `register()`):

```python
import re

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _collect_link_targets(fm: dict[str, Any], body: str) -> list[str]:
    """Return all link refs from both frontmatter.links_to and inline [[page]] in body."""
    targets: list[str] = []
    for t in (fm.get("links_to", []) or []):
        targets.append(str(t))
    for m in _WIKILINK_RE.finditer(body):
        targets.append(m.group(1).strip().strip("[]").strip())
    return targets


def _find_page_by_slug_or_alias(wiki_dir: Path, slug: str) -> Path | None:
    """Return path of page matching slug (case-insensitive) or any alias."""
    slug_lower = slug.lower()
    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        return None
    for md in pages_root.rglob("*.md"):
        if md.stem.lower() == slug_lower:
            return md
        try:
            fm, _ = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        aliases = fm.get("aliases", []) or []
        if any(str(a).lower() == slug_lower for a in aliases):
            return md
    return None


def _section_present(body: str, section: str) -> bool:
    section_lower = section.strip().lower()
    for m in _HEADING_RE.finditer(body):
        if m.group(1).strip().lower() == section_lower:
            return True
    return False


def wiki_lint_broken_links() -> str:
    """Refs from pages' links_to + inline [[wikilinks]] whose target page doesn't exist.

    For `[[page#section]]`, only reports when the PAGE is missing; missing sections
    are reported by wiki_lint_broken_section_refs.

    Returns JSON {broken: [{from, link}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    broken: list[dict[str, str]] = []
    for md, fm, body in _iter_pages(wiki_dir):
        slug = md.stem
        for target in _collect_link_targets(fm, body):
            page_part = target.split("#", 1)[0].strip()
            if not page_part:
                continue
            resolved = _find_page_by_slug_or_alias(wiki_dir, page_part)
            if resolved is None:
                broken.append({"from": slug, "link": target})
    return json.dumps({"broken": broken})


def wiki_lint_broken_section_refs() -> str:
    """Refs like [[page#section]] where page resolves but section heading doesn't.

    Returns JSON {broken: [{from, link, resolved_page}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    broken: list[dict[str, str]] = []
    for md, fm, body in _iter_pages(wiki_dir):
        slug = md.stem
        for target in _collect_link_targets(fm, body):
            if "#" not in target:
                continue
            page_part, section = target.split("#", 1)
            resolved = _find_page_by_slug_or_alias(wiki_dir, page_part.strip())
            if resolved is None:
                # Page missing — falls to broken_links, not here
                continue
            try:
                _, target_body = fm_mod.parse(resolved.read_text())
            except fm_mod.FrontmatterError:
                continue
            if not _section_present(target_body, section.strip()):
                broken.append({
                    "from": slug,
                    "link": target,
                    "resolved_page": str(resolved),
                })
    return json.dumps({"broken": broken})
```

Update `register()`:

```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)
    mcp.tool()(wiki_lint_broken_links)
    mcp.tool()(wiki_lint_broken_section_refs)
```

- [ ] **Step 6.4: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_lint_broken_links.py -v
```
Expected: 9 tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add plugins/wiki/server/server/tools/lint.py plugins/wiki/server/tests/test_lint_broken_links.py
git commit -m "feat(wiki/688): add wiki_lint_broken_links + wiki_lint_broken_section_refs"
```

---

### Task 7: `wiki_lint_category_violations`

**Goal:** Report pages whose directory or frontmatter category is not in the configured profile's category list.

**Files:**
- Modify: `plugins/wiki/server/server/tools/lint.py`
- Create: `plugins/wiki/server/tests/test_lint_category_violations.py`

- [ ] **Step 7.1: Write failing tests**

File: `plugins/wiki/server/tests/test_lint_category_violations.py`
```python
"""Tests for wiki_lint_category_violations."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintCategoryViolations:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []

    async def test_profile_matches_all(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # software profile has decisions, concepts, etc.
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        _write_page(wiki_setup["wiki_dir"], "decisions", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []

    async def test_off_profile_category(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # "random" is not in software profile (concepts/decisions/references/pitfalls/entities)
        _write_page(wiki_setup["wiki_dir"], "random", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        violations = result["violations"]
        assert len(violations) == 1
        assert violations[0]["page"] == "a"
        assert violations[0]["found_category"] == "random"
        # configured list contains the 5 software-profile categories
        assert "concepts" in violations[0]["configured"]

    async def test_minimal_profile_no_violations(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Switch to minimal profile: empty categories → no violations possible
        import yaml
        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        cfg_path.write_text(yaml.safe_dump({"schema_version": 1, "profile": "minimal"}))
        _write_page(wiki_setup["wiki_dir"], "anything", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []

    async def test_missing_profile_config_no_violations(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Delete profile config → lint can't enforce; returns []
        (wiki_setup["wiki_dir"] / "config.yaml").unlink()
        _write_page(wiki_setup["wiki_dir"], "random", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []
```

- [ ] **Step 7.2: Run tests; verify fail**

- [ ] **Step 7.3: Add wiki_lint_category_violations to lint.py**

Add to `plugins/wiki/server/server/tools/lint.py`:

```python
from server.lib import profile as profile_mod


def wiki_lint_category_violations() -> str:
    """Pages whose directory is not in the active profile's configured categories.

    Returns JSON {violations: [{page, found_category, configured}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    try:
        profile = profile_mod.load_profile(wiki_dir)
    except profile_mod.ProfileError:
        return json.dumps({"violations": []})

    # Minimal profile explicitly allows anything — skip check.
    if not profile.categories:
        return json.dumps({"violations": []})

    configured = set(profile.categories)
    pages_root = storage.pages_dir(wiki_dir)
    violations: list[dict[str, Any]] = []
    for md, _fm, _body in _iter_pages(wiki_dir):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else None
        if cat is None:
            continue
        if cat not in configured:
            violations.append({
                "page": md.stem,
                "found_category": cat,
                "configured": sorted(configured),
                "path": str(md),
            })
    return json.dumps({"violations": violations})
```

Update `register()`:

```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)
    mcp.tool()(wiki_lint_broken_links)
    mcp.tool()(wiki_lint_broken_section_refs)
    mcp.tool()(wiki_lint_category_violations)
```

- [ ] **Step 7.4: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_lint_category_violations.py -v
```
Expected: 5 tests pass.

- [ ] **Step 7.5: Commit**

```bash
git add plugins/wiki/server/server/tools/lint.py plugins/wiki/server/tests/test_lint_category_violations.py
git commit -m "feat(wiki/688): add wiki_lint_category_violations tool"
```

---

### Task 8: `wiki_lint_stale`

**Goal:** Report pages where `last_ingested` is older than N days (default from lint.stale_after_days, or param override).

**Files:**
- Modify: `plugins/wiki/server/server/tools/lint.py`
- Create: `plugins/wiki/server/tests/test_lint_stale.py`

- [ ] **Step 8.1: Write failing tests**

File: `plugins/wiki/server/tests/test_lint_stale.py`
```python
"""Tests for wiki_lint_stale."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintStale:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        assert result["stale"] == []

    async def test_fresh_pages_not_stale(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested=recent)
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        assert result["stale"] == []

    async def test_old_page_flagged(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "ancient",
                    last_ingested="2020-01-01T00:00:00Z")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        slugs = [p["slug"] for p in result["stale"]]
        assert "ancient" in slugs

    async def test_days_param_override(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Page 10 days old; default threshold 90 → not stale; with days=5 → stale
        from datetime import datetime, timedelta, timezone
        ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested=ten_days_ago)

        r_default = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        assert r_default["stale"] == []

        r_strict = json.loads(await call_tool(mcp_app, "wiki_lint_stale", days=5))
        assert any(p["slug"] == "a" for p in r_strict["stale"])

    async def test_malformed_date_excluded(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested="not-a-date")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        # Unparseable dates are not flagged as stale — reported under schema lint instead
        assert result["stale"] == []
```

- [ ] **Step 8.2: Run tests; verify fail**

- [ ] **Step 8.3: Add wiki_lint_stale to lint.py**

Add to `plugins/wiki/server/server/tools/lint.py`:

```python
from datetime import datetime, timedelta, timezone


def _parse_iso_utc(value: str) -> datetime | None:
    """Best-effort parse of an ISO-8601 UTC datetime string. Returns None on failure."""
    if not value:
        return None
    # Accept trailing 'Z' (replace with +00:00 for fromisoformat compatibility on py<3.11)
    normalized = value.rstrip("Z")
    if normalized == value.rstrip():
        # No Z suffix; try as-is
        pass
    else:
        normalized = normalized + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def wiki_lint_stale(days: int = 0) -> str:
    """Pages whose last_ingested is older than `days` (or lint.stale_after_days default).

    Pages with unparseable last_ingested are NOT flagged here — they're caught
    by wiki_lint_schema.

    Returns JSON {stale: [{slug, path, last_ingested, age_days}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    lint_cfg = _load_lint_config(wiki_dir)
    threshold_days = int(days) if days > 0 else int(lint_cfg.get("stale_after_days", 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
    stale: list[dict[str, Any]] = []
    for md, fm, _ in _iter_pages(wiki_dir):
        last_ingested = str(fm.get("last_ingested", "") or "")
        parsed = _parse_iso_utc(last_ingested)
        if parsed is None:
            continue
        if parsed < cutoff:
            age_days = (datetime.now(timezone.utc) - parsed).days
            stale.append({
                "slug": md.stem,
                "path": str(md),
                "last_ingested": last_ingested,
                "age_days": age_days,
            })
    return json.dumps({"stale": stale})
```

Update `register()`:

```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)
    mcp.tool()(wiki_lint_broken_links)
    mcp.tool()(wiki_lint_broken_section_refs)
    mcp.tool()(wiki_lint_category_violations)
    mcp.tool()(wiki_lint_stale)
```

- [ ] **Step 8.4: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_lint_stale.py -v
```
Expected: 5 tests pass.

- [ ] **Step 8.5: Commit**

```bash
git add plugins/wiki/server/server/tools/lint.py plugins/wiki/server/tests/test_lint_stale.py
git commit -m "feat(wiki/688): add wiki_lint_stale with days threshold"
```

---

### Task 9: `wiki_lint_schema`

**Goal:** Pages violating `config.yaml:required_frontmatter` (missing any required key or wrong type).

**Files:**
- Modify: `plugins/wiki/server/server/tools/lint.py`
- Create: `plugins/wiki/server/tests/test_lint_schema.py`

- [ ] **Step 9.1: Write failing tests**

File: `plugins/wiki/server/tests/test_lint_schema.py`
```python
"""Tests for wiki_lint_schema."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintSchema:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        assert result["violations"] == []

    async def test_fully_valid_page_no_violations(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        assert result["violations"] == []

    async def test_missing_required_fields_flagged(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Hand-write a page with only title + tags (missing links_to, scope, sources, last_ingested)
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "bad.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: Bad\ntags: []\n---\nbody")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        violations = result["violations"]
        assert len(violations) == 1
        assert violations[0]["page"] == "bad"
        missing = set(violations[0]["missing_fields"])
        assert {"links_to", "scope", "sources", "last_ingested"}.issubset(missing)

    async def test_malformed_last_ingested_flagged(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested="not-a-date")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        violations = result["violations"]
        assert len(violations) == 1
        assert "last_ingested" in violations[0].get("invalid_fields", [])

    async def test_config_override_required_fields(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Override required_frontmatter in wiki/config.yaml to be stricter
        import yaml
        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        data = yaml.safe_load(cfg_path.read_text())
        data["required_frontmatter"] = [
            "title", "tags", "links_to", "scope", "sources", "last_ingested", "verified_at"
        ]
        cfg_path.write_text(yaml.safe_dump(data))
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        assert any("verified_at" in v["missing_fields"] for v in result["violations"])
```

- [ ] **Step 9.2: Run tests; verify fail**

- [ ] **Step 9.3: Add wiki_lint_schema to lint.py**

Add to `plugins/wiki/server/server/tools/lint.py`:

```python
_DEFAULT_REQUIRED_FIELDS = ("title", "tags", "links_to", "scope", "sources", "last_ingested")


def _load_required_fields(wiki_dir: Path) -> list[str]:
    """Load required_frontmatter list from wiki/config.yaml. Returns defaults if absent."""
    cfg_path = wiki_dir / "config.yaml"
    if not cfg_path.exists():
        return list(_DEFAULT_REQUIRED_FIELDS)
    try:
        data = yaml.safe_load(cfg_path.read_text()) or {}
    except yaml.YAMLError:
        return list(_DEFAULT_REQUIRED_FIELDS)
    required = data.get("required_frontmatter") if isinstance(data, dict) else None
    if isinstance(required, list):
        return [str(f) for f in required]
    return list(_DEFAULT_REQUIRED_FIELDS)


def wiki_lint_schema() -> str:
    """Pages violating required_frontmatter.

    A page violates schema when: (a) any required field is absent, OR (b) the
    last_ingested value is not a parseable ISO-8601 datetime.

    Returns JSON {violations: [{page, path, missing_fields, invalid_fields}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    required = _load_required_fields(wiki_dir)
    violations: list[dict[str, Any]] = []
    for md, fm, _ in _iter_pages(wiki_dir):
        missing = [f for f in required if f not in fm]
        invalid: list[str] = []
        if "last_ingested" in fm:
            li = str(fm.get("last_ingested", "") or "")
            if li and _parse_iso_utc(li) is None:
                invalid.append("last_ingested")
        if missing or invalid:
            violations.append({
                "page": md.stem,
                "path": str(md),
                "missing_fields": missing,
                "invalid_fields": invalid,
            })
    return json.dumps({"violations": violations})
```

Update `register()`:

```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)
    mcp.tool()(wiki_lint_broken_links)
    mcp.tool()(wiki_lint_broken_section_refs)
    mcp.tool()(wiki_lint_category_violations)
    mcp.tool()(wiki_lint_stale)
    mcp.tool()(wiki_lint_schema)
```

- [ ] **Step 9.4: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_lint_schema.py -v
```
Expected: 5 tests pass.

- [ ] **Step 9.5: Commit**

```bash
git add plugins/wiki/server/server/tools/lint.py plugins/wiki/server/tests/test_lint_schema.py
git commit -m "feat(wiki/688): add wiki_lint_schema for frontmatter validation"
```

---

### Task 10: `wiki_lint_duplicates`

**Goal:** Report pages with colliding slugs (same filename stem in different category dirs).

**Files:**
- Modify: `plugins/wiki/server/server/tools/lint.py`
- Create: `plugins/wiki/server/tests/test_lint_duplicates.py`

- [ ] **Step 10.1: Write failing tests**

File: `plugins/wiki/server/tests/test_lint_duplicates.py`
```python
"""Tests for wiki_lint_duplicates."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintDuplicates:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        assert result["duplicates"] == []

    async def test_no_duplicates(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        _write_page(wiki_setup["wiki_dir"], "decisions", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        assert result["duplicates"] == []

    async def test_duplicate_slug_different_categories(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        dupes = result["duplicates"]
        assert len(dupes) == 1
        # Each group is [path_a, path_b, ...]
        paths = dupes[0]
        assert len(paths) == 2
        assert all("hooks.md" in p for p in paths)

    async def test_case_insensitive_match(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "Hooks")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        assert len(result["duplicates"]) == 1
```

- [ ] **Step 10.2: Run tests; verify fail**

- [ ] **Step 10.3: Add wiki_lint_duplicates to lint.py**

Add to `plugins/wiki/server/server/tools/lint.py`:

```python
def wiki_lint_duplicates() -> str:
    """Pages whose filename stem (slug) collides (case-insensitive) across the wiki.

    Returns JSON {duplicates: [[path_a, path_b, ...], ...]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    by_slug: dict[str, list[str]] = {}
    for md, _fm, _body in _iter_pages(wiki_dir):
        key = md.stem.lower()
        by_slug.setdefault(key, []).append(str(md))
    duplicates = [sorted(paths) for paths in by_slug.values() if len(paths) > 1]
    return json.dumps({"duplicates": duplicates})
```

Update `register()`:

```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)
    mcp.tool()(wiki_lint_broken_links)
    mcp.tool()(wiki_lint_broken_section_refs)
    mcp.tool()(wiki_lint_category_violations)
    mcp.tool()(wiki_lint_stale)
    mcp.tool()(wiki_lint_schema)
    mcp.tool()(wiki_lint_duplicates)
```

- [ ] **Step 10.4: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_lint_duplicates.py -v
```
Expected: 4 tests pass.

- [ ] **Step 10.5: Commit**

```bash
git add plugins/wiki/server/server/tools/lint.py plugins/wiki/server/tests/test_lint_duplicates.py
git commit -m "feat(wiki/688): add wiki_lint_duplicates (case-insensitive slug collisions)"
```

---

### Task 11: Wire `main.py` to register search + lint

**Goal:** main.py imports the two new tool modules + calls their register().

**Files:**
- Modify: `plugins/wiki/server/server/main.py`

- [ ] **Step 11.1: Update main.py**

File: `plugins/wiki/server/server/main.py`
```python
"""Wiki plugin MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import index, lint, links, log, page, scope, search

mcp = FastMCP("wiki")
enable_hook_dispatch(mcp)

page.register(mcp)
index.register(mcp)
log.register(mcp)
links.register(mcp)
scope.register(mcp)
search.register(mcp)
lint.register(mcp)


def main() -> None:
    run_dual(mcp, "wiki", default_port=19109)


if __name__ == "__main__":
    main()
```

- [ ] **Step 11.2: just check clean**

```bash
cd plugins/wiki/server && just check
```
Expected: 0 errors.

- [ ] **Step 11.3: Smoke — all 19 tools exposed**

```bash
cd plugins/wiki/server && uv run python -c "
from server.main import mcp
import asyncio
async def list_tools():
    tools = await mcp.list_tools()
    print(sorted([t.name for t in tools]))
asyncio.run(list_tools())
"
```

Expected output (sorted) contains these 19 tool names:
- wiki_index_read, wiki_index_rebuild
- wiki_link_resolve
- wiki_lint_broken_links, wiki_lint_broken_section_refs, wiki_lint_category_violations, wiki_lint_duplicates, wiki_lint_orphans, wiki_lint_schema, wiki_lint_stale
- wiki_log_append, wiki_log_read
- wiki_page_delete, wiki_page_get, wiki_page_list, wiki_page_write
- wiki_scope_detect
- wiki_search_bm25, wiki_search_index_refresh

- [ ] **Step 11.4: Commit**

```bash
git add plugins/wiki/server/server/main.py
git commit -m "feat(wiki/688): register Phase 2 search + lint tool modules in main.py"
```

---

### Task 12: `/wiki:init` skill

**Goal:** Interactive skill that creates `~/.claude/wiki/`, prompts user to pick a category profile, writes both config files, + emits empty index.md + log.md.

**Files:**
- Create: `plugins/wiki/skills/init/SKILL.md`

- [ ] **Step 12.1: Write SKILL.md**

File: `plugins/wiki/skills/init/SKILL.md`
```markdown
---
name: init
description: Initialize the Karpathy LLM wiki. Creates `~/.claude/wiki/` + `~/.claude/wiki.yaml`, prompts user to pick a category profile, writes empty index.md + log.md. Use when user says "init wiki", "create wiki", "set up wiki", "wiki init".
allowed-tools: mcp__plugin_wiki_wiki__wiki_log_append, mcp__plugin_wiki_wiki__wiki_index_rebuild, AskUserQuestion, Bash, Write
argument-hint: ""
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Initialize wiki. Interactive; no args needed.

**1.** Check if wiki already initialized.
- `Bash`: `ls ~/.claude/wiki.yaml 2>/dev/null && echo EXISTS`
- `EXISTS` → print "Wiki already initialized at ~/.claude/wiki/. Re-init not supported. Edit `~/.claude/wiki.yaml` + `~/.claude/wiki/config.yaml` manually if needed." + stop.

**2.** Prompt user for category profile via `AskUserQuestion`:
- Question: "Which category profile fits your wiki's domain?"
- Header: "Profile"
- Options (single-select):
    - `software` — concepts / decisions / references / pitfalls / entities. Best for code projects, architecture notes, team docs.
    - `personal` — journal / topics / people / places / lessons. Best for life tracking, journal entries, relationship notes.
    - `research` — concepts / sources / findings / questions. Best for academic research, literature review, thesis writing.
    - `minimal` — flat `pages/`, no subdirs. Best if you want full freedom + tag-based grouping only.
    - `custom` — let user define categories via free-text.

**3.** If `custom` picked: prompt via `AskUserQuestion` (Other field) for comma-separated categories. Parse into list of strings.

**4.** Create wiki directory + config files via `Bash`:

```bash
set -e
mkdir -p ~/.claude/wiki/pages
touch ~/.claude/wiki/.lock
```

**5.** Write `~/.claude/wiki.yaml` via `Write` with:

```yaml
enabled: true
wiki_dir: ~/.claude/wiki
reingest_cooldown_hours: 24
bootstrap_pending: false
session_ingest:
  section_map: {}
```

**6.** Write `~/.claude/wiki/config.yaml` via `Write`:
- `software` / `personal` / `research` / `minimal` → just write `profile: <name>` + `schema_version: 1` + `lint` defaults.
- `custom` → also write `categories: [...]` list from user's input.

Ex. for `software`:
```yaml
schema_version: 1
profile: software
required_frontmatter:
  - title
  - tags
  - links_to
  - scope
  - sources
  - last_ingested
lint:
  stale_after_days: 90
  orphan_min_page_count: 3
```

**7.** Create category subdirs for non-minimal profiles via `Bash`:
- For picked profile, mkdir each category under `~/.claude/wiki/pages/`.
- `software`: `mkdir -p ~/.claude/wiki/pages/{concepts,decisions,references,pitfalls,entities}`
- `personal`: `mkdir -p ~/.claude/wiki/pages/{journal,topics,people,places,lessons}`
- `research`: `mkdir -p ~/.claude/wiki/pages/{concepts,sources,findings,questions}`
- `minimal`: none.
- `custom`: `mkdir -p ~/.claude/wiki/pages/<cat>` per user category.

**8.** Rebuild index + append log entry:
- `mcp__plugin_wiki_wiki__wiki_index_rebuild` → creates empty `index.md`
- `mcp__plugin_wiki_wiki__wiki_log_append` w/ `action=init`, `title=<profile>`, `body=Wiki initialized w/ <profile> profile.`

**9.** Print confirmation:
- "Wiki initialized at `~/.claude/wiki/` w/ `<profile>` profile."
- List next steps: "To add content: `/wiki:ingest <source>` (Phase 3). To query: `/wiki:query <question>`. To lint: `/wiki:lint`."

## Err handling

- Step 4 mkdir fails → err msg + stop. Don't write config files.
- Step 5 / 6 `Write` fails → err msg. Suggest user check `~/.claude/` perms.
- Step 8 `wiki_index_rebuild` fails → warn but don't stop; index can be rebuilt later via `/wiki:lint` or by calling the tool directly.
```

- [ ] **Step 12.2: Manual smoke — dry-run via reading**

Read the SKILL.md you wrote + verify:
- Frontmatter has `name`, `description`, `allowed-tools`.
- `allowed-tools` references full MCP tool names (`mcp__plugin_wiki_wiki__...`).
- Each step is actionable.

Run:
```bash
cat plugins/wiki/skills/init/SKILL.md | head -20
```
Expected: frontmatter visible.

- [ ] **Step 12.3: Commit**

```bash
git add plugins/wiki/skills/init/SKILL.md
git commit -m "feat(wiki/688): add /wiki:init interactive skill"
```

---

### Task 13: `/wiki:query` skill

**Goal:** LLM-driven skill that takes a question + synthesizes a citation-backed answer. Uses BM25 to narrow candidates when wiki is large, then LLM-reads.

**Files:**
- Create: `plugins/wiki/skills/query/SKILL.md`

- [ ] **Step 13.1: Write SKILL.md**

File: `plugins/wiki/skills/query/SKILL.md`
```markdown
---
name: query
description: Query the Karpathy LLM wiki. Reads index + runs BM25 on large wikis, drills into candidate pages, synthesizes a cited answer. Use when user says "wiki query", "search wiki", "what do we know about X", "wiki:query <question>".
allowed-tools: mcp__plugin_wiki_wiki__wiki_index_read, mcp__plugin_wiki_wiki__wiki_page_list, mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_search_bm25, mcp__plugin_wiki_wiki__wiki_link_resolve, mcp__plugin_wiki_wiki__wiki_scope_detect
argument-hint: "<question> [--scope <scope>] [--raw] [--file-back]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Answer user's question from wiki. `$ARGUMENTS` = full query string; may contain flags.

**1.** Parse `$ARGUMENTS`:
- Extract `--scope <val>`, `--raw`, `--file-back` flags.
- Remaining text = question.
- Empty question → stop: "Question required. Usage: `/wiki:query <your question>`."

**2.** `mcp__plugin_wiki_wiki__wiki_scope_detect` → get scope info (informational; default query reads all scopes).

**3.** `mcp__plugin_wiki_wiki__wiki_index_read` → get catalog (content + categories + recent).
- Empty wiki → stop: "Wiki empty. Add content via `/wiki:ingest <source>` first."

**4.** Pick retrieval path:
- Total pages (sum of categories) <~100 → **index-only path**: reason over index entries to pick 3-10 candidate slugs by title/category/summary match.
- Total pages ≥100 → **BM25 path**: `mcp__plugin_wiki_wiki__wiki_search_bm25` w/ `query=<extracted-keywords>`, `limit=20`. Use returned hits as candidates.
- If `scope_filter` flag passed: apply to BM25 call OR filter index-only candidates post-hoc.

**5.** Read each candidate via `mcp__plugin_wiki_wiki__wiki_page_get(slug, category)`:
- If candidate references `[[wikilink]]` or `[[page#section]]` that adds info → resolve via `wiki_link_resolve` + `wiki_page_get` + read too.

**6.** Synthesize answer (markdown):
- Every claim → cite specific `[[page-slug]]` refs. Quote exact text where possible.
- If wiki has nothing relevant → say so + suggest `/wiki:ingest <source>`.

**7.** Flag handling:
- `--raw` → print candidate pages + excerpts, skip synthesis step.
- `--file-back` → after synthesis, if answer is durable + high-value, propose new `query-summary` page via `wiki_page_write` (confirm w/ user first).

**8.** Render output:
```
## Answer

<synthesized markdown>

## Citations

| Slug | Category | Excerpt | Last ingested |
|------|----------|---------|---------------|
| [[hooks-architecture]] | concepts | "Centralized MCP-to-MCP registry..." | 2026-04-23 |
| ...

## Pages read

N pages (via BM25 | index-only)
```

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- `wiki_index_read` returns empty → as step 3.
- `wiki_search_bm25` returns empty hits → fall back to index-only path.
- No relevant content found → "No pages relevant to the query. Ingest source via `/wiki:ingest`."
```

- [ ] **Step 13.2: Commit**

```bash
git add plugins/wiki/skills/query/SKILL.md
git commit -m "feat(wiki/688): add /wiki:query skill w/ BM25 + LLM-reads hybrid"
```

---

### Task 14: `/wiki:lint` skill

**Goal:** Run all 7 Tier-1 lint tools, aggregate findings, prompt user to fix / skip per item. Tier-2 deferred to Phase 4.

**Files:**
- Create: `plugins/wiki/skills/lint/SKILL.md`

- [ ] **Step 14.1: Write SKILL.md**

File: `plugins/wiki/skills/lint/SKILL.md`
```markdown
---
name: lint
description: Run Tier-1 lint on the wiki — orphans / broken links / section refs / category violations / stale pages / schema / duplicates. Interactive fix prompts per finding. Use when user says "lint wiki", "wiki:lint", "check wiki health".
allowed-tools: mcp__plugin_wiki_wiki__wiki_lint_orphans, mcp__plugin_wiki_wiki__wiki_lint_broken_links, mcp__plugin_wiki_wiki__wiki_lint_broken_section_refs, mcp__plugin_wiki_wiki__wiki_lint_category_violations, mcp__plugin_wiki_wiki__wiki_lint_stale, mcp__plugin_wiki_wiki__wiki_lint_schema, mcp__plugin_wiki_wiki__wiki_lint_duplicates, mcp__plugin_wiki_wiki__wiki_page_write, mcp__plugin_wiki_wiki__wiki_page_delete, mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_log_append, AskUserQuestion
argument-hint: ""
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Run Tier-1 lint + interactive fix flow.

**1.** Call all 7 Tier-1 lint tools in parallel:
- `mcp__plugin_wiki_wiki__wiki_lint_orphans`
- `mcp__plugin_wiki_wiki__wiki_lint_broken_links`
- `mcp__plugin_wiki_wiki__wiki_lint_broken_section_refs`
- `mcp__plugin_wiki_wiki__wiki_lint_category_violations`
- `mcp__plugin_wiki_wiki__wiki_lint_stale`
- `mcp__plugin_wiki_wiki__wiki_lint_schema`
- `mcp__plugin_wiki_wiki__wiki_lint_duplicates`

**2.** Aggregate findings. Count total per check. Render summary table:
```
| Check | Findings |
|-------|----------|
| Orphans | 3 |
| Broken links | 2 |
| Broken section refs | 0 |
| Category violations | 1 |
| Stale (>90d) | 5 |
| Schema violations | 0 |
| Duplicate slugs | 0 |
```
- Zero findings across all → "Wiki is clean. No lint issues." + stop.

**3.** For each finding (grouped by check), present + prompt user via `AskUserQuestion`:
- Question: "[<check>] <page-slug>: <detail>. Fix?"
- Options: `fix` / `skip`
- (Note: `file-todo` option is only enabled when proj is installed; hide otherwise. In Phase 2 w/ no proj integration, only `fix` + `skip` offered.)

**4.** If `fix` picked:
- **Orphan**: offer `delete page` (via `wiki_page_delete`) OR `leave` (mark as intentional).
- **Broken link**: offer `remove ref from source page's links_to` (via `wiki_page_get` → edit frontmatter → `wiki_page_write`) OR `create target page stub` (use `wiki_page_write` w/ `mode=create` + empty body + minimal frontmatter).
- **Broken section ref**: offer `change ref to page-only` (drop `#section`) OR `add missing heading to target page`.
- **Category violation**: offer `move page to configured category` (delete + recreate in new dir OR prompt user for target) OR `add category to config.yaml`.
- **Stale**: offer `refresh page` (prompt for updated last_ingested) OR `archive`.
- **Schema violation**: offer `auto-fix missing fields w/ defaults` (e.g. `sources: []`, `tags: []`, `last_ingested: <now>`) OR `skip`.
- **Duplicate**: print paths + prompt user to rename one manually. No auto-fix.

**5.** After all findings processed: `mcp__plugin_wiki_wiki__wiki_log_append` w/ `action=lint`, `title=full`, `body=<summary: N fixed, M skipped>`.

**6.** Print final summary:
- "Lint complete. <N> issues fixed, <M> skipped."

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- Any lint tool returns error → print err + continue w/ other checks.
- Fix tool call fails → print err, mark finding as unresolved, continue.
```

- [ ] **Step 14.2: Commit**

```bash
git add plugins/wiki/skills/lint/SKILL.md
git commit -m "feat(wiki/688): add /wiki:lint interactive Tier-1 skill"
```

---

### Task 15: Add _write_page helper to conftest (cleanup from Phase 1 review)

**Goal:** Address review follow-up #3 from todo 706: move cross-test `_write_page` helper from `test_page_list.py` into `conftest.py`. This is a pre-req for Phase 2's cleanup.

**Files:**
- Modify: `plugins/wiki/server/tests/conftest.py` — add `_write_page` module-level helper
- Modify: `plugins/wiki/server/tests/test_page_list.py` — import from conftest
- Modify: test files that imported it: `test_index.py`, `test_links.py`, `test_page_delete.py`, plus new Phase 2 tests: `test_search.py`, `test_lint_*.py` — import from conftest instead

- [ ] **Step 15.1: Move helper to conftest**

Add to bottom of `plugins/wiki/server/tests/conftest.py`:

```python
def _write_page(
    wiki_dir: Path, category: str | None, slug: str, **fm_overrides
) -> None:
    """Write a wiki page with default frontmatter + overridable fields.

    Body is always 'body' unless overridden. Use for tests that need a known page.
    """
    import yaml
    base: dict[str, Any] = {
        "title": slug.replace("-", " ").title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    base.update(fm_overrides)
    path = wiki_dir / "pages"
    if category:
        path = path / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{yaml.safe_dump(base)}---\nbody")
```

- [ ] **Step 15.2: Update import sites**

In each of: `test_page_list.py`, `test_index.py`, `test_links.py`, `test_page_delete.py`, and Phase 2 files written so far (`test_search.py`, `test_lint_orphans.py`, `test_lint_category_violations.py`, `test_lint_stale.py`, `test_lint_schema.py`, `test_lint_duplicates.py`, `test_lint_broken_links.py`):

Change:
```python
from tests.test_page_list import _write_page
```
to:
```python
from tests.conftest import _write_page
```

Remove the `_write_page` definition from `tests/test_page_list.py` (it's now in conftest).

- [ ] **Step 15.3: Run full suite — verify green**

```bash
cd plugins/wiki/server && uv run pytest
```
Expected: all tests pass.

- [ ] **Step 15.4: Commit**

```bash
git add plugins/wiki/server/tests/
git commit -m "refactor(wiki/688): move _write_page helper to conftest (phase1 review followup)"
```

---

### Task 16: Coverage gate + full-suite green

**Goal:** Confirm Phase 2 additions keep the plugin ≥85% coverage + `just ci` green.

- [ ] **Step 16.1: Full suite + coverage**

```bash
cd plugins/wiki/server && uv run pytest --cov=server --cov-report=term-missing
```
Expected: all tests pass; total coverage ≥85%. If below, add tests for uncovered critical paths (typically: lint branches, BM25 staleness edge cases, search filter paths).

- [ ] **Step 16.2: `just ci` clean**

```bash
cd plugins/wiki/server && just ci
```
Expected: ruff + basedpyright + pytest + bandit + pip-audit all green.

- [ ] **Step 16.3: No commit unless gaps filled**

If coverage gaps exist, add targeted tests in the relevant test file (e.g. `test_bm25.py` for staleness edge, `test_search.py` for filter combos), then commit:

```bash
git add plugins/wiki/server/tests/
git commit -m "test(wiki/688): cover Phase 2 gap branches"
```

---

### Task 17: Phase-2 close smoke + README + final review

**Goal:** Ensure nothing else broke, + update plugin README to mention Phase 2 status.

**Files:**
- Modify: `plugins/wiki/README.md` — add Phase 2 completion note

- [ ] **Step 17.1: Update README**

Change the `## Phase status` section at the bottom of `plugins/wiki/README.md` from:

```markdown
Phase 1 (this release): core MCP tools only (page CRUD, index, log, links, scope). No skills yet; no lint; no search.
```

to:

```markdown
## Phase status

- **Phase 1** — core persistence tools (page CRUD, index, log, links, scope). ✅
- **Phase 2** — BM25 search (`wiki_search_bm25`, `wiki_search_index_refresh`), 7 Tier-1 lint tools (`wiki_lint_*`), 3 standalone skills (`/wiki:init`, `/wiki:query`, `/wiki:lint`). ✅
- **Phase 3** — ingest + bootstrap (URL, file, session, note, search, MCP sources). Pending.
- **Phase 4** — proj touchpoints (router hook, `/proj:save` integration, wizard), Tier-2 semantic lint. Pending.
- **Phase 5** — polish + docs. Pending.
```

- [ ] **Step 17.2: Repo-wide smoke (best-effort)**

From repo root:
```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
git status --short
```
Expected: clean (only the README change staged).

Optional: repo-wide `just sync` + `just test` if time allows; skip if it drags in unrelated deltas.

- [ ] **Step 17.3: Commit**

```bash
git add plugins/wiki/README.md
git commit -m "docs(wiki/688): update README w/ Phase 2 completion status"
```

- [ ] **Step 17.4: Dispatch final Phase 2 code reviewer**

Dispatch a superpowers:code-reviewer subagent with:
- BASE_SHA: the HEAD of Phase 1 (101e2e0)
- HEAD_SHA: current HEAD after Task 17 commit
- Focus: coherence of new modules, BM25 correctness, skill SKILL.md quality, Phase-1-review followup completeness

Address any critical/important issues the reviewer surfaces; file minor ones as a Phase-2 followup todo for Phase 3 execution.

---

## Verification

At phase-end, verify:

1. **All 9 new MCP tools exposed** via `wiki-server` — verify by smoke test Step 11.3.
2. **All 3 skills installed** under `plugins/wiki/skills/` — verify: `ls plugins/wiki/skills/` prints `init  lint  query`.
3. **Coverage ≥85%** on `plugins/wiki/server/server/` — verify Step 16.1.
4. **`just ci` green** in `plugins/wiki/server/` — verify Step 16.2.
5. **BM25 staleness works** — manually touch a page file + confirm next `wiki_search_bm25` picks up the change (covered by `test_rebuilds_on_staleness`).
6. **Phase-1 review followup #3 resolved** — `_write_page` now lives in conftest; Task 15 lands this.

## Handoff to Phase 3

Phase 3 will add:
- `/wiki:ingest` skill w/ subagent protocol for all 6 source types (URL, file, session, note, search, mcp)
- `/wiki:bootstrap` skill (standalone-mode; proj-aware path comes in Phase 4 w/ proj integration)
- `/wiki:promote` skill
- No new MCP tools (Phase 2's primitives suffice)

Phase 3 plan to be written after Phase 2 is ready to merge.

"""BM25 index over wiki pages. Sidecar persistence at .index/bm25.json.

Lazy-rebuild via load_or_rebuild + is_stale. Uses rank-bm25 (pure Python).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from rank_bm25 import BM25Okapi

from server.lib import frontmatter as fm_mod
from server.lib import storage

if TYPE_CHECKING:
    from pathlib import Path

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
        scores: Any = self._bm25.get_scores(tokens)  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]
        ranked = sorted(
            [(slug, float(score)) for slug, score in zip(self._slugs, scores, strict=True)],  # type: ignore[reportUnknownArgumentType]
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
    """Rebuild the BM25 sidecar index.

    NOTE: Caller MUST hold wiki_lock around invocation. This helper does NOT
    acquire the lock itself (changed in W1 fix 2026-04-26 — see todo 764).
    """
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

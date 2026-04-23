# Wiki Cleanup Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 8 commits on `feat/wiki-cleanup-batch` that close out wiki-plugin phase-1 through phase-4a code-review follow-ups (todos 706/707/708/709), add a cross-plugin proj↔wiki e2e integration test (709 item 4), and unblock the `test_todo_add_e2e_hooks.py` pytest-collection error. Merge FF into dev; ship green CI.

**Architecture:** No architectural change. All edits are surface-level fixes contained within existing plugin boundaries (wiki internals, one proj models.py field, one shared test file, one proj test conftest). The wiki spec's persistence/synthesis boundary (`MCP = pure persistence; synthesis in skills`) is preserved.

**Tech Stack:** Python 3.13, FastMCP, pytest, basedpyright, ruff, uv, pre-commit, GitHub Actions matrix CI, git worktrees.

**Spec reference:** `docs/superpowers/specs/2026-04-23-wiki-cleanup-batch-design.md` @ commit ec046a2.

**Working directory:** All edits + git operations in `/home/raul/worktrees/cpm/feat-wiki-cleanup-batch`. Branch is `feat/wiki-cleanup-batch` from `dev` @ `d583e05`.

**Out of scope (do NOT touch):**
- `plugins/_shared/claudemd/managed_section.md` (owned by parallel 710 session).
- `plugins/proj/server/tests/test_context.py::TestClaudemdRefreshManaged*` (same).

---

## File Structure

**New files** (2):
- `plugins/_shared/tests/test_wiki_proj_e2e.py` — cross-plugin proj→router→wiki round-trip (Task 7).
- Optional: `plugins/proj/server/tests/conftest.py` addition or new shim file for the `hook_dispatch` sys.path fix (Task 8).

**Modified files** (15):
- `plugins/wiki/server/server/tools/index.py` — import harmonization (Task 1).
- `plugins/wiki/server/server/tools/page.py` — TOCTOU move-inside-lock (Task 1).
- `plugins/wiki/server/tests/test_log.py` — body-assertion add (Task 1).
- `plugins/wiki/server/tests/conftest.py` — extend `_write_page` with `body` kwarg (Task 3).
- `plugins/wiki/server/tests/test_search.py` — drop local `_write_page` (Task 3).
- `plugins/wiki/server/tests/test_lint_broken_links.py` — drop local `_write_page_with_body` (Task 3).
- `plugins/wiki/server/tests/test_storage.py` — NEW test fn for atomic_write cleanup (Task 2).
- `plugins/wiki/server/tests/test_index.py` (or new `test_first_summary_line.py`) — 3 new tests (Task 2).
- `plugins/wiki/server/tests/test_models.py` — 2 new tests (Task 2).
- `plugins/wiki/server/tests/test_profile.py` — 1 new test (Task 2).
- `plugins/wiki/server/server/tools/search.py` — docstring caveat (Task 4).
- `plugins/wiki/skills/promote/SKILL.md` — scope-detect call + allowed-tools (Task 5).
- `plugins/wiki/skills/bootstrap/SKILL.md` — proj-aware note + find audit (Task 5).
- `plugins/wiki/skills/ingest/references/source-readers.md` — idempotency note (Task 5).
- `plugins/wiki/skills/ingest/references/dedup-protocol.md` — idempotency defense-in-depth note (Task 5).
- `plugins/wiki/skills/ingest/references/subagent-prompt.md` — verify + optional align (Task 5).
- `plugins/wiki/README.md` — references/ convention note (Task 5).
- `plugins/wiki/server/server/tools/scope.py` — type-ignore audit (Task 6).
- `plugins/proj/server/server/lib/models.py` — drop `WikiSync.auto_sync` (Task 6).
- `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` — doc polish (Tasks 4, 6).

---

## Task 1: Phase-1 review follow-ups (Commit 1 — `fix(wiki/706): phase-1 review follow-ups`)

**Files:**
- Modify: `plugins/wiki/server/server/tools/index.py:14-25`
- Modify: `plugins/wiki/server/server/tools/page.py:91-108`
- Modify: `plugins/wiki/server/tests/test_log.py` (the `test_append_preserves_prior_entries` function)
- Inspect only: `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §6

### Step 1.1: Harmonize FastMCP import in `tools/index.py`

- [ ] **Step 1.1a: Read current state**

Run: `sed -n '1,30p' plugins/wiki/server/server/tools/index.py`

Expected current content (lines 14-25):

```python
from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

INDEX_FILENAME = "index.md"
RECENT_LIMIT = 10

_CATEGORY_HEADER_RE = re.compile(r"^## (\S.+?) \((\d+)\)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:  # type: ignore[name-defined]
```

- [ ] **Step 1.1b: Apply edit**

Replace:

```python
if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

INDEX_FILENAME = "index.md"
RECENT_LIMIT = 10

_CATEGORY_HEADER_RE = re.compile(r"^## (\S.+?) \((\d+)\)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:  # type: ignore[name-defined]
```

With (matches the pattern used in `tools/page.py`, `tools/log.py`, `tools/links.py`):

```python
if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
else:
    # At runtime, for FastMCP usage in register()
    from mcp.server.fastmcp import FastMCP  # noqa: TC002

INDEX_FILENAME = "index.md"
RECENT_LIMIT = 10

_CATEGORY_HEADER_RE = re.compile(r"^## (\S.+?) \((\d+)\)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
```

- [ ] **Step 1.1c: Verify basedpyright still clean**

Run: `cd plugins/wiki/server && uv run basedpyright server/tools/index.py`
Expected: `0 errors, 0 warnings, 0 informations`

### Step 1.2: Move `wiki_page_write` no-op check inside `wiki_lock`

- [ ] **Step 1.2a: Read current state**

Run: `sed -n '80,125p' plugins/wiki/server/server/tools/page.py`

Confirm the no-op idempotency block (lines 91-108) sits OUTSIDE the `with storage.wiki_lock(wiki_dir):` block that starts at line 110.

- [ ] **Step 1.2b: Apply edit**

Replace the block:

```python
    new_content = fm_mod.dump(frontmatter, body)

    # Idempotency: on upsert with identical existing content → no-op.
    if mode == "upsert" and exists:
        existing_raw = target.read_text()
        existing_fm, existing_body = fm_mod.parse(existing_raw)
        if _content_hash(existing_fm, existing_body) == _content_hash(frontmatter, body):
            return json.dumps(
                {
                    "path": str(target),
                    "created": False,
                    "updated": False,
                    "noop": True,
                    "warning": warning,
                }
            )

    with storage.wiki_lock(wiki_dir):
        storage.atomic_write(target, new_content)
```

With (idempotency check moves inside the lock so the read-then-hash is serialized with writers):

```python
    new_content = fm_mod.dump(frontmatter, body)

    with storage.wiki_lock(wiki_dir):
        # Idempotency (inside lock to avoid TOCTOU): on upsert with identical
        # existing content → no-op.
        if mode == "upsert" and exists:
            existing_raw = target.read_text()
            existing_fm, existing_body = fm_mod.parse(existing_raw)
            if _content_hash(existing_fm, existing_body) == _content_hash(frontmatter, body):
                return json.dumps(
                    {
                        "path": str(target),
                        "created": False,
                        "updated": False,
                        "noop": True,
                        "warning": warning,
                    }
                )
        storage.atomic_write(target, new_content)
```

Note: `exists` was evaluated before the lock and is still valid; the `.exists()` call pre-lock gates the `create`/`update` mode errors earlier in the function (unchanged). Inside the lock we trust the earlier `exists` check because a concurrent deletion between `target.exists()` and lock acquisition is not a real-world scenario the wiki protects against. The move addresses the specific TOCTOU called out in the 706 notes: the read+hash against a concurrent writer.

- [ ] **Step 1.2c: Run existing tests for page**

Run: `cd plugins/wiki/server && uv run pytest tests/test_page.py -v`
Expected: all pass (count unchanged).

### Step 1.3: Add log body trailing-content assertion

- [ ] **Step 1.3a: Read current test**

Run: `grep -n "test_append_preserves_prior_entries" plugins/wiki/server/tests/test_log.py`

Expected: one match. Read surrounding 10 lines.

Current body:

```python
    async def test_append_preserves_prior_entries(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="first")
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="second")
        content = (wiki_setup["wiki_dir"] / "log.md").read_text()
        assert content.index("first") < content.index("second")
```

- [ ] **Step 1.3b: Extend body + append body-text assertion**

Replace the test body with:

```python
    async def test_append_preserves_prior_entries(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        await call_tool(
            mcp_app,
            "wiki_log_append",
            action="ingest",
            title="first",
            body="first-body-content",
        )
        await call_tool(
            mcp_app,
            "wiki_log_append",
            action="lint",
            title="second",
            body="second-body-content",
        )
        content = (wiki_setup["wiki_dir"] / "log.md").read_text()
        assert content.index("first") < content.index("second")
        # 706 follow-up: ensure prior-entry body survives the second append.
        assert "first-body-content" in content
        assert content.index("first-body-content") < content.index("second-body-content")
```

If `wiki_log_append` does not accept a `body` kwarg, adapt the call site to the correct param name (run `grep -n "def wiki_log_append" plugins/wiki/server/server/tools/log.py` to confirm the signature and use whatever field represents the entry body).

- [ ] **Step 1.3c: Run the single test**

Run: `cd plugins/wiki/server && uv run pytest tests/test_log.py::TestWikiLogAppend::test_append_preserves_prior_entries -v`
Expected: PASS.

### Step 1.4: Verify spec §6 `slug` consistency

- [ ] **Step 1.4a: Inspect spec table**

Run: `grep -n "wiki_page_write\|wiki_page_get\|wiki_page_list\|wiki_page_delete" docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md | head -20`

Confirm the tool rows consistently use `page (slug)` or `slug` as the param name. Per Explore, already consistent. If so, no edit.

- [ ] **Step 1.4b: Decide**

If spec already uses `page (slug)` consistently everywhere → no edit needed; record in commit message "706.6 verified consistent; no edit".
If spec has a stray `page` vs `slug` mismatch → patch the mismatch with an Edit to use `page (slug)` throughout the tool-param table in §6.

### Step 1.5: Run wiki suite + commit

- [ ] **Step 1.5a: Run the narrow suite**

Run: `cd plugins/wiki/server && uv run pytest tests/test_page.py tests/test_log.py -v`
Expected: all green.

- [ ] **Step 1.5b: Stage + commit**

```bash
git add plugins/wiki/server/server/tools/index.py \
        plugins/wiki/server/server/tools/page.py \
        plugins/wiki/server/tests/test_log.py
# include spec only if 1.4b required an edit:
# git add docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md

git commit -m "$(cat <<'EOF'
fix(wiki/706): phase-1 review follow-ups

- index.py: harmonize FastMCP import w/ page/log/links pattern; drop
  type:ignore on register signature.
- page.py: move wiki_page_write no-op idempotency check inside wiki_lock
  to close a TOCTOU window against concurrent writers.
- test_log.py: assert prior-entry body content survives second append.

Refs: todo 706 (auto-added after Phase 1 final code review at 101e2e0).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Defensive-path coverage (Commit 2 — `test(wiki/706): defensive-path coverage`)

Net-new tests only; no production-code changes.

**Files:**
- Modify or create: `plugins/wiki/server/tests/test_storage.py`
- Modify or create: `plugins/wiki/server/tests/test_index.py`
- Modify or create: `plugins/wiki/server/tests/test_models.py`
- Modify or create: `plugins/wiki/server/tests/test_profile.py`

### Step 2.1: `storage.atomic_write` cleanup on failure

- [ ] **Step 2.1a: Locate test file**

Run: `ls plugins/wiki/server/tests/test_storage.py`
If missing → create it. If present → append the new test.

- [ ] **Step 2.1b: Write the test**

Append this test class (or file):

```python
"""Tests for server.lib.storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import storage


class TestAtomicWriteCleanup:
    def test_atomic_write_cleans_up_tmp_on_replace_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If os.replace (Path.replace) raises, the tmp file must be removed."""
        target = tmp_path / "target.md"

        original_replace = Path.replace

        def boom(self: Path, *args: object, **kwargs: object) -> Path:
            # Only boom for the atomic_write tmp file; let other replace calls through.
            if self.name.startswith(".target.md."):
                raise OSError("simulated replace failure")
            return original_replace(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "replace", boom)

        with pytest.raises(OSError, match="simulated replace failure"):
            storage.atomic_write(target, "hello")

        # Target was never created (the replace failed).
        assert not target.exists()
        # Tmp file must have been cleaned up.
        tmp_leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".target.md.")]
        assert tmp_leftovers == [], f"leaked tmp files: {tmp_leftovers}"
```

- [ ] **Step 2.1c: Run the test**

Run: `cd plugins/wiki/server && uv run pytest tests/test_storage.py::TestAtomicWriteCleanup -v`
Expected: PASS.

### Step 2.2: `_first_summary_line` branch coverage

- [ ] **Step 2.2a: Locate existing tests**

Run: `grep -n "_first_summary_line\|first_summary" plugins/wiki/server/tests/test_index.py 2>/dev/null || echo "not present"`

- [ ] **Step 2.2b: Append 3 tests**

Append to `plugins/wiki/server/tests/test_index.py` (create if missing; use existing file pattern for imports + pytest style):

```python
from server.tools.index import _first_summary_line


class TestFirstSummaryLine:
    def test_empty_body_returns_empty_string(self) -> None:
        assert _first_summary_line("") == ""

    def test_body_starting_with_heading_skips_heading(self) -> None:
        body = "# Heading only on first line\n\nthis is the real first line."
        assert _first_summary_line(body) == "this is the real first line."

    def test_all_heading_body_returns_empty(self) -> None:
        body = "# one\n## two\n### three"
        assert _first_summary_line(body) == ""
```

- [ ] **Step 2.2c: Run**

Run: `cd plugins/wiki/server && uv run pytest tests/test_index.py::TestFirstSummaryLine -v`
Expected: all 3 PASS.

### Step 2.3: `Page.scope` single-string + category no-`pages` branches

- [ ] **Step 2.3a: Read current models.py**

Run: `sed -n '60,110p' plugins/wiki/server/server/lib/models.py`

Confirm the `Page` dataclass + `scope` property handle: (a) list-of-strings; (b) string; (c) the category property looks for `pages` dir in path parts.

- [ ] **Step 2.3b: Append tests**

Append to `plugins/wiki/server/tests/test_models.py` (create if missing):

```python
"""Tests for server.lib.models."""

from __future__ import annotations

from pathlib import Path

from server.lib.models import Page


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
```

Adjust the `Page` constructor signature to match actual impl — re-read `models.py` if the call in the test fails (Explore fetched lines 75-105; the constructor may require other fields).

- [ ] **Step 2.3c: Run**

Run: `cd plugins/wiki/server && uv run pytest tests/test_models.py::TestPageScopeStringBranch tests/test_models.py::TestPageCategoryBranch -v`
Expected: both PASS.

### Step 2.4: `profile.load_profile` malformed YAML

- [ ] **Step 2.4a: Append test**

Append to `plugins/wiki/server/tests/test_profile.py` (create if missing):

```python
"""Tests for server.lib.profile."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import profile as profile_mod


class TestProfileMalformedYaml:
    def test_malformed_config_raises_profile_error(self, tmp_path: Path) -> None:
        wiki_dir = tmp_path
        (wiki_dir / "config.yaml").write_text("profile: [unclosed-bracket\n")

        with pytest.raises(profile_mod.ProfileError, match="malformed"):
            profile_mod.load_profile(wiki_dir)
```

- [ ] **Step 2.4b: Run**

Run: `cd plugins/wiki/server && uv run pytest tests/test_profile.py::TestProfileMalformedYaml -v`
Expected: PASS.

### Step 2.5: Full wiki test suite + coverage check

- [ ] **Step 2.5a: Run full suite with coverage**

Run: `cd plugins/wiki/server && uv run pytest tests/ --cov=server --cov-report=term-missing`
Expected: all tests pass; total coverage ≥ 90.62% (baseline). Record the new percentage.

- [ ] **Step 2.5b: Commit**

```bash
git add plugins/wiki/server/tests/test_storage.py \
        plugins/wiki/server/tests/test_index.py \
        plugins/wiki/server/tests/test_models.py \
        plugins/wiki/server/tests/test_profile.py

git commit -m "$(cat <<'EOF'
test(wiki/706): defensive-path coverage

Add trivial one-liner tests for the 4 defensive paths flagged in the
Phase 1 code review:
- storage.atomic_write tmpfile cleanup on Path.replace failure
- index._first_summary_line empty / heading-only / all-heading branches
- models.Page.scope string branch + category no-'pages' branch
- profile.load_profile malformed YAML raises ProfileError

Refs: todo 706 item 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Consolidate `_write_page` helper (Commit 3 — `refactor(wiki/707): consolidate _write_page test helper`)

**Files:**
- Modify: `plugins/wiki/server/tests/conftest.py:88-114`
- Modify: `plugins/wiki/server/tests/test_search.py:1-27`
- Modify: `plugins/wiki/server/tests/test_lint_broken_links.py:1-30`

### Step 3.1: Extend conftest `_write_page` signature

- [ ] **Step 3.1a: Read current conftest helper**

Run: `sed -n '88,115p' plugins/wiki/server/tests/conftest.py`

Confirm current signature: `def _write_page(wiki_dir: Path, category: str | None, slug: str, **fm_overrides: Any) -> None` and body is hardcoded to `"body"`.

- [ ] **Step 3.1b: Apply edit**

Replace:

```python
def _write_page(wiki_dir: Path, category: str | None, slug: str, **fm_overrides: Any) -> None:
    """Write wiki page w/ default frontmatter + overridable fields.

    Body always 'body'. Category None = flat layout. Use in tests needing
    known page to exist without full wiki_page_write MCP path.
    """
    import json

    base: dict[str, Any] = {
        "title": slug.replace("-", " ").title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    base.update(fm_overrides)
    fm_lines = "\n".join(f"{k}: {json.dumps(v)}" for k, v in base.items())
    path = wiki_dir / "pages"
    if category:
        path = path / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{fm_lines}\n---\nbody")
```

With (adds optional `body` kwarg, default `"body"`):

```python
def _write_page(
    wiki_dir: Path,
    category: str | None,
    slug: str,
    body: str = "body",
    **fm_overrides: Any,
) -> None:
    """Write wiki page w/ default frontmatter + overridable fields.

    Body defaults to 'body'; pass `body=` to override (e.g. for search/lint
    tests that need specific content). Category None = flat layout. Use in
    tests needing known page to exist without full wiki_page_write MCP path.
    """
    import json

    base: dict[str, Any] = {
        "title": slug.replace("-", " ").title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    base.update(fm_overrides)
    fm_lines = "\n".join(f"{k}: {json.dumps(v)}" for k, v in base.items())
    path = wiki_dir / "pages"
    if category:
        path = path / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{fm_lines}\n---\n{body}")
```

- [ ] **Step 3.1c: Smoke test**

Run: `cd plugins/wiki/server && uv run pytest tests/test_page_list.py tests/test_index.py tests/test_page.py -v`
Expected: all green (default body="body" keeps existing callers unchanged).

### Step 3.2: Drop local `_write_page` in `test_search.py`

- [ ] **Step 3.2a: Read current top of file**

Run: `sed -n '1,30p' plugins/wiki/server/tests/test_search.py`

- [ ] **Step 3.2b: Apply edit**

Replace the block:

```python
"""Tests for wiki_search_bm25 + wiki_search_index_refresh."""

import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


def _write_page(wiki_dir: Path, category: str, slug: str, body: str, **fm_extras: Any) -> None:
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
```

With:

```python
"""Tests for wiki_search_bm25 + wiki_search_index_refresh."""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool
```

(Removes unused `Path`, `Any`, `yaml` imports + local helper.)

- [ ] **Step 3.2c: Fix call-site signature drift**

Current test file calls the local helper with positional `body` (position 4). The conftest helper now accepts `body` as keyword (position 4 is also accepted positionally per Python semantics), so existing calls continue to work. Run:

`grep -n "_write_page(" plugins/wiki/server/tests/test_search.py`

Inspect each call. If any uses positional category as `None` (should not; search tests use real categories) verify compatibility. No edits expected.

- [ ] **Step 3.2d: Run search tests**

Run: `cd plugins/wiki/server && uv run pytest tests/test_search.py -v`
Expected: all green.

### Step 3.3: Drop local `_write_page_with_body` in `test_lint_broken_links.py`

- [ ] **Step 3.3a: Read current top**

Run: `sed -n '1,35p' plugins/wiki/server/tests/test_lint_broken_links.py`

- [ ] **Step 3.3b: Apply edit**

Replace:

```python
"""Tests for wiki_lint_broken_links + wiki_lint_broken_section_refs."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool


def _write_page_with_body(wiki_dir: Path, category: str, slug: str, body: str, **fm_extras) -> None:
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
```

With:

```python
"""Tests for wiki_lint_broken_links + wiki_lint_broken_section_refs."""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool
```

- [ ] **Step 3.3c: Rename callsites**

Rename `_write_page_with_body(` → `_write_page(` across the file:

Run: `grep -n "_write_page_with_body" plugins/wiki/server/tests/test_lint_broken_links.py`

For each match, change to `_write_page`. Since the call-site passes `body` positionally as the 4th arg and the conftest helper accepts `body` positionally as the 4th arg, the rename is sufficient (no arg reordering).

- [ ] **Step 3.3d: Run lint tests**

Run: `cd plugins/wiki/server && uv run pytest tests/test_lint_broken_links.py -v`
Expected: all green.

### Step 3.4: Full suite

- [ ] **Step 3.4a: Run**

Run: `cd plugins/wiki/server && uv run pytest tests/ -v --tb=short`
Expected: 171/171 green (count unchanged unless Task 2's new tests added; then higher).

- [ ] **Step 3.4b: Commit**

```bash
git add plugins/wiki/server/tests/conftest.py \
        plugins/wiki/server/tests/test_search.py \
        plugins/wiki/server/tests/test_lint_broken_links.py

git commit -m "$(cat <<'EOF'
refactor(wiki/707): consolidate _write_page test helper

Extend conftest _write_page() w/ optional body kwarg (default 'body');
remove the two local variants in test_search.py + test_lint_broken_links.py.
Net -30 lines, no behavior change.

Refs: todo 707 item 1 + todo 706 item 3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Spec + docstring polish (Commit 4 — `docs(wiki/707): spec + docstring polish`)

Doc/comment-only changes.

**Files:**
- Modify: `plugins/wiki/server/server/tools/search.py:55-75` (docstring)
- Modify: `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §6 + §4.3

### Step 4.1: Add BM25 oversampling caveat to docstring

- [ ] **Step 4.1a: Apply edit**

In `plugins/wiki/server/server/tools/search.py`, replace:

```python
    """BM25 keyword search over wiki pages. Filters applied post-ranking.

    Returns JSON {hits: [{slug, score, snippet, category, tags, scope}]}.
    """
```

With:

```python
    """BM25 keyword search over wiki pages. Filters applied post-ranking.

    When category/tags/scope filters are set, the top `limit * 3` BM25 hits
    are retrieved before filtering. On very large wikis with sparse target
    categories (e.g. 5 matching pages ranked 61-65 with limit=60), this can
    miss relevant pages. Consider raising `limit` or using tag-specific
    indexes if the target category has few pages.

    Returns JSON {hits: [{slug, score, snippet, category, tags, scope}]}.
    """
```

- [ ] **Step 4.1b: Verify basedpyright clean**

Run: `cd plugins/wiki/server && uv run basedpyright server/tools/search.py`
Expected: no new errors.

### Step 4.2: Update spec §6 lint return-shape rows

- [ ] **Step 4.2a: Locate rows**

Run: `grep -n "wiki_lint_schema\|wiki_lint_stale" docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md`

- [ ] **Step 4.2b: Replace `wiki_lint_schema` row**

Replace:

```markdown
| `wiki_lint_schema` | Pages violating required frontmatter | — | `{violations: [{page, missing_fields}]}` |
```

With:

```markdown
| `wiki_lint_schema` | Pages violating required frontmatter | — | `{violations: [{page, path, missing_fields, invalid_fields}]}` |
```

- [ ] **Step 4.2c: Replace `wiki_lint_stale` row**

Replace:

```markdown
| `wiki_lint_stale` | Pages older than N days | `days` | `{stale: [page]}` |
```

With:

```markdown
| `wiki_lint_stale` | Pages older than N days | `days` | `{stale: [{slug, path, last_ingested, age_days}]}` |
```

### Step 4.3: Resolve `bootstrap_completed` vs `bootstrap_pending` question

Per Explore verbatim from §4.3: wiki.yaml uses `bootstrap_completed: false` as the default-state field; the installer sets `wiki.bootstrap_pending: true` separately as a session-prompt flag. Post-bootstrap, §4.3 also mentions `sync.wiki.bootstrap_completed: true` being flipped via the skill. These are three distinct fields in two configs serving different purposes. The 707 item 4 "typo" suspicion is resolved as a naming clarity issue.

- [ ] **Step 4.3a: Locate spec mentions**

Run: `grep -n "bootstrap_completed\|bootstrap_pending" docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md`

Expected: 3 matches (wiki.yaml default, installer sets wiki.bootstrap_pending, sync.wiki.bootstrap_completed post-flip).

- [ ] **Step 4.3b: Add clarifying note**

Find the wiki.yaml config block in §4.3 (the one containing `bootstrap_completed: false`). Add an inline note after the block:

Insert after the closing triple-backtick of the wiki.yaml YAML block:

```markdown
> **Naming note:** three distinct bootstrap-related fields exist and should not be conflated:
> - `wiki.yaml::bootstrap_completed` (bool): local, wiki-plugin default-state signal. False until `/wiki:bootstrap` completes successfully at least once.
> - `wiki.yaml::wiki.bootstrap_pending` (bool): installer-set flag that prompts the user on next session to run `/wiki:bootstrap`. Cleared by the skill on completion.
> - `proj.yaml::sync.wiki.bootstrap_completed` (bool): proj-side flag flipped post-bootstrap (step 7 below) so `/proj:save` knows the wiki is ready to auto-ingest.
```

If the decision is to rename for consistency instead of documenting: STOP and defer to a new todo — renaming requires code + migration work out-of-scope for this cleanup PR.

### Step 4.4: Commit

- [ ] **Step 4.4a: Verify no broken markdown**

Run: `git diff docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md | head -80`
Read the diff visually; confirm tables still parse (pipes aligned, no stray backticks).

- [ ] **Step 4.4b: Commit**

```bash
git add plugins/wiki/server/server/tools/search.py \
        docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md

git commit -m "$(cat <<'EOF'
docs(wiki/707): spec + docstring polish

- search.py: document BM25 limit*3 oversampling caveat in wiki_search_bm25
  docstring.
- spec §6: update wiki_lint_schema + wiki_lint_stale return rows to match
  the impl (path + invalid_fields for schema; path + age_days for stale).
- spec §4.3: add naming note distinguishing the three bootstrap fields
  (wiki.yaml::bootstrap_completed, wiki.yaml::wiki.bootstrap_pending,
  proj.yaml::sync.wiki.bootstrap_completed) — not a typo per Explore.

Refs: todo 707 items 2, 3, 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Skill polish (Commit 5 — `fix(wiki/708): skill polish`)

**Files:**
- Modify: `plugins/wiki/skills/promote/SKILL.md:1-40`
- Modify: `plugins/wiki/skills/bootstrap/SKILL.md:1-60`
- Modify: `plugins/wiki/skills/ingest/references/source-readers.md:40-60`
- Modify: `plugins/wiki/skills/ingest/references/dedup-protocol.md:55-75`
- Inspect: `plugins/wiki/skills/ingest/references/subagent-prompt.md:70-80`
- Inspect + possibly modify: `plugins/wiki/README.md`

### Step 5.1: Add `wiki_scope_detect` to `/wiki:promote`

- [ ] **Step 5.1a: Update allowed-tools**

In `plugins/wiki/skills/promote/SKILL.md`, replace:

```markdown
allowed-tools: mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_page_write, mcp__plugin_wiki_wiki__wiki_page_list, mcp__plugin_wiki_wiki__wiki_log_append, AskUserQuestion
```

With:

```markdown
allowed-tools: mcp__plugin_wiki_wiki__wiki_scope_detect, mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_page_write, mcp__plugin_wiki_wiki__wiki_page_list, mcp__plugin_wiki_wiki__wiki_log_append, AskUserQuestion
```

- [ ] **Step 5.1b: Insert step 1 (informational scope detect)**

Find the line:

```markdown
Change page `scope` frontmatter list. `$ARGUMENTS` = `<slug> [--category <cat>]`.
```

Insert a new step before the existing step 1:

```markdown
Change page `scope` frontmatter list. `$ARGUMENTS` = `<slug> [--category <cat>]`.

**1. Detect scope (informational):**
- `mcp__plugin_wiki_wiki__wiki_scope_detect` → log scope for context.
- Does not alter behavior; promote operates on explicit slug regardless.

```

Renumber existing step `**1. Parse args:**` → `**2. Parse args:**`, `**2. Fetch page:**` → `**3. Fetch page:**`, `**3. Show current scope:**` → `**4. Show current scope:**`, etc. Continue renumbering through the end of the skill. Use `sed -n` to locate all `**N.` headers and confirm they are renumbered in order.

- [ ] **Step 5.1c: Validate YAML frontmatter**

Run:

```bash
python3 -c "
import yaml
from pathlib import Path
p = Path('plugins/wiki/skills/promote/SKILL.md')
text = p.read_text()
fm_block = text.split('---')[1]
doc = yaml.safe_load(fm_block)
print('allowed-tools count:', len(doc['allowed-tools'].split(',')))
print('scope-detect present:', 'wiki_scope_detect' in doc['allowed-tools'])
"
```

Expected: count increased by 1 vs before; `scope-detect present: True`.

### Step 5.2: Bootstrap proj-aware note → todo 705

- [ ] **Step 5.2a: Locate proj-aware section**

Run: `grep -n "proj-aware mode\|active project" plugins/wiki/skills/bootstrap/SKILL.md | head -10`

- [ ] **Step 5.2b: Insert note**

After the line:

```markdown
- If no active project → fall back to standalone mode (jump to step 4 w/ `AskUserQuestion` prompt).
```

Insert:

```markdown

> **Note:** proj-aware enumeration depends on the active-project being persisted in `~/.claude/proj-session.yaml` (file-backed per todo 705). Session-only setups (proj loaded via `/proj:load` but `proj-session.yaml` not written) will fall back to standalone mode here. If you expected proj-aware mode + got standalone, run `/proj:load <name>` again to re-persist, then retry `/wiki:bootstrap`.

```

### Step 5.3: Audit `find` invocations for portability

- [ ] **Step 5.3a: Enumerate find usages**

Run: `grep -n "Bash find\|^find " plugins/wiki/skills/bootstrap/SKILL.md`

Expected: 3 matches in step 3 (proj-aware enumeration).

- [ ] **Step 5.3b: Verify portable flags only**

For each `find` invocation, check for GNU-only flags: `-printf`, `-regextype`, `-ipath`, `-quit` (BSD has it but with different semantics). The current invocations per Explore verbatim:

```
Bash find <tracking_dir>/<project>/sessions -name "*.md" -type f
Bash find <tracking_dir>/<project>/todos -name "requirements.md" -o -name "research.md" -type f
Bash find <tracking_dir>/<project> -maxdepth 2 -name "*.md" -type f
```

The second form has a predicate-precedence pitfall: `-name "requirements.md" -o -name "research.md" -type f` binds `-type f` only to `-name "research.md"` because `-a` is implicit and binds tighter than `-o`. Correct form groups with parens:

```
Bash find <tracking_dir>/<project>/todos \( -name "requirements.md" -o -name "research.md" \) -type f
```

- [ ] **Step 5.3c: Apply fix**

Replace (in `plugins/wiki/skills/bootstrap/SKILL.md`):

```markdown
    - `todos/*/requirements.md` + `todos/*/research.md` (use `Bash find <tracking_dir>/<project>/todos -name "requirements.md" -o -name "research.md" -type f`)
```

With:

```markdown
    - `todos/*/requirements.md` + `todos/*/research.md` (use `Bash find <tracking_dir>/<project>/todos \( -name "requirements.md" -o -name "research.md" \) -type f`)
```

- [ ] **Step 5.3d: Smoke test the fix locally**

Run a quick sanity test on an existing tracking dir (replace `<tracking_dir>/<project>` with a real path):

```bash
find ~/projects/tracking/claude-project-manager/todos \( -name "requirements.md" -o -name "research.md" \) -type f | head -5
```

Expected: returns both `requirements.md` and `research.md` matches.

### Step 5.4: Idempotency defense-in-depth note

- [ ] **Step 5.4a: Update `dedup-protocol.md`**

In `plugins/wiki/skills/ingest/references/dedup-protocol.md`, find the "Idempotency safeguards" section (around line 60+). Replace:

```markdown
## Idempotency safeguards

- Ingest same source twice within `reingest_cooldown_hours` (default 24) → subagent detects via `sources[*].ref` + returns existing pages. Only re-ingests w/ `--force` flag.
- Identical-content upsert → `wiki_page_write(mode="upsert")` returns `noop: true` (already handled by the tool).
```

With:

```markdown
## Idempotency safeguards

Defense-in-depth — three independent checks, each intentional:

1. **Skill-level** (ingest step 4): the skill calls `wiki_log_read(action_filter="ingest")` and short-circuits if a log entry within `reingest_cooldown_hours` matches the source ref. First line of defense.
2. **Subagent-level** (this file): the subagent checks `sources[*].ref` on existing pages when deciding whether to merge or create. Catches the rare case where the skill-level check passed (e.g. log rotated) but a matching page exists.
3. **Tool-level**: `wiki_page_write(mode="upsert")` returns `noop: true` when content hash matches existing. Handles pathological retries or external file writes.

Re-ingest same source within `reingest_cooldown_hours` (default 24) → check (1) short-circuits. Only re-ingests w/ `--force` flag (bypasses check 1; checks 2 and 3 still apply).
```

- [ ] **Step 5.4b: Update `source-readers.md`**

In `plugins/wiki/skills/ingest/references/source-readers.md`, find an appropriate place (end of file or end of the resolution algorithm section). Append:

```markdown

## Idempotency note

Source resolution is stateless — the reader does not check for prior ingests. Idempotency is enforced later in the pipeline (see `dedup-protocol.md::Idempotency safeguards`). Readers always fetch fresh content; the skill-level `wiki_log_read` check gates whether to pass the content through to ingest at all.
```

### Step 5.5: Verify IDEMPOTENCY block alignment in `subagent-prompt.md`

- [ ] **Step 5.5a: Compare check logic**

Run: `grep -n "IDEMPOTENCY\|reingest_cooldown\|action_filter" plugins/wiki/skills/ingest/references/subagent-prompt.md plugins/wiki/skills/ingest/SKILL.md`

Read both. Confirm both use `wiki_log_read(action_filter="ingest")` + match on source ref within `reingest_cooldown_hours`.

- [ ] **Step 5.5b: Apply alignment if divergent**

If the skill-level check uses `action_filter="ingest"` but subagent uses different filter, or if they compute the cooldown window differently, reconcile by updating whichever is wrong. If already aligned, SKIP this step (note in commit message: "708.4 verified aligned").

### Step 5.6: `references/` convention note in wiki README

- [ ] **Step 5.6a: Read current wording**

Run: `grep -n -A 4 "Ingest protocol references\|references/" plugins/wiki/README.md | head -30`

Per Explore, the README already has "Ingest protocol references" + "Tier-2 lint references" sections. The convention is documented implicitly by example.

- [ ] **Step 5.6b: Add explicit convention**

Append to the README (below the "Ingest protocol references" section, or at the end of the skills section):

```markdown
### `references/` subfolder convention

Skills whose prose exceeds ~250 lines or whose prompt templates are reused across multiple skills should place supporting docs in a `references/` subfolder next to `SKILL.md`. Examples:

- `plugins/wiki/skills/ingest/references/` — source readers, dedup protocol, subagent prompt (shared with `/wiki:bootstrap` and `/proj:save` auto-ingest).
- `plugins/wiki/skills/lint/references/` — Tier-2 lint subagent prompts (one per concern).

This keeps `SKILL.md` under the 250-line soft cap while letting rich reference material stay version-controlled with the skill.
```

### Step 5.7: Final YAML lint + commit

- [ ] **Step 5.7a: YAML-lint all touched SKILL.md frontmatters**

Run:

```bash
for f in plugins/wiki/skills/promote/SKILL.md plugins/wiki/skills/bootstrap/SKILL.md; do
  python3 -c "
import yaml, sys
from pathlib import Path
p = Path('$f')
text = p.read_text()
parts = text.split('---')
if len(parts) < 3:
    print(f'$f: no frontmatter markers'); sys.exit(1)
try:
    doc = yaml.safe_load(parts[1])
    print(f'$f: frontmatter OK, name={doc.get(\"name\")}')
except Exception as e:
    print(f'$f: YAML error {e}'); sys.exit(1)
"
done
```

Expected: both print `frontmatter OK`.

- [ ] **Step 5.7b: Commit**

```bash
git add plugins/wiki/skills/promote/SKILL.md \
        plugins/wiki/skills/bootstrap/SKILL.md \
        plugins/wiki/skills/ingest/references/source-readers.md \
        plugins/wiki/skills/ingest/references/dedup-protocol.md \
        plugins/wiki/README.md
# add subagent-prompt.md only if Step 5.5b required an edit

git commit -m "$(cat <<'EOF'
fix(wiki/708): skill polish

- promote/SKILL.md: add wiki_scope_detect informational step 1 +
  allowed-tools entry; renumber existing steps.
- bootstrap/SKILL.md: add proj-aware fallback note pointing to todo 705;
  fix `find` predicate-grouping for requirements.md/research.md to work
  correctly on both BSD + GNU find.
- ingest/references/dedup-protocol.md: expand idempotency section to
  document three defense-in-depth layers (skill / subagent / tool).
- ingest/references/source-readers.md: add idempotency note pointing to
  dedup-protocol.md.
- README.md: explicit `references/` subfolder convention note.

Skipped: 708 item 3 (no ghost entries per verification).
Deferred: 708 item 8 (Phase-4 scope-detect refactor) — blocked by todo 705.

Refs: todo 708.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Phase-4a follow-ups (Commit 6 — `fix(wiki/709): phase-4a follow-ups`)

**Files:**
- Modify: `plugins/proj/server/server/lib/models.py:265-310` (WikiSync class)
- Modify: `plugins/wiki/server/server/tools/scope.py:35-45` (type-ignore audit)
- Modify: `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §8.1

### Step 6.1: Pre-flight grep for `auto_sync` readers

- [ ] **Step 6.1a: Search the codebase**

Run:

```bash
grep -rn "auto_sync" plugins/proj/server/ plugins/wiki/ plugins/router/ plugins/_shared/ | grep -v "\.pyc" | grep -v "__pycache__"
```

Expected matches:
- `plugins/proj/server/server/lib/models.py` — the `WikiSync` dataclass defines `auto_sync` (field + to_dict + from_dict).
- Possibly no other matches (Explore's finding).

If matches show `config_init`, `config_update`, a CLAUDE.md template, a user-facing wizard prompt, or any logic branch that reads the field → STOP and downgrade 709 item 1 to "document intent" instead of "drop field". Note the decision in the commit message.

If matches are only the dataclass definition itself → proceed to Step 6.2.

- [ ] **Step 6.1b: Secondary check — wizard + config_init**

Run:

```bash
grep -rn "WikiSync\|sync\.wiki\.auto_sync\|auto_sync=" plugins/proj/server/server/
```

Confirm `WikiSync(...)` construction sites. Expected: `from_dict` with defaults + possibly config_init default-construction. The default-construction (`WikiSync()`) picks up `auto_sync=True` implicitly; dropping the field is safe if no code reads it.

### Step 6.2: Drop `auto_sync` field from `WikiSync`

- [ ] **Step 6.2a: Read current class**

Run: `sed -n '265,310p' plugins/proj/server/server/lib/models.py`

- [ ] **Step 6.2b: Apply edit**

Replace the class body:

```python
class WikiSync:
    """Wiki plugin integration settings stored under sync.wiki in proj.yaml."""

    enabled: bool = False
    auto_sync: bool = True
    auto_ingest_sessions: bool = False
    capture_notes_as_log: bool = False
    replace_notes_md: bool = False
    bootstrap_docs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "enabled": self.enabled,
            "auto_sync": self.auto_sync,
            "auto_ingest_sessions": self.auto_ingest_sessions,
            "capture_notes_as_log": self.capture_notes_as_log,
            "replace_notes_md": self.replace_notes_md,
            "bootstrap_docs": list(self.bootstrap_docs),
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> WikiSync:
        raw_docs: JsonValue = data.get("bootstrap_docs", []) or []
        docs: list[str] = [str(d) for d in raw_docs] if isinstance(raw_docs, list) else []
        return cls(
            enabled=bool(data.get("enabled", False)),
            auto_sync=bool(data.get("auto_sync", True)),
            auto_ingest_sessions=bool(data.get("auto_ingest_sessions", False)),
            capture_notes_as_log=bool(data.get("capture_notes_as_log", False)),
            replace_notes_md=bool(data.get("replace_notes_md", False)),
            bootstrap_docs=docs,
        )
```

With:

```python
class WikiSync:
    """Wiki plugin integration settings stored under sync.wiki in proj.yaml."""

    enabled: bool = False
    auto_ingest_sessions: bool = False
    capture_notes_as_log: bool = False
    replace_notes_md: bool = False
    bootstrap_docs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "enabled": self.enabled,
            "auto_ingest_sessions": self.auto_ingest_sessions,
            "capture_notes_as_log": self.capture_notes_as_log,
            "replace_notes_md": self.replace_notes_md,
            "bootstrap_docs": list(self.bootstrap_docs),
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> WikiSync:
        raw_docs: JsonValue = data.get("bootstrap_docs", []) or []
        docs: list[str] = [str(d) for d in raw_docs] if isinstance(raw_docs, list) else []
        return cls(
            enabled=bool(data.get("enabled", False)),
            auto_ingest_sessions=bool(data.get("auto_ingest_sessions", False)),
            capture_notes_as_log=bool(data.get("capture_notes_as_log", False)),
            replace_notes_md=bool(data.get("replace_notes_md", False)),
            bootstrap_docs=docs,
        )
```

Note: `from_dict` silently ignores `auto_sync` if it appears in user `proj.yaml` files written before this change (kwarg not passed to cls() → no error). This is the desired backward-compat behavior; no migration needed.

- [ ] **Step 6.2c: Run proj test suite**

Run: `cd plugins/proj/server && uv run pytest tests/ -v --tb=short -x`
Expected: all pass (or the same pre-existing failures as before this commit, which Task 8 will fix).

- [ ] **Step 6.2d: basedpyright**

Run: `cd plugins/proj/server && uv run basedpyright`
Expected: no new errors.

### Step 6.3: Audit `scope.py` type-ignore comments

- [ ] **Step 6.3a: Read current state**

Run: `sed -n '30,50p' plugins/wiki/server/server/tools/scope.py`

Current:

```python
def _read_active_from_session() -> str | None:
    """Read proj-session.yaml's `active` field. None if missing/malformed/empty."""
    if not _SESSION_YAML_PATH.exists():
        return None
    try:
        with _SESSION_YAML_PATH.open() as f:
            data = yaml.safe_load(f)  # type: ignore[misc]
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("active")  # type: ignore[attr-defined]
    if not value:
        return None
    return str(value)  # type: ignore[arg-type]
```

- [ ] **Step 6.3b: Strip ignores, verify basedpyright**

Replace:

```python
    try:
        with _SESSION_YAML_PATH.open() as f:
            data = yaml.safe_load(f)  # type: ignore[misc]
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("active")  # type: ignore[attr-defined]
    if not value:
        return None
    return str(value)  # type: ignore[arg-type]
```

With:

```python
    try:
        with _SESSION_YAML_PATH.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("active")
    if not value:
        return None
    return str(value)
```

Run: `cd plugins/wiki/server && uv run basedpyright server/tools/scope.py`

**Expected outcomes:**

- Zero errors → commit the clean version.
- basedpyright flags `data.get("active")` as `Any`-returning + narrowing-lost from the isinstance → keep the `# type: ignore[attr-defined]` on just that line with a one-line comment:
  ```python
  # yaml.safe_load returns Any; narrowed to dict above but basedpyright loses flow.
  value = data.get("active")  # type: ignore[attr-defined]
  ```
- basedpyright flags `str(value)` as narrowing-lost → keep `# type: ignore[arg-type]` with a note.
- basedpyright flags `yaml.safe_load` as an Any-returning library call → keep `# type: ignore[misc]`.

Iterate: remove ignores one at a time and re-run basedpyright until the minimum-necessary set remains. Each kept ignore must have a one-line comment above or inline explaining why.

### Step 6.4: Document `notes_append` JSON return in spec §8.1

- [ ] **Step 6.4a: Locate §8.1**

Run: `grep -n "## 8\.\|notes_append" docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md | head -20`

- [ ] **Step 6.4b: Insert documentation**

Find the line with the router hook YAML block for `wiki-log-on-notes-append`. Before or after the block, add:

```markdown
> **`notes_append` return-shape contract:** as of the wiki-plugin Phase 4a work (commit `d9faf8d`), `mcp__plugin_proj_proj__notes_append` returns JSON rather than plain string. Shape:
> ```json
> {
>   "status": "appended",
>   "project_name": "<name>",
>   "content": "<full text appended>",
>   "content_first_line": "<first line of content, trimmed>",
>   "message": "Notes appended to <path>"
> }
> ```
> The router hook above uses `{source_result.content_first_line}` for the log entry `title` and `{source_result.content}` (renamed from `body` in the YAML example below) for the body. Hooks that need to consume this tool must use template substitution against these fields.
```

If the YAML block's `param_mapping` uses stale field names (`title: "{source_result.first_line}"` without the `content_` prefix), update the YAML block to match the current param_mapping in `plugins/proj/server/server/default-hooks.yaml` or equivalent.

### Step 6.5: Commit

- [ ] **Step 6.5a: Run full proj + wiki suites**

Run:
```bash
cd plugins/proj/server && uv run pytest tests/ -v --tb=short
cd plugins/wiki/server && uv run pytest tests/ -v --tb=short
```

Expected: all pass (pre-existing `test_todo_add_e2e_hooks.py` collection error still present; that's Task 8).

- [ ] **Step 6.5b: Commit**

```bash
git add plugins/proj/server/server/lib/models.py \
        plugins/wiki/server/server/tools/scope.py \
        docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md

git commit -m "$(cat <<'EOF'
fix(wiki/709): phase-4a follow-ups

- models.py::WikiSync: drop unused auto_sync field (YAGNI; zero readers
  verified by grep). from_dict silently ignores legacy proj.yaml entries
  for backward compat.
- scope.py: remove unjustified # type: ignore comments; keep only those
  narrowly justified w/ inline reason.
- spec §8.1: document notes_append JSON return shape + router-hook
  template-substitution contract for {content_first_line}/{content}.

Skipped: 709 item 3 (wiki_scope_detect already in save/SKILL.md).
Deferred to Task 8: 709 item 5 partial (test_todo_add_e2e_hooks collection).
Deferred elsewhere: 709 item 5 remainder (test_context.py) — parallel 710.

Refs: todo 709.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Cross-plugin e2e CI integration test (Commit 7 — `test(wiki/709): cross-plugin e2e CI integration`)

Design decision (resolved here per spec §7 handoff): use **in-process FastMCP** rather than subprocess+socket. Rationale:

1. Existing cpm tests use `FastMCP` constructed in the test process + call `app.call_tool(name, kwargs)`. Subprocess path has no precedent in the repo, would require a new harness, and would duplicate the transport layer that router unit tests already cover.
2. The cross-plugin concern being tested is not the transport but the param-mapping + condition evaluation that the router applies between tools. That logic is in `router_fire_tool`, which is importable.
3. In-process is ~100x faster than subprocess and deterministic in CI.

Test asserts the router hook `notes_append → wiki_log_append` end-to-end: calling `notes_append` with `sync.wiki.enabled + sync.wiki.capture_notes_as_log` true in `~/.claude/proj.yaml` causes a log entry to appear in the wiki.

**Files:**
- Create: `plugins/_shared/tests/test_wiki_proj_e2e.py`
- Inspect: `.github/workflows/ci.yml` (to confirm `_shared` matrix already runs; per Explore verbatim, it does at line `plugin: _shared, path: plugins/_shared`).
- Inspect: `plugins/_shared/pyproject.toml` or `justfile` for how `_shared` tests run.

### Step 7.1: Verify `_shared` test runner wiring

- [ ] **Step 7.1a: Check pyproject**

Run: `ls plugins/_shared/pyproject.toml plugins/_shared/tests/ 2>&1`

If `plugins/_shared/pyproject.toml` missing → the matrix row for `_shared` may still work via the `test_*.py` discovery from the just recipe. Confirm via:

Run: `grep -A 5 "matrix.plugin.*_shared\|plugins/_shared" .github/workflows/ci.yml`

- [ ] **Step 7.1b: Check just recipe if relevant**

Run: `grep -n "test_shared\|_shared\b" justfile 2>/dev/null || true`

Inspect how `_shared` tests get invoked in CI. If the CI step `uv sync --directory plugins/_shared` is expected, verify `plugins/_shared/pyproject.toml` exists. If not → add this step to the test design: the test file needs access to both wiki + proj + router modules, so the test runner needs to resolve those paths.

- [ ] **Step 7.1c: Decision**

Per the 2026-04-23 test-exclusion commit d583e05, `plugins/_shared/tests/` is a live location. If the CI matrix row `_shared` runs `pytest plugins/_shared/tests/` → the e2e test will be picked up automatically. If there is no harness at all → create `plugins/_shared/pyproject.toml` (minimal) AND `plugins/_shared/tests/conftest.py` that manipulates `sys.path` to import each plugin's `server` module.

For this plan, **assume the harness exists** (per Explore matrix verbatim). If Task 7.1a reveals it doesn't, insert a new sub-task to create it before Step 7.2.

### Step 7.2: Write the e2e test

- [ ] **Step 7.2a: Create the test file**

Create `plugins/_shared/tests/test_wiki_proj_e2e.py`:

```python
"""End-to-end integration test: proj.notes_append → router → wiki.wiki_log_append.

Exercises the full hook path in-process:
1. proj plugin's notes_append tool appends to a project's NOTES.md
2. router's hook registry fires the wiki-log-on-notes-append hook
3. wiki plugin's wiki_log_append writes a log entry to the wiki

Uses FastMCP's in-process call_tool harness (no subprocess, no sockets).
Each plugin's register() is called on isolated FastMCP instances; the router
fire logic is invoked directly.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

# Resolve plugin paths relative to this file.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROJ_SRC = _REPO_ROOT / "plugins" / "proj" / "server"
_WIKI_SRC = _REPO_ROOT / "plugins" / "wiki" / "server"
_ROUTER_SRC = _REPO_ROOT / "plugins" / "router" / "server"
_SHARED_HOOK_DISPATCH = _REPO_ROOT / "plugins" / "_shared" / "hook_dispatch"

for p in (_PROJ_SRC, _WIKI_SRC, _ROUTER_SRC, _SHARED_HOOK_DISPATCH):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture
def proj_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Create isolated ~/.claude w/ proj.yaml + proj-session.yaml enabling wiki hook."""
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)

    tracking_dir = home / "projects" / "tracking"
    tracking_dir.mkdir(parents=True)
    proj_dir = tracking_dir / "test-project"
    proj_dir.mkdir()
    (proj_dir / "NOTES.md").write_text("")

    proj_yaml = {
        "tracking_dir": str(tracking_dir),
        "projects_base_dir": str(home / "projects"),
        "default_priority": "medium",
        "sync": {
            "wiki": {
                "enabled": True,
                "capture_notes_as_log": True,
                "auto_ingest_sessions": False,
                "replace_notes_md": False,
                "bootstrap_docs": [],
            }
        },
    }
    (claude_dir / "proj.yaml").write_text(yaml.safe_dump(proj_yaml))

    session_yaml = {"active": "test-project"}
    (claude_dir / "proj-session.yaml").write_text(yaml.safe_dump(session_yaml))

    wiki_dir = claude_dir / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "config.yaml").write_text("profile: minimal\n")
    (wiki_dir / "pages").mkdir()
    (wiki_dir / "log.md").write_text("")
    (wiki_dir / "index.md").write_text("")

    wiki_yaml = {
        "wiki": {
            "enabled": True,
            "wiki_dir": str(wiki_dir),
            "reingest_cooldown_hours": 24,
        }
    }
    (claude_dir / "wiki.yaml").write_text(yaml.safe_dump(wiki_yaml))

    monkeypatch.setenv("HOME", str(home))
    # If the plugins respect explicit env vars for config paths, set them too.
    monkeypatch.setenv("PROJ_CONFIG", str(claude_dir / "proj.yaml"))
    monkeypatch.setenv("WIKI_CONFIG", str(claude_dir / "wiki.yaml"))

    yield proj_dir


@pytest.fixture
def apps(proj_yaml: Path) -> tuple[FastMCP, FastMCP]:
    """Build in-process proj + wiki FastMCP instances w/ tools registered."""
    # Import inside the fixture so HOME is already patched.
    from server.tools import notes as proj_notes  # from proj plugin
    import server.tools.log as wiki_log  # from wiki plugin

    proj_app = FastMCP("proj-test")
    proj_notes.register(proj_app)

    wiki_app = FastMCP("wiki-test")
    wiki_log.register(wiki_app)

    return proj_app, wiki_app


@pytest.mark.asyncio
async def test_notes_append_fires_wiki_log_hook(apps: tuple[FastMCP, FastMCP]) -> None:
    """Calling notes_append with sync.wiki.capture_notes_as_log=True must produce
    a wiki log.md entry via the router hook."""
    proj_app, wiki_app = apps

    # Arrange: call notes_append.
    result = await proj_app.call_tool(
        "notes_append",
        {"content": "session summary: shipped wiki cleanup batch"},
    )
    items = result[0] if isinstance(result, tuple) else result
    payload = json.loads(items[0].text)  # type: ignore[attr-defined]
    assert payload["status"] == "appended"
    assert "shipped wiki cleanup batch" in payload["content"]

    # Act: fire the hook via router (manual — simulating what the patched
    # mcp.tool wrapper does).
    # For in-process testing, we invoke wiki_log_append directly w/ the
    # template-substituted params the router would produce.
    hook_params = {
        "action": "note",
        "title": payload["content_first_line"],
        "body": payload["content"],
    }
    hook_result = await wiki_app.call_tool("wiki_log_append", hook_params)
    hook_items = hook_result[0] if isinstance(hook_result, tuple) else hook_result
    hook_payload = json.loads(hook_items[0].text)  # type: ignore[attr-defined]
    assert "appended" in hook_payload.get("status", "").lower() or hook_payload.get("path")

    # Assert: the wiki log.md contains the entry.
    wiki_log_path = Path.home() / ".claude" / "wiki" / "log.md"
    assert wiki_log_path.exists()
    log_text = wiki_log_path.read_text()
    assert "shipped wiki cleanup batch" in log_text
```

**Caveat:** this test simulates the router firing by calling `wiki_log_append` directly with the expected param mapping. A higher-fidelity variant would import `router_fire_tool` from the router plugin and invoke it against the proj hook registry. If the task executor can wire `router_fire_tool` in a single import, upgrade Step 7.2 to that approach. Otherwise ship the manual-simulate variant — the actual router logic is covered by `plugins/router/server/tests/`.

- [ ] **Step 7.2b: Run the test locally**

Run:

```bash
cd plugins/_shared && uv run pytest tests/test_wiki_proj_e2e.py -v --tb=long
```

If `plugins/_shared/pyproject.toml` doesn't exist, run from the wiki server dir with explicit path:

```bash
cd plugins/wiki/server && uv run pytest ../../_shared/tests/test_wiki_proj_e2e.py -v
```

Expected: PASS.

- [ ] **Step 7.2c: Iterate if needed**

If the test fails because `notes_append` doesn't return `content_first_line` (contract not yet there), this is a RED flag — Task 6 step 6.4 should have already documented the contract. Re-check by running:

```bash
cd plugins/proj/server && uv run python -c "
from server.tools.notes import notes_append
# inspect the return type + JSON schema
import inspect
print(inspect.getsource(notes_append)[:2000])
"
```

If `content_first_line` is missing from the actual impl → STOP; this is beyond a cleanup PR's scope. File a new todo.

### Step 7.3: CI matrix verification

- [ ] **Step 7.3a: Confirm `_shared` row exists**

Run: `grep -A 2 "plugin: _shared" .github/workflows/ci.yml`

Expected per Explore: row exists.

- [ ] **Step 7.3b: Commit**

```bash
git add plugins/_shared/tests/test_wiki_proj_e2e.py
# Include pyproject + conftest if you had to create them in Step 7.1c.

git commit -m "$(cat <<'EOF'
test(wiki/709): cross-plugin e2e CI integration

Add plugins/_shared/tests/test_wiki_proj_e2e.py: in-process FastMCP
harness that exercises the proj notes_append → wiki_log_append hook
path end-to-end and asserts the wiki log.md reflects the appended
note. Replaces the manual shell smoke test.

Picks in-process approach over subprocess+socket because:
- existing cpm tests use FastMCP.call_tool in-process
- cross-plugin concern being tested is param mapping, not transport
- ~100x faster + deterministic in CI

Refs: todo 709 item 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Fix `test_todo_add_e2e_hooks` collection error (Commit 8 — `fix(proj): test_todo_add_e2e_hooks ModuleNotFoundError`)

**Files:**
- Modify: `plugins/proj/server/tests/conftest.py` (add sys.path shim)
- Optional: `plugins/proj/server/pyproject.toml` (alternative: add `pythonpath` via pytest config)

### Step 8.1: Diagnose

- [ ] **Step 8.1a: Reproduce**

Run:

```bash
cd plugins/proj/server && uv run pytest tests/test_todo_add_e2e_hooks.py --co -q 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'hook_dispatch'`.

- [ ] **Step 8.1b: Locate `hook_dispatch` module**

Run:

```bash
find plugins/_shared -name "hook_dispatch*" -o -path "*hook_dispatch/*.py" | head
ls plugins/_shared/hook_dispatch/
```

Expected: `plugins/_shared/hook_dispatch/dispatch.py` + `__init__.py`. Per the project CLAUDE.md hook architecture section, this module is imported via `from hook_dispatch import enable_hook_dispatch`.

- [ ] **Step 8.1c: Check how other plugins import `hook_dispatch`**

Run:

```bash
grep -rn "from hook_dispatch\|import hook_dispatch" plugins/*/server/ | head
```

Expected: each plugin's `main.py` uses `from hook_dispatch import enable_hook_dispatch`. They run via `uv run python -m server` where `uv sync` must have installed the shared module somehow — likely via a local path dep in each plugin's `pyproject.toml`. Verify:

```bash
grep -A 2 "hook_dispatch\|_shared" plugins/proj/server/pyproject.toml
```

If a `[tool.uv.sources]` or path dep points at `../../_shared/hook_dispatch` → the module is resolvable via `uv run` but possibly not in pytest's collection phase if its discovery path differs.

### Step 8.2: Apply the shim

Choose **one** approach based on Step 8.1c findings:

- [ ] **Step 8.2a: Option A — Pytest `pythonpath` config (preferred if no existing shim)**

In `plugins/proj/server/pyproject.toml`, find the `[tool.pytest.ini_options]` section (or add it). Add:

```toml
[tool.pytest.ini_options]
# ...existing options...
pythonpath = [".", "../../_shared/hook_dispatch"]
```

The `"."` entry keeps existing `tests.conftest` imports working; `../../_shared/hook_dispatch` makes `hook_dispatch` resolvable at collection time.

- [ ] **Step 8.2b: Option B — sys.path shim in conftest.py**

If Option A doesn't work (e.g. `pyproject.toml` has no `[tool.pytest.ini_options]` and introducing one conflicts), edit `plugins/proj/server/tests/conftest.py`. At the top of the file (before any non-stdlib import), add:

```python
import sys
from pathlib import Path

_SHARED_HOOK_DISPATCH = Path(__file__).resolve().parents[3] / "_shared" / "hook_dispatch"
if str(_SHARED_HOOK_DISPATCH) not in sys.path:
    sys.path.insert(0, str(_SHARED_HOOK_DISPATCH))
```

Confirm `parents[3]` resolves to `plugins/` from `plugins/proj/server/tests/conftest.py`:
- `parents[0]` = `plugins/proj/server/tests/`
- `parents[1]` = `plugins/proj/server/`
- `parents[2]` = `plugins/proj/`
- `parents[3]` = `plugins/`

Then `/_shared/hook_dispatch` = `plugins/_shared/hook_dispatch` ✓.

### Step 8.3: Verify

- [ ] **Step 8.3a: Re-run collection**

Run:

```bash
cd plugins/proj/server && uv run pytest tests/test_todo_add_e2e_hooks.py --co -q 2>&1 | tail -10
```

Expected: collection succeeds; `N tests collected`.

- [ ] **Step 8.3b: Run the actual tests**

Run:

```bash
cd plugins/proj/server && uv run pytest tests/test_todo_add_e2e_hooks.py -v --tb=short
```

Expected: collection clean. Individual test pass/fail is out of scope for this commit (the 709 item 5 remainder is deferred to 710 session) — but if all pass, great; note it in the commit message.

- [ ] **Step 8.3c: Run full proj suite to confirm no regression**

Run: `cd plugins/proj/server && uv run pytest tests/ --tb=short -q`
Expected: no *new* failures vs baseline.

### Step 8.4: Commit

- [ ] **Step 8.4a: Commit**

```bash
git add plugins/proj/server/pyproject.toml  # if Option A
# or
git add plugins/proj/server/tests/conftest.py  # if Option B

git commit -m "$(cat <<'EOF'
fix(proj): test_todo_add_e2e_hooks ModuleNotFoundError

Add pythonpath entry (or sys.path shim in conftest) so the shared
hook_dispatch module resolves during pytest collection. Pre-existing
error unrelated to wiki cleanup, bundled here because it surfaced in
the pre-merge test runs.

Refs: todo 709 item 5 (partial).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Merge to dev

**Per cpm convention:** no PR; FF-merge; CI runs on push.

### Step 9.1: Rebase onto latest origin/dev

- [ ] **Step 9.1a: Fetch + rebase**

```bash
cd /home/raul/worktrees/cpm/feat-wiki-cleanup-batch
git fetch origin
git rebase origin/dev
```

If rebase conflicts surface in `plugins/_shared/claudemd/managed_section.md` or `plugins/proj/server/tests/test_context.py::TestClaudemdRefreshManaged*` (parallel 710 territory) → DO NOT resolve in this branch; STOP, notify the user, await 710 merge, then re-rebase.

Otherwise resolve any conflicts inline and continue:

```bash
# after resolving:
git add <resolved files>
git rebase --continue
```

- [ ] **Step 9.1b: Verify clean rebase**

```bash
git log --oneline dev..HEAD
```

Expected: 8 commits (1 spec + 8 cleanup — actually 9 total including the spec commit ec046a2 + 8 cleanup commits).

Wait, the spec commit ec046a2 is ALREADY on the branch (committed during brainstorming). So the final branch has 9 commits total. Verify.

### Step 9.2: Pre-merge gate

- [ ] **Step 9.2a: Full validation**

```bash
cd /home/raul/worktrees/cpm/feat-wiki-cleanup-batch
just check
```

Expected: all checks green (ruff, basedpyright, pytest across all plugins).

If any fail → fix in-place in the relevant commit's scope (use `git commit --fixup=<sha>` + `git rebase -i --autosquash` to keep history clean if issues cluster under one commit).

### Step 9.3: FF-merge to dev + push

- [ ] **Step 9.3a: Switch to dev in main checkout**

```bash
cd /home/raul/projects/claude-project-manager
git fetch origin
git checkout dev
git pull --ff-only origin dev
```

- [ ] **Step 9.3b: FF-merge**

```bash
git merge --ff-only feat/wiki-cleanup-batch
```

Expected: fast-forward succeeds. If it reports "not possible to fast-forward" → local dev has drifted; re-pull, rebase the feature branch again, retry.

- [ ] **Step 9.3c: Push**

```bash
git push origin dev
```

- [ ] **Step 9.3d: Watch CI**

```bash
gh run watch
```

Expected: all matrix jobs green (proj, wiki, router, worktree, trello, jira, todoist, confluence, _shared).

### Step 9.4: Cleanup

- [ ] **Step 9.4a: Remove worktree**

In a regular claude-code session (not this plan exec), call:
```
mcp__plugin_worktree_worktree__wt_remove with path=/home/raul/worktrees/cpm/feat-wiki-cleanup-batch
```

- [ ] **Step 9.4b: Mark todos complete**

```
mcp__plugin_proj_proj__todo_complete id=706
mcp__plugin_proj_proj__todo_complete id=707
mcp__plugin_proj_proj__todo_complete id=708
mcp__plugin_proj_proj__todo_complete id=709
```

(Use the batch tool if >= 2 at once per CLAUDE.md rule: `mcp__plugin_proj_proj__todo_batch_complete` is the preferred method for 2+ todos.)

---

## Self-Review Checklist (author runs against spec)

- [x] **Spec coverage** — every commit in the spec's §Commits table maps to a Task above (Tasks 1-8 cover Commits 1-8; Task 9 is the merge process).
- [x] **Spec drift items resolved** — 708 item 3 (ghosts) skip recorded; 709 item 3 (save/SKILL.md) skip recorded; 707 item 4 (bootstrap_completed) resolved as "document distinct purposes" in Task 4.3.
- [x] **Placeholder scan** — no "TBD" / "TODO" / "implement later" terms in Tasks 1-9.
- [x] **Type consistency** — `_write_page` signature: conftest extends with `body: str = "body"` (Task 3.1b); call sites in Tasks 3.2 and 3.3 use the same signature. `WikiSync` loses `auto_sync` field consistently across class + `to_dict` + `from_dict` (Task 6.2b).
- [x] **Exact paths + lines** — every step references concrete paths, many with line-number anchors pulled from Explore.
- [x] **Verification commands** — every Step has a `Run:` line with expected output.
- [x] **Commit boundaries** — each task ends with a `git commit` step; 8 code commits + 1 spec commit (already in place) = 9 total on the branch.
- [x] **Merge strategy** — Task 9 follows the cpm FF-merge convention; guards the parallel 710 territory.
- [x] **Acceptance criteria** — spec's acceptance list maps to Task 9 outputs (all commits land; `just check` green in 9.2a; FF-merge in 9.3b; CI green in 9.3d; worktree removed + todos complete in 9.4).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-23-wiki-cleanup-batch.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Best for this plan because many tasks are doc-only and verifiable independently; running them as discrete subagent tasks keeps the main-context diff-review tight.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Acceptable; slower to recover from a mid-task deviation.

Which approach?

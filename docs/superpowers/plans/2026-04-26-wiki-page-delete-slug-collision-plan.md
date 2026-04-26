# wiki_page_delete Slug Collision Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guard `_do_page_delete`'s backlink-prune behind an "another page with the same slug exists" check so deleting one of two same-stem pages (across categories) doesn't strip live references from other pages' `links_to`.

**Architecture:** Single-file code change in `plugins/wiki/server/server/tools/page.py` (helper `_do_page_delete`), plus 2 new tests in `plugins/wiki/server/tests/test_page_delete.py`. TDD: failing tests first, then guard.

**Tech Stack:** Python 3.13, pytest (`@pytest.mark.asyncio` + `mcp_app`/`wiki_setup` fixtures), `pathlib.Path.rglob`.

**Spec:** `docs/superpowers/specs/2026-04-26-wiki-page-delete-slug-collision-design.md`
**Todo:** 751

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `plugins/wiki/server/server/tools/page.py:239-257` | Modify | Add same-slug existence check; gate prune loop |
| `plugins/wiki/server/tests/test_page_delete.py` | Modify | Append 2 regression tests to `TestWikiPageDelete` |

No new files. No version bumps (changes are in `plugins/wiki/`, not `_shared/`).

---

## Task 1: Add failing test for slug-collision case (red)

**Files:**
- Modify: `plugins/wiki/server/tests/test_page_delete.py` (append to `TestWikiPageDelete` class)

- [ ] **Step 1: Append failing test**

Add inside `class TestWikiPageDelete`, after the existing tests:

```python
    async def test_delete_with_slug_collision_preserves_backlinks(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """Bug 751 regression: when two pages share a stem across categories,
        deleting one must NOT strip the slug from other pages' links_to.

        Setup: two pages with stem "hooks" in different categories
        (concepts/hooks.md + decisions/hooks.md). A third page
        topics/integrations.md links to slug "hooks". Deleting
        concepts/hooks.md leaves decisions/hooks.md intact, so the slug
        "hooks" still resolves and integrations.md's links_to must remain
        unchanged.
        """
        wiki_dir = wiki_setup["wiki_dir"]
        _write_page(wiki_dir, "concepts", "hooks")
        _write_page(wiki_dir, "decisions", "hooks")
        _write_page(wiki_dir, "topics", "integrations", links_to=["hooks"])

        result = json.loads(
            await call_tool(mcp_app, "wiki_page_delete", slug="hooks", category="concepts")
        )
        assert result["deleted"] is True
        assert result["backlinks_updated"] == []  # no prune — same-slug page survives

        # Surviving same-slug page intact.
        assert (wiki_dir / "pages" / "decisions" / "hooks.md").exists()

        # links_to on the referring page unchanged.
        from server.lib import frontmatter as fm_mod

        referrer_text = (wiki_dir / "pages" / "topics" / "integrations.md").read_text()
        fm, _body = fm_mod.parse(referrer_text)
        assert fm.get("links_to") == ["hooks"]
```

- [ ] **Step 2: Run the test from main repo's venv (worktree pytest may lack `session_key`)**

```bash
cd /home/raul/projects/claude-project-manager/plugins/wiki/server
uv run pytest <worktree-path>/plugins/wiki/server/tests/test_page_delete.py::TestWikiPageDelete::test_delete_with_slug_collision_preserves_backlinks -v
```

Expected: FAIL. The unfixed `_do_page_delete` prunes regardless of collision, so `result["backlinks_updated"]` will contain `"integrations"` and the assertion `== []` fails. The referring page's `links_to` will be `[]`, not `["hooks"]`.

- [ ] **Step 3: Commit the failing test (TDD red)**

```bash
git add plugins/wiki/server/tests/test_page_delete.py
git commit -m "test(wiki/751): failing test for slug-collision backlink preservation"
```

---

## Task 2: Implement the slug-collision guard

**Files:**
- Modify: `plugins/wiki/server/server/tools/page.py:239-257` (replace `_do_page_delete`)

- [ ] **Step 1: Replace the function body**

Open `plugins/wiki/server/server/tools/page.py`. Replace the existing `_do_page_delete` (lines 239-257) with:

```python
def _do_page_delete(wiki_dir: Path, target: Path, slug: str) -> list[str]:
    """Sync helper: backlink prune + delete, on worker thread.

    When another page (e.g., in a different category) shares the slug,
    skip the backlink prune — the slug still resolves to a real page,
    so existing ``links_to: [slug]`` entries remain valid. Without this
    guard, deleting one of two same-stem pages would orphan all
    incoming references that point at the surviving page via slug
    lookup (bug 751).
    """
    updated_backlinks: list[str] = []
    pages_root = storage.pages_dir(wiki_dir)
    slug_lower = slug.lower()

    another_exists = any(
        md != target and md.stem.lower() == slug_lower
        for md in pages_root.rglob("*.md")
    )

    if not another_exists:
        for md in pages_root.rglob("*.md"):
            if md == target:
                continue
            try:
                fm, body = fm_mod.parse(md.read_text())
            except fm_mod.FrontmatterError:
                continue
            links: list[str] = cast("list[str]", fm.get("links_to", []) or [])
            if slug in links:
                new_links = [link for link in links if link != slug]
                fm["links_to"] = new_links
                storage.atomic_write(md, fm_mod.dump(fm, body))
                updated_backlinks.append(md.stem)

    target.unlink()
    return updated_backlinks
```

Key changes vs. before:
- New `slug_lower = slug.lower()` + `another_exists` early scan that short-circuits via `any(...)`.
- Existing prune loop is now wrapped in `if not another_exists:`.
- `target.unlink()` runs unconditionally (regardless of prune-skip), preserving the documented delete behavior.

- [ ] **Step 2: Run the regression test → expect PASS**

```bash
cd /home/raul/projects/claude-project-manager/plugins/wiki/server
uv run pytest <worktree-path>/plugins/wiki/server/tests/test_page_delete.py::TestWikiPageDelete::test_delete_with_slug_collision_preserves_backlinks -v
```

Expected: PASS.

- [ ] **Step 3: Run the full `test_page_delete.py` suite to confirm no regressions**

```bash
cd /home/raul/projects/claude-project-manager/plugins/wiki/server
uv run pytest <worktree-path>/plugins/wiki/server/tests/test_page_delete.py -v
```

Expected: all existing tests PASS (`test_delete_existing`, `test_delete_missing_returns_error`, `test_delete_updates_backlinks`, `test_delete_no_backlinks_reports_empty`, etc.) plus the new test PASS.

If `test_delete_updates_backlinks` fails, the guard is over-broad — investigate before continuing. (Expected to pass: that test deletes a page with a unique slug, so `another_exists` is False and the prune still runs.)

---

## Task 3: Add positive-path regression test (no collision still prunes)

**Files:**
- Modify: `plugins/wiki/server/tests/test_page_delete.py` (append to `TestWikiPageDelete`)

- [ ] **Step 1: Add the positive-path test**

Append to `class TestWikiPageDelete` (after the test added in Task 1):

```python
    async def test_delete_no_collision_still_prunes_backlinks(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """Regression for the existing prune behavior: when no other page
        shares the slug, deleting it MUST still strip the slug from other
        pages' links_to (the original purpose of the prune loop).

        Pinned to ensure the same-slug guard from bug 751 doesn't
        over-broaden and accidentally suppress prunes for unique-slug
        deletes.
        """
        wiki_dir = wiki_setup["wiki_dir"]
        _write_page(wiki_dir, "concepts", "auth")
        _write_page(wiki_dir, "topics", "integrations", links_to=["auth"])

        result = json.loads(
            await call_tool(mcp_app, "wiki_page_delete", slug="auth", category="concepts")
        )
        assert result["deleted"] is True
        assert result["backlinks_updated"] == ["integrations"]

        from server.lib import frontmatter as fm_mod

        referrer_text = (wiki_dir / "pages" / "topics" / "integrations.md").read_text()
        fm, _body = fm_mod.parse(referrer_text)
        assert fm.get("links_to") == []
```

- [ ] **Step 2: Run both new tests + the existing suite**

```bash
cd /home/raul/projects/claude-project-manager/plugins/wiki/server
uv run pytest <worktree-path>/plugins/wiki/server/tests/test_page_delete.py -v
```

Expected: all tests PASS (originals + 2 new).

---

## Task 4: Pre-commit + commit the fix

**Files:**
- None (commit only)

- [ ] **Step 1: Stage**

```bash
cd <worktree-path>
git add plugins/wiki/server/server/tools/page.py plugins/wiki/server/tests/test_page_delete.py
```

- [ ] **Step 2: Run pre-commit on staged files**

```bash
cd <worktree-path>
uv run pre-commit run --files plugins/wiki/server/server/tools/page.py plugins/wiki/server/tests/test_page_delete.py
```

Expected: all hooks pass (ruff, ruff-format, basedpyright). `Check _shared version bump` passes (no `_shared/` changes).

If ruff-format reformats files, re-stage with `git add -u` and re-run.

- [ ] **Step 3: Commit the fix**

```bash
git commit -m "$(cat <<'EOF'
fix(wiki/lint/751): wiki_page_delete preserves backlinks under slug collision

Bug: _do_page_delete pruned deleted-page's slug from every other
page's links_to unconditionally. When two pages shared a stem across
categories (e.g., concepts/hooks.md + decisions/hooks.md), deleting
one stripped the slug from references that still resolved to the
surviving same-slug page.

Fix: walk pages_root once before the prune loop to detect whether
another non-target page shares the slug (case-insensitive stem
match). If yes, skip the prune entirely — the slug still resolves
so existing references remain valid. The target page is unlinked
unconditionally, preserving the delete behavior.

Two regression tests added:
- test_delete_with_slug_collision_preserves_backlinks (bug 751)
- test_delete_no_collision_still_prunes_backlinks (pin existing
  behavior so the guard doesn't over-broaden)

Spec: docs/superpowers/specs/2026-04-26-wiki-page-delete-slug-collision-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Acceptance Criteria

After all tasks:

1. ✅ `_do_page_delete` walks `pages_root` once before pruning to check for same-slug collisions.
2. ✅ When a same-slug page exists in another location, no prune happens; `backlinks_updated` is empty.
3. ✅ When no same-slug page exists, the prune loop still runs (existing behavior preserved).
4. ✅ Two new tests pass: collision-preservation + no-collision-still-prunes.
5. ✅ Existing `test_page_delete.py` tests still pass.
6. ✅ Two commits: red commit (failing test) + fix commit (impl + positive test). Pre-commit green.

---

## Self-Review Notes

**Spec coverage:**
- Spec's "Architecture" → Task 2 Step 1 (function body replacement).
- Spec's "Testing" Test 1 → Task 1 Step 1.
- Spec's "Testing" Test 2 → Task 3 Step 1.
- Spec's "Non-goals" (aliases, case-sensitivity in `links_to`, `index.md`) → enforced by limited diff scope.

**Placeholder scan:** none. All commands, code, and assertions are explicit.

**Type/name consistency:** `_do_page_delete`, `pages_root`, `slug_lower`, `another_exists`, `updated_backlinks`, `_write_page`, `wiki_setup`, `mcp_app`, `call_tool`, `wiki_page_delete` (tool name) used identically across spec, plan, tests, and impl.

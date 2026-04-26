# wiki_page_delete Slug Collision Fix — Design

**Date**: 2026-04-26
**Status**: approved (brainstorm); ready for implementation
**Tracks todo**: 751

## Problem

`_do_page_delete` in `plugins/wiki/server/server/tools/page.py:239-257` unconditionally prunes the deleted page's slug from every other page's `links_to` frontmatter. When two pages share the same stem across categories (e.g., `concepts/hooks.md` + `decisions/hooks.md`, both with slug `"hooks"`), deleting one strips the slug from all backlinks — orphaning the surviving page's incoming references for slug-based lookup.

## Goal

Before pruning backlinks pointing at a slug, verify the slug no longer resolves to any other page. If another same-slug page exists, skip the prune entirely so existing references stay valid.

## Non-goals

1. **Alias collisions**: pages can also be referenced by `aliases` frontmatter values. Backlink pruning today doesn't consider aliases at all — out of scope for this fix.
2. **Case-sensitivity in `links_to` matching**: current `link != slug` exact-match behavior preserved. Slug equality check uses `.lower()` to mirror the rest of the wiki's slug-handling.
3. **Index file (`index.md`) regeneration**: handled by `wiki_index_rebuild` which rebuilds from a disk scan; unaffected.

## Architecture

Single-file change: `plugins/wiki/server/server/tools/page.py`. `_do_page_delete` gains a pre-loop check that walks `pages_root.rglob("*.md")` once to determine whether any non-target page shares the slug. The existing prune loop is gated on the result.

```python
def _do_page_delete(wiki_dir: Path, target: Path, slug: str) -> list[str]:
    """Sync helper: backlink prune + delete, on worker thread.

    When another page (in a different category) shares the slug, skip the
    backlink prune — the slug still resolves to a real page, so existing
    `links_to: [slug]` entries remain valid.
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

**Why two `rglob` walks instead of one**: the first walk needs to terminate early on the first non-target match (`any(...)` short-circuits). The second walk needs to read every page's frontmatter for prune logic. Combining them would force loading all pages even after the early-exit signal, defeating the optimization. Each walk is cheap (filesystem `os.walk` + stat); total cost is bounded by page count.

## Testing

Two regression tests appended to `plugins/wiki/server/tests/test_pages.py` (or wherever existing `wiki_page_delete` tests live).

### Test 1: slug-collision preserves backlinks

- Setup: write `concepts/hooks.md` + `decisions/hooks.md` (both slug `"hooks"`). Write a third page `topics/integrations.md` with `links_to: ["hooks"]`.
- Call: `wiki_page_delete("hooks", "concepts")`.
- Assert:
  - Returns `{"deleted": True, "backlinks_updated": [], "path": ...}`.
  - `topics/integrations.md`'s `links_to` is still `["hooks"]` (unchanged).
  - `decisions/hooks.md` still exists.

### Test 2: no collision still prunes (regression for existing behavior)

- Setup: write `concepts/auth.md` (unique slug). Write `topics/integrations.md` with `links_to: ["auth"]`.
- Call: `wiki_page_delete("auth", "concepts")`.
- Assert:
  - Returns `{"deleted": True, "backlinks_updated": ["integrations"], ...}`.
  - `topics/integrations.md`'s `links_to` is now `[]` (pruned).

Existing tests in `test_pages.py` covering the basic delete path stay valid.

## Risks Accepted

- **Two-walk cost**: O(n) extra filesystem traversal per delete. Negligible for any realistic wiki size.
- **Aliases out of scope**: a deletion can still orphan alias-based references if the deleted page had aliases that no other page replicates. Documented as a separate follow-up todo if it becomes a real complaint.

# Wiki Plugin Phase 4c: Tier-2 Semantic Lint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Extend `/wiki:lint` with 4 Tier-2 semantic checks (LLM-driven subagents dispatched in parallel after Tier-1). Ship reference prompts so checks are reusable + auditable.

**Architecture:** `/wiki:lint` SKILL.md adds a Tier-2 phase after Tier-1. Dispatches a team (one subagent per check) via `TeamCreate`. Each subagent runs a prompt template from `plugins/wiki/skills/lint/references/*.md` + returns JSON findings. Skill aggregates Tier-1 + Tier-2 findings before presenting to user. No new MCP tools. No new Python.

**Spec reference:** §11.2. Prior: P4b shipped.

---

## Scope

**IN:**
- 4 reference prompt files at `plugins/wiki/skills/lint/references/`:
  - `tier2-contradictions.md`
  - `tier2-deprecation.md`
  - `tier2-missing-cross-refs.md`
  - `tier2-category-clusters.md`
- Extend `plugins/wiki/skills/lint/SKILL.md` — add Tier-2 phase + aggregation + per-finding fix prompts for the 3 new fixable finding types (contradictions / deprecation / missing cross-refs).
- Category-cluster suggestions: accepting → update `wiki/config.yaml::categories` + move pages via multiple `wiki_page_write(mode=update)` + `wiki_page_delete` calls (or rename-move via shell). Interactive prompt per suggestion.

**OUT:**
- Tier-2 lint doesn't run on every `/wiki:lint` invocation by default — add `--tier=2` or `--tier=all` flag. Default: Tier-1 only (fast).
- Any Python implementation — no MCP tool changes.

---

## Tasks

### Task 1: Write 4 Tier-2 reference prompts

**Files:**
- Create: `plugins/wiki/skills/lint/references/tier2-contradictions.md`
- Create: `plugins/wiki/skills/lint/references/tier2-deprecation.md`
- Create: `plugins/wiki/skills/lint/references/tier2-missing-cross-refs.md`
- Create: `plugins/wiki/skills/lint/references/tier2-category-clusters.md`

Each prompt template shape (substitute `{wiki_dir}` + check-specific inputs):

**`tier2-contradictions.md`:**

```markdown
# Tier-2 Lint: Contradictions

Subagent-prompt template. Used by `/wiki:lint --tier=2`.

## Template

```
You are a wiki lint agent detecting factual contradictions between pages.

WIKI_DIR: {wiki_dir}

MCP TOOLS AVAILABLE (READ-ONLY):
- mcp__plugin_wiki_wiki__wiki_page_list
- mcp__plugin_wiki_wiki__wiki_page_get

PROTOCOL:
1. wiki_page_list → collect all pages.
2. Group pages by shared tags (Jaccard > 0.3) — these are likely to cover
   overlapping subject matter.
3. For each tag-cluster of 2+ pages: wiki_page_get each page + read.
4. LLM reasoning: identify factual claims A in page X that directly contradict
   claim B in page Y. Contradiction means: "X says P is true, Y says P is false"
   or similar logically-incompatible assertions.
5. Skip: stylistic differences, complementary claims, historical progressions
   (e.g. "old approach was X" vs "new approach is Y" is NOT a contradiction).

Return JSON: {
  contradictions: [
    {
      pages: [<slug-a>, <slug-b>],
      claim_a: "<verbatim or close paraphrase>",
      claim_b: "<verbatim or close paraphrase>",
      evidence: "<1-2 sentence explanation why these conflict>",
      severity: "hard" | "soft"    // hard: direct negation; soft: nuance-dependent
    },
    ...
  ]
}

If no contradictions: return {contradictions: []}.
```
```

**`tier2-deprecation.md`:**

```markdown
# Tier-2 Lint: Deprecation Candidates

Subagent-prompt template. Used by `/wiki:lint --tier=2`.

## Template

```
You are a wiki lint agent identifying pages that may be obsolete.

WIKI_DIR: {wiki_dir}

INPUT: Pages whose `last_ingested` is older than 90 days AND no inbound
`[[wikilink]]` from any newer page.

MCP TOOLS AVAILABLE (READ-ONLY):
- mcp__plugin_wiki_wiki__wiki_page_list
- mcp__plugin_wiki_wiki__wiki_page_get
- mcp__plugin_wiki_wiki__wiki_log_read

PROTOCOL:
1. wiki_page_list → find pages with last_ingested < now-90d.
2. For each, wiki_page_get → read body.
3. wiki_log_read(action_filter="ingest") → check if any recent session ingest
   updated it (if yes, it was refreshed; skip).
4. LLM reasoning: page is a "deprecation candidate" if:
   - Discusses technology / project / concept that is no longer in active use
   - References files / tools / teams that no longer exist (check via grep on
     other pages' frontmatter; orphaned references are a strong signal)
   - Explicitly marked "superseded by" or "use X instead"
5. Skip: reference pages (category=references) that document external APIs —
   those can be old but still valid.

Return JSON: {
  candidates: [
    {
      page: <slug>,
      category: <cat>,
      last_ingested: <date>,
      reason: "<why this is a candidate>",
      recommended_action: "delete" | "mark_deprecated" | "merge_into:<target-slug>"
    },
    ...
  ]
}
```
```

**`tier2-missing-cross-refs.md`:**

```markdown
# Tier-2 Lint: Missing Cross-References

Subagent-prompt template. Used by `/wiki:lint --tier=2`.

## Template

```
You are a wiki lint agent suggesting cross-references that should exist but don't.

WIKI_DIR: {wiki_dir}

MCP TOOLS AVAILABLE (READ-ONLY):
- mcp__plugin_wiki_wiki__wiki_page_list
- mcp__plugin_wiki_wiki__wiki_page_get
- mcp__plugin_wiki_wiki__wiki_link_resolve

PROTOCOL:
1. wiki_page_list → collect all pages (limit 100 per scan to stay within context).
2. For each page X, wiki_page_get → read body.
3. LLM reasoning: scan body text for noun phrases that match other pages'
   titles or aliases (use wiki_link_resolve to check for alias match).
4. If a noun phrase matches another page title BUT is NOT wrapped in
   [[wikilinks]] → cross-ref is missing.
5. Skip: phrases that appear inside code blocks, or where the existing
   wording would change meaning with a wikilink insertion.

Return JSON: {
  suggestions: [
    {
      from: <slug>,
      to: <slug>,
      suggested_phrase: "<text to replace>",
      line_hint: <approximate line number>,
      confidence: "high" | "medium" | "low"
    },
    ...
  ]
}

Only report "high" + "medium" confidence suggestions. Low-confidence = noisy.
```
```

**`tier2-category-clusters.md`:**

```markdown
# Tier-2 Lint: Category-Cluster Suggestions

Subagent-prompt template. Used by `/wiki:lint --tier=2`.

## Template

```
You are a wiki lint agent suggesting new categories based on page-tag clusters.

WIKI_DIR: {wiki_dir}
CURRENT_CATEGORIES: {current_categories}

MCP TOOLS AVAILABLE (READ-ONLY):
- mcp__plugin_wiki_wiki__wiki_page_list
- mcp__plugin_wiki_wiki__wiki_page_get

PROTOCOL:
1. wiki_page_list → collect all pages w/ frontmatter tags + category + summary.
2. LLM reasoning: identify tag-clusters (groups of 3+ pages sharing 2+ tags
   AND similar summaries) that don't fit any CURRENT_CATEGORIES well.
3. For each cluster: propose a new category name that captures the theme.
4. Report pages that would move into the new category.

Return JSON: {
  suggestions: [
    {
      proposed_category: <slug>,
      rationale: "<why this cluster deserves its own category>",
      pages: [<slug-1>, <slug-2>, ...]
    },
    ...
  ]
}

Skip clusters of < 3 pages. Only suggest if the cluster is meaningfully distinct
from existing categories.
```
```

- [ ] Create the 4 files above. Commit together.

---

### Task 2: Extend `/wiki:lint` SKILL.md for Tier-2

**Files:**
- Modify: `plugins/wiki/skills/lint/SKILL.md`

- [ ] **Step 2.1:** Update frontmatter — add `Task` + `TeamCreate` to allowed-tools; add `argument-hint: "[--tier=1|2|all]"`.

- [ ] **Step 2.2:** After existing Tier-1 step 2 (aggregate summary table), add Tier-2 dispatch:

```markdown
**3.** Parse `$ARGUMENTS` for `--tier` flag:
 - `--tier=1` (default) → skip to step 5 (present Tier-1 only).
 - `--tier=2` → skip Tier-1 summary; run only Tier-2 checks.
 - `--tier=all` → run both.

**4.** Tier-2 dispatch (`--tier=2` or `--tier=all`):
 - Read each `references/tier2-*.md` template + substitute `{wiki_dir}` (read from `~/.claude/wiki.yaml::wiki_dir`) and `{current_categories}` (read from `~/.claude/wiki/config.yaml`).
 - `TeamCreate` w/ 4 agents:
    - Agent `contradictions`: prompt from `references/tier2-contradictions.md`
    - Agent `deprecation`: prompt from `references/tier2-deprecation.md`
    - Agent `cross-refs`: prompt from `references/tier2-missing-cross-refs.md`
    - Agent `clusters`: prompt from `references/tier2-category-clusters.md`
 - Wait for all 4. Collect JSON results.

**5.** Aggregate Tier-1 + Tier-2 findings. Present combined summary:
```
| Tier | Check | Findings |
|------|-------|----------|
| 1 | Orphans | 3 |
| 1 | Broken links | 2 |
| ... |
| 2 | Contradictions | 1 |
| 2 | Deprecation candidates | 5 |
| 2 | Missing cross-refs | 12 |
| 2 | Category cluster suggestions | 1 |
```

**6.** Per-finding prompts (extend existing Tier-1 prompts):
 - Tier-1 findings: same as before.
 - Contradictions: `fix` offers `edit-page-a-body` / `edit-page-b-body` / `add-reconciliation-note` / `skip`.
 - Deprecation candidates: `fix` applies `recommended_action` (delete / mark-deprecated via frontmatter `deprecated: true` + `deprecated_in_favor_of` / merge-into).
 - Missing cross-refs: `fix` inserts the `[[wikilink]]` into the source page body via `wiki_page_get` + edit + `wiki_page_write(mode="update")`, + updates `links_to` frontmatter.
 - Category cluster suggestions: `fix` updates `wiki/config.yaml::categories` to include the new category + moves the listed pages via `wiki_page_delete` + `wiki_page_write(mode="create")` in new category. Confirm the whole migration before any page-moves fire.

**7.** `wiki_log_append(action="lint", title="full" | "tier-2", body=<summary>)`.

**8.** Print final summary (same as before + Tier-2 counts).
```

- [ ] **Step 2.3:** Commit.

---

### Task 3: Sanity + README + final

**Files:**
- Modify: `plugins/wiki/README.md`

- [ ] **Step 3.1:** Update README Phase status to P4c ✅ + add section listing the 4 Tier-2 reference files.
- [ ] **Step 3.2:** Full wiki test suite (unchanged; Phase is prose-only).
- [ ] **Step 3.3:** Commit.

---

## Verification

1. 4 new reference files at `plugins/wiki/skills/lint/references/`.
2. `plugins/wiki/skills/lint/SKILL.md` lists Tier-2 dispatch step + aggregates findings.
3. Wiki test suite still passes (no Python changes).
4. Manual smoke (after phase merges): `/wiki:lint --tier=all` on a seeded fixture w/ known contradictions — verify the contradictions agent finds them.

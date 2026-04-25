# Wiki Tier-2 Lint Architecture — Design Spec

**Date**: 2026-04-25
**Todo**: 737 — `Wiki tier-2 lint architecture: standardize on Python-driven vs prose-driven impl (resolve dual-impl in section_map drift check)`
**Author**: brainstorming session (Raul + Claude Opus 4.7)
**Status**: design approved; awaiting user spec review → writing-plans

---

## Problem statement

`section_map_drift` is the only tier-2 lint check with a dual implementation:

- `plugins/wiki/server/server/tools/lint.py::check_section_map_drift` — Python, tested, **NOT registered as MCP tool** (~50 lines + ~10 lines helpers + ~15 lines SYNC CONTRACT comment).
- `plugins/wiki/skills/lint/references/tier2-section-map-drift.md` — prose subagent template, runtime impl, NOT covered by tests.

Currently mitigated by SYNC CONTRACT comments cross-referencing the files (commit `14f90dd`) — process-level mitigation, not structural. Drift between the two impls remains possible.

The other 4 tier-2 checks (`category-clusters`, `contradictions`, `deprecation`, `missing-cross-refs`) are already prose-only. `section_map_drift` is the architectural outlier.

## Goal

1. Eliminate the dual-impl smell by deleting the Python `check_section_map_drift` runtime + tests.
2. Document the architectural principle so future contributors don't re-introduce the anomaly.

## Non-goals

- Re-implementing tier-1 lint (still Python — out of scope, tier-1 is deterministic data/persistence).
- Adding any new tier-2 checks.
- Building an LLM-driven test harness for prose subagent outputs.
- Generalizing the architectural principle beyond wiki tier-2 lint.

## Architectural principle (to codify)

**"Tier-2 lint checks MUST be prose-only (LLM synthesis in skills). Python helpers in MCP layer reserved for tier-1 deterministic data/persistence operations only. Synthesis tasks (section-map drift, contradictions, deprecation, missing cross-refs, category clusters) live in `plugins/wiki/skills/lint/references/tier2-*.md` prose subagents."**

This principle aligns with the wiki-plugin's existing persistence/synthesis boundary documented in `[[wiki-plugin]]` wiki page: *"MCP = pure persistence + pure data; all synthesis in LLM-driven skills."*

The principle is added to:
- `[[wiki-plugin]]` wiki page (the canonical doc for the boundary).
- `plugins/wiki/skills/lint/SKILL.md` (the lint skill's own documentation, so contributors editing tier-2 see it).

## Architecture — what gets deleted

### Code deletions in `plugins/wiki/server/server/tools/lint.py`

| Lines (approx) | Content | Action |
|---|---|---|
| 343-355 | SYNC CONTRACT comment block | Delete |
| 356-358 | `_TEMPLATE_START_RE`, `_TEMPLATE_END_RE`, `_TEMPLATE_H2_RE` regex constants | Delete (only used by `_extract_save_skill_h2s`) |
| 361-393 | `_extract_save_skill_h2s` helper fn | Delete (only called by `check_section_map_drift`) |
| 396-447 | `check_section_map_drift` fn | Delete |

The `import re` at line 10 stays — used 7+ times elsewhere in lint.py.

### Test deletions

- `plugins/wiki/server/tests/test_lint_tier2_drift.py` (entire 243-line file) → delete.

### Reference doc edit

- `plugins/wiki/skills/lint/references/tier2-section-map-drift.md` line 7 — remove the SYNC CONTRACT line. The rest of the file (the prose impl) stays.

The SYNC CONTRACT line currently reads:

```
> **SYNC CONTRACT**: This prose is the runtime impl. `plugins/wiki/server/server/tools/lint.py::check_section_map_drift` is a parallel reference impl pinned by tests. If you change the algorithm here (anchor markers, sentinel semantics, output kinds), update lint.py too — and vice versa. See todo 736 for plan to consolidate.
```

This entire blockquote is removed.

## Test coverage tradeoff

**Loss**: no automated regression for the prose impl of section_map_drift.

**Acceptance rationale**:
1. The prose IS the runtime — bugs in the prose surface immediately on next `/wiki:lint --tier=2` invocation.
2. The other 4 tier-2 checks operate this way already; no precedent for tier-2 testing.
3. Tier-1 lint (deterministic) still has full Python regression coverage.
4. Adding LLM-output testing for prose would be a much larger build (out of scope).

**Mitigation**: the architectural principle (codified in wiki + skill) prevents future Python siblings, which is the actual smell. Drift between impls cannot drift if there's only one impl.

## Wiki + skill updates

### `[[wiki-plugin]]` wiki page

Add a new section or extend the existing persistence/synthesis-boundary section with:

```markdown
## Tier-2 lint architecture (decided 2026-04-25 per todo 737)

Tier-2 lint checks MUST be prose-only (LLM synthesis in skills). Python helpers
in MCP layer are reserved for tier-1 deterministic data/persistence operations
only. Each tier-2 check lives as a single prose subagent template at
`plugins/wiki/skills/lint/references/tier2-<check-name>.md` — no parallel
Python implementation, no SYNC CONTRACT comment, no test pinning the algorithm.

Rationale: dual-impl drift is a category of bug that disappears if there's only
one impl. The prose subagent IS the runtime; bugs surface on next
`/wiki:lint --tier=2` invocation.

Tier-1 lint (orphans, broken-links, broken-section-refs, category-violations,
stale, schema, duplicates) remains Python-driven — these are deterministic
data/persistence ops aligned with the MCP boundary.
```

Use `mcp__plugin_wiki_wiki__wiki_page_write` to update.

### `plugins/wiki/skills/lint/SKILL.md`

Add a brief Architecture note (TBD on exact placement — top of file or near tier-2 section). Suggested wording:

```
## Architecture (tier-1 vs tier-2)

Tier-1 lint checks (orphans, broken-links, etc.) are Python-driven, registered
as MCP tools (`wiki_lint_*`), tested. Tier-2 checks (contradictions, deprecation,
missing cross-refs, category-clusters, section_map_drift) are prose-only — each
lives at `references/tier2-<check-name>.md` as an LLM subagent template. No
Python helpers for tier-2; no dual-impl. See [[wiki-plugin]] for the architectural
principle (decided 2026-04-25 per todo 737).
```

## Files affected

| File | Action |
|---|---|
| `plugins/wiki/server/server/tools/lint.py` | Delete lines 343-447 (SYNC CONTRACT + helpers + check_section_map_drift) |
| `plugins/wiki/server/tests/test_lint_tier2_drift.py` | Delete file (243 lines) |
| `plugins/wiki/skills/lint/references/tier2-section-map-drift.md` | Remove SYNC CONTRACT line 7 |
| `plugins/wiki/skills/lint/SKILL.md` | Add Architecture section documenting tier-1 vs tier-2 split |
| `~/.claude/wiki/pages/entities/wiki-plugin.md` | Add tier-2 architectural principle section |
| `plugins/wiki/.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` | Bump wiki plugin version (per project convention — non-breaking change) |

## Validation

1. **Lint runs cleanly**: `/wiki:lint --tier=2` returns expected results post-deletion (no Python errors from missing `check_section_map_drift`; subagent prose still drives the runtime).
2. **Full wiki test suite passes**: existing tier-1 tests untouched; tier-2 drift tests deleted (expected).
3. **No dangling references**: `grep -r 'check_section_map_drift\|_extract_save_skill_h2s' plugins/wiki` returns 0 matches post-deletion.
4. **Wiki + skill prose is consistent**: the architectural principle documented in both [[wiki-plugin]] page + `lint/SKILL.md` says the same thing.
5. **Manual smoke**: invoke `/wiki:lint --tier=2` against a wiki with a known section_map drift — verify the prose subagent still detects + reports it correctly.

## Risks

| Risk | Mitigation |
|---|---|
| Future contributor adds Python helper for a new tier-2 check | Architectural principle in wiki + skill; reviewer should catch it. |
| Prose subagent has a bug that goes uncaught | Bugs surface on next runtime invocation. Acceptable per other 4 tier-2 checks' precedent. |
| Removing tests reduces coverage stat | Tier-2 was synthesis-side coverage; tier-1 (deterministic) coverage unchanged. Wiki plugin's overall coverage % drops slightly but the dropped coverage was for an unused-at-runtime impl — not a real regression. |
| Documentation drift between wiki page + skill | Cross-reference both files; reviewer should verify alignment. Single source of truth is the wiki page; skill defers to it. |

## Cross-references

- Wiki: [[wiki-plugin]] (canonical persistence/synthesis boundary doc — gets the new principle section)
- Wiki: [[parallel-orchestration-boundary-issues]] (the diagnosis page that flagged 737 as the architectural axis)
- Code: `plugins/wiki/server/server/tools/lint.py:343-447` (deletion target)
- Code: `plugins/wiki/server/tests/test_lint_tier2_drift.py` (deletion target — entire file)
- Code: `plugins/wiki/skills/lint/references/tier2-section-map-drift.md` (SYNC CONTRACT line removal)
- Code: `plugins/wiki/skills/lint/SKILL.md` (Architecture section addition)
- Sibling todos (just shipped): 736 (detection axis — parallel-batch-execute SKILL), 735 (worktree-rebase-artifact root cause + fix). 737 is the resolution axis of the same retro.
- Mitigation commit: `14f90dd` (added the SYNC CONTRACT comments — superseded by this fix).
- Trigger session: 2026-04-25 (D+E + Batch A retro by Opus, batch-A wiki-ingest fix that introduced the dual-impl).

## Open questions (deferred — non-blocking for plan)

1. Should we extend the architectural principle to OTHER plugins (proj? worktree?) where similar synthesis-vs-persistence boundaries exist? **Decision**: out of scope for v1; revisit only if another plugin shows the same dual-impl smell.
2. If a future tier-2 check genuinely needs deterministic per-element checking (e.g. a new tier-2 contradiction-finder with structured outputs), should we revisit allowing Python helpers? **Decision**: revisit then. Not now.
3. Is "tier-2 = prose-only" wording precise enough, or should we allow Python helpers for *non-runtime* purposes (e.g. test fixtures)? **Decision**: prose-only at runtime; test fixtures CAN exist as Python data structures (e.g. expected drift outputs). The principle is about **runtime impl**, not about all Python files in tier-2 paths.

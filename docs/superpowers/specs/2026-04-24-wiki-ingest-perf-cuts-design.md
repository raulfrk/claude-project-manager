# Wiki Ingest Perf Cuts — Design

**Status**: draft
**Owner**: raul
**Date**: 2026-04-24
**Related todo**: [727](../../../) — "Wiki ingest latency: is /proj:save ingesting too much per session? Investigate scope + granularity before building queue"
**Related (deferred)**: 702 (queue-based ingest) — out of scope

## Context & Motivation

`/proj:save` step 11 spawns a wiki ingest subagent for every save. Per a real session on 2026-04-24, the subagent created 6 pages, updated 3, and added 18 cross-references in roughly 4 minutes. Three observed pain points:

1. **Wall-clock latency** — subagent ingest is the longest step in `/proj:save`.
2. **Token / context cost** — subagent extracts 3-15 candidates per session; each candidate triggers a tag-list + BM25 dedup pass plus cross-ref noun-phrase scanning across the full wiki.
3. **Ingest noise** — every save triggers ingest, including trivial sessions (status checks, one-offs) that yield low-value pages.

Investigation of the ingest path (see exploration notes in todo 727 and `plugins/wiki/skills/ingest/references/`) confirmed three concrete inefficiencies:

- **No substance gate**: `/proj:save` always dispatches, regardless of whether the session contains anything wiki-worthy.
- **`session_ingest.section_map` defined but unused**: `wiki.yaml` exposes a `session_ingest.section_map` config block (heading → category mapping) but the subagent prompt does not consume it. Section information is lost during candidate extraction.
- **Cross-ref pass is full-wiki**: when inserting `[[wikilinks]]` into a new page, the subagent scans every page title in the wiki for noun-phrase matches, even when most matches across categories are noise.

This spec proposes hypothesis-driven fixes to all three. Per user direction (brainstorm 2026-04-24): hypothesis-first, no instrumentation; scope strictly to 727; defer 702 (queue) until data shows these cuts are insufficient.

## Goals

- Skip ingest for trivial sessions (zero behavior on user-perceived latency for `/status`-style saves).
- Reduce subagent token cost by activating section-aware extraction (already designed, just unwired).
- Reduce cross-ref pass cost by limiting to same-category page set; recover any lost cross-category links via the existing `/wiki:lint` tier-2 sweep.

## Non-goals

- Candidate cap changes (kept at current 3-15 range — substance gate handles the trivial-session axis; cap tightening defers until data justifies).
- Instrumentation / timing counters (defer; revisit if pain remains after these cuts).
- New `wiki.yaml` config keys for thresholds — gate constants are inline in skill prose; revisit if production reveals a needed knob.
- Queue-based async ingest (todo 702 — out of scope).

## Architecture

Three surgical changes, no new code modules, no MCP tool changes:

| File | Change |
|---|---|
| `plugins/proj/skills/save/SKILL.md` (step 11) | Insert substance gate before subagent dispatch. Skip dispatch on gate-fail. |
| `plugins/wiki/skills/ingest/references/subagent-prompt.md` | Wire `session_ingest.section_map` into candidate extraction; cap cross-ref pass to same-category pages. |
| `plugins/wiki/skills/ingest/references/dedup-protocol.md` | Update cross-ref protocol section to reflect same-category scope. |

The existing `wiki.yaml::session_ingest.section_map` field gets activated (no schema change).

## Components

### 1. Substance gate (in `/proj:save` step 11)

Before dispatching the wiki ingest subagent, the skill checks the just-written session file:

- Parse the `## Key Decisions` section. Count bullet items.
- Parse the `## Insights Discovered` section. Count bullet items.
- Compute total word count of the session file.

**Gate fail (skip dispatch) when ALL of:**
- `## Key Decisions` section has zero bullets (or section absent entirely), AND
- `## Insights Discovered` section has zero bullets (or section absent entirely), AND
- Total word count < 300.

A missing section is treated identically to an empty section (zero bullets). This handles older session files that may pre-date the current section template.

On gate fail, log to console:
```
Wiki ingest skipped: trivial session (no decisions/insights, <300 words).
```
And do not dispatch the subagent. Continue with remaining `/proj:save` steps.

On gate pass, proceed with current dispatch logic unchanged.

**Rationale**: all three conditions must hold for skip — i.e. the session must be substance-free across all three signals. False-positive rate (substantive session skipped) is low. False-negative rate (trivial session ingested) is acceptable; it's the current behavior.

### 2. Section-aware extraction (in subagent-prompt.md)

The wiki ingest subagent's extraction step changes:

- **Before**: subagent reads the full session body and extracts 3-15 candidates without per-section structure.
- **After**: subagent reads `wiki.yaml::session_ingest.section_map` (e.g. `{Key Decisions: decisions, Insights Discovered: insights, Open Questions: questions}`). Walks the session file section by section. For each section heading present in `section_map`, candidates extracted from that section's bullets receive the mapped category as a **category hint** (not a hard assignment — the subagent may override based on candidate content).

Behavior when `section_map` is empty, missing, or unset: subagent falls back to current wholesale extraction. No error.

This unlocks (a) better category accuracy without an extra LLM pass, (b) cleaner inputs for the same-category cross-ref change below.

### 3. Cross-ref pass scope change (in subagent-prompt.md + dedup-protocol.md)

The cross-ref pass currently scans every page title in the wiki for noun-phrase matches in a candidate's body. Change:

- For a candidate landing in category `X`, the cross-ref pass scans **only pages within category `X`** for noun-phrase matches.
- `wiki_link_resolve` calls are bounded to that category.
- Cross-category links lost at ingest time → recovered later by `/wiki:lint` tier-2 sweep, which already runs cross-ref linting and is the natural place for cross-category coherence work.

`dedup-protocol.md`'s cross-ref section updates to document the new scope and the lint-tier-2 fallback.

## Data flow

```
/proj:save step 11
  ├─ Read just-written session file (sessions/session-YYYY-MM-DD.md)
  ├─ Substance gate: decisions empty? insights empty? word count <300?
  │   └─ All true → skip + log → done
  ├─ Read sync.wiki.* + section_map from configs
  └─ Dispatch wiki ingest subagent (Task tool, non-blocking, source=session:<path>)
       └─ Subagent (in fork):
            ├─ Idempotency: wiki_log_read cooldown check (unchanged)
            ├─ Section-aware extraction: walk sections, apply section_map as category hint
            ├─ For each candidate (3-15, unchanged): dedup → write/update page
            ├─ Cross-ref pass: scoped to candidate's category dir
            └─ wiki_log_append + wiki_index_rebuild
```

## Error handling

- **Gate false-negative** (substantive session skipped): user can manually run `/wiki:ingest session:<path>` to force-ingest. The console log line tells them the gate fired.
- **Empty / missing `section_map`**: subagent falls back to current wholesale extraction. Logged at debug level, not user-visible.
- **Category dir missing** for cross-ref scope (e.g. ingesting first page into a fresh category): cross-ref pass yields zero candidates for that page; no error. Lint tier-2 will fill in inline links once the category populates.
- **Cooldown still applies**: gate fires before cooldown check; if a session hits the gate AND would have hit cooldown, both protect.

## Testing

All changes are skill prose + subagent prompt edits — no Python module changes, no automated test additions. Manual verification:

1. **Gate-skip path**: trigger `/proj:save` after a session that's only `/status` queries (no decisions/insights, short). Verify subagent NOT dispatched; console message shown.
2. **Gate-pass path**: trigger `/proj:save` after a real work session (at least one decision recorded). Verify subagent dispatches as normal.
3. **Section-aware extraction**: with `section_map: {Key Decisions: decisions, Insights Discovered: insights}` set in wiki.yaml, run ingest on a session with both sections. Verify created pages land in correct category dirs.
4. **Cross-ref scope**: ingest a session yielding a new page in `decisions/`. Verify inline `[[wikilinks]]` resolve only to other `decisions/*.md` titles (not, e.g., `concepts/*.md`).
5. **Backward compat — empty section_map**: with `section_map` empty/unset, verify ingest behavior matches current (wholesale extraction, all pages eligible for cross-ref).
6. **Backward compat — gate disabled**: temporarily comment the gate; verify dispatch still works for the trivial session from test 1.

## Acceptance

- All three changes shipped together on a single feat branch, FF-merged to dev (per project convention).
- Manual verification 1-5 pass.
- A trivial session (e.g. one where the only entry is a `/status` query) does not trigger ingest.
- A real work session still ingests, with pages landing in `section_map`-derived categories when configured.
- Cross-ref pass demonstrably faster on the next ingest after this lands (subjective wall-clock check; no instrumentation gate).

## Open questions for implementation plan

- Where exactly the substance gate prose belongs in `/proj:save`'s SKILL.md step 11 (before or after the `sync.wiki.*` config check). Implementation plan should pick.
- Subagent-prompt.md edit ordering: section-aware extraction comes before cross-ref scope change, or both in one diff? Implementation plan should pick (likely one diff since both touch the same file).
- Should the substance gate threshold (300 words) be promoted to a `wiki.yaml::session_ingest.gate.*` config key now, or wait? Out of scope per spec; flagged here only.

## Risks

- **Substance gate over-skips**: if user-style sessions tend to be terse (decisions and insights captured elsewhere), gate may skip substantive saves. Mitigation: console log makes it visible; manual `/wiki:ingest` available; threshold revisitable if pattern emerges.
- **Cross-ref scope loses real links**: cross-category links (e.g. a `decisions/` page that should link to a `concepts/` page) are lost until lint tier-2 runs. Mitigation: lint tier-2 already exists and runs as a sweep; users running it periodically catch this.
- **Section_map drift**: section_map in `wiki.yaml` and section names in `/proj:save`'s session-file template can drift. Mitigation: implementation plan should add a comment in both pointing at the other; consider a `wiki:lint` check that flags missing section names later (out of scope here).

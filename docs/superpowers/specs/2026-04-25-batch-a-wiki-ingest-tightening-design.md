# Batch A: Wiki Ingest Tightening — Design

**Status**: draft
**Owner**: raul
**Date**: 2026-04-25
**Todos covered**: 729, 730, 731, 732, 734
**Workflow**: light per-todo plans inline (no separate spec docs); per-todo worktree; subagent-driven impl; serialized FF-merges; single push at end. No revdiff. Same orchestration recipe as the [[D+E batch]] (see [[parallel-impl-orchestration]]).

## Context & Motivation

Five todos cluster around **wiki ingest discipline + research workflow**. All are follow-ups from the 727 perf cuts (substance gate, section_map wiring, same-category cross-ref) and the 734 user-prompted research-synthesis guidance. Together they form a coherent "tighten wiki ingest + codify research workflow" batch that re-validates the parallel-orchestration recipe on lower-stakes work.

Per user direction (brainstorm 2026-04-25):
- 4 worktrees parallel (731 + 732 combined into one worktree since both touch `subagent-prompt.md`).
- Sonnet implementers, run_in_background.
- Single push at end → one CI run.
- No revdiff for spec or per-todo plans (text fallback for review).
- Wiki research already done as part of brainstorm (see 727's design + 734's rule-15 reference).

## Goals

- Make the 727 substance gate's word/decision/insight thresholds user-configurable (729).
- Detect drift between `/proj:save` session template H2 headings and `wiki.yaml::session_ingest.section_map` keys via lint (730).
- Document heading-match semantics + extend to H3 subsections in the ingest subagent prompt (731 + 732).
- Add managed-CLAUDE.md guidance (NOT mandate) recommending wiki + code + web research synthesis for brainstorm/spec/plan work (734).

## Non-goals

- Vector DB (701), queue ingest (702), profile marketplace (703), wiki:lint automation (725) — separate batch (B).
- Promoting console-output format of substance-gate-skipped sessions to user config — explicitly deferred per 727 spec.
- Building auto-regen pre-commit hook for uv.locks — deferred per 715 rubric.

## Architecture

4 worktrees, file scopes verified disjoint:

| Branch | Todos | Files touched |
|---|---|---|
| `feat/729-wiki-gate-config-knobs` | 729 | `plugins/wiki/server/server/lib/models.py` (schema), `plugins/proj/skills/save/SKILL.md` (step 11), tests |
| `feat/730-wiki-lint-section-map-drift` | 730 | `plugins/wiki/skills/lint/SKILL.md`, new `plugins/wiki/skills/lint/references/tier2-section-map-drift.md`, tests |
| `feat/731-732-section-map-match-semantics` | 731 + 732 | `plugins/wiki/skills/ingest/references/subagent-prompt.md` |
| `feat/734-managed-claudemd-research-synthesis` | 734 | `plugins/_shared/claudemd/managed_section.md`, `plugins/_shared/pyproject.toml` (version bump), all 9 uv.locks via `just sync` |

## Per-Todo Plans

Each plan is intentionally tight (~30-50 lines). Full task discipline (read → edit → verify → commit) is in the implementer prompt. Per-todo plan section captures: goal, files, decisions locked in by brainstorm, success criteria.

---

### Todo 729 — Three-knob substance gate config

**Branch**: `feat/729-wiki-gate-config-knobs`

**Goal**: Promote 727's hardcoded substance gate thresholds (`decisions == 0`, `insights == 0`, `word_count < 300`) to user-configurable `wiki.yaml::session_ingest.gate.*` keys. Defaults match current behavior — back-compat.

**Decisions locked in (brainstorm)**:
- **Three knobs**: `decisions_min`, `insights_min`, `word_count_min` (NOT a single word_count knob).
- Default values match current hardcoded behavior: `decisions_min=1, insights_min=1, word_count_min=300`. Gate fail when ALL counts < their min.
- Schema lives in `plugins/wiki/server/server/lib/models.py` as a new nested dataclass under the existing wiki config model.

**Files**:
- `plugins/wiki/server/server/lib/models.py` — add `SessionIngestGate` dataclass + nest under `WikiYamlSchema.session_ingest`.
- `plugins/proj/skills/save/SKILL.md` — step 11 reads gate config; gate-fail condition uses configured mins.
- `plugins/wiki/server/tests/test_lib_models.py` (or equivalent) — new test for default values + custom-config parsing.
- `plugins/proj/server/tests/test_save_substance_gate.py` (if it exists; create if not) — synthetic config w/ stricter gates → assert sessions w/ N=1 decision still skip when `decisions_min=2`.

**Success criteria**: Default behavior identical to pre-change (same gate semantics). Setting `gate.decisions_min: 2` in `wiki.yaml` causes sessions w/ exactly 1 decision to be skipped where they previously wouldn't (assuming insights = 0 and word count < `word_count_min`).

---

### Todo 730 — /wiki:lint tier-2 section_map drift check

**Branch**: `feat/730-wiki-lint-section-map-drift`

**Goal**: Detect when `wiki.yaml::session_ingest.section_map` keys diverge from `## <heading>` H2 entries in `/proj:save` SKILL.md's session-file template (step 7).

**Decisions locked in (brainstorm)**:
- Tier-2 lint check (LLM-driven sweep), NOT tier-1 (deterministic).
- Lives next to existing tier-2 references (`tier2-missing-cross-refs.md` etc).
- Output style matches existing tier-2 lint: `WARN: section_map key 'X' has no matching H2 in /proj:save template` and reciprocal.

**Files**:
- `plugins/wiki/skills/lint/SKILL.md` — extend tier-2 dispatch to include section-map-drift check.
- `plugins/wiki/skills/lint/references/tier2-section-map-drift.md` — new reference describing the check's protocol (read both files, regex-extract H2 headings from save SKILL, set diff vs section_map keys).
- `plugins/wiki/server/tests/test_lint_tier2_drift.py` — synthetic SKILL fixture + section_map fixture; assert lint detects added/removed keys.

**Path discovery**: implementer must locate `/proj:save` SKILL.md robustly. Canonical path: `~/.claude/plugins/marketplaces/<marketplace-id>/cpm/proj/skills/save/SKILL.md` OR via plugin metadata. Test against fixture path; document the canonical lookup in the new reference doc.

**Success criteria**: Synthetic test where section_map = `{"Key Decisions": "decisions"}` and save template H2s = `["Key Decisions", "Insights Discovered"]` produces a single warning ("Insights Discovered has no section_map entry"). Bidirectional drift detected.

---

### Todo 731 + 732 — Heading-match semantics + H3 participation

**Branch**: `feat/731-732-section-map-match-semantics`

**Goal**: Single coherent edit to `subagent-prompt.md` PROTOCOL step 2 covering both (a) match semantics for the `## <heading>` lookup against section_map keys, and (b) extension to H3 + deeper subsections.

**Decisions locked in (brainstorm)**:
- Match semantics: **exact-match, case-sensitive, whitespace-trimmed**. (Whitespace trimming covers `## Key Decisions` vs `##  Key Decisions`; case-sensitive enforces template discipline.)
- H3 participation: **walk session sections at any heading depth (H2, H3, H4)**; tie-breaker = **deepest matching heading wins** (innermost) when a candidate's bullet sits under nested matching headings.

**Files**:
- `plugins/wiki/skills/ingest/references/subagent-prompt.md` — single edit to PROTOCOL step 2.

**Edit shape**: extend the existing `if SOURCE is a session: ... walk the session file section by section` clause with:
- "Match semantics: exact (case-sensitive, whitespace-trimmed). `## Key Decisions` matches `Key Decisions`; `## key decisions` does not."
- "Walk H2, H3, and H4 headings (not just H2). When a bullet sits under nested matching headings, the deepest (innermost) matching heading's category hint wins. Example: `## Key Decisions / ### Architecture` → both `Key Decisions` and `Architecture` checked against section_map; if both map, `Architecture`'s mapping wins."

**Success criteria**: subagent prompt unambiguously instructs the LLM agent on match rules + heading-depth handling. No code change. Manual verification = re-read step 2 with fresh eyes; rule reads cleanly.

---

### Todo 734 — Managed CLAUDE.md research-synthesis guidance

**Branch**: `feat/734-managed-claudemd-research-synthesis`

**Goal**: Add managed-CLAUDE.md rule recommending wiki + code + web research synthesis for brainstorm/spec/plan work. **Guidance, not mandate** — phrasing uses "consider" / "prefer" / "where applicable", NOT "must" / "always" / "only".

**Decisions locked in (brainstorm)**:
- **Placement**: NEW separate bullet (rule 25 or next available slot — implementer to verify current numbering).
- **Gating**: inline degradation clause — `"...if wiki plugin enabled (check enabledPlugins['wiki@*']); otherwise skip wiki step + proceed w/ code + web alone"`.
- **Order**: wiki → code → web (cheapest-first, matches rule 15's lookup priority).
- **Examples**: include 1 short concrete example.

**Suggested rule prose** (implementer can refine):

> **Research synthesis for brainstorm/spec/plan work** — When investigating a topic for a brainstorm, spec, or implementation plan, prefer combining sources rather than relying on a single one. Recommended order: (1) `/wiki:query` if wiki plugin enabled (check `enabledPlugins["wiki@*"]`); (2) code research via `Explore` subagent or direct grep+read; (3) web research via `WebSearch`/`WebFetch` for canonical external sources. Guidance, not mandate — other sources (project notes, decisions log) remain valid where relevant. *Example*: brainstorming a new plugin → `/wiki:query existing patterns` + `Explore similar plugin code` + `WebSearch external API docs`.

**Files**:
- `plugins/_shared/claudemd/managed_section.md` — add new bullet after the last current rule.
- `plugins/_shared/pyproject.toml` — version bump (per CLAUDE.md "Version must be bumped in both plugin.json and marketplace.json" — but `_shared` doesn't ship as a marketplace plugin, only the version field in pyproject.toml + uv.lock regen).
- All 9 uv.lock files (root + 7 plugins) — regenerated via `just sync`.
- `plugins/_shared/tests/test_claudemd_managed_section.py` — assert new bullet present + correctly placed (after current last rule, before any closing markers).

**Critical implementer dance**:
1. Edit `managed_section.md`.
2. Edit `pyproject.toml` version.
3. Run `just sync` from repo root → regen all 9 uv.locks.
4. `git add` everything (managed_section + pyproject + 9 uv.locks + test).
5. Commit (the `check_shared_version.py` pre-commit hook will fire + must pass).

**Success criteria**: managed-block test passes; pre-commit `check_shared_version` validator passes; new bullet visible in regenerated `~/.claude/CLAUDE.md` after a `claudemd_refresh_managed` call. Phrasing uses guidance verbs throughout.

---

## Setup Sequence (controller, before fan-out)

For each todo (4 worktrees):
1. `wt_create(repo_label="cpm", branch="<branch>", base_branch="dev")` → returns `worktree_path`.
2. `cd <worktree_path> && git fetch origin && git rev-list origin/dev..dev` → confirm 0 (FF-mergeable) → reset per CLAUDE.md rule 13.
3. (For 729 + 730 only): `cd plugins/wiki/server && uv sync --all-groups`. (For 734: `cd plugins/_shared && uv sync --all-groups`.) Skip for 731+732 (no Python tests).

## Implementer Dispatch Pattern

```
Agent({
  description: "Impl <todo-id>",
  subagent_type: "general-purpose",
  model: "sonnet",
  run_in_background: true,
  prompt: <full per-todo plan + work directory + commit msg template + report format>
})
```

Per-todo plan inlined in implementer prompt — never make subagent read the spec file.

## Review Pattern

Same as D+E batch:
- Implementer DONE → spec compliance reviewer (haiku).
- Spec ✅ → code quality reviewer (`superpowers:code-reviewer`).
- Re-review loop on findings.

## Merge + Push Sequence

After all 4 implementers + reviews complete:

1. `cd /home/raul/projects/claude-project-manager && git pull --ff-only origin dev` (sanity).
2. `git merge --ff-only feat/729-wiki-gate-config-knobs` (no rebase needed for first).
3. Rebase + merge: `feat/730-wiki-lint-section-map-drift`.
4. Rebase + merge: `feat/731-732-section-map-match-semantics`.
5. **Last**: rebase + merge `feat/734-managed-claudemd-research-synthesis` (because version bump triggers uv.lock regen across whole tree; landing it last avoids forcing other branches' rebases to absorb the lockfile churn).
6. `git push origin dev` — single push, single CI run.
7. `gh run watch <id> --exit-status` (background).

## Cleanup

- `wt_remove` × 4 (parallel).
- `git branch -d` × 4.
- `mcp__plugin_proj_proj__todo_complete(todo_ids=["729", "730", "731", "732", "734"])` — batch complete.

## Risks

- **734 _shared bump dance**: `just sync` regen + staging all 9 uv.locks is mechanical but error-prone. Implementer prompt must call this out + reference `scripts/check_shared_version.md` (the rubric we just shipped) for context.
- **730 path discovery**: `/proj:save` SKILL.md path lookup — implementer should test against fixture path AND verify against `~/.claude/plugins/.../proj/skills/save/SKILL.md` resolution.
- **731+732 H3 tie-breaker** ("deepest wins") may surprise users who expect "outermost wins". Mitigation: doc the rule explicitly in subagent-prompt.md; revisit if real session files have deeply-nested categorical headings.
- **Worktree-rebase artifact** ([[worktree-rebase-artifact]] pitfall from D+E batch) may recur. Mitigation: run `git restore .` then `git rebase` if any rebase fails with "unstaged changes."
- **5 todos but only 4 worktrees** — confirm no implementer accidentally tries to ship 731 OR 732 separately; combined commit is the contract.

## Out of scope

- Same as D+E batch + the explicit non-goals at top of this doc.

## Acceptance

- All 4 implementers + spec + quality reviews pass.
- All 4 FF-merge cleanly to local dev (sequential rebases).
- Single push lands all on origin/dev.
- CI green.
- Worktrees + branches cleaned.
- Todos 729, 730, 731, 732, 734 batch-completed.

# Karpathy CPM Integration Design

**Date:** 2026-04-23
**Todo:** 699
**Branch (planned):** `feat/699-karpathy-cpm-integration`

---

## Goals

1. Apply Karpathy's late-2025 agentic-engineering principles to CPM's managed CLAUDE.md block + workflow tooling.
2. Adopt forrestchang/andrej-karpathy-skills's 4-principle distillation (validated by 79.8k stars + direct Karpathy tweet attribution) as the rule backbone.
3. Layer CPM-specific operationalizations on top: chronological-log convention, mid-execution checkpoint affordance, reset-over-recover discipline, principled-across-scales constraint, reproduce-before-fix bug-work rule.
4. Audit existing managed-block rules for overlap; add cross-references where helpful, no removals.
5. Ship in 4 phases for reversibility, behavioral attribution, and measured rollout.

## Non-goals

- **Karpathy Loop / long-running autonomous agent contract** — out of scope. Karpathy's `autoresearch/program.md` pattern (NEVER STOP, simplicity criterion, allow/forbid files, `results.tsv` schema) is ML-domain-specific (numerical-metric optimization) and does not fit CPM's project-management workflow.
- **Changes to the superpowers plugin** (brainstorming, writing-plans, executing-plans skills) — out of scope. CPM uses superpowers as-is per the existing managed-block rule.
- **Wiki log absorbing decision_log** — out of scope. Karpathy's llm-wiki gist exactly matches this design, but it would require touching proj + wiki + router and is too invasive for this spec.
- **`proj_decision_log` MCP tool removal** — out of scope. Tool stays for `/proj:save` post-session extraction and structured A/B picks needing tag-based filtering.
- **Skill mirror of forrestchang principles** (e.g. `/proj:karpathy-check`) — out of scope. Managed-block coverage only, per Q&A: keeps surface area small + always-on enforcement.
- **Migration of existing `decisions.json` entries** — out of scope. Leave dual-source until decay; 5+ existing entries do not warrant migration tooling.

## Background

### Karpathy's late-2025 → 2026 shift

Karpathy publicly walked back his February 2025 "vibe coding" tweet over the course of 2025–2026. Operative shift:

- **Feb 2025**: "Accept All, I don't read the diffs anymore … just see stuff, say stuff, run stuff, copy paste stuff, and it mostly works." (https://x.com/karpathy/status/1886192184808149383)
- **Oct 2025** (Dwarkesh interview): agents "are not net useful" for novel work; autocomplete is the sweet spot.
- **Late 2025** (LLM-coding-pitfalls tweet, https://x.com/karpathy/status/2015883857489522876): catalogues the failure modes — silent assumptions, overcomplication, drive-by edits to code agents don't understand, missing tradeoff surfacing.
- **2026** ("agentic engineering"): rebranded successor to vibe coding. "Not writing code directly 99% of the time … orchestrating agents who do and acting as oversight."

### Sources informing this spec

| Source | Type | Used for |
|---|---|---|
| https://x.com/karpathy/status/2015883857489522876 (via forrestchang/andrej-karpathy-skills README) | Karpathy tweet | Core failure-mode catalogue |
| https://github.com/forrestchang/andrej-karpathy-skills (79.8k ⭐) | Third-party Claude Code plugin distilling above tweet into 4 principles, MIT-licensed | Phase 1 backbone (verbatim w/ attribution) |
| https://karpathy.bearblog.dev/year-in-review-2025/ | Karpathy essay | Localhost-first, context engineering, jagged intelligence |
| https://www.dwarkesh.com/p/andrej-karpathy | Dwarkesh interview | Autonomy slider, scope-pointing, build-from-scratch discipline |
| https://www.latent.space/p/s3 | Software 3.0 talk writeup | Generate/verify cycle, agent-first interfaces |
| https://fortune.com/2026/03/17/andrej-karpathy-loop-autonomous-ai-agents-future/ | Fortune | Karpathy Loop (out of scope but principles influenced rule selection) |
| https://github.com/karpathy/nanochat (`dev/LOG.md`) | Karpathy repo | Append-only chronological log convention |
| https://github.com/karpathy/autoresearch (`program.md`) | Karpathy repo | Simplicity criterion (rule #6) |
| https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f | Karpathy llm-wiki gist | Log heading convention `## [YYYY-MM-DD] op | title` |
| Simon Willison blog (agents/, claude-code/ tags, late 2025–early 2026) | Adjacent | Code-as-proof, dedicated-sandbox-repo |
| Kyle Howells `swift-justhtml-porting-html5-parser-to-swift` | Adjacent | Reset-over-recover, reproduce-before-fix, test-harness-first |
| Armin Ronacher (via Simon's `agent-design-is-still-hard`) | Adjacent | Abort-rather-than-compact, context plumbing |

---

## Phase 1 — Managed-block update + consolidation

**Scope**: pure markdown edits to `plugins/_shared/claudemd/managed_section.md` (the canonical source loaded by `claudemd.py::MANAGED_SECTION`). No Python code changes, no test changes. After merge, end users pick up changes via `/proj:claudemd-refresh`.

**Net change**: 15 → 24 rules, no removals, 6 cross-reference additions.

### 1A — forrestchang 4-principle backbone (verbatim, attributed)

Adopted from https://github.com/forrestchang/andrej-karpathy-skills (MIT). Inline attribution comment in `managed_section.md`. Rule numbering continues from existing block.

**Rule 16 — Think Before Coding.** Don't assume. Don't hide confusion. Surface tradeoffs. Before implementing: state assumptions explicitly (if uncertain, ask); if multiple interpretations exist, present them — don't pick silently; if a simpler approach exists, say so + push back when warranted; if something is unclear, stop, name what's confusing, ask. Cross-ref existing rule 4 (Interactive Q&A batching) for *how* to batch the asks.

**Rule 17 — Simplicity First.** Minimum code that solves the problem. Nothing speculative. No features beyond what was asked. No abstractions for single-use code. No "flexibility" or "configurability" that wasn't requested. No error handling for impossible scenarios. If you write 200 lines and it could be 50, rewrite. Senior-engineer-overcomplicated test: would a senior engineer say this is overcomplicated? If yes, simplify.

**Rule 18 — Surgical Changes.** Touch only what you must. Clean up only your own mess. When editing existing code: don't "improve" adjacent code, comments, or formatting; don't refactor things that aren't broken; match existing style; if you notice unrelated dead code, mention it — don't delete it. When your changes create orphans: remove imports/variables/functions that YOUR changes made unused; don't remove pre-existing dead code unless asked. Test: every changed line traces directly to the user's request.

**Rule 19 — Goal-Driven Execution.** Define success criteria. Loop until verified. Transform tasks into verifiable goals: "Add validation" → "Write tests for invalid inputs, then make them pass"; "Fix the bug" → "Write a test that reproduces it, then make it pass"; "Refactor X" → "Ensure tests pass before and after". For multi-step tasks, state a brief plan: `1. [Step] → verify: [check]`. Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### 1B — CPM-layer additions

**Rule 20 — Append-only log convention.** Record events / findings / decisions to project notes via `notes_append` with the heading prefix `## [YYYY-MM-DD HH:MM] {op} | {title}`, where `op` ∈ {note, decision, incident, experiment, fix, refactor, checkpoint, save, …}. Reserve `proj_decision_log` for structured A/B picks needing tag-based filtering. Result: chronological scan via `grep "^## \[" notes.md | tail -10` works universally. *(Source: Karpathy nanochat `dev/LOG.md` + llm-wiki gist. Phase 2 adds enforcement via `notes_append` `heading` param.)*

**Rule 21 — Reset-over-recover on agent drift.** When an agent skips cases, fabricates completion, or degrades reasoning during multi-step work, prefer `wt_remove` + new `wt_create` with tightened scope over patching the failing trajectory. Pair with `/proj:checkpoint` (Phase 3) for explicit invocation. Cross-ref existing rules 6 (worktree caveat) + 13 (sync-after-`wt_create`). *(Source: Howells swift-port writeup + Ronacher abort-before-compact discipline.)*

**Rule 22 — Reproduce-before-fix.** Bug-fix tasks must produce a reproducible failing test before patching code. No exceptions for "obvious" bugs. The test commit comes first; the fix commit comes second. *(Source: Howells "told the agent not to fix any fuzzer crashes … but to investigate and create a test file which reproduces the crash". Sharper than rule 19 generic verification; specific to bug-fix domain.)*

**Rule 23 — Principled across config scales.** Changes to plugins or shared infra reject point fixes that only help one config / profile / plugin. Changes must work across the plugin matrix. When a fix only helps one row, either expand the fix or document why the asymmetry is intentional. *(Source: Karpathy nanochat — "any candidate changes to the repo have to be principled enough that they work for all settings of depth".)*

**Rule 24 — Mid-execution checkpoint rhythm.** During multi-step implementation, suggest `/proj:checkpoint` (Phase 3) when a TaskCreate-tracked phase completes, or when the user pauses to evaluate progress. The checkpoint asks: continue / reset + restart with tightened scope / tighten scope only. Do not require Claude to count completed tasks — anchor on phase-boundary signals or explicit user pause. *(Source: derived from Howells reset-over-recover + Karpathy autonomy-slider per task.)*

### 1C — Audit-for-overlap consolidations

No rules removed. Cross-references added inline within the new rule text (above) and as bidirectional notes on the existing rules below.

| Existing rule | Overlap with new rule | Action |
|---|---|---|
| 14 (Verify before asserting) | 19 (Goal-Driven Execution) — both about verification | **Cross-ref**: existing fires mid-task ("re-check artifact still exists"); new fires pre-task (define success criteria). Different lifecycle moments. Add inline note to existing #14: "see also rule 19 for pre-task verification framing." |
| 3 (Auto-capture issues as todos) | 20 (Append-only log) — both capture findings | **Cross-ref**: auto-capture = persistent project state (todos.yaml); log = chronological event stream (notes.md). Add inline note to existing #3: "for non-actionable findings or event records, see rule 20 (chronological log) instead." |
| 5 (Patch-style editing) | 18 (Surgical Changes) — both about minimal change | **Cross-ref**: existing = API choice (patch vs full-rewrite); new = diff scope. Add inline note to existing #5: "see also rule 18 for diff-scope discipline." |
| 4 (Interactive Q&A batching) | 16 (Think Before Coding "ask when unclear") | **Cross-ref already inline in rule 16 above.** Existing = how to ask; new = when to ask. |
| 10 (Sub-task nesting) | 19 (multi-step plan w/ verify) | **No action**. Different concerns: sub-task nesting is about Task-tool mechanics; rule 19 is about plan structure. |
| 6 (Worktree caveat) + 13 (sync-after-wt_create) | 21 (reset-over-recover) | **Strong synergy**. Rule 21 builds on existing 6 + 13. Cross-ref already inline in rule 21 above. |

### Phase 1 deliverable

Single PR. Files changed:
- `plugins/_shared/claudemd/managed_section.md` (new rules 16–24 + cross-references on existing 3, 5, 14)
- `plugins/_shared/claudemd/CHANGELOG.md` (if exists; create if not) — entry summarizing rule additions + attribution
- `README.md` — short "Karpathy alignment" section under existing managed-block docs section, citing forrestchang + Karpathy tweet
- No Python changes
- Existing `claudemd.py` tests should pass unchanged (parser handles flat block; new rules are additional content, same shape)

---

## Phase 2 — `notes_append` heading param + `/proj:save` convention adoption

**Scope**: Python code change to `plugins/proj/server/server/tools/context.py` (verified `notes_append` location: `context.py:385-402`) + possibly `plugins/proj/server/server/storage.py` (the `storage.append_note` helper) + `plugins/proj/skills/save/SKILL.md` update + tests.

### `notes_append` API extension

Current signature (verified at `context.py:386`):
```python
notes_append(text: str, project_name: str | None = None) -> str
```

Proposed signature:
```python
notes_append(
    text: str,
    heading: str | None = None,
    op: str = "note",
    project_name: str | None = None,
) -> str
```

Behavior:
- `heading` provided → prepend `## [{YYYY-MM-DD HH:MM}] {op} | {heading}\n\n` to `text`, then append. Composition happens at tool layer in `context.py`; passes the composed string to existing `storage.append_note` (no storage-layer change needed unless we want timestamp normalization at storage).
- `heading` absent → current behavior unchanged (full backward compatibility for existing callers + the router hook in `default-hooks.yaml` that consumes `content_first_line`).
- `op` defaults to `"note"`. Allowed values: any non-empty string; convention recommends {note, decision, incident, experiment, fix, refactor, checkpoint, save}. Not enforced server-side (free-form for extensibility).
- Timestamp format: `2026-04-23 14:32` (24-hour, local timezone for human-readable; document in tool docstring).
- Idempotent w.r.t. existing `notes_append` semantics (still pure append, no dedup).
- Return JSON unchanged shape: `{status, project_name, content, content_first_line, message}`. The `content_first_line` becomes the heading line when `heading` is provided — useful for the existing router hook that maps `content_first_line` to log-entry titles.

### `/proj:save` adoption

Update `plugins/proj/skills/save/SKILL.md`:
- When appending the session-level summary section: `notes_append(heading=<session-title>, op="session", text=<body>)`.
- When extracting individual decisions for `proj_decision_log` (existing behavior): unchanged.
- New step: at end of session save, count session-level `notes_append`-with-`heading` calls. If zero such calls in this session: prompt user via `AskUserQuestion` — single light reminder, *"No decisions logged this session. Any to capture before save?"* (Yes → user supplies, append via convention; No → proceed). Threshold-based variants (e.g. only prompt if session > 20 tool calls) deferred to Phase 4 audit if needed.

### Phase 2 testing

- `tests/test_notes_append.py` — new param handling, format correctness, backward compat with existing callers, op default, missing-heading case.
- `tests/test_save_skill_integration.py` (or extend existing) — end-of-`/proj:save` adopts convention; reminder prompt fires only when zero session-level decisions logged.

### Phase 2 deliverable

Single PR. Files:
- `plugins/proj/server/server/tools/context.py` (`notes_append` extension)
- `plugins/proj/server/server/storage.py` (only if storage-layer normalization desired; otherwise unchanged)
- `plugins/proj/skills/save/SKILL.md`
- `plugins/proj/server/tests/test_context.py` (extend existing test file for `notes_append`; verify exact path during writing-plans)
- Integration test for `/proj:save` adoption (extend existing save-skill test or add new)

---

## Phase 3 — `/proj:checkpoint` skill

**Scope**: new SKILL.md only. No new MCP tools. Composes existing primitives.

### Skill location + namespace

`plugins/proj/skills/checkpoint/SKILL.md`. Invoked as `/proj:checkpoint`.

### Skill behavior

1. **Identify scope**: read active project via `proj_get_active`; read worktree info via `wt_list` filtered to active project's repos. If multiple worktrees, prompt user to pick (or default to current `cwd` worktree if unambiguous).
2. **Compute diff since last checkpoint**: read git note tag `checkpoint:<id>` on the worktree branch via `git notes list`. If absent, default to "since branch divergence from base" (`git merge-base origin/<base>..HEAD`). Bash composition; no new MCP tool.
3. **Surface diff**: per existing managed-block rule 11 (revdiff routing) — check `enabledPlugins["revdiff@revdiff"]` in `~/.claude/settings.json` and `which revdiff`. If both succeed, invoke `revdiff:revdiff` skill on the diff. Else: render `git diff --stat` + per-file bullet summary inline.
4. **Surface state context**: pull recent commits, open todos via `todo_list` (compact), and recent `notes.md` entries since last checkpoint.
5. **Prompt user via `AskUserQuestion`** with 3 options:
   - **Continue** — work continues on current branch; checkpoint marker advances.
   - **Reset + restart with tightened scope** — `wt_remove` current worktree, `wt_create` new worktree with branch suffix `-v2` (or user-supplied), prompt user for tightened scope statement, log via `notes_append(op="checkpoint", heading="reset to v2", ...)`.
   - **Tighten scope only** — keep branch + worktree, prompt user for new constraint, log via `notes_append(op="checkpoint", heading="tightened scope", ...)`.
6. **Mark checkpoint**: place git note `checkpoint:<timestamp>` on `HEAD` of the active branch (Bash: `git notes add -m "checkpoint" <sha>`). Used by next checkpoint invocation to compute diff-since.
7. **Auto-suggestion** (managed-block rule 24): suggest invocation when a TaskCreate-tracked phase completes or user pauses to evaluate. Skill itself doesn't enforce — relies on Claude's instruction-following per rule 24.

### Composition surface

| Primitive | Use |
|---|---|
| `proj_get_active` | active project lookup |
| `wt_list` | worktree info |
| Bash (`git notes`, `git diff`, `git merge-base`, `git log`) | diff/marker computation |
| `revdiff:revdiff` (conditional) | diff display |
| `todo_list` | open-todo context |
| `notes_append` (Phase 2 enhanced) | checkpoint logging |
| `AskUserQuestion` | 3-option prompt |
| `wt_remove`, `wt_create` | reset path |

### Phase 3 testing

- E2E smoke test: skill loads, dispatches a no-op checkpoint on a test repo, returns the 3 options. User-interactive prompts cannot be automated; skill includes a manual checklist in its SKILL.md for verification.
- No unit tests (pure skill prompt; no Python).

### Phase 3 deliverable

Single PR. Files:
- `plugins/proj/skills/checkpoint/SKILL.md` (new, caveman ultra per project convention)
- `plugins/proj/skills/checkpoint/manual-checklist.md` (verification steps)
- Update `plugins/proj/README.md` skill table + "Skills by category" list
- Update `README.md` (top-level marketplace) skill reference table

---

## Phase 4 — 30-day usage audit

**Scope**: no code changes. Manual usage review + audit doc.

### Trigger

30 days after Phase 3 PR merges to dev (or main, depending on release cadence). Audit todo created at Phase 3 merge with target date populated.

### Measurements

1. **Logging discipline**:
   - `decision_log.add` call count over the audit window (parse `~/projects/tracking/*/decisions.json` mtimes + entry counts).
   - `notes_append`-with-`heading` call count over the audit window (parse `~/projects/tracking/*/notes.md` for `## [YYYY-MM-DD ...]` lines added in window).
   - Ratio: heading-style logging vs. decision-log logging. Target: heading-style ≥ 3× decision-log usage (chronological is now primary).

2. **Checkpoint usage**:
   - `/proj:checkpoint` invocations over window (count `checkpoint:` git notes added across active project repos).
   - Outcome distribution: continue vs reset vs tighten. Outcome captured in `notes_append` checkpoint events.
   - Target: at least one checkpoint per multi-step session with 3+ tasks; no specific outcome distribution target (informative).

3. **Rule adherence (qualitative)**:
   - Manual review of last 10 multi-step sessions in active projects. For each, score:
     - Drive-by-refactor incidents (rule 18 violations)
     - Assumptions surfaced before coding vs picked silently (rule 16 adherence)
     - Bug fixes preceded by failing test (rule 22 adherence) — if any bug fixes in window
     - Reset-over-recover invocations on detected drift (rule 21)
   - Score: 0–3 per category per session.

### Deliverable

`docs/superpowers/audits/2026-MM-DD-karpathy-integration-audit.md` containing:
- Quantitative metrics + targets met/missed
- Qualitative rule-adherence scorecard
- Iteration todos: rules to reword, skill UX gaps, enforcement mechanisms to consider (Phase 5 candidates)

### Phase 4 deliverable

Single low-friction PR with the audit doc + iteration todos in `todos.yaml`. No code, no tests.

---

## Testing strategy summary

| Phase | Test approach |
|---|---|
| 1 | No new automated tests. Manual verification: run `/proj:claudemd-refresh` on a clean test environment; diff before/after. Spec self-review pass catches rule contradictions before merge. |
| 2 | pytest unit tests for `notes_append` param handling + format. Integration test for `/proj:save` adopting convention + reminder-prompt logic. |
| 3 | E2E smoke (skill loads + dispatches options on test repo). Manual checklist for user-interactive prompts. |
| 4 | Manual usage audit. No automated tests. |

CI matrix: existing proj-server matrix row covers Phase 2 changes; no new matrix row needed since no new plugin.

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Managed-block size growth: 15 → 24 rules increases per-session token cost | High | Low | Caveman-ultra phrasing per project convention. Section headings within block deferred (per Q&A) but available as fallback if size becomes painful. Audit Phase 4 reports actual token cost. |
| Rule conflict: 24 rules may have implicit edge-case contradictions | Medium | Medium | Spec self-review pass (next step) + explicit precedence note in managed-block preamble: "user instructions > superpowers skills > managed-block rules > defaults". Adopt the existing precedence statement from `superpowers:using-superpowers`. |
| Adoption gap: instruction-following ≠ behavior change | Medium | Medium | Phase 4 audit measures actual behavior. Phase 5 (separate spec, not yet scoped) handles enforcement (router hooks, auto-suggest mechanisms) if audit shows gap. |
| forrestchang license/attribution risk | Low | Low | MIT license confirmed in `skills/karpathy-guidelines/SKILL.md` frontmatter. Inline attribution per rule + repo-level credit in README. |
| Checkpoint skill: revdiff fallback might be ugly | Medium | Low | Phase 3 spec includes both surfaces. Manual UX check before merge. Iterate in Phase 4 if needed. |
| Rule 24 ("when phase completes / user pauses") still relies on Claude to detect signals | Medium | Low | Anchor language is testable (TaskCreate phase boundaries are explicit; user pauses are detectable from message patterns). Phase 4 measures invocation rate. If gap, consider explicit hook trigger in Phase 5. |
| `/proj:save` reminder annoys users on genuinely decision-free sessions | Low | Low | Single dismissible prompt only when zero session-decisions logged. User can answer "No" to skip. Phase 4 audit reports dismiss rate. |

---

## Resolved decisions (from brainstorm Q&A)

- **Single integrated spec** covering both threads (workflow principles + managed-block additions). Not split.
- **Deliverable**: spec → ready for writing-plans, not investigation-only.
- **Sources**: cited essays + Karpathy GitHub + nanochat + adjacent thinkers + forrestchang.
- **Surfaces**: managed CLAUDE.md + new/edited CPM skills + proj MCP tool params (`notes_append`). Not superpowers plugin.
- **Karpathy Loop**: out of scope (ML domain mismatch).
- **Log strategy**: chronological-log convention with small enforcement (Phase 2). Not aspirational doc-only; not bigger wiki-log refactor.
- **Checkpoint**: new `/proj:checkpoint` skill + managed-block rule. Not skill-only or rule-only. Reproduce-before-fix is its own rule, not folded into checkpoint skill.
- **Forrestchang adoption**: 4-principle backbone verbatim with attribution. Not cherry-picked, not paraphrased.
- **Forrestchang surface**: managed-block only. No skill mirror.
- **Existing rule consolidation**: cross-references added inline; no removals.
- **Phase 3 implementation**: pure skill + Bash + existing MCP tools. No new MCP tool.
- **Rule 24 trigger reword**: TaskCreate phase boundary OR user pause (not "every 2-3 tasks").
- **`/proj:save` reminder**: light single prompt when zero decisions logged.
- **`decisions.json` migration**: leave dual-source until decay.

## Remaining open questions (carry into writing-plans)

- **Attribution style**: inline per-rule citations (current draft) vs. repo-level footer in `managed_section.md`. Resolve in writing-plans pass; either acceptable.
- **Caveman-ultra rule phrasing**: Phase 1 rules drafted in spec body in normal prose for clarity. Final compression to caveman-ultra happens in writing-plans. Keep `200 → 50` numerals, code-style examples, and verbatim Karpathy quotes intact during compression.
- **Phase 2 reminder threshold**: light prompt always vs threshold (e.g. `> 20 tool calls + 0 decisions`). Spec defaults to "always when 0 decisions"; Phase 4 audit reports false-positive rate; tighten in Phase 5 if needed.
- **Phase 3 git-note vs notes.md anchor for checkpoint markers**: spec defaults to git note (`git notes add`) for diff-since calculation. Alternative: parse most recent `## [...] checkpoint | ...` heading in notes.md. Git note is more git-native; notes.md anchor is more visible. Resolve in writing-plans based on git note availability across all worktrees (some configs disable notes).
- **Phase 4 audit triggering**: who creates the audit todo + populates target date? Spec assumes Phase 3 merge ceremony creates it. Confirm in writing-plans.

---

## References

### Karpathy primary sources
- LLM-coding-pitfalls tweet: https://x.com/karpathy/status/2015883857489522876
- Original vibe-coding tweet: https://x.com/karpathy/status/1886192184808149383
- 2025 LLM year-in-review: https://karpathy.bearblog.dev/year-in-review-2025/
- Dwarkesh interview: https://www.dwarkesh.com/p/andrej-karpathy
- Software 3.0 talk: https://www.latent.space/p/s3
- Karpathy Loop (Fortune): https://fortune.com/2026/03/17/andrej-karpathy-loop-autonomous-ai-agents-future/
- nanochat repo: https://github.com/karpathy/nanochat
- autoresearch repo: https://github.com/karpathy/autoresearch
- llm-council repo: https://github.com/karpathy/llm-council
- llm-wiki gist: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

### Third-party / adjacent
- forrestchang/andrej-karpathy-skills: https://github.com/forrestchang/andrej-karpathy-skills
- Simon Willison agents tag: https://simonwillison.net/tags/agents/
- Simon Willison Claude Code tag: https://simonwillison.net/tags/claude-code/
- Kyle Howells Swift port: http://ikyle.me/blog/2025/swift-justhtml-porting-html5-parser-to-swift
- Armin Ronacher (via Simon): https://simonwillison.net/2025/Nov/23/agent-design-is-still-hard/
- Kyle Howells Karpathy notes: http://ikyle.me/blog/2025/andrej-karpathy-software-is-changing-again
- Matt Webb context plumbing: https://simonwillison.net/2025/Nov/29/context-plumbing/

### CPM internal
- Existing managed block: `~/.claude/CLAUDE.md` (lines 29–48)
- Managed-block source: `plugins/_shared/claudemd/managed_section.md`
- `claudemd.py` module: `plugins/_shared/claudemd/claudemd.py`
- `notes_append` tool: `plugins/proj/server/server/tools/context.py:385-402`
- `/proj:save` skill: `plugins/proj/skills/save/SKILL.md`
- `proj_decision_log` tool: `plugins/proj/server/server/tools/decisions.py`
- Related decision-log usage data: `~/projects/tracking/claude-project-manager/decisions.json`

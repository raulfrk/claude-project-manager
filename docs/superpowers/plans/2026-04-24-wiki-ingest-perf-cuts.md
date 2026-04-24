# Wiki Ingest Perf Cuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut wiki ingest wall-time, token cost, and page sprawl by adding a substance gate to `/proj:save` step 11, wiring `session_ingest.section_map` into subagent extraction, and scoping the cross-ref pass to same-category pages.

**Architecture:** Three surgical edits to skill prose / subagent prompt files. No Python module changes. No new MCP tools. No new config keys (existing `wiki.yaml::session_ingest.section_map` field gets activated). Spec at `docs/superpowers/specs/2026-04-24-wiki-ingest-perf-cuts-design.md`.

**Tech Stack:** Markdown skill prose only. Verification is manual (no automated tests added — the changes are agent-instruction prose, not Python code).

---

## File Structure

| File | Responsibility | Modified by task |
|---|---|---|
| `plugins/proj/skills/save/SKILL.md` | `/proj:save` skill prose; step 11 owns wiki ingest dispatch | Task 1 |
| `plugins/wiki/skills/ingest/references/subagent-prompt.md` | Subagent template instructing extraction + cross-ref pass | Task 2, Task 3 |
| `plugins/wiki/skills/ingest/references/dedup-protocol.md` | Documents extraction + dedup + cross-ref protocol details | Task 3 |
| `plugins/proj/.claude-plugin/plugin.json` | proj plugin version | Task 5 |
| `plugins/wiki/.claude-plugin/plugin.json` | wiki plugin version | Task 5 |
| `.claude-plugin/marketplace.json` | marketplace versions for both plugins | Task 5 |

The first three are the substantive changes. Task 4 is manual verification. Task 5 is version bumps + branch finishing per project convention.

---

## Pre-Task Setup

Before starting any task, create an isolated worktree per project rules.

- [ ] **Step 1: Create worktree from dev**

```bash
# Via worktree MCP tool (preferred):
# mcp__plugin_worktree_worktree__wt_create(repo_label="cpm", branch="feat/727-wiki-ingest-perf-cuts", base_branch="dev")
```

Expected: returns `worktree_path: /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts`.

- [ ] **Step 2: Sync worktree to remote per CLAUDE.md rule**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts
git fetch origin
# Local dev not ahead of origin → reset:
git rev-list origin/dev..dev  # if empty, reset:
git reset --hard origin/dev
```

Expected: HEAD at the most recent dev commit (currently `8569f8f` or later).

- [ ] **Step 3: Sync uv groups for proj server (so subprocess CLI tests don't break later)**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts/plugins/proj/server
uv sync --all-groups
```

Expected: pytest available in venv. (Same fix as 5.1.4 work — fresh worktree venv lacks dev deps.)

**All subsequent task file paths assume the worktree at `/home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts/`.**

---

## Task 1: Substance gate in `/proj:save` step 11

**Files:**
- Modify: `plugins/proj/skills/save/SKILL.md` (step 11, lines 82-90 in dev)

**Goal:** Insert a substance gate before the wiki ingest dispatch. Gate fails (skip dispatch) when ALL of: zero Decisions bullets AND zero Insights bullets AND total word count < 300. Missing section treated as zero bullets.

- [ ] **Step 1: Read current step 11 prose to anchor the edit**

Read the file via Read tool. Anchor on the existing block:

```
**11.** Wiki auto-ingest (if enabled):
 - `mcp__proj__config_load` → check `sync.wiki.enabled` + `sync.wiki.auto_ingest_sessions`.
 - Both false → skip silently.
 - Both true → spawn forked subagent via `Task`:
```

This is the prose to wrap with the gate.

- [ ] **Step 2: Replace step 11 with gated version**

Use Edit tool. Replace the existing step 11 block (lines starting at `**11.** Wiki auto-ingest (if enabled):` through `Subagent failure → warn:` line) with:

```
**11.** Wiki auto-ingest (if enabled):
 - `mcp__proj__config_load` → check `sync.wiki.enabled` + `sync.wiki.auto_ingest_sessions`.
 - Both false → skip silently.
 - Both true → run substance gate before dispatch:
   - Read just-written session file (path from steps 5-7).
   - Count bullets under `## Key Decisions` (missing section = 0).
   - Count bullets under `## Insights Discovered` (missing section = 0).
   - Compute total word count of session file.
   - **Gate fail when ALL true**: Decisions bullets == 0 AND Insights bullets == 0 AND word count < 300.
   - Gate fail → log to console: `Wiki ingest skipped: trivial session (no decisions/insights, <300 words).` Skip subagent dispatch. Continue to step 12.
   - Gate pass → spawn forked subagent via `Task`:
     - `subagent_type="general-purpose"`
     - `description="Wiki ingest session file"`
     - `prompt` = contents of `plugins/wiki/skills/ingest/references/subagent-prompt.md` (read via `Read`) w/ `{source}` = `session:<tracking_dir>/<name>/sessions/<filename>`, `{scope}` = `project:<name>` (from step 1), `{wiki_config}` = JSON of `~/.claude/wiki.yaml` + `~/.claude/wiki/config.yaml` (read via `Read`).
 - Subagent success → "Wiki ingest: N pages created, M updated."
 - Subagent failure → warn: "Wiki ingest failed: <err>. Session file saved. Retry manually via `/wiki:ingest session:<path>`." + continue.
```

**Important:** preserve caveman ultra style (no articles, fragments, arrows where possible). Code blocks stay verbatim.

- [ ] **Step 3: Verify edit by re-reading step 11**

Read the file again, lines 80-100. Confirm:
- "run substance gate before dispatch" prose present.
- Gate's three conditions present and joined by ALL/AND (skip when ALL trivial).
- Gate-fail console log line present.
- Gate-pass branch preserves the original Task dispatch with all four arg lines (subagent_type, description, prompt template, scope).

- [ ] **Step 4: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts
git add plugins/proj/skills/save/SKILL.md
git commit -m "$(cat <<'EOF'
feat(proj/727): substance gate in /proj:save wiki ingest dispatch

Skip wiki ingest subagent when session has zero Decisions bullets AND
zero Insights bullets AND <300 words total. Missing section = zero
bullets. Console log line on skip so user can manually run /wiki:ingest
if false-positive.

Spec: docs/superpowers/specs/2026-04-24-wiki-ingest-perf-cuts-design.md
EOF
)"
```

Expected: commit succeeds, pre-commit hooks pass (skill prose only, no code linters fire).

---

## Task 2: Wire `session_ingest.section_map` into extraction

**Files:**
- Modify: `plugins/wiki/skills/ingest/references/subagent-prompt.md` (PROTOCOL block, lines 33-58 in dev)

**Goal:** Activate the existing `wiki.yaml::session_ingest.section_map` config. When present, subagent walks session sections and applies the heading→category mapping as a category hint during candidate extraction.

- [ ] **Step 1: Read current PROTOCOL step 2 prose**

Read the file. Anchor on:

```
2. Extract 3-15 candidate entities per the `dedup-protocol.md` extraction rules.
   Each candidate has: title, slug, category, tags, summary, body_candidate, evidence.
```

This is what gets the section-aware extension.

- [ ] **Step 2: Replace step 2 with section-aware version**

Use Edit. Replace the line above with:

```
2. Extract 3-15 candidate entities per the `dedup-protocol.md` extraction rules.
   Each candidate has: title, slug, category, tags, summary, body_candidate, evidence.
   - If SOURCE is a session file (`session:` prefix) AND CONFIG includes a
     non-empty `session_ingest.section_map` (e.g. `{"Key Decisions": "decisions",
     "Insights Discovered": "insights"}`): walk the session file section by
     section. For each `## <heading>` matching a key in `section_map`, candidates
     extracted from that section's bullets receive `<section_map[heading]>` as a
     CATEGORY HINT. The hint is not a hard assignment — override based on
     candidate content if the body clearly belongs in a different category.
   - If `section_map` is empty, missing, or SOURCE is not a session file:
     extract wholesale (current behavior, unchanged).
```

- [ ] **Step 3: Verify by re-reading step 2 of PROTOCOL**

Read file, lines around the PROTOCOL block. Confirm:
- New section_map clause references SOURCE prefix `session:`.
- Hint vs hard-assignment distinction present.
- Fallback clause for empty/missing section_map present.
- Step numbering 1-9 still intact (no accidental renumbering).

- [ ] **Step 4: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts
git add plugins/wiki/skills/ingest/references/subagent-prompt.md
git commit -m "$(cat <<'EOF'
feat(wiki/727): wire session_ingest.section_map into ingest extraction

When SOURCE is a session: file and CONFIG has non-empty section_map,
subagent walks sections and applies heading→category mapping as a
category hint during candidate extraction. Empty/missing section_map
falls back to current wholesale extraction.

Spec: docs/superpowers/specs/2026-04-24-wiki-ingest-perf-cuts-design.md
EOF
)"
```

Expected: commit succeeds.

---

## Task 3: Cross-ref pass scope change

**Files:**
- Modify: `plugins/wiki/skills/ingest/references/subagent-prompt.md` (PROTOCOL step 6)
- Modify: `plugins/wiki/skills/ingest/references/dedup-protocol.md` (Cross-ref pass section, lines 56-61)

**Goal:** Limit the cross-ref pass scope from full-wiki to same-category pages. Cross-category links recovered later by `/wiki:lint` tier-2 sweep.

- [ ] **Step 1: Read current cross-ref step in subagent-prompt.md**

Read file. Anchor on:

```
6. Cross-ref pass: for each written page, scan body for noun phrases that
   match other page titles/aliases via wiki_link_resolve → insert [[wikilinks]]
   inline → update links_to frontmatter → wiki_page_write(mode="update").
```

- [ ] **Step 2: Replace cross-ref step with scoped version**

Use Edit. Replace the lines above with:

```
6. Cross-ref pass (same-category scope): for each written page in category X,
   scan body for noun phrases that match titles/aliases of OTHER pages within
   category X only (not full wiki). Use wiki_link_resolve scoped via
   wiki_page_list(category=X) → insert [[wikilinks]] inline → update links_to
   frontmatter → wiki_page_write(mode="update"). Cross-category links are not
   added here; `/wiki:lint` tier-2 fills them in as a separate sweep.
```

- [ ] **Step 3: Read current cross-ref section in dedup-protocol.md**

Read file. Anchor on lines 56-61:

```
## Cross-ref pass (after all candidates written)

1. Walk each new/updated page's body.
2. For each noun phrase that matches another page's title or alias (via `wiki_link_resolve`): insert `[[wikilink]]` replacement inline.
3. Update the page's `links_to` frontmatter (union of existing + newly inserted).
4. Write back via `wiki_page_write(mode="update")`.
```

- [ ] **Step 4: Replace cross-ref section in dedup-protocol.md**

Use Edit. Replace the block above with:

```
## Cross-ref pass (after all candidates written)

Scope: **same-category only**. For a page in category X, this pass considers
links to other pages within category X. Cross-category links are not added
here; `/wiki:lint` tier-2 sweep fills them in separately. Rationale: most
ingest-time noun-phrase matches across categories are noise; restricting to
same-category cuts wiki_link_resolve calls roughly proportional to the
category-to-wiki size ratio.

1. Walk each new/updated page's body.
2. For each noun phrase that matches the title/alias of ANOTHER page in the
   SAME category (via `wiki_link_resolve` scoped via `wiki_page_list(category=X)`):
   insert `[[wikilink]]` replacement inline.
3. Update the page's `links_to` frontmatter (union of existing + newly inserted).
4. Write back via `wiki_page_write(mode="update")`.

Cross-category links: not handled here. The `/wiki:lint` tier-2 sweep
identifies missing-cross-ref candidates across categories and either inserts
them or surfaces them for user review. This split keeps ingest fast and lint
authoritative for cross-category coherence.
```

- [ ] **Step 5: Verify both files**

Read subagent-prompt.md PROTOCOL step 6 — confirm same-category clause present, `wiki_page_list(category=X)` mentioned, lint-tier-2 fallback noted.

Read dedup-protocol.md Cross-ref section — confirm scope paragraph, scoped wiki_link_resolve, and trailing cross-category paragraph all present. Step numbering 1-4 intact.

- [ ] **Step 6: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts
git add plugins/wiki/skills/ingest/references/subagent-prompt.md plugins/wiki/skills/ingest/references/dedup-protocol.md
git commit -m "$(cat <<'EOF'
feat(wiki/727): scope cross-ref pass to same-category pages

Cross-ref pass during ingest now limits wiki_link_resolve to pages within
the candidate's category. Cross-category links recovered later by
/wiki:lint tier-2 sweep. Cuts ingest-time wiki_link_resolve calls roughly
proportional to category-to-wiki ratio.

Spec: docs/superpowers/specs/2026-04-24-wiki-ingest-perf-cuts-design.md
EOF
)"
```

Expected: commit succeeds.

---

## Task 4: Manual verification

**No automated tests** — all changes are agent-instruction prose, not Python. Walk the spec's 6 scenarios manually and record results.

- [ ] **Step 1: Verify gate-skip path (trivial session)**

Setup: in any tracked project, run `/proj:save` after a session that contains only `/status` queries (no decisions, no insights). Use a synthetic test if needed:

1. Create a minimal session manually: `~/.claude/test-session.md` with content `# Session: 2026-04-24\n\n## Key Decisions\n\n## Insights Discovered\n\n## Open Questions\n- placeholder\n`. Word count <300. Decisions and Insights empty.
2. Trigger `/proj:save` (or simulate the step 11 logic by reading the file + running the gate manually).

Expected: console line `Wiki ingest skipped: trivial session (no decisions/insights, <300 words).` No subagent dispatched. Record outcome.

- [ ] **Step 2: Verify gate-pass path (real session)**

Setup: trigger `/proj:save` after a real work session with at least one Decisions bullet recorded.

Expected: subagent dispatches normally, returns `pages_created: [...]` summary. No "skipped" line. Record outcome.

- [ ] **Step 3: Verify section-aware extraction with section_map set**

Setup: ensure `~/.claude/wiki.yaml` has:
```yaml
session_ingest:
  section_map:
    Key Decisions: decisions
    Insights Discovered: insights
```

Trigger ingest on a session with both sections populated. Verify created pages land in the correct category dirs (`~/.claude/wiki/decisions/*.md` for Decisions-derived candidates, `~/.claude/wiki/insights/*.md` for Insights-derived).

Expected: at least one page from each section ends up in the mapped category. Record slugs + categories.

- [ ] **Step 4: Verify cross-ref scope**

Setup: ensure the wiki has at least 3 pages in `decisions/` AND at least 3 pages in another category (e.g. `concepts/`). Ingest a session that creates a new page in `decisions/` whose body contains noun phrases matching pages in BOTH `decisions/` and `concepts/`.

Expected: inline `[[wikilinks]]` in the new page's body resolve only to other `decisions/*.md` titles. Cross-category links to `concepts/` are absent until `/wiki:lint` tier-2 runs.

Record: which cross-category links were missed; confirm `/wiki:lint --tier=2` adds them on subsequent run.

- [ ] **Step 5: Verify backward compat (empty section_map)**

Setup: temporarily set `session_ingest.section_map: {}` in `~/.claude/wiki.yaml`. Trigger ingest on a substantive session.

Expected: subagent extracts wholesale (no section bucketing); pages created with subagent's chosen categories. Record that behavior matches pre-change ingest.

- [ ] **Step 6: Verify backward compat (gate disabled)**

Setup: temporarily comment the gate block in `/proj:save` step 11 (revert the gate for one test). Trigger `/proj:save` for the trivial session from Step 1.

Expected: subagent dispatches as it would have pre-change. Confirms the gate is the only thing changing dispatch behavior. Restore the gate after.

- [ ] **Step 7: Record verification results**

Append to the spec doc (`docs/superpowers/specs/2026-04-24-wiki-ingest-perf-cuts-design.md`) under a new `## Verification Results` section:

```markdown
## Verification Results (YYYY-MM-DD)

| Scenario | Outcome | Notes |
|---|---|---|
| 1. Gate-skip (trivial) | pass / fail | <details> |
| 2. Gate-pass (real) | pass / fail | <details> |
| 3. Section-aware extraction | pass / fail | <details> |
| 4. Cross-ref same-category scope | pass / fail | <details> |
| 5. Backward compat (empty section_map) | pass / fail | <details> |
| 6. Backward compat (gate disabled) | pass / fail | <details> |
```

- [ ] **Step 8: Commit verification results**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts
git add docs/superpowers/specs/2026-04-24-wiki-ingest-perf-cuts-design.md
git commit -m "docs(727): manual verification results for wiki ingest perf cuts"
```

Expected: commit succeeds.

---

## Task 5: Version bumps + finishing branch

Per project convention (CLAUDE.md): version must be bumped in `plugin.json` AND `.claude-plugin/marketplace.json` together. Both proj and wiki had skill-prose changes.

**Files:**
- Modify: `plugins/proj/.claude-plugin/plugin.json` (version field)
- Modify: `plugins/wiki/.claude-plugin/plugin.json` (version field)
- Modify: `.claude-plugin/marketplace.json` (proj entry version, wiki entry version)

- [ ] **Step 1: Bump proj 5.1.4 → 5.1.5 in plugin.json**

Read `plugins/proj/.claude-plugin/plugin.json`. Find the `"version": "5.1.4"` line (or whatever current is). Edit to `"version": "5.1.5"`.

- [ ] **Step 2: Bump wiki 0.1.1 → 0.1.2 in plugin.json**

Read `plugins/wiki/.claude-plugin/plugin.json`. Find `"version": "0.1.1"`. Edit to `"version": "0.1.2"`.

- [ ] **Step 3: Bump both versions in marketplace.json**

Read `.claude-plugin/marketplace.json`. Find the proj entry's version field, bump to 5.1.5. Find the wiki entry's version field, bump to 0.1.2.

- [ ] **Step 4: Commit version bumps (let pre-commit auto-update README)**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts
git add plugins/proj/.claude-plugin/plugin.json plugins/wiki/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(727): bump proj 5.1.4 → 5.1.5, wiki 0.1.1 → 0.1.2"
```

If pre-commit fails with "README.md updated by hook":
```bash
git add README.md
git commit -m "chore(727): bump proj 5.1.4 → 5.1.5, wiki 0.1.1 → 0.1.2"
```

Expected: commit succeeds, README badges updated.

- [ ] **Step 5: Diff vs origin/dev before merge (CLAUDE.md rule)**

```bash
cd /home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts
git fetch origin
git diff origin/dev..HEAD --stat
git rev-list HEAD..origin/dev | wc -l  # 0 = FF-mergeable
```

Expected: stat shows only the files modified across tasks 1-5. Rev-list count is 0 (no behind).

- [ ] **Step 6: Switch to main repo, FF-merge, push**

```bash
cd /home/raul/projects/claude-project-manager
git pull --ff-only origin dev
git merge --ff-only feat/727-wiki-ingest-perf-cuts
git push origin dev
```

Expected: push succeeds. CI fires on push to dev (per project convention; no PR).

- [ ] **Step 7: Watch CI**

```bash
gh run list --branch dev --limit 2
gh run watch <latest-run-id> --exit-status
```

Expected: CI green. If red, investigate before considering done.

- [ ] **Step 8: Cleanup worktree**

```bash
# Via worktree MCP tool:
# mcp__plugin_worktree_worktree__wt_remove(path="/home/raul/worktrees/cpm/feat-727-wiki-ingest-perf-cuts")
git branch -d feat/727-wiki-ingest-perf-cuts
```

Expected: worktree removed; merged feat branch deleted.

- [ ] **Step 9: Mark todo 727 complete**

Via proj todo skill: `/proj:todo done 727`.

Expected: todo 727 marked complete; Todoist hook syncs.

---

## Acceptance Checklist

- [ ] Substance gate prose present in `/proj:save` step 11 with all three conditions joined by ALL.
- [ ] Section-aware extraction clause added to subagent-prompt.md PROTOCOL step 2; gated on `session:` source AND non-empty section_map.
- [ ] Cross-ref pass in both subagent-prompt.md AND dedup-protocol.md scoped to same-category; lint-tier-2 fallback documented.
- [ ] Version bumps in both plugin.jsons + marketplace.json; README badges auto-updated.
- [ ] All 6 manual verification scenarios pass (or failures documented in spec results table).
- [ ] FF-merged to dev. CI green. Worktree cleaned. Todo 727 closed.

---

## Notes for the executing engineer

- This plan touches **agent-instruction prose** (skill SKILL.md + subagent-prompt.md + dedup-protocol.md). There is no Python code to compile or test. Do not write pytest tests for these changes — the verification is the manual scenarios in Task 4.
- Keep the **caveman ultra** style of the existing skill prose: drop articles, use fragments, arrows, abbreviations. Code blocks and inline `code` stay byte-exact.
- The `wiki.yaml::session_ingest.section_map` field already exists in the schema — you do not need to add it to wiki config code or wiki-init wizard. Just consume it in the subagent prompt.
- If during verification (Task 4) you find a gate criterion that's clearly wrong (e.g. real sessions get skipped), STOP and surface it before pushing. Do not silently tweak the threshold without spec amendment.
- If pre-commit hook auto-fixes (e.g. README badges) cause a commit-amend loop, use the "stage the auto-fix and re-commit" pattern shown in Task 5 Step 4 — never `--amend`.

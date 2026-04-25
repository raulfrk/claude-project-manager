# Wiki Tier-2 Lint Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the Python `check_section_map_drift` runtime + tests; align `section_map_drift` with the other 4 tier-2 checks (already prose-only); document the architectural principle in [[wiki-plugin]] wiki page + lint SKILL.md.

**Architecture:** Surgical deletion of ~110 Python lines + 1 test file (243 lines) + 1 prose comment line. Two doc additions (wiki page principle, lint SKILL Architecture section). Wiki plugin version bump per project convention.

**Tech Stack:** Python 3.13 (tested but no test changes — just deletion); Markdown for skill + wiki edits.

**Spec:** `docs/superpowers/specs/2026-04-25-wiki-tier2-lint-architecture-design.md`

---

## File Structure

| File | Action | Modified by task |
|---|---|---|
| `plugins/wiki/server/server/tools/lint.py` | Delete lines 343-447 (SYNC CONTRACT comment + `_TEMPLATE_*_RE` constants + `_extract_save_skill_h2s` helper + `check_section_map_drift` fn) | Task 2 |
| `plugins/wiki/server/tests/test_lint_tier2_drift.py` | Delete entire file (243 lines) | Task 2 |
| `plugins/wiki/skills/lint/references/tier2-section-map-drift.md` | Remove SYNC CONTRACT line 7 | Task 2 |
| `plugins/wiki/skills/lint/SKILL.md` | Add Architecture section after frontmatter | Task 3 |
| `~/.claude/wiki/pages/entities/wiki-plugin.md` | Add tier-2 architectural principle section after "Persistence/synthesis boundary" | Task 3 |
| `plugins/wiki/.claude-plugin/plugin.json` | Bump version `0.1.2 → 0.1.3` | Task 4 |
| `.claude-plugin/marketplace.json` | Bump wiki plugin version `0.1.2 → 0.1.3` | Task 4 |

---

## Pre-Task Setup

- [ ] **Step 1: Create worktree from dev**

```
mcp__plugin_worktree_worktree__wt_create(
  repo_label="cpm",
  branch="feat/737-wiki-tier2-lint-architecture",
  new_branch=true
)
```

- [ ] **Step 2: Sync worktree to remote per managed rule 13**

```bash
cd <worktree_path>
git fetch origin
local_ahead=$(git rev-list origin/dev..dev)
if [ -z "$local_ahead" ]; then
  git reset --hard origin/dev
else
  git reset --hard dev
fi
git status
```

Expected: clean working tree.

- [ ] **Step 3: Sync uv groups for wiki server**

```bash
cd <worktree_path>/plugins/wiki/server
uv sync --all-groups
```

---

## Task 1: Baseline verification (pre-deletion)

**Files**: read-only.

- [ ] **Step 1: Run wiki plugin's full test suite to confirm green baseline**

```bash
cd <worktree_path>/plugins/wiki/server
uv run pytest --no-cov 2>&1 | tail -5
```

Expected: all tests pass (likely 200+ tests). Note the count — Task 5 will verify the count drops by exactly the number of tests in `test_lint_tier2_drift.py` (~28 tests per the file's structure).

```bash
cd <worktree_path>/plugins/wiki/server
grep -c '^    def test_\|^def test_' tests/test_lint_tier2_drift.py
```

Note this number — that's the expected drop in test count post-deletion.

- [ ] **Step 2: Confirm `/wiki:lint --tier=2` runs cleanly against current wiki**

(Optional manual smoke; skip if no scratch wiki available. Implementation continues either way.)

---

## Task 2: Delete Python `check_section_map_drift` + tests + SYNC CONTRACT prose

**Files**:
- Modify: `plugins/wiki/server/server/tools/lint.py` (delete lines 343-447)
- Delete: `plugins/wiki/server/tests/test_lint_tier2_drift.py` (entire file)
- Modify: `plugins/wiki/skills/lint/references/tier2-section-map-drift.md` (remove SYNC CONTRACT line 7)

- [ ] **Step 1: Verify exact line range to delete in `lint.py`**

```bash
cd <worktree_path>
sed -n '340,450p' plugins/wiki/server/server/tools/lint.py
```

Confirm:
- Line 343-355 is the SYNC CONTRACT comment block (starts `# SYNC CONTRACT (todos 730 + Batch A validation):`).
- Line 356-358 is the `_TEMPLATE_*_RE` regex constants.
- Line 361-393 is `_extract_save_skill_h2s` helper.
- Line 396-447 is `check_section_map_drift` fn.
- Line 449+ should be `def wiki_lint_duplicates(...)` (the next unrelated function — stays).

If line numbers shift slightly (e.g. due to whitespace changes), find by content not by absolute line number.

- [ ] **Step 2: Delete the block in `lint.py`**

Use Edit tool. Replace this block (starting at line 343):

```python
# SYNC CONTRACT (todos 730 + Batch A validation):
# The functions below are the canonical reference impl of the section-map drift
# algorithm. The PRODUCTION drift check at /wiki:lint runtime is performed by
# the LLM subagent dispatched per `plugins/wiki/skills/lint/references/tier2-section-map-drift.md`,
# which re-implements the same algorithm in prose. Tests pin THIS impl; nothing
# pins the prose. If you change the algorithm here (anchor regex, sentinel
# semantics, output kinds), you MUST also update the prose in the reference doc
# above — and vice versa. Two sources of truth = drift over time.
#
# Why we keep both: the Python is testable + machine-checkable; the prose is
# what the runtime LLM actually executes. Promoting one to the other is a
# larger refactor (todo 736 follow-up — investigate parallel-orchestration
# quality recipe).
_TEMPLATE_START_RE = re.compile(r"<!--\s*session-template-start\s*-->")
_TEMPLATE_END_RE = re.compile(r"<!--\s*session-template-end\s*-->")
_TEMPLATE_H2_RE = re.compile(r"^## (.+)$")


def _extract_save_skill_h2s(skill_text: str) -> list[str] | None:
    """Extract H2 headings from /proj:save SKILL.md step-7 session template.

    Anchors on HTML comment markers <!-- session-template-start --> and
    <!-- session-template-end --> wrapping the fenced template block.
    Lines inside the block may be indented (e.g. 3 spaces) — each line is stripped
    before matching so both indented + flush formats are supported.

    Returns:
        None  — anchor or fence not found (parse failure / malformed SKILL)
        []    — anchor + fence found but template contains zero H2s (legit-empty)
        [...]  — list of whitespace-trimmed H2 heading names
    """
    start_match = _TEMPLATE_START_RE.search(skill_text)
    if not start_match:
        return None
    after_start = skill_text[start_match.end() :]
    # Find opening ``` fence after the start marker
    open_fence = after_start.find("```")
    if open_fence == -1:
        return None
    block_start = open_fence + 3
    # Find closing ``` after the opening fence
    close_fence = after_start.find("```", block_start)
    if close_fence == -1:
        return None
    block = after_start[block_start:close_fence]
    headings: list[str] = []
    for line in block.splitlines():
        m = _TEMPLATE_H2_RE.match(line.strip())
        if m:
            headings.append(m.group(1).strip())
    return headings


def check_section_map_drift(
    skill_path: Path | None,
    section_map: dict[str, str],
) -> list[dict[str, str]]:
    """Detect drift between wiki.yaml section_map keys and /proj:save template H2s.
```

…through the end of `check_section_map_drift` (find the closing of its `return warnings` block, then a blank line before `def wiki_lint_duplicates(...)`).

Replace with: nothing (i.e., delete the whole block, leaving a single blank line between the preceding `return json.dumps({"violations": violations})` and the next `def wiki_lint_duplicates(` definition).

Use Edit tool's `old_string` matching the full block + `new_string` of empty (or a single blank line between adjacent functions). If the block is too long for a single Edit, split into 2-3 sequential Edits (delete from end of file backwards to avoid line-number drift).

- [ ] **Step 3: Verify `re` import is still used (don't delete it)**

```bash
cd <worktree_path>
grep -c 're\.' plugins/wiki/server/server/tools/lint.py
```

Expected: ≥4 (the deletion removes 4 `re.compile` calls; remaining `re.` references should still exist for OTHER lint code in the file). If 0, then `re` import can be deleted (line 10) — but verify by reading first.

```bash
grep -nE 're\.compile|re\.match|re\.search|re\.findall' plugins/wiki/server/server/tools/lint.py
```

If post-deletion zero matches, also remove the `import re` line (line 10).

- [ ] **Step 4: Delete the test file entirely**

```bash
cd <worktree_path>
git rm plugins/wiki/server/tests/test_lint_tier2_drift.py
```

(Use `git rm` to mark the deletion in the index.)

- [ ] **Step 5: Remove SYNC CONTRACT line 7 from `tier2-section-map-drift.md`**

```bash
cd <worktree_path>
head -10 plugins/wiki/skills/lint/references/tier2-section-map-drift.md
```

Identify line 7 (the `> **SYNC CONTRACT**: ...` blockquote). Use Edit tool to remove this line (and any blank line above/below it that becomes redundant — keep the file's vertical rhythm consistent).

The line to remove (exact text):

```
> **SYNC CONTRACT**: This prose is the runtime impl. `plugins/wiki/server/server/tools/lint.py::check_section_map_drift` is a parallel reference impl pinned by tests. If you change the algorithm here (anchor markers, sentinel semantics, output kinds), update lint.py too — and vice versa. See todo 736 for plan to consolidate.
```

Verify by reading post-edit:

```bash
head -10 plugins/wiki/skills/lint/references/tier2-section-map-drift.md
```

The remaining 9 lines should describe the prose impl algorithm without the SYNC CONTRACT blockquote.

- [ ] **Step 6: Run wiki tests to confirm nothing broke (the test count drops by ~28; everything else still passes)**

```bash
cd <worktree_path>/plugins/wiki/server
uv run pytest --no-cov 2>&1 | tail -5
```

Expected: tests pass. Test count = baseline - ~28 (the deleted tier-2 drift tests). Verify the count drop matches Task 1 Step 1's expectation.

- [ ] **Step 7: Verify no dangling references**

```bash
cd <worktree_path>
grep -rn 'check_section_map_drift\|_extract_save_skill_h2s\|_TEMPLATE_START_RE\|_TEMPLATE_END_RE\|_TEMPLATE_H2_RE' plugins/wiki 2>/dev/null
```

Expected: 0 matches. If any reference remains, delete it.

- [ ] **Step 8: Commit deletion**

```bash
cd <worktree_path>
git add plugins/wiki/server/server/tools/lint.py plugins/wiki/skills/lint/references/tier2-section-map-drift.md
git commit -m "refactor(wiki/737): delete Python check_section_map_drift dual-impl

Removes the Python runtime + tests + SYNC CONTRACT prose. Aligns
section_map_drift with the other 4 tier-2 checks (already prose-only).
Wiki plugin's persistence/synthesis boundary now consistent: MCP layer
= deterministic data only; all tier-2 synthesis lives in skills/lint/
references/tier2-*.md prose subagents."
```

(Note: `git rm` on the test file is staged automatically; the explicit `git add` of the modified files completes the staging.)

---

## Task 3: Document the architectural principle (wiki page + SKILL.md)

**Files**:
- Modify: `plugins/wiki/skills/lint/SKILL.md` (add Architecture section after frontmatter)
- Modify: `~/.claude/wiki/pages/entities/wiki-plugin.md` (add tier-2 principle section)

- [ ] **Step 1: Add Architecture section to `lint/SKILL.md`**

The skill currently has caveman header + "Run Tier-1 lint + interactive fix flow." then `## Execution` at line 12. Insert the Architecture section between the caveman header and `## Execution`.

Locate insertion point:

```bash
cd <worktree_path>
sed -n '8,14p' plugins/wiki/skills/lint/SKILL.md
```

Use Edit tool to insert (after line 10's "Run Tier-1 lint + interactive fix flow." and before `## Execution`):

```
## Architecture (tier-1 vs tier-2)

Tier-1 lint checks (orphans, broken-links, broken-section-refs, category-violations, stale, schema, duplicates) → Python-driven, registered as MCP tools (`wiki_lint_*`), tested. Tier-2 checks (contradictions, deprecation, missing-cross-refs, category-clusters, section-map-drift) → prose-only — each lives at `references/tier2-<check-name>.md` as an LLM subagent template. No Python helpers for tier-2; no dual-impl. See [[wiki-plugin]] for the architectural principle (decided 2026-04-25 per todo 737).

```

(Caveman ultra style — fragments, arrows, dropped articles. Verify it matches sibling sections.)

- [ ] **Step 2: Add tier-2 architectural principle section to wiki entity page**

Read the wiki entity page first:

```
mcp__plugin_wiki_wiki__wiki_page_get(slug="wiki-plugin", category="entities")
```

Locate the `## Persistence/synthesis boundary` section (around line 34) + the next `## MCP tools` section (around line 40). Insert a new section between them.

New section content (to insert):

```markdown
## Tier-2 lint architecture (decided 2026-04-25 per todo 737)

Tier-2 lint checks MUST be prose-only (LLM synthesis in skills). Python helpers in MCP layer reserved for tier-1 deterministic data/persistence operations only. Each tier-2 check lives as a single prose subagent template at `plugins/wiki/skills/lint/references/tier2-<check-name>.md` — no parallel Python implementation, no SYNC CONTRACT comment, no test pinning the algorithm.

Rationale: dual-impl drift is a category of bug that disappears if there's only one impl. The prose subagent IS the runtime; bugs surface on next `/wiki:lint --tier=2` invocation.

Tier-1 lint (orphans, broken-links, broken-section-refs, category-violations, stale, schema, duplicates) remains Python-driven — these are deterministic data/persistence ops aligned with the MCP boundary.
```

Compose the full updated body (existing content + new section inserted) and write back:

```
mcp__plugin_wiki_wiki__wiki_page_write(
  slug="wiki-plugin",
  category="entities",
  frontmatter=<existing frontmatter, unchanged>,
  body=<existing body w/ new section inserted between Persistence/synthesis boundary and MCP tools>,
  mode="update"
)
```

Preserve frontmatter exactly. Update `last_ingested` to current timestamp + add a sources entry referencing this todo.

- [ ] **Step 3: Verify SKILL.md still parses + lint runs**

```bash
cd <worktree_path>
python3 -c "
import yaml
with open('plugins/wiki/skills/lint/SKILL.md') as f:
    fm = yaml.safe_load(f.read().split('---', 2)[1])
print('skill name:', fm['name'])
print('allowed-tools count:', len(fm.get('allowed-tools', '').split(',')))
"
```

Expected: skill name = `lint`; allowed-tools count unchanged.

- [ ] **Step 4: Verify wiki page lint clean**

```
mcp__plugin_wiki_wiki__wiki_lint_schema(category="entities")
mcp__plugin_wiki_wiki__wiki_lint_broken_links(category="entities")
```

Expected: no errors.

- [ ] **Step 5: Commit SKILL.md change**

```bash
cd <worktree_path>
git add plugins/wiki/skills/lint/SKILL.md
git commit -m "docs(wiki/737): document tier-1 vs tier-2 architecture in lint SKILL"
```

(Wiki page changes don't appear in `git status` — separately note via notes_append in Task 5.)

---

## Task 4: Bump wiki plugin version

**Files**:
- Modify: `plugins/wiki/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Bump plugin.json version 0.1.2 → 0.1.3**

```bash
cd <worktree_path>
grep -n '"version"' plugins/wiki/.claude-plugin/plugin.json
```

Edit the file to change `"version": "0.1.2"` → `"version": "0.1.3"`.

- [ ] **Step 2: Bump marketplace.json wiki entry to match**

```bash
cd <worktree_path>
grep -n '"name": "wiki"' .claude-plugin/marketplace.json
```

Find the wiki plugin's entry block in marketplace.json. Update its `"version"` field to `"0.1.3"`.

- [ ] **Step 3: Verify both versions match**

```bash
cd <worktree_path>
grep -A 5 '"name": "wiki"' .claude-plugin/marketplace.json | grep version
grep '"version"' plugins/wiki/.claude-plugin/plugin.json
```

Both should show `0.1.3`.

- [ ] **Step 4: Commit version bump**

```bash
cd <worktree_path>
git add plugins/wiki/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(wiki/737): bump wiki plugin 0.1.2 → 0.1.3 (tier-2 architecture refactor)"
```

---

## Task 5: Pre-commit + tests + manual smoke + notes log

- [ ] **Step 1: Run pre-commit on all changes**

```bash
cd <worktree_path>
pre-commit run --all-files 2>&1 | tail -10
```

Expected: all hooks pass. (basedpyright may report new warnings if removed code had type-only references elsewhere — investigate + fix if so.)

- [ ] **Step 2: Run wiki plugin's full test suite**

```bash
cd <worktree_path>/plugins/wiki/server
uv run pytest --no-cov 2>&1 | tail -10
```

Expected: tests pass; total count = baseline - ~28 (the deleted tier-2 drift tests).

- [ ] **Step 3: Verify no dangling refs across the whole repo**

```bash
cd <worktree_path>
grep -rn 'check_section_map_drift\|_extract_save_skill_h2s' \
  --include='*.py' --include='*.md' \
  -l 2>/dev/null
```

Expected: 0 matches OUTSIDE the spec/plan/notes/wiki-page-already-updated set. If any source code or active doc still references the deleted symbols, delete those references too.

- [ ] **Step 4: Manual smoke (optional but recommended)**

Invoke `/wiki:lint --tier=2` against the user's actual wiki:

```
mcp__plugin_wiki_wiki__wiki_search_index_refresh()
# Then invoke the lint skill manually in the conversation OR:
# Locate a wiki + cpm-config pair where /proj:save SKILL.md has known H2 drift
# vs wiki.yaml session_map; verify the prose subagent reports the drift
# correctly (no Python helper involved).
```

This validates the prose subagent still works as the sole runtime path. If the prose has unforeseen issues post-deletion (e.g. removed something the prose depended on), they surface here.

If smoke is impractical (no test wiki available), skip — the architectural change is structural; the prose impl was already the runtime pre-deletion.

- [ ] **Step 5: Notes log entry per managed rule 20**

```
mcp__plugin_proj_proj__notes_append(
  op="checkpoint",
  heading="737 wiki tier-2 lint architecture shipped",
  text="Deleted Python check_section_map_drift + tests + SYNC CONTRACT. Aligned section_map_drift with the other 4 tier-2 checks (prose-only). Documented the principle in [[wiki-plugin]] page + lint SKILL.md. Wiki plugin 0.1.2 → 0.1.3."
)
```

---

## Task 6: Branch finishing

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Per managed rule 11.

- [ ] **Step 2: Per project memory `feedback_624_merge_convention` — FF-merge to dev (no PR)**

```bash
cd <worktree_path>
git fetch origin
git rebase origin/dev
cd /home/raul/projects/claude-project-manager
git checkout dev
git merge --ff-only feat/737-wiki-tier2-lint-architecture
git push origin dev
```

- [ ] **Step 3: Watch CI**

```bash
gh run list --branch dev --limit 1
gh run watch <run-id> --exit-status
```

Expected: green.

- [ ] **Step 4: Cleanup worktree + branch**

```
mcp__plugin_worktree_worktree__wt_remove(path="<worktree_path>")
```

```bash
git branch -d feat/737-wiki-tier2-lint-architecture
```

- [ ] **Step 5: Mark todo 737 done**

```
mcp__plugin_proj_proj__todo_complete(todo_id="737")
```

---

## Self-Review

**Spec coverage check** — every spec section maps to a task:

| Spec section | Task |
|---|---|
| Problem statement (dual-impl smell) | Task 2 (deletes the Python half) |
| Architectural principle to codify | Task 3 (wiki page + SKILL.md) |
| Code deletions in `lint.py` | Task 2 |
| Test deletions | Task 2 |
| Reference doc edit (SYNC CONTRACT line) | Task 2 |
| Wiki + skill updates (architectural principle) | Task 3 |
| Test coverage tradeoff (acknowledged) | Task 1 (baseline) + Task 5 (post-deletion verify) |
| Validation (lint runs, full suite, no dangling refs, manual smoke) | Task 5 |
| Risks (no automated regression for prose) | Documented in spec; mitigation via principle codification (Task 3) |
| Version bump | Task 4 |
| Branch finishing | Task 6 |

Every spec section is mapped.

**Placeholder scan** — no `TBD`, `Add appropriate`, `Similar to Task`, `Write tests for the above`. Each step has exact commands + exact prose to insert.

**Type/name consistency** — symbol names: `check_section_map_drift`, `_extract_save_skill_h2s`, `_TEMPLATE_*_RE` consistent throughout; branch name `feat/737-wiki-tier2-lint-architecture`; version bump `0.1.2 → 0.1.3` consistent.

---

## Notes for the implementer

- **Caveman ultra**: Architecture section in lint/SKILL.md uses caveman style (drop articles, fragments, arrows). Compare against existing `## Execution` and `## Error Handling` sections for tone.
- **Wiki page edits don't show in git status**: `~/.claude/wiki/` lives outside the repo. Verify via `mcp__plugin_wiki_wiki__wiki_page_get` post-edit; note via `notes_append` for traceability.
- **No revdiff for this session**: per session-scoped user preference; user reads files directly for spec/plan review.
- **Baseline test count + post-deletion test count**: capture both. The expected drop is the count of `def test_` patterns in `test_lint_tier2_drift.py`. Document the actual delta in the Task 5 commit message or notes log.
- **`re` import survives** since other lint code uses it. Don't accidentally delete `import re` at line 10.
- **Test file deletion via `git rm`**, not just `rm`: ensures the deletion is staged for commit.

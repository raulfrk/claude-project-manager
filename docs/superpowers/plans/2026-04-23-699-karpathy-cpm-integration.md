# Karpathy CPM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply Karpathy's late-2025 agentic-engineering principles (via forrestchang/andrej-karpathy-skills 4-principle distillation) to cpm's managed CLAUDE.md block + add small infrastructure (notes_append heading convention + `/proj:checkpoint` skill) to operationalize them.

**Architecture:** 4 sequential phases, each its own worktree + PR. Phase 1 = managed-block additions (markdown only). Phase 2 = `notes_append` heading param + `/proj:save` adoption. Phase 3 = new `/proj:checkpoint` skill. Phase 4 = create audit todo (30-day delayed review).

**Tech Stack:** Python (FastMCP server), pytest, markdown, Claude Code skill format, git worktrees.

**Spec:** `docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md`

**Todo:** 699

---

## File Structure

| Phase | File | Action | Responsibility |
|---|---|---|---|
| 1 | `plugins/_shared/claudemd/managed_section.md` | modify | add 9 new rules + 3 cross-refs |
| 1 | `README.md` (top-level) | modify | add Karpathy alignment section |
| 2 | `plugins/proj/server/server/lib/storage.py` | modify | extend `append_note` w/ `heading` + `op` params |
| 2 | `plugins/proj/server/server/tools/context.py` | modify | extend `notes_append` MCP tool to forward params |
| 2 | `plugins/proj/server/tests/test_storage.py` | modify | add `append_note` heading + op tests |
| 2 | `plugins/proj/server/tests/test_context.py` | modify | add `notes_append` heading + op tests |
| 2 | `plugins/proj/skills/save/SKILL.md` | modify | adopt convention in step 10 + add reminder step |
| 3 | `plugins/proj/skills/checkpoint/SKILL.md` | create | new `/proj:checkpoint` skill |
| 3 | `plugins/proj/skills/checkpoint/manual-checklist.md` | create | E2E manual verification steps |
| 3 | `plugins/proj/README.md` | modify | add `/proj:checkpoint` to skill table + category list |
| 3 | `README.md` (top-level) | modify | add `/proj:checkpoint` to marketplace skill reference |
| 4 | (no file change) | — | call `mcp__plugin_proj_proj__todo_add` to create audit todo |

---

# Phase 1 — Managed-block update (markdown only)

**Worktree branch**: `feat/699-karpathy-phase1-managed-block`

### Task 1: Set up Phase 1 worktree

**Files:**
- Create worktree at: `~/worktrees/cpm/feat-699-karpathy-phase1`

- [ ] **Step 1: Create the worktree**

```python
# Via worktree MCP tool:
mcp__plugin_worktree_worktree__wt_create(
    repo_label="cpm",
    branch="feat/699-karpathy-phase1-managed-block",
    base="dev",
    path="~/worktrees/cpm/feat-699-karpathy-phase1"
)
```

- [ ] **Step 2: Sync to remote per managed-block rule**

Run inside the new worktree path:

```bash
cd ~/worktrees/cpm/feat-699-karpathy-phase1
git fetch origin
git rev-list origin/dev..dev  # if empty, local not ahead
# If output empty:
git reset --hard origin/dev
# If output non-empty (local ahead):
git reset --hard dev
```

- [ ] **Step 3: Verify clean working tree**

```bash
git status --short
```

Expected: empty output (clean tree on `feat/699-karpathy-phase1-managed-block` branch).

### Task 2: Read current managed_section.md to confirm structure

**Files:**
- Read: `plugins/_shared/claudemd/managed_section.md`

- [ ] **Step 1: Read the file**

```python
# Use Read tool on the absolute path:
# /home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md
```

Expected structure:
- Line 1: `<!-- claude-project-manager:start -->`
- Line 2: `## Claude Project Manager Rules`
- Line 4: `IMPORTANT: These rules take priority over all other instructions.`
- Lines 6-20: 14 numbered rules (one per line, hyphen-bullet, bold rule name)
- Line 21: `<!-- claude-project-manager:end -->`

If the file deviates from this structure, **stop** and re-evaluate the plan with the user — the rules below assume this layout.

### Task 3: Add forrestchang 4-principle backbone (rules 16-19)

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md` (insert after current rule on line 20)

- [ ] **Step 1: Append rules 16-19 before the end marker**

Use Edit tool to insert these 4 rules between the last existing rule (line 20, the wiki+proj_search rule) and the `<!-- claude-project-manager:end -->` marker on line 21.

The new content (caveman-ultra phrasing, attributed inline):

```markdown
- **Think before coding** — Don't assume; don't hide confusion; surface tradeoffs. Before impl: state assumptions explicit (uncertain → ask); multi-interpretations → present, don't pick silently; simpler approach exists → push back; unclear → stop + ask. See rule 4 for batching the asks. *(Source: Karpathy late-2025 LLM-coding-pitfalls tweet, distilled by forrestchang/andrej-karpathy-skills MIT.)*
- **Simplicity first** — Min code that solves problem. No features beyond ask. No abstractions for single-use code. No "flexibility"/"configurability" not requested. No err handling for impossible scenarios. 200 lines could be 50 → rewrite. Senior-eng overcomplicated test: yes → simplify. *(Source: same.)*
- **Surgical changes** — Touch only what task requires. No drive-by refactor. Match existing style. Notice unrelated dead code → mention, don't delete. Changes that orphan imports/vars/fns → remove only orphans you created. Test: every changed line traces directly to user request. See also rule 5 for patch-style API choice. *(Source: same.)*
- **Goal-driven execution** — Define success criteria. Loop until verified. Transform tasks → verifiable goals: "Add validation" → "Tests for invalid inputs, then make pass"; "Fix bug" → "Test that reproduces, then make pass"; "Refactor X" → "Tests pass before + after". Multi-step: `[step] → verify: [check]`. Strong criteria → loop independently; weak criteria → constant clarification. See also rule 14 for mid-task verification. *(Source: same.)*
```

Edit operation:

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md",
    old_string="- **Wiki + proj_search are primary knowledge sources** — When you need project or domain info, first query `/wiki:query` (skip if wiki plugin disabled), then `mcp__plugin_proj_proj__proj_search_knowledge`, then fall back to `Explore` / `general-purpose` subagents for code-level search. These stores are authoritative; training priors and guesswork are not. Use before making claims, design decisions, or asking the user for information that might already be captured.\n<!-- claude-project-manager:end -->",
    new_string="- **Wiki + proj_search are primary knowledge sources** — When you need project or domain info, first query `/wiki:query` (skip if wiki plugin disabled), then `mcp__plugin_proj_proj__proj_search_knowledge`, then fall back to `Explore` / `general-purpose` subagents for code-level search. These stores are authoritative; training priors and guesswork are not. Use before making claims, design decisions, or asking the user for information that might already be captured.\n- **Think before coding** — Don't assume; don't hide confusion; surface tradeoffs. Before impl: state assumptions explicit (uncertain → ask); multi-interpretations → present, don't pick silently; simpler approach exists → push back; unclear → stop + ask. See rule 4 for batching the asks. *(Source: Karpathy late-2025 LLM-coding-pitfalls tweet, distilled by forrestchang/andrej-karpathy-skills MIT.)*\n- **Simplicity first** — Min code that solves problem. No features beyond ask. No abstractions for single-use code. No \"flexibility\"/\"configurability\" not requested. No err handling for impossible scenarios. 200 lines could be 50 → rewrite. Senior-eng overcomplicated test: yes → simplify. *(Source: same.)*\n- **Surgical changes** — Touch only what task requires. No drive-by refactor. Match existing style. Notice unrelated dead code → mention, don't delete. Changes that orphan imports/vars/fns → remove only orphans you created. Test: every changed line traces directly to user request. See also rule 5 for patch-style API choice. *(Source: same.)*\n- **Goal-driven execution** — Define success criteria. Loop until verified. Transform tasks → verifiable goals: \"Add validation\" → \"Tests for invalid inputs, then make pass\"; \"Fix bug\" → \"Test that reproduces, then make pass\"; \"Refactor X\" → \"Tests pass before + after\". Multi-step: `[step] → verify: [check]`. Strong criteria → loop independently; weak criteria → constant clarification. See also rule 14 for mid-task verification. *(Source: same.)*\n<!-- claude-project-manager:end -->",
)
```

- [ ] **Step 2: Verify the file now contains 18 hyphen-bulleted rules between markers**

```bash
grep -c "^- \*\*" plugins/_shared/claudemd/managed_section.md
```

Expected: `18`

### Task 4: Add cpm-layer additions (rules 20-24)

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md`

- [ ] **Step 1: Append rules 20-24 before the end marker**

The new content:

```markdown
- **Append-only log convention** — Record events/findings/decisions to project notes via `notes_append` w/ heading param. Heading prefix format: `## [YYYY-MM-DD HH:MM] {op} | {title}`. `op` ∈ {note, decision, incident, experiment, fix, refactor, checkpoint, save}. `grep "^## \[" notes.md | tail -10` works universally. Reserve `proj_decision_log` for structured A/B picks needing tag-based filtering. See also rule 3 for actionable findings → todos. *(Source: Karpathy nanochat dev/LOG.md + llm-wiki gist.)*
- **Reset over recover** — Agent skips cases / fabricates completion / degrades reasoning during multi-step work → prefer `wt_remove` + new `wt_create` w/ tightened scope over patching trajectory. Use `/proj:checkpoint` for explicit invocation. See also rules 6 + 13 for worktree mechanics. *(Source: Howells swift-port writeup + Ronacher abort-before-compact.)*
- **Reproduce before fix** — Bug-fix tasks must produce reproducible failing test before patching code. No exceptions for "obvious" bugs. Test commit first, fix commit second. *(Source: Howells "told the agent not to fix any fuzzer crashes … but to investigate and create a test file which reproduces the crash".)*
- **Principled across config scales** — Changes to plugins / shared infra reject point fixes that only help one config / profile / plugin. Must work across plugin matrix. Single-row fix → expand fix or document why asymmetry intentional. *(Source: Karpathy nanochat — "any candidate changes to the repo have to be principled enough that they work for all settings of depth".)*
- **Mid-execution checkpoint rhythm** — During multi-step impl, suggest `/proj:checkpoint` when TaskCreate-tracked phase completes OR user pauses to evaluate. Asks: continue / reset+restart w/ tightened scope / tighten scope only. Don't require Claude to count tasks — anchor on phase-boundary signals or explicit user pause. *(Source: derived from Howells reset-over-recover + Karpathy autonomy-slider per task.)*
```

Edit operation: same pattern as Task 3 — find the rule 19 closing line + end marker, replace with rule 19 + new rules 20-24 + end marker.

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md",
    old_string="- **Goal-driven execution** — Define success criteria. Loop until verified. Transform tasks → verifiable goals: \"Add validation\" → \"Tests for invalid inputs, then make pass\"; \"Fix bug\" → \"Test that reproduces, then make pass\"; \"Refactor X\" → \"Tests pass before + after\". Multi-step: `[step] → verify: [check]`. Strong criteria → loop independently; weak criteria → constant clarification. See also rule 14 for mid-task verification. *(Source: same.)*\n<!-- claude-project-manager:end -->",
    new_string="- **Goal-driven execution** — Define success criteria. Loop until verified. Transform tasks → verifiable goals: \"Add validation\" → \"Tests for invalid inputs, then make pass\"; \"Fix bug\" → \"Test that reproduces, then make pass\"; \"Refactor X\" → \"Tests pass before + after\". Multi-step: `[step] → verify: [check]`. Strong criteria → loop independently; weak criteria → constant clarification. See also rule 14 for mid-task verification. *(Source: same.)*\n- **Append-only log convention** — Record events/findings/decisions to project notes via `notes_append` w/ heading param. Heading prefix format: `## [YYYY-MM-DD HH:MM] {op} | {title}`. `op` ∈ {note, decision, incident, experiment, fix, refactor, checkpoint, save}. `grep \"^## \\[\" notes.md | tail -10` works universally. Reserve `proj_decision_log` for structured A/B picks needing tag-based filtering. See also rule 3 for actionable findings → todos. *(Source: Karpathy nanochat dev/LOG.md + llm-wiki gist.)*\n- **Reset over recover** — Agent skips cases / fabricates completion / degrades reasoning during multi-step work → prefer `wt_remove` + new `wt_create` w/ tightened scope over patching trajectory. Use `/proj:checkpoint` for explicit invocation. See also rules 6 + 13 for worktree mechanics. *(Source: Howells swift-port writeup + Ronacher abort-before-compact.)*\n- **Reproduce before fix** — Bug-fix tasks must produce reproducible failing test before patching code. No exceptions for \"obvious\" bugs. Test commit first, fix commit second. *(Source: Howells \"told the agent not to fix any fuzzer crashes … but to investigate and create a test file which reproduces the crash\".)*\n- **Principled across config scales** — Changes to plugins / shared infra reject point fixes that only help one config / profile / plugin. Must work across plugin matrix. Single-row fix → expand fix or document why asymmetry intentional. *(Source: Karpathy nanochat — \"any candidate changes to the repo have to be principled enough that they work for all settings of depth\".)*\n- **Mid-execution checkpoint rhythm** — During multi-step impl, suggest `/proj:checkpoint` when TaskCreate-tracked phase completes OR user pauses to evaluate. Asks: continue / reset+restart w/ tightened scope / tighten scope only. Don't require Claude to count tasks — anchor on phase-boundary signals or explicit user pause. *(Source: derived from Howells reset-over-recover + Karpathy autonomy-slider per task.)*\n<!-- claude-project-manager:end -->",
)
```

- [ ] **Step 2: Verify the file now contains 23 hyphen-bulleted rules**

```bash
grep -c "^- \*\*" plugins/_shared/claudemd/managed_section.md
```

Expected: `23`

### Task 5: Add cross-references to existing rules 3, 5, 14

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md`

These edits append a "See also rule N" suffix to existing rules so the cross-references are bidirectional.

- [ ] **Step 1: Cross-ref on existing rule 3 (Auto-capture issues as todos)**

Find the rule 3 text and append a cross-reference at the end of the bullet (before the closing newline / next bullet).

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md",
    old_string="If the user says to ignore a finding, do not auto-add it.",
    new_string="If the user says to ignore a finding, do not auto-add it. For non-actionable findings or event records (no follow-up action needed), use `notes_append` w/ heading convention (rule 20) instead of creating a todo.",
)
```

- [ ] **Step 2: Cross-ref on existing rule 5 (Patch-style editing)**

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md",
    old_string="This reduces payload size by 95%+ on large notes/requirements.",
    new_string="This reduces payload size by 95%+ on large notes/requirements. See also rule 18 for diff-scope discipline (touch only what's needed).",
)
```

- [ ] **Step 3: Cross-ref on existing rule 14 (Verify before asserting)**

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md",
    old_string="This rule fires mid-task — not only at completion — and complements `superpowers:verification-before-completion` (which runs at the claim-work-done boundary).",
    new_string="This rule fires mid-task — not only at completion — and complements `superpowers:verification-before-completion` (which runs at the claim-work-done boundary). See also rule 19 for pre-task verification framing (define success criteria up front).",
)
```

- [ ] **Step 4: Verify cross-refs landed**

```bash
grep -n "See also rule" plugins/_shared/claudemd/managed_section.md
```

Expected: at least 5 matches (3 from this task: lines for rules 3, 5, 14; plus the 2 already inline in new rules 18 + 19 from Task 3).

### Task 6: Update top-level README.md w/ Karpathy alignment section

**Files:**
- Modify: `README.md` (top-level marketplace README)

- [ ] **Step 1: Read existing README.md to find the right insertion point**

Use Read to find the section that documents the managed CLAUDE.md block (search for "managed" or "CLAUDE.md" in headings). The new section should be a sub-section under the existing managed-block documentation.

If no managed-block doc section exists, add a new top-level section titled `## Karpathy alignment`.

- [ ] **Step 2: Insert the alignment section**

Content to insert (adapt heading level to match the surrounding section):

```markdown
### Karpathy alignment

The managed CLAUDE.md block adopts Andrej Karpathy's late-2025 LLM-coding-pitfalls observations as 4 of its rules (Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution), via the [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) distillation (MIT-licensed).

Original Karpathy tweet: https://x.com/karpathy/status/2015883857489522876

These rules are layered with cpm-specific operationalizations:
- Append-only log convention (chronological project history grep-able via `## [YYYY-MM-DD HH:MM] op | title` headings)
- Reset-over-recover discipline (prefer `wt_remove` + new `wt_create` with tightened scope over patching agent drift)
- Reproduce-before-fix for bug-work
- Mid-execution checkpoint rhythm (`/proj:checkpoint`)
- Principled-across-config-scales constraint

See `~/.claude/CLAUDE.md` for the full block (auto-installed by the cpm installer; refresh via `/proj:claudemd-refresh`).
```

- [ ] **Step 3: Verify README.md is well-formed**

```bash
head -30 README.md  # spot check the top
grep -n "Karpathy alignment" README.md
```

Expected: exactly one `Karpathy alignment` heading.

### Task 7: Verify managed-block via `claudemd_refresh_managed` dry-run

**Files:**
- No file change. Run the MCP tool to confirm the new content parses + writes correctly.

- [ ] **Step 1: Call the refresh tool**

Set up a temp HOME first to avoid clobbering the user's real `~/.claude/CLAUDE.md`:

```bash
TEMP_HOME=$(mktemp -d)
mkdir -p "$TEMP_HOME/.claude"
echo "# Test CLAUDE.md" > "$TEMP_HOME/.claude/CLAUDE.md"
HOME="$TEMP_HOME" python3 -c "
from server.lib.claudemd_helpers import ensure_managed_section  # adjust import per actual location
from pathlib import Path
result = ensure_managed_section(Path('$TEMP_HOME/.claude/CLAUDE.md'))
print(f'modified: {result}')
print(Path('$TEMP_HOME/.claude/CLAUDE.md').read_text()[:500])
"
```

If the import path differs, find the correct one:

```bash
grep -rn "def ensure_managed_section" plugins/_shared/claudemd/ | head -3
```

- [ ] **Step 2: Verify the temp CLAUDE.md contains the new rules**

```bash
grep -c "^- \*\*" "$TEMP_HOME/.claude/CLAUDE.md"
```

Expected: `23` (all rules present).

```bash
grep "Think before coding\|Append-only log convention\|Reset over recover\|Mid-execution checkpoint rhythm" "$TEMP_HOME/.claude/CLAUDE.md"
```

Expected: 4 matching lines.

- [ ] **Step 3: Clean up temp**

```bash
rm -rf "$TEMP_HOME"
```

### Task 8: Run existing claudemd tests + commit Phase 1

**Files:**
- No file change.

- [ ] **Step 1: Run claudemd tests**

```bash
cd /home/raul/projects/claude-project-manager
just test-shared 2>&1 | tail -30
# or, if no recipe exists for shared:
cd plugins/_shared && uv run pytest 2>&1 | tail -30
```

Expected: all tests pass. Existing tests should still pass since the markdown content shape (flat block w/ start/end markers) is unchanged.

- [ ] **Step 2: Stage + commit Phase 1**

```bash
cd ~/worktrees/cpm/feat-699-karpathy-phase1
git add plugins/_shared/claudemd/managed_section.md README.md
git status
git commit -m "$(cat <<'EOF'
feat(claudemd/699): managed-block additions for Karpathy alignment

Add rules 16-24 to the cpm managed CLAUDE.md block:
- Rules 15-18: forrestchang/andrej-karpathy-skills 4-principle backbone
  (Think Before Coding, Simplicity First, Surgical Changes,
  Goal-Driven Execution) verbatim w/ MIT attribution.
- Rules 19-23: cpm-layer additions (append-only log convention,
  reset-over-recover, reproduce-before-fix, principled-across-
  config-scales, mid-execution checkpoint rhythm).
- Cross-references added on existing rules 3, 5, 14.

Phase 1 of the 4-phase Karpathy CPM integration plan
(docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push the branch**

```bash
git push -u origin feat/699-karpathy-phase1-managed-block
```

- [ ] **Step 4: FF-merge to dev (per memory: feedback_624_merge_convention)**

```bash
git checkout dev
git pull origin dev
git merge --ff-only feat/699-karpathy-phase1-managed-block
git push origin dev
```

If FF-merge fails because dev has advanced: rebase the feature branch onto current dev, then retry FF-merge.

- [ ] **Step 5: Watch CI**

```bash
gh run watch
```

Expected: green CI on dev (managed-block change is markdown-only; only existing claudemd tests should be affected).

---

# Phase 2 — `notes_append` heading param + `/proj:save` adoption

**Worktree branch**: `feat/699-karpathy-phase2-notes-append`

### Task 9: Set up Phase 2 worktree

**Files:**
- Create worktree at: `~/worktrees/cpm/feat-699-karpathy-phase2`

- [ ] **Step 1: Create the worktree**

```python
mcp__plugin_worktree_worktree__wt_create(
    repo_label="cpm",
    branch="feat/699-karpathy-phase2-notes-append",
    base="dev",
    path="~/worktrees/cpm/feat-699-karpathy-phase2"
)
```

- [ ] **Step 2: Sync to remote**

```bash
cd ~/worktrees/cpm/feat-699-karpathy-phase2
git fetch origin
git rev-list origin/dev..dev
# If empty:
git reset --hard origin/dev
# If non-empty:
git reset --hard dev
```

### Task 10: Read existing `append_note` + `notes_append` + `/proj:save`

**Files:**
- Read: `plugins/proj/server/server/lib/storage.py:260-280`
- Read: `plugins/proj/server/server/tools/context.py:380-405`
- Read: `plugins/proj/server/tests/test_storage.py:101-110` (existing `test_append_note_creates_file`)
- Read: `plugins/proj/skills/save/SKILL.md`

- [ ] **Step 1: Confirm current `append_note` signature**

Expected at `lib/storage.py:266`:

```python
def append_note(cfg: ProjConfig, project_name: str, text: str) -> None:
    path = notes_path(cfg, project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    today = str(date.today())
    entry = f"\n## {today}\n\n{text.strip()}\n"
    existing = path.read_text() if path.exists() else ""
    _atomic_write_text(path, existing + entry)
```

If the signature differs, **stop** and re-evaluate — the rest of Phase 2 depends on this exact shape.

- [ ] **Step 2: Confirm current `notes_append` MCP tool**

Expected at `tools/context.py:386`:

```python
@app.tool(description="Append a dated note to the active project's NOTES.md.")
def notes_append(text: str, project_name: str | None = None) -> str:
    cfg = require_config()
    name = state.resolve_project(project_name)
    if not name:
        return json.dumps({"status": "error", "error": "No active project."})
    storage.append_note(cfg, name, text)
    first_line = (text.splitlines()[0].strip() if text.strip() else "")[:200]
    return json.dumps({
        "status": "appended",
        "project_name": name,
        "content": text,
        "content_first_line": first_line,
        "message": f"Note appended to {name}/NOTES.md.",
    })
```

### Task 11: TDD — failing test for `storage.append_note(heading, op)` extension

**Files:**
- Modify: `plugins/proj/server/tests/test_storage.py`

- [ ] **Step 1: Add the failing tests**

Insert after the existing `test_append_note_creates_file` function (around line 108):

```python
def test_append_note_with_heading_uses_convention_format(tmp_cfg: ProjConfig) -> None:
    """When heading is provided, prefix uses ## [YYYY-MM-DD HH:MM] {op} | {title} format."""
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    storage.append_note(tmp_cfg, "myapp", "First decision body", heading="initial choice", op="decision")
    notes = storage.read_notes(tmp_cfg, "myapp")
    # Heading line format: ## [YYYY-MM-DD HH:MM] decision | initial choice
    import re
    pattern = r"## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] decision \| initial choice"
    assert re.search(pattern, notes), f"Heading prefix not found in: {notes!r}"
    assert "First decision body" in notes


def test_append_note_with_heading_default_op_is_note(tmp_cfg: ProjConfig) -> None:
    """When op not provided, defaults to 'note'."""
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    storage.append_note(tmp_cfg, "myapp", "Body text", heading="Some title")
    notes = storage.read_notes(tmp_cfg, "myapp")
    import re
    pattern = r"## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] note \| Some title"
    assert re.search(pattern, notes), f"Default op 'note' not used: {notes!r}"


def test_append_note_without_heading_keeps_legacy_format(tmp_cfg: ProjConfig) -> None:
    """Backward compat: when heading is None, use the existing ## YYYY-MM-DD prefix."""
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    storage.append_note(tmp_cfg, "myapp", "legacy body")
    notes = storage.read_notes(tmp_cfg, "myapp")
    today = str(date.today())
    # Legacy format: ## YYYY-MM-DD (no time, no op, no title)
    assert f"## {today}" in notes
    # Verify the new-format prefix is NOT present
    import re
    new_pattern = r"## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]"
    assert not re.search(new_pattern, notes), f"Legacy call should not use new format: {notes!r}"
    assert "legacy body" in notes
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd plugins/proj/server
uv run pytest tests/test_storage.py::test_append_note_with_heading_uses_convention_format tests/test_storage.py::test_append_note_with_heading_default_op_is_note tests/test_storage.py::test_append_note_without_heading_keeps_legacy_format -v 2>&1 | tail -20
```

Expected: 2 FAILS (heading + default-op tests fail because `heading` param doesn't exist yet → `TypeError: append_note() got an unexpected keyword argument 'heading'`). 1 PASS (the legacy backward-compat test passes immediately because the existing behavior already produces `## YYYY-MM-DD` and no new-format prefix).

### Task 12: Implement `heading` + `op` params in `lib/storage.py`

**Files:**
- Modify: `plugins/proj/server/server/lib/storage.py:266-272`

- [ ] **Step 1: Update the `append_note` signature + body**

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/proj/server/server/lib/storage.py",
    old_string="def append_note(cfg: ProjConfig, project_name: str, text: str) -> None:\n    path = notes_path(cfg, project_name)\n    path.parent.mkdir(parents=True, exist_ok=True)\n    today = str(date.today())\n    entry = f\"\\n## {today}\\n\\n{text.strip()}\\n\"\n    existing = path.read_text() if path.exists() else \"\"\n    _atomic_write_text(path, existing + entry)",
    new_string="def append_note(\n    cfg: ProjConfig,\n    project_name: str,\n    text: str,\n    heading: str | None = None,\n    op: str = \"note\",\n) -> None:\n    path = notes_path(cfg, project_name)\n    path.parent.mkdir(parents=True, exist_ok=True)\n    if heading is not None:\n        from datetime import datetime\n        ts = datetime.now().strftime(\"%Y-%m-%d %H:%M\")\n        entry = f\"\\n## [{ts}] {op} | {heading}\\n\\n{text.strip()}\\n\"\n    else:\n        today = str(date.today())\n        entry = f\"\\n## {today}\\n\\n{text.strip()}\\n\"\n    existing = path.read_text() if path.exists() else \"\"\n    _atomic_write_text(path, existing + entry)",
)
```

- [ ] **Step 2: Run the storage tests to verify all 3 new tests now pass**

```bash
cd plugins/proj/server
uv run pytest tests/test_storage.py -v 2>&1 | tail -30
```

Expected: all `test_append_note_*` tests PASS, including:
- `test_append_note_creates_file` (existing, still passes — uses 3-arg form)
- `test_append_note_with_heading_uses_convention_format` (new, now passes)
- `test_append_note_with_heading_default_op_is_note` (new, now passes)
- `test_append_note_without_heading_keeps_legacy_format` (new, still passes)

### Task 13: TDD — failing test for `notes_append` MCP tool extension

**Files:**
- Modify: `plugins/proj/server/tests/test_context.py`

- [ ] **Step 1: Add failing test for the MCP tool**

Append at the end of `test_context.py` (after the last test function):

```python
def test_notes_append_with_heading_passes_to_storage(tmp_cfg, monkeypatch):
    """notes_append MCP tool forwards heading + op to storage.append_note."""
    captured = {}

    def fake_append_note(cfg, name, text, heading=None, op="note"):
        captured["text"] = text
        captured["heading"] = heading
        captured["op"] = op

    monkeypatch.setattr(storage, "append_note", fake_append_note)

    # Set up active project (re-use existing project setup pattern from this file)
    name = "myapp"
    _setup_project_with_todos(tmp_cfg, name, Path(tmp_cfg.tracking_dir).parent, todos=[])

    result = call_tool("notes_append", text="body", heading="Some title", op="decision")
    parsed = json.loads(result)
    assert parsed["status"] == "appended"
    assert captured["heading"] == "Some title"
    assert captured["op"] == "decision"
    assert captured["text"] == "body"


def test_notes_append_without_heading_passes_none(tmp_cfg, monkeypatch):
    """notes_append MCP tool with no heading param forwards heading=None."""
    captured = {}

    def fake_append_note(cfg, name, text, heading=None, op="note"):
        captured["heading"] = heading
        captured["op"] = op

    monkeypatch.setattr(storage, "append_note", fake_append_note)
    name = "myapp"
    _setup_project_with_todos(tmp_cfg, name, Path(tmp_cfg.tracking_dir).parent, todos=[])

    result = call_tool("notes_append", text="legacy")
    parsed = json.loads(result)
    assert parsed["status"] == "appended"
    assert captured["heading"] is None
    assert captured["op"] == "note"  # default


def test_notes_append_content_first_line_is_heading_when_provided(tmp_cfg):
    """When heading is provided, content_first_line returns the composed heading line
    (sans ## prefix), so the default-hooks router can use it as a log-entry title.
    Implementation choice (per spec): tool layer composes the first_line from heading + op + ts.
    """
    name = "myapp"
    _setup_project_with_todos(tmp_cfg, name, Path(tmp_cfg.tracking_dir).parent, todos=[])

    result = call_tool("notes_append", text="multi-line\nbody\ntext", heading="My Title", op="note")
    parsed = json.loads(result)
    import re
    assert re.match(
        r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] note \| My Title",
        parsed["content_first_line"],
    ), f"content_first_line should be the composed heading sans '## ' prefix: {parsed['content_first_line']!r}"
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd plugins/proj/server
uv run pytest tests/test_context.py::test_notes_append_with_heading_passes_to_storage tests/test_context.py::test_notes_append_without_heading_passes_none tests/test_context.py::test_notes_append_content_first_line_is_heading_when_provided -v 2>&1 | tail -20
```

Expected: at least one FAIL (the heading-passes test fails because the tool doesn't accept `heading` kwarg yet).

### Task 14: Implement `heading` + `op` params in `tools/context.py:notes_append`

**Files:**
- Modify: `plugins/proj/server/server/tools/context.py:386-402`

- [ ] **Step 1: Update the tool signature + forward params**

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/proj/server/server/tools/context.py",
    old_string="    @app.tool(description=\"Append a dated note to the active project's NOTES.md.\")\n    def notes_append(text: str, project_name: str | None = None) -> str:\n        cfg = require_config()\n        name = state.resolve_project(project_name)\n        if not name:\n            return json.dumps({\"status\": \"error\", \"error\": \"No active project.\"})\n        storage.append_note(cfg, name, text)\n        # First line (stripped) for routing to log-entry titles that must be short.\n        first_line = (text.splitlines()[0].strip() if text.strip() else \"\")[:200]\n        return json.dumps(\n            {\n                \"status\": \"appended\",\n                \"project_name\": name,\n                \"content\": text,\n                \"content_first_line\": first_line,\n                \"message\": f\"Note appended to {name}/NOTES.md.\",\n            }\n        )",
    new_string="    @app.tool(description=\"Append a dated note to the active project's NOTES.md. When heading is provided, uses the chronological convention prefix '## [YYYY-MM-DD HH:MM] {op} | {heading}'; when absent, uses the legacy '## YYYY-MM-DD' prefix for backward compat.\")\n    def notes_append(\n        text: str,\n        heading: str | None = None,\n        op: str = \"note\",\n        project_name: str | None = None,\n    ) -> str:\n        cfg = require_config()\n        name = state.resolve_project(project_name)\n        if not name:\n            return json.dumps({\"status\": \"error\", \"error\": \"No active project.\"})\n        storage.append_note(cfg, name, text, heading=heading, op=op)\n        # First line: when heading is provided, return the composed heading line\n        # so router hooks consuming content_first_line get the structured title.\n        if heading is not None:\n            from datetime import datetime\n            ts = datetime.now().strftime(\"%Y-%m-%d %H:%M\")\n            first_line = f\"[{ts}] {op} | {heading}\"[:200]\n        else:\n            first_line = (text.splitlines()[0].strip() if text.strip() else \"\")[:200]\n        return json.dumps(\n            {\n                \"status\": \"appended\",\n                \"project_name\": name,\n                \"content\": text,\n                \"content_first_line\": first_line,\n                \"message\": f\"Note appended to {name}/NOTES.md.\",\n            }\n        )",
)
```

- [ ] **Step 2: Run all `test_context.py` notes_append tests + verify pass**

```bash
cd plugins/proj/server
uv run pytest tests/test_context.py -k "notes_append" -v 2>&1 | tail -20
```

Expected: 3 PASSes for the new notes_append tests.

### Task 15: Update `/proj:save` SKILL.md to use convention + add reminder

**Files:**
- Modify: `plugins/proj/skills/save/SKILL.md` (specifically step 10 + add new pre-step before step 13)

- [ ] **Step 1: Update step 10 (final notes_append call) to use the heading convention**

Find the existing step 10:

```markdown
**10.** `mcp__proj__notes_append` w/ one-line summary.
```

Replace with:

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/proj/skills/save/SKILL.md",
    old_string="**10.** `mcp__proj__notes_append` w/ one-line summary.",
    new_string="**10.** `mcp__proj__notes_append(heading=\"<session date>\", op=\"session\", text=<one-line summary>)` — uses chronological log convention (rule 20) so notes.md becomes `grep \"^## \\[\" notes.md | tail -10`-friendly.",
)
```

- [ ] **Step 2: Add a new step 10b: light reminder if zero decisions logged this session**

After step 10, before step 11 (Wiki auto-ingest):

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/proj/skills/save/SKILL.md",
    old_string="**10.** `mcp__proj__notes_append(heading=\"<session date>\", op=\"session\", text=<one-line summary>)` — uses chronological log convention (rule 20) so notes.md becomes `grep \"^## \\[\" notes.md | tail -10`-friendly.\n\n**11.** Wiki auto-ingest (if enabled):",
    new_string="**10.** `mcp__proj__notes_append(heading=\"<session date>\", op=\"session\", text=<one-line summary>)` — uses chronological log convention (rule 20) so notes.md becomes `grep \"^## \\[\" notes.md | tail -10`-friendly.\n\n**10b.** Decision-log reminder (light prompt, single dismiss):\n - Step 8 logged 0 decisions (no Key Decisions in synthesis) → ask via `AskUserQuestion`: \"No decisions logged this session. Any to capture before save?\" Options: Yes / No.\n - Yes → user supplies decision text; call `mcp__proj__notes_append(heading=<short title>, op=\"decision\", text=<full text>)`. Optionally also call `mcp__proj__proj_decision_log` if user marks it as a structured A/B pick.\n - No → proceed silently to step 11.\n - Step 8 logged ≥1 decision → skip reminder.\n\n**11.** Wiki auto-ingest (if enabled):",
)
```

- [ ] **Step 3: Verify the SKILL.md still parses + has the expected step count**

```bash
grep -c "^\*\*[0-9]" plugins/proj/skills/save/SKILL.md
```

Expected: original step count + 1 (for the new 10b). If original was 13, new is 14.

```bash
grep "^\*\*10b\." plugins/proj/skills/save/SKILL.md
```

Expected: 1 match.

### Task 16: Run full proj test suite

**Files:**
- No change.

- [ ] **Step 1: Run all proj-server tests**

```bash
cd /home/raul/projects/claude-project-manager
just test-proj 2>&1 | tail -50
# or:
cd plugins/proj/server && uv run pytest 2>&1 | tail -50
```

Expected: all tests pass. New test counts: 3 added in `test_storage.py` + 3 added in `test_context.py` = 6 new passing tests.

If any test fails: investigate root cause. Do NOT skip or weaken assertions to make tests pass.

### Task 17: Commit Phase 2

**Files:**
- All Phase 2 modified files.

- [ ] **Step 1: Stage + commit**

```bash
cd ~/worktrees/cpm/feat-699-karpathy-phase2
git add plugins/proj/server/server/lib/storage.py \
        plugins/proj/server/server/tools/context.py \
        plugins/proj/server/tests/test_storage.py \
        plugins/proj/server/tests/test_context.py \
        plugins/proj/skills/save/SKILL.md
git status
git commit -m "$(cat <<'EOF'
feat(proj/699): notes_append heading param + /proj:save adoption

Phase 2 of the Karpathy CPM integration. Implements the chronological
log convention (managed-block rule 20, shipped in Phase 1):

- storage.append_note: new heading + op kwargs. When heading provided,
  uses '## [YYYY-MM-DD HH:MM] {op} | {title}' prefix. When absent,
  preserves the legacy '## YYYY-MM-DD' prefix (backward compat).
- notes_append MCP tool: forwards heading + op. content_first_line
  returns the composed heading line when heading is provided so the
  default-hooks router can use it as a log-entry title.
- /proj:save step 10 adopts the convention. New step 10b adds a single
  light reminder prompt when zero decisions were logged this session.

Spec: docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Push + FF-merge to dev**

```bash
git push -u origin feat/699-karpathy-phase2-notes-append
git checkout dev
git pull origin dev
git merge --ff-only feat/699-karpathy-phase2-notes-append
git push origin dev
gh run watch
```

Expected: green CI on dev (proj-server matrix row covers the changes).

---

# Phase 3 — `/proj:checkpoint` skill

**Worktree branch**: `feat/699-karpathy-phase3-checkpoint`

### Task 18: Set up Phase 3 worktree

**Files:**
- Create worktree at: `~/worktrees/cpm/feat-699-karpathy-phase3`

- [ ] **Step 1: Create the worktree**

```python
mcp__plugin_worktree_worktree__wt_create(
    repo_label="cpm",
    branch="feat/699-karpathy-phase3-checkpoint",
    base="dev",
    path="~/worktrees/cpm/feat-699-karpathy-phase3"
)
```

- [ ] **Step 2: Sync to remote** (same pattern as Tasks 1, 9)

```bash
cd ~/worktrees/cpm/feat-699-karpathy-phase3
git fetch origin
git rev-list origin/dev..dev
# If empty:
git reset --hard origin/dev
# If non-empty:
git reset --hard dev
```

### Task 19: Draft `/proj:checkpoint` SKILL.md (caveman ultra)

**Files:**
- Create: `plugins/proj/skills/checkpoint/SKILL.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p plugins/proj/skills/checkpoint
```

- [ ] **Step 2: Write the SKILL.md**

```markdown
---
name: checkpoint
description: Mid-execution checkpoint — review in-flight work, decide continue/reset/tighten. Use when a TaskCreate-tracked phase completes during multi-step impl, when user pauses to evaluate, or when the user says "checkpoint", "/proj:checkpoint", "review where we are", or "should we keep going".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__notes_append, mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_remove, mcp__plugin_worktree_worktree__wt_create, mcp__proj__todo_list, AskUserQuestion, Bash, Skill
argument-hint: "[optional: scope hint or branch suffix]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Mid-exec checkpoint. Read in-flight diff; surface state; prompt continue/reset/tighten.

**1.** Session context: `mcp__proj__proj_session_context` → extract `project.name`, `config.tracking_dir`, `project.repos[].path`. (Same call shape as `/proj:save` step 1.)

**2.** Worktrees: `mcp__plugin_worktree_worktree__wt_list(repo_label=<from project meta>)`. Multiple worktrees → prompt user via `AskUserQuestion` to pick one. Single → use it.

**3.** Compute base SHA for diff:
 - Determine base branch: `git -C <wt_path> config --get branch.<branch>.remote-base` (rare; user-set) → fallback to `dev`.
 - `base_sha = git -C <wt_path> merge-base origin/<base> HEAD`.
 - Diff cmd: `git -C <wt_path> diff <base_sha>..HEAD --stat` + `git -C <wt_path> diff <base_sha>..HEAD --name-only`.

**4.** Surface diff:
 - revdiff available (check: `enabledPlugins["revdiff@revdiff"]` in `~/.claude/settings.json` AND `which revdiff` returns 0):
     - Invoke `revdiff:revdiff` skill w/ ref args `<base-sha> HEAD`.
 - Else: render inline — `git diff --stat` output + bullet summary per file (line counts, brief purpose).

**5.** State context:
 - Recent commits: `git log <base-sha>..HEAD --oneline | head -10`.
 - Open todos: `mcp__proj__todo_list(status="open", compact=True)` → first 5.
 - Recent notes: `tail -20 <tracking_dir>/<name>/notes.md` (last few entries).

**6.** Prompt user via `AskUserQuestion`:
 - Q: "Checkpoint review — what next?"
 - Options:
     - **Continue** — Work continues. Log audit-trail entry via `notes_append`; no git state change.
     - **Reset + restart w/ tightened scope** — `wt_remove` current; `wt_create` new w/ branch suffix `-v2` (or `$ARGUMENTS` if provided). Prompt for tightened-scope statement. Log via `notes_append(op="checkpoint", heading="reset to v2: <scope>")`.
     - **Tighten scope only** — Keep branch + worktree. Prompt for new constraint. Log via `notes_append(op="checkpoint", heading="tightened: <constraint>")`.

**7.** Apply chosen action:
 - Continue → `notes_append(op="checkpoint", heading="continue", text="<diff summary + decision rationale>")`. Audit trail; no git state change.
 - Reset → `mcp__plugin_worktree_worktree__wt_remove(path=<old>)`. Then prepare `dev`: `git -C <repo_root> fetch origin && git -C <repo_root> checkout dev && git -C <repo_root> reset --hard origin/dev` (so the new worktree branches from current `origin/dev`). Then `mcp__plugin_worktree_worktree__wt_create(repo_label=<x>, branch=<old-branch>-v2, path=<old>-v2)` (no `base` kwarg — `wt_create` cuts from current `dev` HEAD; sync handled above). Sync new worktree per rule 13. `notes_append(op="checkpoint", heading="reset to v2: <user-supplied scope>", text="<reason>")`. Inform user new wt path.
 - Tighten → `notes_append(op="checkpoint", heading="tightened: <constraint>", text="<full text>")`. Keep branch + worktree.

**8.** "Checkpoint complete. Next action: <continue|reset|tighten>."

## Prerequisites

- Active project loaded (`mcp__proj__proj_session_context` returns project meta).
- Project has at least one repo registered.
- Repo has at least one worktree (created via `wt_create` per managed-block rule 6).

## Err Handling

- No active project → display err, stop.
- No worktrees → display err: "No worktrees found. Create via wt_create first.", stop.
- revdiff missing or fails to launch → fall back to inline diff render silently.
- User cancels AskUserQuestion → no action; state preserved.
- wt_create fails on reset path → display err, original worktree NOT removed (safety).

## Output

Selected action + applied change + log entry confirmation. Diff display happens via revdiff or inline.

## Usage

- `/proj:checkpoint` → review w/o scope hint; reset path uses `-v2` default suffix.
- `/proj:checkpoint <scope-hint>` → `$ARGUMENTS` becomes the branch suffix on reset (replaces `-v2` default) and is included in the tightened-scope prompt.
```

Save via Write tool.

### Task 20: Add manual-checklist.md for E2E verification

**Files:**
- Create: `plugins/proj/skills/checkpoint/manual-checklist.md`

- [ ] **Step 1: Write the checklist**

```markdown
# /proj:checkpoint — Manual E2E Verification Checklist

This checklist verifies `/proj:checkpoint` works end-to-end. User-interactive prompts cannot be automated, so run through this manually before merge.

## Prerequisites

- Test project initialized via `/proj:init` in a scratch directory
- One worktree created via `mcp__plugin_worktree_worktree__wt_create`
- `revdiff` plugin enabled (per `~/.claude/settings.json::enabledPlugins["revdiff@revdiff"]`) AND `which revdiff` returns 0 — for the revdiff path
- Run separately with revdiff disabled to verify the inline-fallback path

## Scenarios

### Scenario A: Continue path (revdiff enabled)

1. [ ] Make 2-3 small commits on the worktree branch.
2. [ ] Invoke `/proj:checkpoint` (no args).
3. [ ] Verify diff is surfaced via revdiff TUI overlay (terminal popup).
4. [ ] Quit revdiff with no annotations.
5. [ ] Verify `AskUserQuestion` prompt appears with 3 options.
6. [ ] Select "Continue".
7. [ ] Verify `tracking_dir/<project>/notes.md` has a new entry with heading `## [YYYY-MM-DD HH:MM] checkpoint | continue` (audit-trail entry; no git state change).

### Scenario B: Reset path (default `-v2` suffix)

1. [ ] On a fresh worktree branch with 1 commit, invoke `/proj:checkpoint`.
2. [ ] Select "Reset + restart with tightened scope".
3. [ ] Provide a tightened-scope statement when prompted.
4. [ ] Verify the original worktree is removed (`wt_list` no longer shows it).
5. [ ] Verify a new worktree exists with branch suffix `-v2` (e.g. `feat/foo` → `feat/foo-v2`).
6. [ ] Verify the new worktree was synced to remote (per rule 13).
7. [ ] Verify `notes.md` has a new entry with heading `## [YYYY-MM-DD HH:MM] checkpoint | reset to v2: <scope>`.

### Scenario C: Reset path with custom suffix via $ARGUMENTS

1. [ ] On a fresh worktree branch, invoke `/proj:checkpoint focus-impl-only`.
2. [ ] Select "Reset + restart".
3. [ ] Verify new branch is `<original>-focus-impl-only` (not `-v2`).
4. [ ] Verify notes.md heading reflects the user-supplied scope.

### Scenario D: Tighten path

1. [ ] On a worktree with diverging commits, invoke `/proj:checkpoint`.
2. [ ] Select "Tighten scope only".
3. [ ] Provide a new constraint when prompted.
4. [ ] Verify worktree + branch are unchanged (still on the same branch + path).
5. [ ] Verify `notes.md` has a new entry with heading `## [YYYY-MM-DD HH:MM] checkpoint | tightened: <constraint>`.

### Scenario E: revdiff fallback (revdiff disabled)

1. [ ] Disable revdiff in `~/.claude/settings.json::enabledPlugins`.
2. [ ] Invoke `/proj:checkpoint`.
3. [ ] Verify diff is rendered inline (text), not via revdiff TUI.
4. [ ] Verify the rest of the flow (state context, AskUserQuestion, action) works the same.
5. [ ] Re-enable revdiff after testing.

### Scenario F: No worktrees error

1. [ ] In a project with no registered worktrees, invoke `/proj:checkpoint`.
2. [ ] Verify the skill exits cleanly with the error message: "No worktrees found. Create via wt_create first."
3. [ ] Verify no notes.md entry is added.

## Pass criteria

All 6 scenarios complete without errors. Diff surface (revdiff/inline) renders correctly. Each path produces the expected log entry in notes.md with the convention heading format.
```

Save via Write tool.

### Task 21: Update plugins/proj/README.md skill table + category list

**Files:**
- Modify: `plugins/proj/README.md`

- [ ] **Step 1: Locate the skill reference table**

```bash
grep -n "^## Skills\|^## Skills by category\|^| .* |" plugins/proj/README.md | head -20
```

- [ ] **Step 2: Add `/proj:checkpoint` to the skill table**

Insert a row alphabetically into the existing skill table. Row format follows existing entries (consult the file via Read first to match exact column count + style).

Example row (adapt columns to match existing schema):

```markdown
| `/proj:checkpoint` | Mid-execution checkpoint — review in-flight work, decide continue/reset/tighten | execute |
```

- [ ] **Step 3: Add to "Skills by category" list**

Find the category list (likely "Code exploration" or "Workflow" category) and append `/proj:checkpoint` under the appropriate category. If "Workflow" doesn't exist, add to "Code exploration".

### Task 22: Update top-level README.md skill reference table

**Files:**
- Modify: `README.md` (marketplace top-level)

- [ ] **Step 1: Locate the proj skills section**

```bash
grep -n "/proj:save\|/proj:status\|/proj:explore" README.md | head -10
```

- [ ] **Step 2: Add `/proj:checkpoint` row**

Insert alphabetically into the proj skills section. Match the existing row format.

### Task 23: E2E manual smoke test (optional but recommended)

**Files:**
- No file change.

- [ ] **Step 1: Run the manual checklist**

Open `plugins/proj/skills/checkpoint/manual-checklist.md` and execute Scenario A (continue path) at minimum on a scratch project.

If time permits, also run Scenario B (reset) + Scenario E (revdiff fallback).

If any scenario fails: do NOT mark Phase 3 complete. Investigate + fix the SKILL.md before commit.

### Task 24: Commit Phase 3

**Files:**
- All Phase 3 created/modified files.

- [ ] **Step 1: Stage + commit**

```bash
cd ~/worktrees/cpm/feat-699-karpathy-phase3
git add plugins/proj/skills/checkpoint/SKILL.md \
        plugins/proj/skills/checkpoint/manual-checklist.md \
        plugins/proj/README.md \
        README.md
git status
git commit -m "$(cat <<'EOF'
feat(proj/699): /proj:checkpoint skill for mid-execution review

Phase 3 of the Karpathy CPM integration. New skill that fills the
"mid-execution continue/reset/tighten" decision surface (managed-block
rules 21 + 24, shipped in Phase 1):

- plugins/proj/skills/checkpoint/SKILL.md (caveman ultra) — composes
  proj_session_context, wt_list/wt_remove/wt_create, revdiff (if
  available), notes_append (Phase 2 heading convention),
  AskUserQuestion, git CLI.
- Manual E2E checklist covers 6 scenarios (continue/reset/tighten +
  custom suffix + revdiff fallback + no-worktrees err path).
- README updates for skill discoverability.

No new MCP tools (per spec, decision: pure skill + Bash + existing
primitives).

Spec: docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Push + FF-merge to dev + watch CI**

```bash
git push -u origin feat/699-karpathy-phase3-checkpoint
git checkout dev
git pull origin dev
git merge --ff-only feat/699-karpathy-phase3-checkpoint
git push origin dev
gh run watch
```

Expected: green CI on dev. Phase 3 only adds skill markdown + README docs, no Python — only existing tests run.

---

# Phase 4 — Audit todo

### Task 25: Create the 30-day audit todo

**Files:**
- No file change. Single MCP tool call.

- [ ] **Step 1: Compute the target date**

Phase 3 merge date + 30 days. Use `date` command:

```bash
date -d "+30 days" +%Y-%m-%d
```

Capture the output as `<target_date>`.

- [ ] **Step 2: Add the todo via the proj MCP tool**

```python
mcp__plugin_proj_proj__todo_add(
    title="Karpathy CPM integration — 30-day usage audit",
    priority="medium",
    tags="audit,karpathy,followup",
    due_date="<target_date from step 1>",
    notes="""
30-day usage audit for the Karpathy CPM integration (todo 699).

Per Phase 4 of the spec (docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md):

## Measurements

1. Logging discipline:
   - decision_log.add call count over the audit window
   - notes_append-with-heading call count over the audit window
   - Ratio target: heading-style ≥ 3× decision-log usage

2. Checkpoint usage:
   - /proj:checkpoint invocations (count `checkpoint:` git notes across active project repos)
   - Outcome distribution: continue / reset / tighten
   - Target: at least one checkpoint per multi-step session with 3+ tasks

3. Rule adherence (qualitative): manual review of last 10 multi-step sessions for:
   - Drive-by-refactor incidents (rule 18 violations)
   - Assumptions surfaced before coding vs picked silently (rule 16 adherence)
   - Bug fixes preceded by failing test (rule 22 adherence)
   - Reset-over-recover invocations on detected drift (rule 21)
   Score 0-3 per category per session.

## Deliverable

docs/superpowers/audits/2026-MM-DD-karpathy-integration-audit.md with:
- Quantitative metrics + targets met/missed
- Qualitative rule-adherence scorecard
- Iteration todos (Phase 5 candidates if adoption gap exists)

## Context for the future-you running this audit

- Spec: docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md
- Phase 1 (managed-block) merged: <Phase 1 merge SHA — fill in when audit runs>
- Phase 2 (notes_append + /proj:save) merged: <Phase 2 merge SHA>
- Phase 3 (/proj:checkpoint) merged: <Phase 3 merge SHA>

If adoption gap detected, scope a Phase 5 spec for enforcement (router hooks, auto-suggest mechanisms). Phase 5 is out of scope for the current spec.
""",
)
```

- [ ] **Step 3: Verify the todo was created**

```python
mcp__plugin_proj_proj__todo_list(tag="karpathy", compact=True)
```

Expected: at least one todo with the audit title. Capture the new ID for the next step.

- [ ] **Step 4: Link the audit todo to the parent (todo 699)**

If the proj plugin supports todo dependencies/parents, optionally add a `group:699` tag or use `todo_update` to set up a relationship. Check current cpm convention via `todo_get(699)` to see existing tag format. If no relationship mechanism is preferred, leave the audit todo standalone with the karpathy tag for filtering.

- [ ] **Step 5: Update the parent todo 699 to mark the integration shipped**

```python
mcp__plugin_proj_proj__todo_notes_append(
    todo_id="699",
    text="\n\n---\n**Shipped 2026-MM-DD**: 4-phase Karpathy CPM integration complete. Phase 1 (managed-block additions w/ forrestchang 4-principle backbone + 5 cpm-layer rules + 3 cross-refs), Phase 2 (notes_append heading param + /proj:save adoption), Phase 3 (/proj:checkpoint skill). Phase 4 audit scheduled — see audit todo created today. Spec: docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md."
)
```

- [ ] **Step 6: Optionally complete todo 699 once Phase 4 audit todo exists**

Discretionary — if treating Phase 4 as a separate ongoing effort (not blocking 699's completion):

```python
mcp__plugin_proj_proj__todo_complete(todo_id="699")
```

If treating Phase 4 as part of 699's completion, leave 699 open until audit runs.

---

## Self-Review (run after the plan above is complete during execution)

After executing each phase, verify:

1. **Spec coverage**: Skim the spec sections (Goals, Phases 1-4, Testing, Risks, Resolved decisions). Each spec requirement should map to at least one task above.
   - Phase 1 spec: 4-principle backbone + 5 cpm-layer rules + cross-refs + README update ↔ Tasks 3, 4, 5, 6 ✓
   - Phase 2 spec: notes_append heading param + /proj:save adoption + reminder ↔ Tasks 11-15 ✓
   - Phase 3 spec: /proj:checkpoint skill (pure skill + Bash) + manual checklist ↔ Tasks 19, 20, 23 ✓
   - Phase 4 spec: 30-day audit todo creation ↔ Task 25 ✓
2. **Worktree discipline**: each phase has its own worktree task (Tasks 1, 9, 18) per spec "4 sequential PRs" rollout.
3. **Test discipline**: Phase 2 follows TDD per writing-plans skill (failing test → impl → passing test) in Tasks 11-14.
4. **No placeholders**: no TBD/TODO outside the audit-todo notes (which intentionally has `<Phase N merge SHA>` placeholders to be filled when the audit runs).
5. **Type consistency**: `notes_append` signature in Phase 2 (`text, heading, op, project_name`) is referenced consistently in Tasks 13, 14, 15, 19 (the checkpoint skill's `notes_append(op="checkpoint", ...)` calls).
6. **Commit messages**: each phase commit cites the spec path + co-authorship trailer.

---

## Notes

- **Phase ordering matters.** Phase 2 is required before Phase 3 (checkpoint skill calls `notes_append(heading=..., op="checkpoint")`, which requires the Phase 2 extension). Phase 1 should land before Phase 2 (the managed-block rule 20 references the convention Phase 2 implements).
- **Each phase ships independently** to dev with its own CI green moment.
- **No worktree for the plan itself** — plan lives on `dev`. Worktrees are created per-phase for implementation.
- **If a phase fails CI**, do NOT proceed to the next phase. Investigate root cause + fix on the same worktree. Per managed-block rule 21, if drift accumulates, prefer `wt_remove` + new `wt_create` over patching the failing trajectory.
- **Caveman-ultra phrasing** in Phase 1 rules + Phase 3 SKILL.md is per project convention (see project CLAUDE.md). Not bargainable.
- **forrestchang attribution** uses inline per-rule citations in the managed-block (`*(Source: ...)*` tail per rule). Per spec open-question resolution: this is the chosen attribution style.
- **Existing decisions.json migration** is explicitly out of scope (spec non-goal). Leave as dual-source.
- **Phase 4 audit will reveal whether the rules changed actual behavior** — instruction-following ≠ behavior change. If audit reveals adoption gap, scope a Phase 5 spec separately.

# Managed-block Hygiene Bundle (722) Design

**Date:** 2026-04-23
**Todo:** 722
**Branch (planned):** `feat/722-managed-block-hygiene`

---

## Goals

Resolve 3 hygiene items in `plugins/_shared/claudemd/managed_section.md` flagged by code review on 720 (commit `8bdc6f5`):

1. Inline rule-number comments to prevent recurring off-by-one errors in specs/commits (Phase 1 had it, 720 had it again).
2. Backtick-normalize bare tool/MCP names so the styling is consistent.
3. Reword rule 24 (Mid-execution checkpoint rhythm) to drop "don't count tasks" framing that surface-conflicts w/ rule 7's "2+ actions" framing.

Single PR, single commit. Pure markdown.

## Non-goals

- No new rules, no rule additions or removals.
- No CI lint check (chose HTML comments over lint per Q&A — lower upfront cost; lower long-term guarantee, accepted).
- No restructure of the managed-block parser or markers.
- No README change.
- No backtick edits to non-tool nouns (e.g. "Task" as generic noun in rule 8 — kept bare).
- No backtick edits to agent tool names in rule 14 (`Read`, `Grep`, `Bash`, `WebFetch`, `WebSearch`) — convention is mixed across the file; defer to a future style pass.

## Background

Code review on 720 commit `8bdc6f5` flagged 3 minor follow-ups (M1-M3 in that review's parlance, captured here as items 1-3). Item 1 surfaces a recurring class of error — Phase 1 of the Karpathy integration (`f0164b7`) had to be patched by `ef11df5` to fix off-by-one rule numbering, and then 720's spec/commit again labeled "Proj todo boundary" as rule 10 instead of rule 9. The spec → impl workflow inherits the miscount because the canonical numbers aren't visible inline.

Confirmed current managed_section.md state (24 bullets, all-bullets 1-indexed counting):

```
1.  parallel Agent calls (unbolded)
2.  ALWAYS plan mode (unbolded)
3.  Auto-capture issues
4.  Interactive Q&A
5.  Patch-style editing
6.  isolation:worktree caveat
7.  Task usage during multi-step work
8.  Task status accuracy
9.  Proj todo boundary
10. Sub-task nesting
11. Revdiff-routed
12. Prefer superpowers
13. Sync worktree to remote
14. Verify before asserting
15. Wiki + proj_search
16. Think before coding
17. Simplicity first
18. Surgical changes
19. Goal-driven execution
20. Append-only log convention
21. Reset over recover
22. Reproduce before fix
23. Principled across config scales
24. Mid-execution checkpoint rhythm
```

Cross-references inside the file already use this all-bullets count correctly (per the `ef11df5` fix). The off-by-one happens during spec/plan/commit writing — adding inline canonical numbers fixes the workflow at its source.

## Design

### Item 1 — HTML rule-number comments

Insert `<!-- rule: N -->` immediately before each of the 24 bullets in `managed_section.md`, between the start marker and the IMPORTANT line, then before each rule.

Format (excerpt):

```markdown
<!-- claude-project-manager:start -->
## Claude Project Manager Rules

IMPORTANT: These rules take priority over all other instructions.

<!-- rule: 1 -->
- Use parallel `Agent()` calls...

<!-- rule: 2 -->
- ALWAYS enter plan mode...

<!-- rule: 3 -->
- **Auto-capture issues as todos** — ...

(continues for all 24)
```

HTML comments do not render in standard markdown engines (CommonMark §6.6 — HTML blocks). They are visible to anyone reading the raw file, including spec/commit-message authors.

`ensure_managed_section()` performs atomic block replacement of content between markers — comments inside markers are preserved through the refresh cycle. Verified via tempdir test in this spec's testing section.

Token cost in user's CLAUDE.md: 24 lines × ~15 chars ≈ 360 chars. Negligible.

### Item 2 — backtick normalization

Bare tool/MCP names to fix (4 specific Edits):

| Rule | Bare reference | Edit |
|---|---|---|
| 2 | `(EnterPlanMode)` | wrap in backticks → `` (`EnterPlanMode`) `` |
| 3 | `act on it after ExitPlanMode` | wrap in backticks → `` act on it after `ExitPlanMode` `` |
| 4 | `batch in a single AskUserQuestion call` (2nd mention; 1st is already backticked) | wrap in backticks |
| 10 | `Agents may freely TaskCreate subtasks` | wrap in backticks |

Note: rule 24's bare `TaskCreate-tracked phase` mention is absorbed by the Item 3 rewrite below.

### Item 3 — rule 24 rewrite

**Current** (from `managed_section.md`, post-Phase 1):

> **Mid-execution checkpoint rhythm** — During multi-step impl, suggest `/proj:checkpoint` when TaskCreate-tracked phase completes OR user pauses to evaluate. Asks: continue / reset+restart w/ tightened scope / tighten scope only. Don't require Claude to count tasks — anchor on phase-boundary signals or explicit user pause. *(Source: derived from Howells reset-over-recover + Karpathy autonomy-slider per task.)*

**Proposed**:

> **Mid-execution checkpoint rhythm** — During multi-step impl, suggest `/proj:checkpoint` when a `TaskCreate`-tracked phase completes OR user pauses to evaluate. Asks: continue / reset+restart w/ tightened scope / tighten scope only. Anchor checkpoint suggestions on phase-boundary signals or explicit user pause (not on completed-task counts). *(Source: derived from Howells reset-over-recover + Karpathy autonomy-slider per task.)*

Diffs:
- Insert `a` before `\`TaskCreate\`-tracked` (grammar)
- Backtick `TaskCreate` (absorbs Item 2's rule-24 mention)
- Replace "Don't require Claude to count tasks — anchor on phase-boundary signals or explicit user pause." → "Anchor checkpoint suggestions on phase-boundary signals or explicit user pause (not on completed-task counts)."

Net effect: removes the "count tasks" phrase that surface-conflicts w/ rule 7's "2+ distinct actions" framing. Semantics unchanged — still anchors checkpoint suggestions on phase boundaries + user pauses.

## Testing

Same approach as 704:

```bash
TEMP_HOME=$(mktemp -d)
mkdir -p "$TEMP_HOME/.claude"
echo "# Test" > "$TEMP_HOME/.claude/CLAUDE.md"
cd plugins/_shared/claudemd
HOME="$TEMP_HOME" uv run python3 -c "
from claudemd import ensure_managed_section
from pathlib import Path
result = ensure_managed_section(Path('$TEMP_HOME/.claude/CLAUDE.md'))
print(f'modified: {result}')
content = Path('$TEMP_HOME/.claude/CLAUDE.md').read_text()
import re
bullet_count = len(re.findall(r'^- \*\*', content, re.MULTILINE))
print(f'bold-rule count: {bullet_count}')
comment_count = len(re.findall(r'^<!-- rule: \d+ -->$', content, re.MULTILINE))
print(f'rule-comment count: {comment_count}')
assert bullet_count == 22
assert comment_count == 24
assert '\`EnterPlanMode\`' in content
assert '\`ExitPlanMode\`' in content
assert '(not on completed-task counts)' in content
assert \"Don't require Claude to count tasks\" not in content
print('all assertions passed')
"
rm -rf "$TEMP_HOME"
```

Plus full shared test suite — should still pass since markdown shape is unchanged (still flat block w/ start/end markers, still 22 bolded rules, plus 24 HTML comments which the parser ignores).

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| HTML comments break `ensure_managed_section()` parser or get stripped on refresh | Low | Medium | Tempdir test in implementation step asserts comments survive the refresh cycle |
| Backtick edits accidentally match wrong text (e.g. `EnterPlanMode` mentioned in unrelated context) | Low | Low | Each `Edit` uses precise `old_string` w/ surrounding prose context for uniqueness |
| Rule 24 rewrite changes Claude's interpretation of when to suggest /proj:checkpoint | Low | Low | Semantics preserved: phase-boundary + user-pause triggers unchanged. Only the negation framing was replaced w/ a parenthetical clarification. |
| 24 HTML comments add ~360 chars to every session's CLAUDE.md | Trivial | Trivial | Absorbed in noise; measured cost negligible vs total CLAUDE.md size |
| Future spec/plan writers ignore the inline numbers anyway | Medium | Low | Best-effort improvement; if numbering errors persist, escalate to lint check (Q&A option B). 30-day audit window can measure. |

## Resolved decisions (from brainstorm Q&A)

- **Item 1 mitigation**: HTML comments per bullet (not lint check, not "leave as-is", not both).
- **Item 2 scope**: full-pass normalization for bare tool/MCP names (not "targeted only", not skip).
- **Item 3 action**: reword rule 24 to drop "don't count tasks" framing (not "leave as-is", not "add cross-ref").
- **Packaging**: single PR (not 3 separate PRs).

## Open questions

None. Spec fully specified. Implementer reads `managed_section.md` to find exact `old_string` anchors for each Edit.

## References

- Code review on 720 commit 8bdc6f5 — flagged the 3 hygiene items
- Phase 1 numbering fix: ef11df5 — established the all-bullets counting convention
- Phase 2 race fix: b558e5c — pattern for "no revdiff per user instruction"
- 704 spec: `docs/superpowers/specs/2026-04-23-704-task-tracking-emphasis-design.md` — pattern for managed-block-only specs
- 720 spec: `docs/superpowers/specs/2026-04-23-720-phase2-polish-design.md` — pattern for SKILL polish specs

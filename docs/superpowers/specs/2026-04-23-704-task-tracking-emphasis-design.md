# Task Tracking Emphasis Design (704)

**Date:** 2026-04-23
**Todo:** 704
**Branch (planned):** `feat/704-task-tracking-emphasis`

---

## Goal

Tighten managed-block rules 7 + 10 in `plugins/_shared/claudemd/managed_section.md` so Claude defaults to using native task tracking on **any multi-step work** (not just 3+ actions) and clearly distinguishes native ephemeral tracking (`TaskCreate` / `TaskUpdate` / `TodoWrite`) from cpm durable project todos (`mcp__plugin_proj_proj__todo_add`).

## Non-goals

- No new rules. Block stays at 24 bullets.
- No native-tool API changes. `TaskCreate` / `TaskUpdate` / `TodoWrite` / `proj_todo_add` signatures unchanged.
- No examples block (rule 7 stays terse — caveman-ultra discipline).
- No section-headed restructuring (preserves the flat-block parser).
- No README change (the existing Karpathy alignment section doesn't reference rules 7 or 10).

## Background

Existing rules in `managed_section.md` (post Phase 1 numbering fix at `ef11df5`):

- **Rule 7 (current):** "Task usage during multi-step work — When starting multi-step implementation (3+ actions), use TaskCreate to track steps. Mark in_progress when beginning each step, completed when done."
- **Rule 10 (current):** "Proj todo boundary — Tasks = execution-time progress tracking. Proj todos = durable project state. Do NOT use todo_add for execution artifacts (use TaskCreate instead). Use todo_add only for real project-level TODOs that should persist after the session."

The user observed (per todo 704) that native task tracking should be used **extensively** — implying the current 3+ threshold and absence of an explicit "default ON" framing under-promote the behavior. Also: only `TaskCreate` is named, leaving older harness sessions (which use `TodoWrite`) ambiguous.

## Design

### Rule 7 — proposed new wording

> **Task usage during multi-step work** — Any work involving 2+ distinct actions → use `TaskCreate` (or `TodoWrite` on older harness) to track steps. Mark in_progress when beginning each step, completed when done. Default ON: when in doubt, create the task. Makes progress visible to the user in real time.

Diffs vs current:
- `(3+ actions)` → `(2+ distinct actions)` — lower threshold, broader applicability
- Add `(or TodoWrite on older harness)` — covers both modern + older harness
- Add `Default ON: when in doubt, create the task` — explicit habit-driving framing
- Drop one redundant connective ("when starting multi-step implementation") — caveman ultra

### Rule 10 — proposed new wording

> **Proj todo boundary** — Native Tasks (`TaskCreate` / `TaskUpdate` / `TodoWrite`) = execution-time progress tracking, ephemeral, in-session only. Proj todos (`mcp__plugin_proj_proj__todo_add`) = durable project state, persist cross-session. Do NOT use `todo_add` for execution artifacts (use `TaskCreate` / `TodoWrite` instead). Use `todo_add` only for real project-level TODOs that should persist after the session.

Diffs vs current:
- Name both surfaces explicitly with qualified names (`TaskCreate`/`TaskUpdate`/`TodoWrite` vs `mcp__plugin_proj_proj__todo_add`)
- Add `ephemeral, in-session only` vs `persist cross-session` — sharpens the boundary
- Add `TodoWrite` to the "use instead of todo_add" guidance for older harness

## Testing

Same approach as Phase 1 of the Karpathy CPM integration:

```bash
TEMP_HOME=$(mktemp -d)
mkdir -p "$TEMP_HOME/.claude"
echo "# Test" > "$TEMP_HOME/.claude/CLAUDE.md"
cd plugins/_shared/claudemd
HOME="$TEMP_HOME" uv run python3 -c "
from claudemd import ensure_managed_section
from pathlib import Path
ensure_managed_section(Path('$TEMP_HOME/.claude/CLAUDE.md'))
content = Path('$TEMP_HOME/.claude/CLAUDE.md').read_text()
assert '2+ distinct actions' in content
assert 'TodoWrite' in content
assert 'ephemeral, in-session only' in content
assert 'persist cross-session' in content
import re
assert len(re.findall(r'^- \*\*', content, re.MULTILINE)) == 22
"
rm -rf "$TEMP_HOME"
```

Plus the existing claudemd test suite (`plugins/_shared` tests) — should continue to pass since markdown shape is unchanged (still flat block w/ start/end markers).

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Lowering 3+ → 2+ adds TaskCreate noise on trivial 2-step sessions (e.g. read file + edit file) | Medium | Low | "When in doubt" framing leaves room for judgment. If audit reveals noise, raise back to 3+ in a follow-up. |
| Mentioning `TodoWrite` may confuse users on newer harness who don't recognize the older tool | Low | Low | `TaskCreate` named first; `TodoWrite` clearly qualified as "older harness". Inert if not present. |
| Managed-block size grows ~70 chars across the 2 rules | Trivial | Trivial | Per-session token cost effectively unchanged. |

## Implementation footprint

- 2 `Edit` operations on `plugins/_shared/claudemd/managed_section.md`
- 1 commit on a `feat/704-task-tracking-emphasis` branch
- FF-merge to `dev`
- No README changes
- No code changes

## Resolved decisions (from brainstorm Q&A)

- **Tool scope**: cover native `TaskCreate` + `TodoWrite` (both harness variants). Do not include cpm `proj.todo_add` as a separate emphasis target — keep the boundary as part of rule 10.
- **Gap**: trigger on 2+ actions (not 3+); current rules under-promote frequency.
- **Form**: strengthen rules 7 + 10 in place. No new rule. No restructuring.
- **README**: not touched (no existing reference to these rules in the Karpathy alignment section).

## Open questions

None. Spec is small enough that implementation is fully determined by the rule rewordings above.

## References

- `plugins/_shared/claudemd/managed_section.md` (post-merge dev state, lines 12 + 15 — rules 7 + 10)
- Phase 1 spec for managed-block discipline pattern: `docs/superpowers/specs/2026-04-23-karpathy-cpm-integration-design.md`
- Phase 1 plan execution pattern (worktree + verify + FF-merge): `docs/superpowers/plans/2026-04-23-699-karpathy-cpm-integration.md`

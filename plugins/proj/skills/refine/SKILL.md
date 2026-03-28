---
name: refine
description: Stress-test requirements with 3 specialized review agents (Skeptic, Edge-Case Finder, Architecture Reviewer). Sub-skill invoked by run, not user-invocable.
allowed-tools: mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__proj_get_todo_context, mcp__proj__notes_append, Read, Glob, Grep, Task
context: fork
agent: general-purpose
argument-hint: "<todo-id>"
---

Refine todo: $ARGUMENTS

**Quality level behavior** (controlled by run/SKILL.md, not this skill):
- `--fast`: refine is skipped entirely (run/SKILL.md guards this before invoking refine)
- `--careful` / `--paranoid`: refine is auto-enabled (run invokes this skill even without `--refine` flag)

**1.** Parse `todo_id` from $ARGUMENTS.

**2.** Load context:
- Call `mcp__proj__proj_get_todo_context` with `todo_id` and `include_parent=true`.
- Call `mcp__proj__content_get_requirements` with `todo_id`.
- Call `mcp__proj__content_get_research` with `todo_id`.
- If no requirements found: note as a critical gap but continue (agents will flag it).

**3.** Spawn 3 review agents in parallel (general-purpose, read-only: `Read, Glob, Grep`):

**Agent 1 — Skeptic:**
> You are a Skeptic reviewer. Your job is to challenge the requirements and research for this todo. Look for:
> - Assumptions stated as facts without evidence
> - Contradictions between requirements sections
> - Acceptance criteria that cannot be objectively tested
> - Scope creep beyond the stated goal
> - Missing failure modes or rollback strategies
>
> Report ONLY new information. Do NOT restate existing requirements.

**Agent 2 — Edge-Case Finder:**
> You are an Edge-Case Finder. Your job is to identify scenarios the requirements miss. Look for:
> - Boundary conditions (zero, one, max, overflow)
> - Empty/null/missing input handling
> - Concurrency and race conditions
> - Backwards compatibility with existing data
> - Error propagation chains
> - State corruption scenarios
>
> Report ONLY new information. Do NOT restate existing edge cases.

**Agent 3 — Architecture Reviewer:**
> You are an Architecture Reviewer. Your job is to check the proposed approach against the actual codebase. Look for:
> - Deviations from existing codebase patterns and conventions
> - Testability of the proposed approach
> - Existing utilities or patterns that could be reused
> - Better alternative approaches based on what the codebase already does
> - Coupling or abstraction concerns
>
> Report ONLY new information. Do NOT restate existing architecture decisions.

Each agent receives: todo context, requirements.md content, research.md content, and codebase read access.

Each agent produces this exact structure:

```markdown
## [Role Name] Findings

### Critical Issues (must address)
- [issue description + why it matters + suggested fix]

### Suggestions (would improve)
- [suggestion + rationale]

### Confirmed Sound
- [aspect that was reviewed and found correct]
```

If an agent finds nothing: all three sections are present, with Critical Issues and Suggestions empty, and Confirmed Sound listing what was validated.

**4.** Wait for all 3 agents. If any agent fails/times out: report partial results from succeeded agents, note the failure.

**5.** Synthesize into Refinement Report:

```
### Refinement Report

**Skeptic** — <N> critical, <M> suggestions
  - CRITICAL: <issue summary>
  - Suggest: <suggestion summary>

**Edge Cases** — <N> critical, <M> suggestions
  - CRITICAL: <issue summary>
  - Suggest: <suggestion summary>

**Architecture** — <N> critical, <M> suggestions
  - CRITICAL: <issue summary>
  - Suggest: <suggestion summary>

### Suggested Amendments

**Requirements changes**:
1. <concrete change to requirements.md>

**Research changes**:
1. <concrete change to research.md> (or "(none)")

**Edge case additions**:
1. <new edge case>
```

**6.** All-clear scenario: if zero criticals AND zero suggestions across all 3 agents:
```
### Refinement Report

No concerns found. All 3 reviewers confirmed the requirements and research are sound.

Proceeding to plan mode.
```
Auto-continue without prompting.

**7.** If issues found, prompt:

```
1. **Apply** — Update requirements.md and research.md with all suggested amendments
2. **Edit** — Modify amendments before applying (display as numbered list, pick which to keep/modify/drop)
3. **Skip** — Proceed to plan mode without changes
4. **Stop** — Exit workflow
```

**8.** Apply flow:
1. Backup: call `content_get_requirements` and store as `pre_refine_requirements`. If research exists, same for research.
2. Merge accepted amendments into content.
3. Call `content_set_requirements` with updated content.
4. If research amendments: call `content_set_research` with updated content.
5. Display: "Requirements updated with N amendments."
6. Re-run the 5 preflight checks (the same structural checks from the preflight block in run/SKILL.md). If any new failures: display and offer (1) Fix (2) Continue (3) Undo amendments.
7. Undo: restore from `pre_refine_requirements` backup via `content_set_requirements`.

**9.** Edit flow:
1. Display amendments as a numbered list.
2. User specifies which to keep, modify, or drop.
3. Apply the edited subset using the same Apply flow (step 8).

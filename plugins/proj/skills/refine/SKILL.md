---
name: refine
description: Stress-test requirements with review agents (3 core + up to 4 tag/quality-based). Sub-skill invoked by run, not user-invocable.
allowed-tools: mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__proj_get_todo_context, mcp__proj__notes_append, Read, Glob, Grep, Task
argument-hint: "<todo-id>"
---

Refine todo: $ARGUMENTS

**Interaction rule**: This skill MUST use `AskUserQuestion` for every user-facing prompt. Do not emit inline numbered text lists for user input. Steps 7, 8.6, and 9 all route their choices through `AskUserQuestion`. The 4-option cap of `AskUserQuestion` applies — prompts must fit within 4 options.

**Quality level behavior** (controlled by `/proj:run`, not this skill):
- `--fast`: refine is skipped entirely (`/proj:run` guards this before invoking refine)
- `--careful` / `--paranoid`: refine is auto-enabled (run invokes this skill even without `--refine` flag)

**1.** Parse `todo_id` from $ARGUMENTS.

**2.** Load context:
- Call `mcp__proj__proj_get_todo_context` with `todo_id` and `include_parent=true`.
- Call `mcp__proj__content_get_requirements` with `todo_id`.
- Call `mcp__proj__content_get_research` with `todo_id`.
- If no requirements found: note as a critical gap but continue (agents will flag it).
- If no research found: note for Architecture Reviewer (will flag missing research as a gap).

**3.** Determine agent set and spawn in parallel (general-purpose, read-only: `Read, Glob, Grep`):

When this skill specifies N review/check roles per target, spawn N individual agents — never combine multiple roles into a single agent.

Load the todo's `tags` field from todo context. Select agents per the agent selection logic below. Spawn all selected agents in parallel:

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

**Agent 4 — Security Reviewer** (triggered by `security` or `breaking-change` tags on the todo):
> You are a Security Reviewer. Your job is to audit the requirements and proposed approach for security risks. Look for:
> - Authentication and authorization gaps
> - Data privacy concerns and sensitive data exposure
> - Injection attack vectors (SQL, command, template, etc.)
> - Secrets management and credential handling
> - Input validation and sanitization weaknesses
> - Access control bypasses
> - Compliance implications
>
> Report ONLY new information. Do NOT restate existing security considerations.

**Agent 5 — Performance & Scalability Reviewer** (triggered by `performance` tag on the todo):
> You are a Performance & Scalability Reviewer. Your job is to identify performance risks in the proposed approach. Look for:
> - Algorithmic complexity issues (O(n^2) or worse where O(n) is possible)
> - Excessive memory consumption or memory leaks
> - Concurrency bottlenecks and lock contention
> - Missing pagination or batching for large datasets
> - Database query patterns (N+1 queries, missing indexes, full table scans)
> - Caching opportunities and cache invalidation risks
> - Resource cleanup and connection pool exhaustion
>
> Report ONLY new information. Do NOT restate existing performance considerations.

**Agent 6 — API & Contract Reviewer** (triggered by `api` tag on the todo):
> You are an API & Contract Reviewer. Your job is to evaluate interface design and backwards compatibility. Look for:
> - Public API surface changes that break existing consumers
> - Parameter naming inconsistencies with existing conventions
> - Response format changes or missing fields
> - Missing versioning or deprecation strategy
> - Error response semantics (status codes, error shapes)
> - Missing or incorrect type annotations on public interfaces
> - Documentation gaps for consumer-facing changes
>
> Report ONLY new information. Do NOT restate existing API decisions.

**Agent 7 — Complexity & Maintainability Reviewer** (triggered by `--paranoid` quality level only):
> You are a Complexity & Maintainability Reviewer. Your job is to assess long-term code health impact. Look for:
> - DRY violations and code duplication across the codebase
> - High cyclomatic complexity in proposed implementations
> - Abstraction level mismatches (too abstract or too concrete)
> - Single-responsibility principle violations
> - Tight coupling between modules that should be independent
> - Test coverage gaps in critical paths
> - Technical debt being introduced without acknowledgment
>
> Report ONLY new information. Do NOT restate existing maintainability concerns.

**Agent selection logic:**
- **Core agents (1-3)**: ALWAYS run regardless of tags or quality level.
- **Tag-based agents (4-6)**: Check the todo's `tags` field. Add matching reviewers:
  - Tags `security` or `breaking-change` → add Agent 4 (Security Reviewer)
  - Tag `performance` → add Agent 5 (Performance & Scalability Reviewer)
  - Tag `api` → add Agent 6 (API & Contract Reviewer)
- **Quality-level agents**: `--paranoid` adds ALL 7 agents regardless of tags.
- **Max parallel**: Respect the quality_level's `max_parallel` setting when spawning agents.

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

**4.** Wait for all agents. If any agent fails/times out: report partial results from succeeded agents, note the failure.

**5.** Synthesize into Refinement Report:

For each agent that ran, include a summary block:

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

[If tag-based or quality-level agents ran, include their blocks:]

**Security** — <N> critical, <M> suggestions
  - CRITICAL: <issue summary>
  - Suggest: <suggestion summary>

**Performance** — <N> critical, <M> suggestions
  - CRITICAL: <issue summary>
  - Suggest: <suggestion summary>

**API & Contract** — <N> critical, <M> suggestions
  - CRITICAL: <issue summary>
  - Suggest: <suggestion summary>

**Complexity** — <N> critical, <M> suggestions
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

**6.** All-clear scenario: if zero criticals AND zero suggestions across all agents:
```
### Refinement Report

No concerns found. All <N> reviewers confirmed the requirements and research are sound.

Proceeding to plan mode.
```
Auto-continue without prompting.

**7.** If issues found, call `AskUserQuestion` **once** with exactly these four options:
- `Apply` — Update requirements.md and research.md with all suggested amendments
- `Edit` — Modify amendments before applying (enters step 9 edit flow)
- `Skip` — Proceed to plan mode without changes
- `Stop` — Exit workflow

Pass the refinement report summary (agent counts, critical issues, suggested amendments) as the `question`/context for the call so the user can decide in-place. Do NOT print these choices as an inline numbered list — the `AskUserQuestion` call is the only user-facing prompt.

**Non-interactive fallback**: Under `--no-interactive`, the Apply/Reject gate defaults to `Skip` (logged note); step 8.6 defaults to `Continue`; step 9 defaults to `Keep-all`. No `AskUserQuestion` calls are made in this mode.

**8.** Apply flow:
1. Backup: call `content_get_requirements` and store as `pre_refine_requirements`. If research exists, same for research.
2. Merge accepted amendments into content.
3. Call `content_set_requirements` with updated content.
4. If research amendments: call `content_set_research` with updated content.
5. Display: "Requirements updated with N amendments."
6. Re-run the 5 preflight checks (the same structural checks from the preflight block in `/proj:run`). If any new failures, call `AskUserQuestion` **once** with exactly these three options and include the failing preflight check names in the `question` text:
   - `Fix` — Spawn a fix pass to address the failing checks
   - `Continue` — Proceed to plan mode despite failures
   - `Undo amendments` — Restore pre-refine requirements/research
   Do not print an inline numbered list — the `AskUserQuestion` call is the only user-facing prompt here.
7. Undo: restore from `pre_refine_requirements` backup via `content_set_requirements`.

**9.** Edit flow:
1. For each amendment (one at a time), call `AskUserQuestion` with exactly these four options — this respects the 4-option cap of `AskUserQuestion`:
   - `Keep` — Accept this amendment as-is
   - `Modify` — Rewrite this amendment (follow-up via a second `AskUserQuestion` or open-ended prompt only if unavoidable)
   - `Drop` — Exclude this amendment
   - `Stop` — Halt the edit flow; apply only decisions made so far
   Pass the amendment text (and its source agent) as the `question`/context. Issue one `AskUserQuestion` call per amendment — do NOT batch multiple amendments into a single call, and do NOT print the amendments as an inline numbered list.
2. Apply the edited subset using the same Apply flow (step 8).

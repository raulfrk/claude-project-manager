---
name: refine
description: Stress-test requirements with review agents (3 core + up to 4 tag/quality-based). Sub-skill invoked by run, not user-invocable.
allowed-tools: mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__content_patch_requirements, mcp__proj__content_patch_research, mcp__proj__proj_get_todo_context, mcp__proj__notes_append, Read, Glob, Grep, Task
argument-hint: "<todo-id>"
---

Refine todo: $ARGUMENTS

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
3. (Preferred path — see 8.3a) For each accepted amendment, classify as section-localized (modifies text entirely within one `##` or `###` block) or wholesale. For section-localized, call `content_patch_requirements` with `section=<heading>`, `pattern=<escaped old text>`, `replacement=<new text>`. If returned `ok=false` and error != 'no match', log and fall back to `content_set_requirements`. If 'no match', refresh via `content_get_requirements` and retry fallback.
4. Fallback path: call `content_set_requirements` with updated content.
5. If research amendments: use `content_patch_research` with the same classification, otherwise fall back to `content_set_research`.
6. Display: "Requirements updated with N amendments."
7. Re-run the 5 preflight checks (the same structural checks from the preflight block in `/proj:run`). If any new failures: display and offer (1) Fix (2) Continue (3) Undo amendments.
8. Undo: restore from `pre_refine_requirements` backup via `content_set_requirements`.

**Patch tool usage notes:**
- **Literal section match** — `section` is compared as a literal, case-sensitive string against the heading text (stripped of leading `#` markers and surrounding whitespace). No fuzzy or regex matching.
- **First occurrence** — if two headings have the same text, only the first match's body is scoped. Disambiguate by editing the duplicate first or by using `section=None` (whole-file scope) with a more specific `pattern`.
- **MULTILINE default** — patterns are compiled with `re.MULTILINE`, so `^` and `$` match line boundaries. Use `\A`/`\Z` to anchor the whole scope.
- **Code-fence edge case** — `#`/`##` lines inside fenced code blocks (` ``` ` or `~~~`) are ignored for section detection, so fenced examples containing Markdown headings will not break section boundaries.
- **No match vs error** — `ok=false` with `error='no match'` means the file/section was found but the pattern did not match; any other `error` string indicates a validation or I/O failure. Handle them distinctly in the fallback logic above.

**9.** Edit flow:
1. Display amendments as a numbered list.
2. User specifies which to keep, modify, or drop.
3. Apply the edited subset using the same Apply flow (step 8).

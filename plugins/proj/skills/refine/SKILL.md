---
name: refine
description: Stress-test requirements with review agents (3 core + up to 4 tag/quality-based). Sub-skill invoked by run, not user-invocable.
allowed-tools: mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__content_patch_requirements, mcp__proj__content_patch_research, mcp__proj__proj_get_todo_context, mcp__proj__notes_append, Read, Glob, Grep, Task
argument-hint: "<todo-id>"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Refine todo: $ARGUMENTS

**Interaction rule**: Use `AskUserQuestion` for every user-facing prompt. No inline numbered lists for user input. Steps 7, 8.6, 9 route choices through `AskUserQuestion`. 4-opt cap applies.

**Quality level behavior** (controlled by `/proj:run`):
- `--fast`: refine skipped entirely
- `--careful`: refine auto-enabled

**1.** Parse `todo_id` from $ARGUMENTS.

**2.** Load ctx:
- `mcp__proj__proj_get_todo_context(todo_id, include_parent=true)`
- `mcp__proj__content_get_requirements(todo_id)`
- `mcp__proj__content_get_research(todo_id)`
- No requirements → note critical gap, continue (agents flag it).
- No research → note for Architecture Reviewer.

**3.** Determine agent set, spawn parallel (read-only: `Read, Glob, Grep`):

N roles = N agents — never combine. **Spawn via `TeamCreate` — never bare parallel Task calls for 2+ agents.** Before spawning: `TeamCreate(name="refine-review-{todo_id}", description="Refine review agents for todo {todo_id}")`, each Agent w/ `team_name="refine-review-{todo_id}"`. After all return (step 4): `TeamDelete(team_name="refine-review-{todo_id}")`.

### ASK_USER Escalation (review agents)

Review agents CANNOT call `AskUserQuestion` directly. Protocol:

1. Agent finds BLOCKING issue requiring user/architectural decision (not just a suggestion)
2. Agent → `SendMessage` to team-lead: `"ASK_USER: <issue details, decision needed, options if applicable>"`
3. Lead calls `AskUserQuestion` w/ agent's question + options
4. User answers
5. Lead → `SendMessage` answer back: `"ASK_USER_RESPONSE: <answer>"`
6. Agent incorporates answer into findings report

Agents must NOT auto-demote blocking findings or guess architectural intent. Non-blocking suggestions → include in Suggestions section, no escalation.

Load todo `tags`. Select agents per logic below. Spawn all selected parallel. Each agent receives todo-specific ctx only (role/expertise defined in agent .md file):

**Agent 1 — Skeptic** (core):
`Agent(subagent_type="skeptic-reviewer", prompt="Todo {todo_id}: {title}\nRequirements:\n{requirements}\nResearch:\n{research}")`

**Agent 2 — Edge-Case Finder** (core):
`Agent(subagent_type="edge-case-finder", prompt="Todo {todo_id}: {title}\nRequirements:\n{requirements}\nResearch:\n{research}")`

**Agent 3 — Architecture Reviewer** (core):
`Agent(subagent_type="architecture-reviewer", prompt="Todo {todo_id}: {title}\nRequirements:\n{requirements}\nResearch:\n{research}")`

**Agent 4 — Security Reviewer** (tags: `security` or `breaking-change`):
`Agent(subagent_type="security-reviewer", prompt="Todo {todo_id}: {title}\nRequirements:\n{requirements}\nResearch:\n{research}")`

**Agent 5 — Performance Reviewer** (tag: `performance`):
`Agent(subagent_type="performance-reviewer", prompt="Todo {todo_id}: {title}\nRequirements:\n{requirements}\nResearch:\n{research}")`

**Agent 6 — API & Contract Reviewer** (tag: `api`):
`Agent(subagent_type="api-contract-reviewer", prompt="Todo {todo_id}: {title}\nRequirements:\n{requirements}\nResearch:\n{research}")`

**Agent 7 — Complexity Reviewer** (tags: `complexity` or `architecture`, or always under `--careful`):
`Agent(subagent_type="complexity-reviewer", prompt="Todo {todo_id}: {title}\nRequirements:\n{requirements}\nResearch:\n{research}")`

**Agent selection:**
- Core (1-3): ALWAYS run.
- Tag-based (4-6): `security`/`breaking-change` → Agent 4; `performance` → Agent 5; `api` → Agent 6.
- `--careful` → ALL 7 despite tags.
- Respect quality_level `max_parallel` when spawning.

Each agent receives: todo ctx, requirements.md, research.md, codebase read access.

Each agent produces exact structure:

```markdown
## [Role Name] Findings

### Critical Issues (must address)
- [issue description + why it matters + suggested fix]

### Suggestions (would improve)
- [suggestion + rationale]

### Confirmed Sound
- [aspect that was reviewed and found correct]
```

Agent finds nothing → all sections present; Critical Issues/Suggestions empty; Confirmed Sound lists what validated.

**4.** Wait all agents. Agent fails/times out → report partial results, note failure. After collecting: `TeamDelete(team_name="refine-review-{todo_id}")`.

**5.** Synthesize Refinement Report — each agent gets summary block:

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

**6.** All-clear (zero criticals AND zero suggestions across all agents):
```
### Refinement Report

No concerns found. All <N> reviewers confirmed the requirements and research are sound.

Proceeding to plan mode.
```
Auto-continue, no prompt.

**7.** Issues found → `AskUserQuestion` **once** w/ exactly 4 opts:
- `Apply` — Update requirements.md/research.md w/ all amendments
- `Edit` — Modify amendments before applying (→ step 9)
- `Skip` — Proceed to plan mode, no changes
- `Stop` — Exit workflow

Pass refinement report summary (agent counts, criticals, amendments) as question ctx. Do NOT print inline numbered list.

**Non-interactive fallback** (`--no-interactive`): Apply/Reject → `Skip` (logged); step 8.6 → `Continue`; step 9 → `Keep-all`. No `AskUserQuestion` calls.

**8.** Apply flow:
1. Backup: `content_get_requirements` → store `pre_refine_requirements`. Research exists → same.
2. Merge accepted amendments into content.
3. **Preferred (section-localized patch):** Each amendment: classify as section-localized (within one `##`/`###` block) or wholesale. Section-localized → `content_patch_requirements(section=<heading>, pattern=<escaped old>, replacement=<new>)`. `ok=false` w/ err != 'no match' → log, fall back `content_set_requirements`. 'no match' → refresh via `content_get_requirements`, retry fallback.
4. **Fallback:** `content_set_requirements` w/ updated content.
5. Research amendments → `content_patch_research` same classification; fallback `content_set_research`.
6. Show: "Requirements updated with N amendments."
7. Re-run 5 preflight checks (same as `/proj:run` preflight). New failures → `AskUserQuestion` **once** w/ 3 opts, include failing check names in question:
 - `Fix` — Spawn fix pass
 - `Continue` — Proceed despite failures
 - `Undo amendments` — Restore pre-refine backup
 No inline numbered list.
8. Undo: restore from `pre_refine_requirements` via `content_set_requirements`.

**Patch tool notes:**
- **Literal section match** — `section` compared literal, case-sensitive against heading text (stripped `#` markers/whitespace). No fuzzy/regex.
- **First occurrence** — duplicate headings → only first scoped. Disambiguate by editing duplicate first or `section=None` (whole-file) w/ more specific `pattern`.
- **MULTILINE default** — `re.MULTILINE`, `^`/`$` match line boundaries. Use `\A`/`\Z` for whole-scope anchors.
- **Code-fence edge case** — `#`/`##` inside fenced blocks (` ``` `/`~~~`) ignored for section detection.
- **No match vs err** — `ok=false` w/ `error='no match'` = file/section found, pattern didn't match; other `error` = validation/IO failure. Handle distinctly in fallback.

**9.** Edit flow:
1. Each amendment (one at time) → `AskUserQuestion` w/ 4 opts:
 - `Keep` — Accept as-is
 - `Modify` — Rewrite (follow-up via second `AskUserQuestion` only if unavoidable)
 - `Drop` — Exclude
 - `Stop` — Halt edit flow; apply only decisions so far
 Pass amendment text + source agent as question ctx. One `AskUserQuestion` per amendment — no batching, no inline list.
2. Apply edited subset via same Apply flow (step 8).

## Agent Fallback

If `subagent_type="<name>"` not found (agent .md file missing/renamed):
1. Log warning via `notes_append`: "Agent definition '<name>' not found, falling back to general-purpose"
2. Use `Agent(subagent_type="general-purpose", prompt=<inline_fallback>)` w/ minimal role desc
3. Fallback prompts (one-line per agent):
   - `skeptic-reviewer`: "Challenge requirements/research. Find assumptions stated as facts, contradictions, untestable criteria, scope creep. Report new findings only."
   - `edge-case-finder`: "Identify scenarios requirements miss: boundary conditions, null/empty inputs, concurrency, backwards compat, err propagation. Report new findings only."
   - `architecture-reviewer`: "Check proposed approach against codebase patterns. Flag deviations, missed reuse opportunities, coupling concerns. Report new findings only."
   - `security-reviewer`: "Audit requirements/approach for auth gaps, injection vectors, secrets handling, access control bypasses. Report new findings only."
   - `performance-reviewer`: "Identify perf risks: algorithmic complexity, memory leaks, N+1 queries, missing pagination, lock contention. Report new findings only."
   - `api-contract-reviewer`: "Evaluate interface design + backwards compat. Flag breaking changes, param naming issues, missing versioning. Report new findings only."
   - `complexity-reviewer`: "Assess long-term code health: DRY violations, high cyclomatic complexity, SRP violations, tight coupling, test coverage gaps. Report new findings only."

---
name: define
description: Gather requirements and research implementation approach for a todo. Runs interactive Q&A, then researches the codebase. Use when asked "define 1", "clarify requirements for 1", or "research 1".
allowed-tools: mcp__proj__proj_get_todo_context, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__todo_set_content_flag, mcp__proj__claudemd_write, mcp__proj__tracking_git_flush, mcp__proj__proj_search_knowledge, mcp__proj__proj_decision_log, EnterPlanMode, ExitPlanMode, Read, Glob, Grep, WebSearch, WebFetch, Task, AskUserQuestion
argument-hint: "<todo-id> [--no-interactive] [--skip-bg-prep]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Define and research todo: $ARGUMENTS

**1.** Parse args

Extract from $ARGUMENTS:
- `todo_id` = first non-flag token
- `no_interactive` = `true` if `--no-interactive` present
- `skip_bg_prep` = `true` if `--skip-bg-prep` present

Empty `todo_id` → stop: "Todo ID required. Usage: `/proj:define <todo-id>`"

`no_interactive` true → skip to **Non-interactive path**.


## Interactive path

**2.** Load ctx

`mcp__proj__proj_get_todo_context(todo_id)`.

Not found → stop: "Todo <id> not found. Run `/proj:todo list` to see available todos."

Review existing req/research/notes. Store for later.

**2b.** Search prior decisions

`mcp__proj__proj_decision_log(action="search", decision=<todo title>)`. Results found → use as bg ctx during Q&step 5. Ref prior decisions when formulating questions/interpreting answers.

**2c.** Bg codebase exploration (skip if `skip_bg_prep`)

Extract keywords from todo title/desc/notes.

Spawn via `TeamCreate(name="define-bg-{todo_id}", description="Background codebase exploration for todo {todo_id}")` — never bare parallel Task calls for 2+ agents. Each agent gets `team_name="define-bg-{todo_id}"`. Team torn down at step 5.5 via `TeamDelete`.

Two bg Task agents (general-purpose, read-only: `Read, Glob, Grep`):

 **Agent A — File discovery:**
 - Glob files matching title keywords (*.py, *.ts, *.md, etc.)
 - Grep fn/class/var names related to todo
 - Return: relevant file paths w/ 1-line desc

 **Agent B — Test/pattern exploration:**
 - Find test dirs related to todo domain
 - Read up to 5 test files for existing patterns
 - Read up to 3 most relevant source files
 - Return: patterns found, key fn signatures, test conventions

Store handles as `bg_explore_agents`. Do NOT wait — → step 3.

### ASK_USER Escalation (bg agents)

Bg agents CANNOT call `AskUserQuestion` directly. Protocol:

1. Agent detects critical finding requiring user decision (e.g. scope conflict, missing dep, architectural blocker)
2. Agent → `SendMessage` to team-lead: `"ASK_USER: <finding details, options if applicable>"`
3. Lead calls `AskUserQuestion` w/ agent's question + options
4. User answers
5. Lead → `SendMessage` answer back: `"ASK_USER_RESPONSE: <answer>"`
6. Agent continues w/ answer

Agents must NOT improvise, guess, or silently continue when user input needed. Non-critical findings → include in return results, no escalation.

**3.** Entry mode selection

Existing req/research present → display under "Previous context" heading.

`AskUserQuestion` w/ single question, 3-4 options:
- **Describe goals now** — free-form goals, constraints, ctx
- **Use existing notes as-is** — proceed w/ prev ctx unchanged
- **Load from similar prior todo** — pull req from related completed todo
- **Skip directly to Q&A** — jump to gap-driven probing

Record `entry_mode`. "Describe goals now" → prompt for free-form text. Otherwise set freeform input to existing ctx (or empty).

**4.** Gap analysis

Analyze freeform input + prev ctx for:
- Vague/untestable language ("should be fast", "handle errors properly")
- Missing acceptance criteria
- Unclear scope boundaries
- Missing edge cases
- Missing testing strategy
- Implicit assumptions needing explicitness

Produce structured gap list. Classify each:
- **CRITICAL** — blocks writing quality req doc (must resolve)
- **MINOR** — can infer without prompting

Present gap list to user before proceeding.

**5.** Probing Q&A

Drive questions from gap analysis — no predefined category lists. Rules:
- Batch all CRITICAL gaps into one `AskUserQuestion` (max 4/call). 5+ gaps → additional rounds.
- MINOR gaps filled by inference silently — never in `AskUserQuestion`.
- Every batched question MUST include 1-2 sentence rationale: **decision impact** (what this controls in req doc) + **default-option reasoning** (why pre-selected opt is safe default).
- User uncertain → multiple-choice opts present 2-3 concrete tradeoffs. Open-ended only if truly unavoidable.
- Continue batched rounds until all CRITICAL gaps addressed.
- Record every Q&pair (incl rationale) as transcript.

User contradicts/corrects prior assumption → immediately `mcp__proj__proj_decision_log(action="add", decision=<correction>, tags="correction", context="define:qa:{todo_id}", todo_id={todo_id})`.

All CRITICAL gaps resolved → route via `AskUserQuestion`: "All critical gaps covered. How proceed?"
- **Proceed** — write req/research now
- **Address minor gaps** — batch remaining MINOR gaps via `AskUserQuestion`
- **Add something else** — open-ended follow-up before writing

"Address minor gaps" → additional batched rounds for MINOR gaps. "Add something else" → accept input, return to completion branch.

**Degraded-harness fallback**: `AskUserQuestion` unavailable or `--no-interactive` → log deterministic default answer each gap w/ `source: "degraded-harness-default"` in transcript. Default MUST match pre-selected opt from batched call.

**5.5.** Collect bg exploration (if `bg_explore_agents` exist)

Wait for completion. Merge into `bg_file_discovery` + `bg_pattern_summary`. Call `TeamDelete(team_name="define-bg-{todo_id}")`. Agents failed → log warning, continue — results advisory only.

**6.** Write req and research

Write `requirements.md`:

```markdown
# Requirements: <todo title>

## Goal
<what this achieves>

## Acceptance Criteria
- [ ] <criterion 1>
- [ ] <criterion 2>

## Edge Cases
- <edge case 1>
- <edge case 2>

## Out of Scope
- <what NOT to do>

## Testing Strategy
<how to verify this works>

## Q&A Transcript
**Q:** <question>
**A:** <answer>
```

Research codebase (`Read`, `Glob`, `Grep`) and external sources (`WebSearch`, `WebFetch`) as needed. Include `bg_file_discovery` + `bg_pattern_summary` — skip re-exploring files already covered by bg agents. Evaluate 2-3 impl approaches.

Write `research.md`:

```markdown
# Research: <todo title>

## Approach Options
### Option 1: <name>
<description, pros, cons>

### Option 2: <name>
<description, pros, cons>

## Recommended Approach
<which option and why>

## Key Dependencies
- <library/API/file>

## Risks
- <risk 1>

## References
- <link or file path>
```

`mcp__proj__content_set_requirements(requirements)`.
`mcp__proj__content_set_research(research)`.

Each major architectural/design decision (chosen approach, key constraint, scope boundary) → `mcp__proj__proj_decision_log(action="add", decision=<concise statement>, tags="requirements", todo_id={todo_id})`. Decisions self-contained, referenceable in future sessions.

**7.** Quality gate loop (hard block)

Validate req against ALL criteria:
- [ ] Every acceptance criterion testable (specific, measurable)
- [ ] No vague language ("fast", "properly", "good", "clean", etc.)
- [ ] At least 2 edge cases documented
- [ ] Out of Scope present and non-empty
- [ ] Testing strategy present and actionable

**PASS** → step 8.

**FAIL** → present failing criteria, offer:
> 1. **Fix** — iterate failing sections, re-run gate
> 2. **Restart** — back to step 3 w/ cur req as bg ctx

Fix → revise sections, `mcp__proj__content_set_requirements`, re-run gate.
Restart → return step 3, show cur req as "Previous context".

3 consecutive gate iterations w/o pass → suggest Restart:
> "3rd gate iteration. Consider restarting from free-form writing to reframe req from scratch."

Do NOT proceed past this step until gate passes.

**8.** CLAUDE.md update

`mcp__proj__claudemd_write` — update w/ project-wide rules, style conventions, standards, impl hints discovered during define session. Only broad project rules. No todo-specific details — those belong in requirements.md.

**9.** Git tracking flush

`mcp__proj__tracking_git_flush(commit_message="Define: {todo-id}")`.
`mcp__proj__todo_set_content_flag(has_requirements=True, has_research=True)`.

Suggested next: `1. /proj:decompose <id>` -- break into subtasks | `2. /proj:execute <id>` -- if straightforward, execute directly


## Non-interactive path

*(Reached when `--no-interactive` present in $ARGUMENTS)*

**NI-1. Load ctx**

`mcp__proj__proj_get_todo_context(todo_id)`.

Not found → stop: "Todo <id> not found. Run `/proj:todo list` to see available todos."

**NI-1b. Search prior decisions**

`mcp__proj__proj_decision_log(action="search", decision=<todo title>)`. Results found → review before exploring codebase.

**NI-1c.** Bg codebase exploration (skip if `skip_bg_prep`)

Same as step 2c: extract keywords, spawn via `TeamCreate(name="define-bg-{todo_id}", description="Background codebase exploration for todo {todo_id}")`, two read-only bg Task agents (Agent file discovery, Agent B test/pattern exploration) w/ `team_name="define-bg-{todo_id}"`. Store as `bg_explore_agents`. Do NOT wait — proceed NI-2. Team torn down at NI-2.5.

**NI-2. Explore codebase**

Use `Read`, `Glob`, `Grep` for existing patterns, relevant code, impl ctx. Be thorough — replaces interactive Q&A.

**NI-2.5.** Collect bg exploration (if `bg_explore_agents` exist)

Wait for completion. Merge into `bg_file_discovery` + `bg_pattern_summary`. `TeamDelete(team_name="define-bg-{todo_id}")`. Agents failed → log warning, continue.

**NI-3. Write req and research**

Write both `requirements.md` and `research.md` from todo ctx + codebase exploration. Same formats as step 6. Include `bg_file_discovery` + `bg_pattern_summary` — skip re-exploring covered files.

`mcp__proj__content_set_requirements(requirements)`.
`mcp__proj__content_set_research(research)`.

**NI-4. Self-assessment**

Rate confidence each section on 5-point scale:

| Section             | Score | Meaning of 1 | Meaning of 5 |
|---------------------|-------|---------------|---------------|
| Goal                | ?/5   | speculative   | certain       |
| Acceptance Criteria | ?/5   | speculative   | certain       |
| Edge Cases          | ?/5   | speculative   | certain       |
| Out of Scope        | ?/5   | speculative   | certain       |
| Testing Strategy    | ?/5   | speculative   | certain       |

Output confidence table, then list actionable gaps w/ suggested fixes:
> **Gaps:**
> - <gap desc> — suggested fix: <what to do>

**NI-5. Finalize**

`mcp__proj__proj_decision_log(action="add", decision=<one-sentence inferred approach summary>, tags="auto", todo_id={todo_id})`.
`mcp__proj__todo_set_content_flag(has_requirements=True, has_research=True)`.
`mcp__proj__claudemd_write` — project-wide rules/standards only, no todo-specific details.
`mcp__proj__tracking_git_flush(commit_message="Define: {todo-id}")`.

## Prerequisites

- Active project loaded.
- Valid todo ID provided.

## Err Handling

- No todo ID → "Todo ID required. Usage: `/proj:define <todo-id>`" + stop.
- Todo not found → "Todo `<id>` not found. Run `/proj:todo list` to see available todos." + stop.
- Quality gate fail → present failing criteria, offer Fix/Restart. Blocks until pass.
- Skill invocation fail → hard stop.

## Output

- **Interactive**: requirements.md + research.md written to todo content dir. Quality gate pass confirmation. CLAUDE.md updated w/ project-wide rules.
- **Non-interactive**: requirements.md + research.md written + confidence self-assessment table + actionable gaps list.

Suggested next: `1. /proj:decompose <id>` -- break into subtasks | `2. /proj:execute <id>` -- if straightforward, execute directly

## Agent Fallback

If `subagent_type="<name>"` not found (agent .md file missing/renamed):
1. Log warning via `notes_append`: "Agent definition '<name>' not found, falling back to general-purpose"
2. Use `Agent(subagent_type="general-purpose", prompt=<inline_fallback>)` w/ minimal role desc
3. Fallback prompts (one-line per agent):
   - `file-discovery`: "Explore codebase for files relevant to this todo. Glob + Grep keywords from title/desc. Return file list w/ relevance notes."
   - `pattern-explorer`: "Find test dirs + source files related to todo domain. Read up to 5 test files + 3 source files. Return patterns, fn signatures, test conventions."

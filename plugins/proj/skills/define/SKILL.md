---
name: define
description: Gather requirements and research implementation approach for a todo. Runs interactive Q&A, then researches the codebase. Use when asked "define 1", "clarify requirements for 1", or "research 1".
allowed-tools: mcp__proj__proj_get_todo_context, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__todo_set_content_flag, mcp__proj__claudemd_write, mcp__proj__tracking_git_flush, mcp__proj__proj_search_knowledge, mcp__proj__proj_decision_log, EnterPlanMode, ExitPlanMode, Read, Glob, Grep, WebSearch, WebFetch, Task, AskUserQuestion
argument-hint: "<todo-id> [--no-interactive] [--skip-bg-prep]"
---

Define and research todo: $ARGUMENTS

**1.** Parse arguments

Extract from $ARGUMENTS:
- `todo_id` = the first non-flag token (the todo ID)
- `no_interactive` = `true` if `--no-interactive` is present in $ARGUMENTS
- `skip_bg_prep` = `true` if `--skip-bg-prep` is present in $ARGUMENTS

If `todo_id` is empty or not present, stop and output:
"Todo ID required. Usage: `/proj:define <todo-id>`"

If `no_interactive` is true, skip directly to the **Non-interactive path** below.

---

## Interactive path

**2.** Load context

Call `mcp__proj__proj_get_todo_context` with the todo ID.

If the result indicates the todo was not found (null todo or error), stop and output:
"Todo <id> not found. Run `/proj:todo list` to see available todos."

Review existing requirements, research, and notes. Store them for later reference.

**2b.** Search prior decisions

Call `mcp__proj__proj_decision_log` with `action="search"` and `decision=<todo title>` to surface prior decisions. If results are found, **use them as background context during the Q&A in step 5** — not just display them. Reference prior decisions when formulating questions and interpreting answers.

**2c.** Background codebase exploration (skip if `skip_bg_prep` is true)

Extract keywords from the todo title and description/notes.

Spawn two background Task agents (general-purpose, read-only tools only: `Read, Glob, Grep`):

  **Agent A — File discovery:**
    - Glob for files matching title keywords (*.py, *.ts, *.md, etc.)
    - Grep for function/class/variable names related to the todo
    - Return: list of relevant file paths with 1-line descriptions

  **Agent B — Test/pattern exploration:**
    - Identify test directories related to the todo's domain
    - Read up to 5 test files to understand existing patterns
    - Read up to 3 source files that appear most relevant
    - Return: summary of patterns found, key function signatures, test conventions

Store agent handles as `bg_explore_agents`.
Do NOT wait for them — proceed to step 3 immediately.

**3.** Entry mode selection

If existing requirements or research are present, display them under a "Previous context" heading so the user can see what already exists.

Call `AskUserQuestion` with a single question offering 3-4 starter options. Example options:
- **Describe goals now** — free-form write goals, constraints, and context
- **Use existing notes as-is** — proceed with previous context unchanged
- **Load from similar prior todo** — pull requirements from a related completed todo
- **Skip directly to Q&A** — jump straight to gap-driven probing without free-form input

Record the selected value as `entry_mode`. If the user chose "Describe goals now", prompt for the free-form text and record it as the freeform input. Otherwise, set the freeform input to the existing context (or empty) and proceed.

**4.** Gap analysis

Analyze the freeform input (plus any previous context) for:
- Vague or untestable language (e.g., "should be fast", "handle errors properly")
- Missing acceptance criteria
- Unclear scope boundaries
- Missing edge cases
- Missing testing strategy
- Implicit assumptions that need to be explicit

Produce a structured gap list. Classify each gap as:
- **CRITICAL** — blocks writing a quality requirements doc (must be resolved)
- **MINOR** — can be inferred without prompting

Anchor definition: **CRITICAL = blocks quality requirements doc; MINOR = can be inferred without prompting.** CRITICAL gaps MUST be raised to the user via `AskUserQuestion` in step 5. MINOR gaps are filled by inference and recorded silently in the transcript.

Present the gap list to the user before proceeding.

**5.** Probing Q&A

Drive questions from the gap analysis — do NOT use predefined category lists. Rules:
- Batch all CRITICAL gaps into one `AskUserQuestion` call (up to 4 questions per call). Split into additional rounds for 5+ gaps.
- MINOR gaps are filled by inference without prompting — do NOT include them in `AskUserQuestion` calls.
- Every batched question MUST include a 1-2 sentence rationale in its `question` or `description` field covering **decision impact** (what this controls in the requirements doc) and **default-option reasoning** (why the pre-selected option is a safe default).
- When the user is uncertain about a question, the multiple-choice options must themselves present 2-3 concrete tradeoffs — do not fall back to open-ended text unless truly unavoidable.
- Continue batched rounds until all CRITICAL gaps are addressed.
- Record every Q&A pair (including the rationale text shown) as a transcript.

When the user contradicts or corrects a prior assumption during Q&A, immediately call `mcp__proj__proj_decision_log` with `action="add"`, `decision=<the correction>`, `tags="correction"`, `context="define:qa:{todo_id}"`, `todo_id={todo_id}`.

When all CRITICAL gaps are resolved, route the completion branch through `AskUserQuestion` as well. Call it with one question — "All critical gaps are covered. How would you like to proceed?" — and these enumerable options:
- **Proceed** — write requirements and research now
- **Address minor gaps** — batch remaining MINOR gaps via `AskUserQuestion` instead of inferring
- **Add something else** — open-ended follow-up before writing

If the user picks "Address minor gaps", continue with additional batched `AskUserQuestion` rounds covering the MINOR gaps. If "Add something else", accept open-ended input, then return to this completion branch.

**Degraded-harness fallback**: when `AskUserQuestion` is unavailable or the skill is invoked under `--no-interactive`, log a deterministic default answer for each gap with `source: "degraded-harness-default"` in the transcript and proceed. The default MUST match the pre-selected option that the batched `AskUserQuestion` call would have surfaced.

**5.5.** Collect background exploration (if `bg_explore_agents` exist)

Wait for `bg_explore_agents` to complete.
Merge results into `bg_file_discovery` (list of relevant files) and `bg_pattern_summary` (patterns and conventions observed).
If agents failed, log warning and continue — results are advisory only.

**6.** Write requirements and research

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

Research the codebase (Read, Glob, Grep) and external sources (WebSearch, WebFetch) as needed. Include `bg_file_discovery` and `bg_pattern_summary` as additional input when researching — skip re-exploring files already covered by background agents. Evaluate 2-3 implementation approaches.

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

Call `mcp__proj__content_set_requirements` with the requirements content.
Call `mcp__proj__content_set_research` with the research content.

For each major architectural or design decision made during this session (chosen approach, key constraint, scope boundary), call `mcp__proj__proj_decision_log` with `action="add"`, `decision=<concise decision statement>`, `tags="requirements"`, `todo_id={todo_id}`. Decisions should be self-contained and referenceable in future sessions.

**7.** Quality gate loop (hard block)

Validate the written requirements against ALL of the following criteria:
- [ ] Every acceptance criterion is testable (specific, measurable)
- [ ] No vague language remains ("fast", "properly", "good", "clean", etc.)
- [ ] At least 2 edge cases documented
- [ ] Out of Scope section is present and non-empty
- [ ] Testing strategy is present and actionable

**PASS** — all criteria met. Proceed to step 8.

**FAIL** — present the failing criteria to the user and offer:
> 1. **Fix** — iterate on the failing sections and re-run the quality gate
> 2. **Restart** — go back to step 3 with current requirements as background context

If the user picks Fix: revise the relevant sections, re-write via `mcp__proj__content_set_requirements`, and re-run the gate.

If the user picks Restart: return to step 3, showing current requirements as "Previous context".

After 3 consecutive gate iterations without passing, suggest Restart:
> "This is the 3rd gate iteration. Consider restarting from free-form writing to reframe the requirements from scratch."

Do NOT proceed past this step until the gate passes.

**8.** CLAUDE.md update

Call `mcp__proj__claudemd_write` to update CLAUDE.md with any project-wide rules, style conventions, standards, or implementation hints discovered during this define session.

Only write rules that apply broadly to the project. Do NOT write todo-specific details — those belong in requirements.md.

**9.** Git tracking flush

Call `mcp__proj__tracking_git_flush` with `commit_message="Define: {todo-id}"`.
Call `mcp__proj__todo_set_content_flag` with `has_requirements=True` and `has_research=True`.

Suggested next: `1. /proj:decompose <id>` -- break into subtasks | `2. /proj:execute <id>` -- if straightforward, execute directly

---

## Non-interactive path

*(Reached when `--no-interactive` is present in $ARGUMENTS)*

**NI-1. Load context**

Call `mcp__proj__proj_get_todo_context` with the todo ID.

If the result indicates the todo was not found (null todo or error), stop and output:
"Todo <id> not found. Run `/proj:todo list` to see available todos."

**NI-1b. Search prior decisions**

Call `mcp__proj__proj_decision_log` with `action="search"` and `decision=<todo title>` to surface prior decisions. If results found, review them before exploring the codebase.

**NI-1c.** Background codebase exploration (skip if `skip_bg_prep` is true)

Same as step 2c: extract keywords, spawn two read-only background Task agents (Agent A for file discovery, Agent B for test/pattern exploration). Store handles as `bg_explore_agents`. Do NOT wait — proceed to NI-2 immediately.

**NI-2. Explore codebase**

Use Read, Glob, and Grep to explore the codebase for existing patterns, relevant code, and implementation context. Be thorough — this replaces the interactive Q&A.

**NI-2.5.** Collect background exploration (if `bg_explore_agents` exist)

Wait for `bg_explore_agents` to complete. Merge results into `bg_file_discovery` and `bg_pattern_summary`. If agents failed, log warning and continue.

**NI-3. Write requirements and research**

Write both `requirements.md` and `research.md` directly from the todo context and codebase exploration. Use the same formats as step 6. Include `bg_file_discovery` and `bg_pattern_summary` as additional input — skip re-exploring files already covered by background agents.

Call `mcp__proj__content_set_requirements` with the requirements content.
Call `mcp__proj__content_set_research` with the research content.

**NI-4. Self-assessment**

Rate confidence for each section on a 5-point scale:

| Section             | Score | Meaning of 1 | Meaning of 5 |
|---------------------|-------|---------------|---------------|
| Goal                | ?/5   | speculative   | certain       |
| Acceptance Criteria | ?/5   | speculative   | certain       |
| Edge Cases          | ?/5   | speculative   | certain       |
| Out of Scope        | ?/5   | speculative   | certain       |
| Testing Strategy    | ?/5   | speculative   | certain       |

Output the confidence table, then list actionable gaps with suggested fixes:
> **Gaps:**
> - <gap description> — suggested fix: <what to do>

**NI-5. Finalize**

Call `mcp__proj__proj_decision_log` with `action="add"`, `decision=<one-sentence summary of the inferred approach>`, `tags="auto"`, `todo_id={todo_id}`.

Call `mcp__proj__todo_set_content_flag` with `has_requirements=True` and `has_research=True`.

Call `mcp__proj__claudemd_write` to update CLAUDE.md with any project-wide rules or standards discovered. Only project-wide rules, not todo-specific details.

Call `mcp__proj__tracking_git_flush` with `commit_message="Define: {todo-id}"`.

## Prerequisites

- An active project must be loaded.
- A valid todo ID must be provided.

## Error Handling

- **No todo ID**: displays "Todo ID required. Usage: `/proj:define <todo-id>`" and stops.
- **Todo not found**: displays "Todo `<id>` not found. Run `/proj:todo list` to see available todos." and stops.
- **Quality gate failure**: presents failing criteria and offers Fix or Restart options. Blocks progress until gate passes.
- **Skill invocation failure**: treated as a hard stop.

## Output

- **Interactive**: requirements.md and research.md written to the todo's content directory. Quality gate pass confirmation. CLAUDE.md updated with project-wide rules.
- **Non-interactive**: requirements.md and research.md written, plus a confidence self-assessment table and actionable gaps list.

Suggested next: `1. /proj:decompose <id>` -- break into subtasks | `2. /proj:execute <id>` -- if straightforward, execute directly

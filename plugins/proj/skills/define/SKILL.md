---
name: define
description: Gather requirements and research implementation approach for a todo. Runs interactive Q&A, then researches the codebase. Use when asked "define 1", "clarify requirements for 1", or "research 1".
allowed-tools: mcp__proj__proj_get_todo_context, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__todo_set_content_flag, mcp__proj__claudemd_write, mcp__proj__tracking_git_flush, EnterPlanMode, ExitPlanMode, Read, Glob, Grep, WebSearch, WebFetch, Task
argument-hint: "<todo-id> [--no-interactive]"
---

Define and research todo: $ARGUMENTS

**1. Parse arguments**

Extract from $ARGUMENTS:
- `todo_id` = the first non-flag token (the todo ID)
- `no_interactive` = `true` if `--no-interactive` is present in $ARGUMENTS

If `todo_id` is empty or not present, stop and output:
"Todo ID required. Usage: /proj:define <todo-id>"

If `no_interactive` is true, skip directly to the **Non-interactive path** below.

---

## Interactive path

**2. Load context**

Call `mcp__proj__proj_get_todo_context` with the todo ID.

If the result indicates the todo was not found (null todo or error), stop and output:
"Todo <id> not found."

Review existing requirements, research, and notes. Store them for later reference.

**3. Free-form writing**

If existing requirements or research are present, display them under a "Previous context" heading so the user can see what already exists.

Prompt the user:
> "Describe the goals, constraints, and anything else important for this todo. Write as much or as little as you want — I'll ask follow-up questions next."

Record the user's response as the freeform input.

**4. Gap analysis**

Analyze the freeform input (plus any previous context) for:
- Vague or untestable language (e.g., "should be fast", "handle errors properly")
- Missing acceptance criteria
- Unclear scope boundaries
- Missing edge cases
- Missing testing strategy
- Implicit assumptions that need to be explicit

Produce a structured gap list. Classify each gap as:
- **CRITICAL** — blocks writing a quality requirements doc (must be resolved)
- **MINOR** — would improve the doc but can be inferred or defaulted

Present the gap list to the user before proceeding.

**5. Probing Q&A**

Drive questions from the gap analysis — do NOT use predefined category lists. Rules:
- Address CRITICAL gaps first, then MINOR gaps if the user is willing
- Ask one focused question at a time
- When the user is uncertain about a question, offer 2-3 concrete options with tradeoffs
- Continue until all CRITICAL gaps are addressed
- Record every Q&A pair as a transcript

When all CRITICAL gaps are resolved, ask:
> "All critical gaps are covered. Would you like to:"
> 1. Proceed — write requirements and research now
> 2. Address remaining minor gaps
> 3. Add something else

If the user picks 2, continue with MINOR gaps. If 3, continue open-ended Q&A.

**6. Write requirements and research**

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

Research the codebase (Read, Glob, Grep) and external sources (WebSearch, WebFetch) as needed. Evaluate 2-3 implementation approaches.

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

**7. Quality gate loop (hard block)**

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

**8. CLAUDE.md update**

Call `mcp__proj__claudemd_write` to update CLAUDE.md with any project-wide rules, style conventions, standards, or implementation hints discovered during this define session.

Only write rules that apply broadly to the project. Do NOT write todo-specific details — those belong in requirements.md.

**9. Git tracking flush**

Call `mcp__proj__tracking_git_flush` with `commit_message="Define: {todo-id}"`.
Call `mcp__proj__todo_set_content_flag` with `has_requirements=True` and `has_research=True`.

Suggested next: (1) /proj:decompose <id> — break into subtasks  (2) /proj:execute <id> — if straightforward, execute directly

---

## Non-interactive path

*(Reached when `--no-interactive` is present in $ARGUMENTS)*

**NI-1. Load context**

Call `mcp__proj__proj_get_todo_context` with the todo ID.

If the result indicates the todo was not found (null todo or error), stop and output:
"Todo <id> not found."

**NI-2. Explore codebase**

Use Read, Glob, and Grep to explore the codebase for existing patterns, relevant code, and implementation context. Be thorough — this replaces the interactive Q&A.

**NI-3. Write requirements and research**

Write both `requirements.md` and `research.md` directly from the todo context and codebase exploration. Use the same formats as step 6.

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

Call `mcp__proj__todo_set_content_flag` with `has_requirements=True` and `has_research=True`.

Call `mcp__proj__claudemd_write` to update CLAUDE.md with any project-wide rules or standards discovered. Only project-wide rules, not todo-specific details.

Call `mcp__proj__tracking_git_flush` with `commit_message="Define: {todo-id}"`.

Suggested next: (1) /proj:decompose <id> — break into subtasks  (2) /proj:execute <id> — if straightforward, execute directly

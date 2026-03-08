---
name: define
description: Gather requirements and research implementation approach for a todo. Runs interactive Q&A, then researches the codebase. Use when asked "define 1", "clarify requirements for 1", or "research 1".
disable-model-invocation: "true"
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

Call `mcp__proj__proj_get_todo_context` with the todo ID to get the todo, existing requirements, and research in one call.

If the result indicates the todo was not found (null todo or error), stop and output:
"Todo <id> not found."

Review existing requirements and research (if any) and identify what's still unclear. If the todo has a non-empty `notes` field, treat it as additional context — incorporate it into your understanding.

**3. Iterative Q&A loop** — ask questions until no meaningful gaps remain:

- Focus on: Goals, Acceptance Criteria, Edge Cases, Out of Scope, Testing Strategy
- Ask the single most important open question
- Record the answer
- Assess whether there are more important questions to ask
- Repeat until you've covered all critical aspects

**Final question (always last):**
> "Are you happy to proceed, or would you like to add more details first?"
> 1. Proceed — write requirements and research now
> 2. Add more details — ask another question

If the user picks "Add more details", continue the Q&A loop.

Record all Q&A pairs as a transcript.

**4. Plan the requirements and research**

Call `EnterPlanMode`. Based on the Q&A transcript and codebase knowledge, outline:
- Requirements document structure (goal, acceptance criteria, out of scope, testing)
- Research approach: which areas of the codebase to explore, what patterns to look for, 2-3 implementation approaches to consider

Call `ExitPlanMode` to present the outline for user review. The user will approve or request changes before you proceed to step 5.

**5. Research the codebase**

After plan approval, research the implementation approach:
- Explore the codebase for existing patterns (Read, Glob, Grep)
- Research external libraries or APIs if needed (WebSearch, WebFetch)
- Evaluate 2-3 different approaches based on what you find

**6. Write requirements and research**

Write `requirements.md`:

```markdown
# Requirements: <todo title>

## Goal
<what this achieves>

## Acceptance Criteria
- [ ] <criterion 1>
- [ ] <criterion 2>

## Out of Scope
- <what NOT to do>

## Testing Strategy
<how to verify this works>

## Q&A
**Q:** <question>
**A:** <answer>
```

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
Call `mcp__proj__todo_set_content_flag` with `has_requirements=True` and `has_research=True`.

---

## Non-interactive path

*(Reached when `--no-interactive` is present in $ARGUMENTS)*

**NI-1.** Call `mcp__proj__proj_get_todo_context` with the todo ID.

If the result indicates the todo was not found (null todo or error), stop and output:
"Todo <id> not found."

**NI-2.** Explore the codebase for existing patterns and relevant code (Read, Glob, Grep).

**NI-3.** Write both `requirements.md` and `research.md` directly from context (no Q&A, no plan mode). Use the same formats as step 6.

Call `mcp__proj__content_set_requirements` with the content.
Call `mcp__proj__content_set_research` with the content.
Call `mcp__proj__todo_set_content_flag` with `has_requirements=True` and `has_research=True`.

---

**7. Update CLAUDE.md**

If the project has a CLAUDE.md, call `mcp__proj__claudemd_write` to append or update the
requirements summary under a `## Requirements: <todo-title>` heading. Write a 1-3 sentence
summary of the goal and the key acceptance criteria.

8. **Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Define: {todo-id}"`.

Suggested next: (1) /proj:decompose <id> — break into subtasks  (2) /proj:execute <id> — if straightforward, execute directly

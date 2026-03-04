---
name: define
description: Gather detailed requirements for a todo through iterative Q&A. Use when the user says "define 1", "clarify requirements for 1", or "what does 1 need". Keeps asking questions until requirements are complete.
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_todo_context, mcp__proj__content_set_requirements, mcp__proj__todo_set_content_flag, mcp__proj__claudemd_write, mcp__proj__proj_get_active, mcp__proj__proj_resolve_agent, Task
argument-hint: "<todo-id> [--no-interactive]"
---

Gather requirements for todo: $ARGUMENTS

**1. Parse arguments**

Extract from $ARGUMENTS:
- `todo_id` = the first non-flag token (the todo ID)
- `no_interactive` = `true` if `--no-interactive` is present in $ARGUMENTS

If `no_interactive` is true, skip directly to the **Non-interactive path** below.

---

## Interactive path

**2. Load context**

Call `mcp__proj__proj_get_todo_context` with the todo ID to get the todo, existing requirements, and research in one call.

Review existing requirements (if any) and identify what's still unclear. If the todo has a non-empty `notes` field, treat it as additional context (e.g. description pulled from Todoist) — incorporate it into your understanding of the goal and use it to inform your questions and the final requirements.md.

**3. Iterative Q&A loop** — run entirely in the main conversation, ask questions until no meaningful gaps remain:

- Focus on: Goals, Acceptance Criteria, Edge Cases, Out of Scope, Testing Strategy
- Ask the single most important open question
- Record the answer
- Assess whether there are more important questions to ask
- Repeat until you've covered all critical aspects

Example questions to consider:
- "What is the exact goal of this task?"
- "How will you know when this is done? What are the acceptance criteria?"
- "Are there any edge cases or failure modes to handle?"
- "What should explicitly NOT be in scope?"
- "How should this be tested?"
- "Are there any technical constraints or dependencies?"

**Final question (always last):** Once you have covered the critical aspects, always end with:
> "Are you happy to proceed with writing the requirements, or would you like to add more details first?"
> 1. Proceed — write requirements now
> 2. Add more details — ask another question

If the user picks "Add more details", continue the Q&A loop. If they pick "Proceed" (or say yes/proceed/go), move to step 4.

Record all Q&A pairs as a transcript in this format:

```markdown
## Q&A Transcript

**Q:** <question>
**A:** <answer>

**Q:** <question>
**A:** <answer>
```

**4. Resolve agent and write requirements**

Call `mcp__proj__proj_resolve_agent` with `step="define"` (and `project_name` if known).

Parse the JSON result: `{"agent": "<name>", "warning": "<msg or null>"}`.
If `warning` is non-null: display it to the user.

**If `agent` is `"general-purpose"`:**

Write a structured `requirements.md` directly in the main conversation:

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

Call `mcp__proj__content_set_requirements` with the content.
Call `mcp__proj__todo_set_content_flag` with `has_requirements=True`.

**If `agent` differs from `"general-purpose"` (e.g. `"Plan"`):**

Spawn a Task agent of type `agent` with the following content:

```
Write requirements.md for todo <id>: <title>

Context:
<full todo context: title, notes, existing requirements if any, existing research if any>

Q&A Transcript (Q&A is already complete — do NOT ask any questions):
<full Q&A transcript from step 3, formatted as ## Q&A Transcript block>

Instructions:
1. Write a structured requirements.md based on the todo context and the Q&A transcript above.
2. Call mcp__proj__content_set_requirements with the complete requirements.md content.
3. Call mcp__proj__todo_set_content_flag with has_requirements=True.
4. Do NOT ask the user any questions — all Q&A is already complete.
```

---

## Non-interactive path

*(Reached when `--no-interactive` is present in $ARGUMENTS)*

**NI-1.** Call `mcp__proj__proj_get_todo_context` with the todo ID.

**NI-2.** Call `mcp__proj__proj_resolve_agent` with `step="define"` (and `project_name` if known).

Parse the JSON result: `{"agent": "<name>", "warning": "<msg or null>"}`.
If `warning` is non-null: display it.

**If `agent` is `"Plan"` (or other non-general-purpose agent):**

Spawn a Task agent of type `agent` with the following content:

```
Write requirements.md for todo <id>: <title> autonomously.

Context:
<full todo context: title, notes, existing requirements if any, existing research if any>

Instructions:
1. Write a complete structured requirements.md based on the todo context above.
2. Call mcp__proj__content_set_requirements with the complete requirements.md content.
3. Call mcp__proj__todo_set_content_flag with has_requirements=True.
4. Do NOT prompt the user — run fully autonomously.
```

**If `agent` is `"general-purpose"`:**

Write requirements.md directly from context (no Q&A):

```markdown
# Requirements: <todo title>

## Goal
<derived from todo context>

## Acceptance Criteria
- [ ] <criterion derived from context>

## Out of Scope
- <derived from context>

## Testing Strategy
<derived from context>
```

Call `mcp__proj__content_set_requirements` with the content.
Call `mcp__proj__todo_set_content_flag` with `has_requirements=True`.

---

**5. Update CLAUDE.md if the project has one.**

💡 Suggested next: (1) /proj:research <id> — research how to implement this  (2) /proj:execute <id> — if it's straightforward, execute directly

---
name: agents-create-define
description: Create a custom Claude Code agent file for the define (requirements) workflow step. Guides through name and specialization, then writes the agent to .claude/agents/ (project) or ~/.claude/agents/ (global). Use when the user says "create define agent", "new define agent", or "build requirements agent".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, Read, Glob, Write, Bash
argument-hint: "[--global] [agent-name]"
---

Create a custom Claude Code agent file for the **define** (requirements) workflow step. Arguments: $ARGUMENTS (optional — agent name; --global flag for global scope)

**Step 0: Determine scope**

Parse $ARGUMENTS for the `--global` flag.

- If `--global` is present in $ARGUMENTS: set scope = `global`. Remove `--global` from the arguments string before further parsing.
- If `--global` is NOT present: ask the user interactively:
  - "Create this agent for the current project or globally? (project / global)"
  - Set scope based on the answer (`project` or `global`).

**Step 1: Get target directory**

- If scope = `global`:
  - Target directory: `~/.claude/agents/`
  - Skip `proj_get_active` — no project context needed.
  - Use Bash to create the directory if needed: `mkdir -p ~/.claude/agents/`
- If scope = `project`:
  - Call `mcp__proj__proj_get_active` to get the active project. Extract the primary repo path from the first entry in `repos` (the `path` field). If no project is active, ask the user to run `/proj:load` first.
  - Target directory: `<repo-path>/.claude/agents/`

2. Explore existing agent files in the target directory:
   - Use Glob to list `<target-directory>/*.md` (only if the directory exists)
   - If any agent files exist, Read one or two to note their structure and conventions
   - Note any patterns (naming conventions, tool lists, system prompt style)

3. Determine the agent name. If a name was provided in the remaining arguments (after removing `--global`), use it. Otherwise ask:
   - "Agent name? (used as the filename — e.g. 'my-definer' → `<target-directory>/my-definer.md`)"
   - Name should be lowercase with hyphens (no spaces, no .md extension)

4. Overwrite check: construct the full target path `<target-directory>/<name>.md`. Use Bash to check if it exists:
   ```bash
   test -f <target-path> && echo "exists" || echo "not found"
   ```
   If it exists, prompt: "Agent `<name>` already exists at `<target-path>`. Overwrite? (y/N)" — abort if not confirmed.

5. Ask for specialization:
   - "What should this define agent specialize in? (e.g. domain expertise, specific question style, output format preferences, constraints to enforce)"

6. Generate the agent file with define-step defaults. For **global** scope, omit all project-specific context from the system prompt (no project name, CLAUDE.md content, or repo path references):

   ```markdown
   ---
   name: <name>
   description: <user's specialization summary — 1 sentence>
   tools: Read, Glob, Grep, mcp__proj__proj_get_todo_context, mcp__proj__content_set_requirements, mcp__proj__todo_set_content_flag, mcp__proj__proj_get_active
   ---

   You are a requirements-gathering agent specializing in <user's specialization>.

   Your role is to gather structured requirements for todos by asking targeted questions and writing a complete `requirements.md`. When gathering requirements:
   - Read the todo and any existing notes before starting the Q&A
   - Ask focused, specific questions — avoid open-ended questions when a precise one will do
   - Cover all five sections: Goal, Acceptance Criteria, Out of Scope, Testing Strategy, Q&A
   - Make Acceptance Criteria testable and specific (avoid vague terms like "works correctly")
   - Out of Scope should list explicit exclusions to prevent scope creep

   Output format for requirements.md:
   ```markdown
   # Requirements: <todo title>

   ## Goal
   <what we're building and why>

   ## Acceptance Criteria
   - [ ] <specific, testable condition>

   ## Out of Scope
   - <explicit exclusion>

   ## Testing Strategy
   <how to verify correctness>

   ## Q&A
   **Q:** <question>
   **A:** <answer>
   ```

   <Additional instructions based on user's specialization>

   Always call `mcp__proj__content_set_requirements` to save the requirements and `mcp__proj__todo_set_content_flag` with `has_requirements=true` when done.
   ```

   Incorporate the user's specialization details into the `<Additional instructions>` section. Be specific — if they say "focus on API contracts", add instructions about documenting request/response shapes, error codes, etc.

7. Write the file to `<target-path>` using the Write tool.

8. Display a confirmation:

   For **project** scope:
   ```
   Agent created at .claude/agents/<name>.md
   Register it with: /proj:agents-set define <name>
   ```

   For **global** scope:
   ```
   Agent created at ~/.claude/agents/<name>.md
   Global agents are available across all projects without registration.
   ```

Suggested next:
- Project scope:
  (1) /proj:agents-set define <name> — activate this agent for the define step
  (2) /proj:agents-list — view all current agent overrides
  (3) /proj:agents-create-research — create a research agent too
- Global scope:
  (1) /proj:create-agent --global research — create a global research agent too
  (2) /proj:agents-create-define — create a project-scoped define agent

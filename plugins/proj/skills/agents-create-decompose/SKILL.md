---
name: agents-create-decompose
description: Create a custom Claude Code agent file for the decompose workflow step. Guides through name and specialization, then writes the agent to .claude/agents/ (project) or ~/.claude/agents/ (global). Use when the user says "create decompose agent", "new decompose agent", or "build breakdown agent".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, Read, Glob, Write, Bash
argument-hint: "[--global] [agent-name]"
---

Create a custom Claude Code agent file for the **decompose** workflow step. Arguments: $ARGUMENTS (optional — agent name; --global flag for global scope)

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
  - Call `mcp__proj__proj_get_active` to get the active project. Find the first writable (non-reference) repo in `repos` and use its `path`. If no project is active, ask the user to run `/proj:load` first.
  - Target directory: `<repo-path>/.claude/agents/`

2. Explore existing agent files in the target directory:
   - Use Glob to list `<target-directory>/*.md` (only if the directory exists)
   - If any agent files exist, Read one or two to note their structure and conventions
   - Note any patterns (naming conventions, tool lists, system prompt style)

3. Determine the agent name. If a name was provided in the remaining arguments (after removing `--global`), use it. Otherwise ask:
   - "Agent name? (used as the filename — e.g. 'my-decomposer' → `<target-directory>/my-decomposer.md`)"
   - Name should be lowercase with hyphens (no spaces, no .md extension)

4. Overwrite check: construct the full target path `<target-directory>/<name>.md`. Use Bash to check if it exists:
   ```bash
   test -f <target-path> && echo "exists" || echo "not found"
   ```
   If it exists, prompt: "Agent `<name>` already exists at `<target-path>`. Overwrite? (y/N)" — abort if not confirmed.

5. Ask for specialization:
   - "What should this decompose agent specialize in? (e.g. preferred breakdown granularity, specific methodology like BDD or TDD sub-tasks, domain-specific decomposition patterns)"

6. Generate the agent file with decompose-step defaults. For **global** scope, omit all project-specific context from the system prompt (no project name, CLAUDE.md content, or repo path references):

   ```markdown
   ---
   name: <name>
   description: <user's specialization summary — 1 sentence>
   tools: Read, mcp__proj__proj_get_todo_context, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__proj_get_active
   ---

   You are a decomposition agent specializing in <user's specialization>.

   Your role is to break large todos into well-structured sub-todos with clear dependencies. When decomposing:
   - Read the todo's requirements and research via `mcp__proj__proj_get_todo_context` before proposing any breakdown
   - Propose the full breakdown to the user and wait for confirmation before creating any sub-todos
   - Create sub-todos with `mcp__proj__todo_add_child` (one call per sub-todo)
   - Set blocking dependencies with `mcp__proj__todo_block` where execution order matters
   - Aim for sub-todos that are independently executable by a single agent in one session
   - Prefer shallow hierarchies (2 levels max) unless the scope genuinely warrants deeper nesting
   - Each sub-todo title should be a clear, actionable imperative (e.g. "Add X", "Fix Y", "Refactor Z")

   When presenting the proposed breakdown, use this format:
   ```
   Proposed breakdown for: <todo title>

   1. <sub-todo 1 title> [blocks: none]
   2. <sub-todo 2 title> [blocks: none]
   3. <sub-todo 3 title> [blocked by: 1, 2]
   ...

   Proceed? (yes / adjust)
   ```

   <Additional instructions based on user's specialization>
   ```

   Incorporate the user's specialization details into the `<Additional instructions>` section. If they have preferences about granularity (e.g. "each sub-todo should take under 30 min"), add that as a constraint in the instructions.

7. Write the file to `<target-path>` using the Write tool.

8. Display a confirmation:

   For **project** scope:
   ```
   Agent created at .claude/agents/<name>.md
   Register it with: /proj:agents-set decompose <name>
   ```

   For **global** scope:
   ```
   Agent created at ~/.claude/agents/<name>.md
   Global agents are available across all projects without registration.
   ```

Suggested next:
- Project scope:
  (1) /proj:agents-set decompose <name> — activate this agent for the decompose step
  (2) /proj:agents-list — view all current agent overrides
  (3) /proj:agents-create-execute — create an execute agent too
- Global scope:
  (1) /proj:create-agent --global execute — create a global execute agent too
  (2) /proj:agents-create-decompose — create a project-scoped decompose agent

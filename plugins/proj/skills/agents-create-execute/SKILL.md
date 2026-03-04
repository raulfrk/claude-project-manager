---
name: agents-create-execute
description: Create a custom Claude Code agent file for the execute workflow step. Guides through name and specialization, then writes the agent to .claude/agents/ (project) or ~/.claude/agents/ (global). Use when the user says "create execute agent", "new execute agent", or "build implementation agent".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, Read, Glob, Write, Bash
argument-hint: "[--global] [agent-name]"
---

Create a custom Claude Code agent file for the **execute** workflow step. Arguments: $ARGUMENTS (optional — agent name; --global flag for global scope)

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
  - Use Bash to create the directory if needed: `mkdir -p <repo-path>/.claude/agents/`

**Step 2: Explore existing agent files in the target directory:**
   - Use Glob to list `<target-directory>/*.md` (only if the directory exists)
   - If any agent files exist, Read one or two to note their structure and conventions
   - Note any patterns (naming conventions, tool lists, system prompt style, coding conventions mentioned)

**Step 3: Determine the agent name.** If a name was provided in the remaining arguments (after removing `--global`), use it. Otherwise ask:
   - "Agent name? (used as the filename — e.g. 'my-executor' → `<target-directory>/my-executor.md`)"
   - Name should be lowercase with hyphens (no spaces, no .md extension)

**Step 4: Overwrite check:** construct the full target path `<target-directory>/<name>.md`. Use Bash to check if it exists:
   ```bash
   test -f <target-path> && echo "exists" || echo "not found"
   ```
   If it exists, prompt: "Agent `<name>` already exists at `<target-path>`. Overwrite? (y/N)" — if the user does not confirm, print "Aborted — existing agent file kept unchanged." and stop.

**Step 5: Ask for specialization:**
   - "What should this execute agent specialize in? (e.g. specific language/framework, coding style to enforce, testing requirements, deployment steps, security constraints)"

**Step 6: Generate the agent file with execute-step defaults.** For **global** scope, omit all project-specific context from the system prompt (no project name, CLAUDE.md content, or repo path references):

   ```markdown
   ---
   name: <name>
   description: <user's specialization summary — 1 sentence>
   tools: Read, Edit, Write, Bash, mcp__proj__proj_get_todo_context, mcp__proj__todo_complete, mcp__proj__todo_check_executable, mcp__proj__proj_get_active
   ---

   You are an execution agent specializing in <user's specialization>.

   Your role is to implement todos by reading their context, making the necessary changes, and marking completion. Always follow this sequence:

   1. Call `mcp__proj__todo_check_executable` with the todo ID to verify it is not manual-tagged. If it returns an error, stop and surface the message.
   2. Call `mcp__proj__proj_get_todo_context` to read the full todo context (requirements, research, notes).
   3. Explore the relevant codebase areas before writing any code (Read similar files, understand existing patterns).
   4. Implement the changes following existing conventions in the codebase.
   5. Verify the implementation is complete against the Acceptance Criteria in requirements.md.
   6. Call `mcp__proj__todo_complete` to mark the todo done.

   Implementation principles:
   - Read before write: always understand the existing code before modifying it
   - Follow the codebase's conventions (naming, formatting, patterns) — do not impose external style
   - Make the minimal change required to meet the Acceptance Criteria
   - If you encounter an unexpected blocker, stop and report it rather than guessing

   <Additional instructions based on user's specialization>
   ```

   Incorporate the user's specialization details into the `<Additional instructions>` section. If they mention a specific language (e.g. Python), add language-specific conventions. If they mention tests, add a step to run tests before calling `todo_complete`. If they mention security, add security-specific checks.

**Step 7: Write the file** to `<target-path>` using the Write tool.

**Step 8: Display a confirmation:**

   For **project** scope:
   ```
   Agent created at .claude/agents/<name>.md
   Register it with: /proj:agents-set execute <name>
   ```

   For **global** scope:
   ```
   Agent created at ~/.claude/agents/<name>.md
   Global agents are available across all projects without registration.
   ```

Suggested next:
- Project scope:
  (1) /proj:agents-set execute <name> — activate this agent for the execute step
  (2) /proj:agents-list — view all current agent overrides
  (3) /proj:create-agent — create an agent for a different step
- Global scope:
  (1) /proj:create-agent --global — create another global agent for a different step
  (2) /proj:agents-create-execute — create a project-scoped execute agent

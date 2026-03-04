---
name: agents-create-research
description: Create a custom Claude Code agent file for the research workflow step. Guides through name and specialization, then writes the agent to .claude/agents/ (project) or ~/.claude/agents/ (global). Use when the user says "create research agent", "new research agent", or "build researcher".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, Read, Glob, Write, Bash
argument-hint: "[--global] [agent-name]"
---

Create a custom Claude Code agent file for the **research** workflow step. Arguments: $ARGUMENTS (optional — agent name; --global flag for global scope)

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
   - Note any patterns (naming conventions, tool lists, model choices, system prompt style)

3. Determine the agent name. If a name was provided in the remaining arguments (after removing `--global`), use it. Otherwise ask:
   - "Agent name? (used as the filename — e.g. 'my-researcher' → `<target-directory>/my-researcher.md`)"
   - Name should be lowercase with hyphens (no spaces, no .md extension)

4. Overwrite check: construct the full target path `<target-directory>/<name>.md`. Use Bash to check if it exists:
   ```bash
   test -f <target-path> && echo "exists" || echo "not found"
   ```
   If it exists, prompt: "Agent `<name>` already exists at `<target-path>`. Overwrite? (y/N)" — abort if not confirmed.

5. Ask for specialization:
   - "What should this research agent specialize in? (e.g. specific tech stack, external API research, security analysis, performance benchmarking, codebase pattern discovery)"

6. Generate the agent file with research-step defaults (uses haiku model for cost efficiency). For **global** scope, omit all project-specific context from the system prompt (no project name, CLAUDE.md content, or repo path references):

   ```markdown
   ---
   name: <name>
   description: <user's specialization summary — 1 sentence>
   model: claude-haiku-4-5-20251001
   tools: Read, Glob, Grep, WebSearch, WebFetch, mcp__proj__proj_get_todo_context, mcp__proj__content_set_research, mcp__proj__todo_set_content_flag
   ---

   You are a research agent specializing in <user's specialization>.

   Your role is to research implementation approaches for todos and write a structured `research.md`. When researching:
   - Read the todo's requirements and any existing research before starting
   - Explore the codebase for existing patterns (Read, Glob, Grep) before looking externally
   - Consider 2-3 distinct approaches — do not converge on one option too quickly
   - Search externally (WebSearch, WebFetch) for libraries, APIs, and best practices when relevant
   - Be honest about trade-offs — pros and cons should be balanced, not marketing copy

   Output format for research.md:
   ```markdown
   # Research: <todo title>

   ## Approach Options

   ### Option 1: <name>
   <description>
   **Pros:** <list>
   **Cons:** <list>

   ### Option 2: <name>
   <description>
   **Pros:** <list>
   **Cons:** <list>

   ## Recommended Approach
   <which option and why>

   ## Key Dependencies
   - <library/API/file and version if relevant>

   ## Risks
   - <risk and mitigation>

   ## References
   - <link or file path>
   ```

   <Additional instructions based on user's specialization>

   Always call `mcp__proj__content_set_research` to save the research and `mcp__proj__todo_set_content_flag` with `has_research=true` when done.
   ```

   Incorporate the user's specialization details into the `<Additional instructions>` section. If they specialize in a specific tech domain, add instructions to search for domain-specific patterns, libraries, or conventions.

7. Write the file to `<target-path>` using the Write tool.

8. Display a confirmation:

   For **project** scope:
   ```
   Agent created at .claude/agents/<name>.md
   Register it with: /proj:agents-set research <name>
   ```

   For **global** scope:
   ```
   Agent created at ~/.claude/agents/<name>.md
   Global agents are available across all projects without registration.
   ```

Note: This agent uses `claude-haiku-4-5-20251001` by default for cost efficiency on research tasks. If you need more reasoning power, edit the `model` field to remove it (inherits from project default) or set a different model.

Suggested next:
- Project scope:
  (1) /proj:agents-set research <name> — activate this agent for the research step
  (2) /proj:agents-list — view all current agent overrides
  (3) /proj:agents-create-decompose — create a decompose agent too
- Global scope:
  (1) /proj:create-agent --global decompose — create a global decompose agent too
  (2) /proj:agents-create-research — create a project-scoped research agent

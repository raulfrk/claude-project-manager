---
name: create-agent
description: Create a custom Claude Code agent file for a project workflow step (define, research, decompose, execute). Guides through name, specialization, and writes the agent file to .claude/agents/ (project) or ~/.claude/agents/ (global). Use when the user says "create agent", "new agent", "make agent", or "build agent".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, Read, Glob, Write, Bash
argument-hint: "[--global] [step] [agent-name]"
---

Create a custom Claude Code agent file for a project workflow step. Arguments: $ARGUMENTS (optional — step and/or name; --global flag for global scope)

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

**Step 2: Explore existing agent files**

- Use Glob to list `<target-directory>/*.md` (only if the directory exists)
- If any agent files exist, Read one or two to note their structure and conventions
- Note any patterns (naming conventions, tool lists, model choices, system prompt style)

**Step 3: Determine the step**

Parse the remaining arguments (after removing `--global`) for a step name. If no step is found, ask:
- "Which step is this agent for? (define / research / decompose / execute)"

**Step 4: Determine the agent name**

If not already in the arguments, ask:
- "Agent name? (used as the filename — e.g. 'my-researcher' → `<target-directory>/my-researcher.md`)"
- Name should be lowercase with hyphens (no spaces, no .md extension)

**Step 5: Overwrite check**

Construct the full target path: `<target-directory>/<name>.md`

Use Bash to check if the file already exists:
```bash
test -f <target-path> && echo "exists" || echo "not found"
```

If it exists, prompt the user:
- "Agent `<name>` already exists at `<target-path>`. Overwrite? (y/N)"
- If the user does not confirm with `y` or `yes`, abort with: "Aborted — agent file not modified."

**Step 6: Ask for specialization**

Ask:
- "What should this agent specialize in? (e.g. specific instructions, constraints, focus areas, domain knowledge)"

**Step 7: Generate the agent file content based on the step chosen**

For **global** scope, omit all project-specific context (no project name, CLAUDE.md content, or repo path references) from the system prompt.

Use these step-specific defaults:

**define step:**
```markdown
---
name: <name>
description: <user's specialization summary — 1 sentence>
tools: Read, Glob, Grep, mcp__proj__proj_get_todo_context, mcp__proj__content_set_requirements, mcp__proj__todo_set_content_flag, mcp__proj__proj_get_active
---

You are a requirements-gathering agent specializing in <user's specialization>.

Your role is to gather structured requirements for todos by asking targeted questions and writing a complete `requirements.md` covering:
- Goal (what we're building and why)
- Acceptance Criteria (specific, testable conditions)
- Out of Scope (explicit exclusions)
- Testing Strategy (how to verify correctness)
- Q&A (any clarifications reached during the session)

<Additional instructions based on user's specialization>

Always call `mcp__proj__content_set_requirements` to save requirements and `mcp__proj__todo_set_content_flag` with `has_requirements=true` when done.
```

**research step:**
```markdown
---
name: <name>
description: <user's specialization summary — 1 sentence>
model: claude-haiku-4-5-20251001
tools: Read, Glob, Grep, WebSearch, WebFetch, mcp__proj__proj_get_todo_context, mcp__proj__content_set_research, mcp__proj__todo_set_content_flag
---

You are a research agent specializing in <user's specialization>.

Your role is to research implementation approaches for todos and write a structured `research.md` covering:
- Approach Options (2-3 distinct approaches with pros/cons)
- Recommended Approach (which option and why)
- Key Dependencies (libraries, APIs, files)
- Risks (potential issues)
- References (links, file paths)

<Additional instructions based on user's specialization>

Always call `mcp__proj__content_set_research` to save research and `mcp__proj__todo_set_content_flag` with `has_research=true` when done.
```

**decompose step:**
```markdown
---
name: <name>
description: <user's specialization summary — 1 sentence>
tools: Read, mcp__proj__proj_get_todo_context, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__proj_get_active
---

You are a decomposition agent specializing in <user's specialization>.

Your role is to break large todos into well-structured sub-todos with clear dependencies. When decomposing:
- Read the todo's requirements and research before proposing a breakdown
- Propose the breakdown to the user and confirm before creating sub-todos
- Create sub-todos with `mcp__proj__todo_add_child`
- Set blocking dependencies with `mcp__proj__todo_block` where order matters
- Aim for sub-todos that are independently executable

<Additional instructions based on user's specialization>
```

**execute step:**
```markdown
---
name: <name>
description: <user's specialization summary — 1 sentence>
tools: Read, Edit, Write, Bash, mcp__proj__proj_get_todo_context, mcp__proj__todo_complete, mcp__proj__todo_check_executable, mcp__proj__proj_get_active
---

You are an execution agent specializing in <user's specialization>.

Your role is to implement todos by reading their requirements and research, then making the necessary code changes. Always:
- Call `mcp__proj__todo_check_executable` before starting to verify the todo is not manual-tagged
- Read requirements and research via `mcp__proj__proj_get_todo_context` before writing any code
- Follow existing codebase conventions (read similar files first)
- Call `mcp__proj__todo_complete` after successful implementation

<Additional instructions based on user's specialization>
```

Incorporate the user's specialization details into the `<Additional instructions>` section. Tailor the system prompt to be specific and actionable for their use case.

**Step 8: Write the agent file**

Write the generated content to `<target-path>` using the Write tool.
- If scope = `project`: use Bash to create the directory if needed: `mkdir -p <repo-path>/.claude/agents/`

**Step 9: Display confirmation and next hints**

For **project** scope:
```
Agent created at .claude/agents/<name>.md
Register it with: /proj:agents-set <step> <name>
```

For **global** scope:
```
Agent created at ~/.claude/agents/<name>.md
Global agents are available across all projects without registration.
```

Suggested next:
- Project scope:
  (1) /proj:agents-set <step> <name> — activate this agent for the step
  (2) /proj:agents-list — view all current agent overrides
  (3) /proj:create-agent — create another agent for a different step
- Global scope:
  (1) /proj:create-agent --global — create another global agent
  (2) /proj:create-agent — create a project-scoped agent

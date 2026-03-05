# claude-project-manager

A Claude Code plugin marketplace for project management workflows.

[![version](https://img.shields.io/badge/version-0.8.0-blue?style=flat-square)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![tests](https://img.shields.io/badge/tests-753%20passing-brightgreen?style=flat-square)](#contributing)

---

## Overview

`claude-project-manager` is a Claude Code plugin marketplace that extends Claude with project management superpowers. Four focused plugins work independently or together to handle the full lifecycle of software projects — from permissions management through task tracking to AI-powered execution.

**perms** (v0.8.0) — Auto-manages `settings.json` permissions. Grants directory Read/Edit access and adds MCP allow-rule wildcards so Claude can act on your filesystem without manual configuration.

**worktree** (v0.8.0) — Git worktree management. Register base repositories once, then create, list, and remove isolated worktrees on demand — all from within a Claude Code conversation.

**proj** (v0.41.0) — Full project lifecycle management. Tracks todos with nested dependencies, appends timestamped notes, syncs bidirectionally with Todoist and Trello (root todos only), detects git activity, generates reports, and drives AI-powered research and parallel execution of work items.

**claude-helper** (v0.4.0) — Review and quality tooling for Claude Code. Analyses SKILL.md files and subagent definition files, scoring them across ten quality dimensions and producing prioritised improvement reports. Pure-skill plugin — no MCP server required.

---

## Installation

Install each plugin individually via the Claude Code plugin command:

```
/plugin install raulfrk/claude-project-manager:perms
/plugin install raulfrk/claude-project-manager:worktree
/plugin install raulfrk/claude-project-manager:proj
/plugin install raulfrk/claude-project-manager:claude-helper
```

After installing `proj`, run the first-time setup wizard:

```
/proj:init-plugin
```

---

## Quick Start

```
1. /plugin install raulfrk/claude-project-manager:perms
   /plugin install raulfrk/claude-project-manager:worktree
   /plugin install raulfrk/claude-project-manager:proj
   /plugin install raulfrk/claude-project-manager:claude-helper  # optional

2. /proj:init-plugin        # configure tracking dir, Todoist, permissions

3. /proj:init               # create your first project

4. /proj:todo add Build something awesome

5. /proj:status             # see your project
```

---

## Plugins

### perms

The `perms` plugin is an MCP-only server (no skills) that provides atomic read/write access to Claude Code's `settings.json`. It is used internally by `proj` and `worktree` during initialization, and can also be called directly.

**MCP tools:**

| Tool | Description |
|------|-------------|
| `perms_add_allow(path)` | Add `Read` and `Edit` rules for a directory path |
| `perms_remove_allow(path)` | Remove Read/Edit rules for a directory |
| `perms_list()` | List all current allow rules |
| `perms_check(path)` | Check whether a path already has allow rules |
| `perms_add_mcp_allow(server)` | Add an `mcp__<server>__*` wildcard allow rule |
| `perms_remove_mcp_allow(server)` | Remove a wildcard allow rule for an MCP server |
| `perms_batch_add_mcp_allow(servers)` | Add wildcard rules for multiple servers in one atomic write |

Paths written to `settings.json` use the double-slash prefix required for absolute paths (e.g., `//home/raul/projects/**`). Rules take effect immediately without restarting Claude Code.

---

### worktree

The `worktree` plugin manages git worktrees from a set of registered base repositories. Register a repo once with a short label, then spin up isolated worktrees for feature branches or parallel work sessions.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/worktree:setup` | Configure the worktree plugin |
| `/worktree:add-repo` | Register a base git repository with a label |
| `/worktree:create` | Create a new worktree from a registered repo |
| `/worktree:list` | List all worktrees (optionally filtered by repo) |
| `/worktree:remove` | Remove a worktree by path |
| `/worktree:prune` | Clean up stale worktree metadata |

---

### claude-helper

The `claude-helper` plugin provides review and quality tooling for Claude Code skill and agent definition files. It has no MCP server — all review logic is pure Claude reasoning over file content.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/claude-helper:review-skill` | Review a single SKILL.md file — scores all 10 quality dimensions and produces an annotated report |
| `/claude-helper:review-agent` | Review a Claude subagent definition file — same workflow with criteria adapted for agent conventions |
| `/claude-helper:review-all` | Batch-review all SKILL.md files under a directory, spawning parallel agents and sorting results by score |
| `/claude-helper:resume-review` | Load a saved review file and continue from the first pending finding |
| `/claude-helper:review-to-todo` | Convert pending review findings into project todos interactively |

Five skills cover the full review lifecycle: individual and batch reviews, resuming interrupted reviews, and converting findings into actionable todos. Each dimension produces a 1–5 score, an impact rating, a finding, and a concrete improvement suggestion. Pass `--include-agents` to `review-all` to also cover agent definition files.

---

### proj

The `proj` plugin is the core of the marketplace. It tracks project metadata, todos with nested dependencies and blocking relationships, timestamped notes, and git activity across multiple repositories. Todos follow a full lifecycle: `pending` → `in_progress` → `done`, with optional `requirements.md` and `research.md` content attached to any item.

**Skills by category:**

- **Setup**: `init-plugin`, `init`, `quick`
- **Daily workflow**: `status`, `todo`, `update`, `sync`, `explore`, `list-proj`, `save`, `trello-sync`, `extract-todos`, `add-repo`, `remove-repo`
- **Deep work**: `define`, `research`, `decompose`, `execute`, `full-workflow`, `prep-workflow`, `quick-workflow`
- **Agents**: `agents-list`, `agents-set`, `agents-remove`, `create-agent`, `agents-create-define`, `agents-create-research`, `agents-create-decompose`, `agents-create-execute`
- **Reports**: `report`
- **Management**: `archive`, `load`, `switch`
- **Maintenance**: `migrate-ids`, `migrate-to-proj`, `perms-sync`

Hooks run automatically at session start, session end, and pre-compact to inject project context without any manual steps.

---

## Skill Reference

### proj skills

| Skill | Plugin | Description | Arguments |
|-------|--------|-------------|-----------|
| `/proj:init-plugin` | proj | First-time setup wizard | none |
| `/proj:init` | proj | Initialize project tracking | `[project-name]` |
| `/proj:quick` | proj | Create a new project and immediately launch full-workflow on the first todo | `[project-name]` |
| `/proj:status` | proj | Show project status, todos, git activity | none |
| `/proj:todo` | proj | Manage todos (add/done/list/tree/block/delete) | `[operation] [args]` |
| `/proj:update` | proj | Record progress, reconcile git, append notes | `[note text]` |
| `/proj:execute` | proj | Execute todo(s) with parallel agents | `[id \| range]` e.g. `1` or `2-4` |
| `/proj:report` | proj | Generate comprehensive project report | none |
| `/proj:archive` | proj | Archive completed project | `[project-name]` |
| `/proj:switch` | proj | Switch active project context | `[project-name]` |
| `/proj:load` | proj | Load project for session (cross-directory) | `[project-name]` |
| `/proj:sync` | proj | Bidirectional Todoist sync | none |
| `/proj:define` | proj | Gather requirements via iterative Q&A | `<todo-id>` |
| `/proj:research` | proj | Research implementation approach | `<todo-id>` or `1,2,3` |
| `/proj:decompose` | proj | Break todo into sub-todos | `<todo-id>` |
| `/proj:migrate-ids` | proj | Migrate todo IDs to numeric format | `[--dry-run]` |
| `/proj:migrate-to-proj` | proj | Migrate existing project directory into proj tracking | `[project-name]` |
| `/proj:perms-sync` | proj | Check settings.json matches project config | none |
| `/proj:explore` | proj | Explore and map a project's codebase, update CLAUDE.md | none |
| `/proj:list-proj` | proj | List all non-archived tracked projects | none |
| `/proj:full-workflow` | proj | Run define → research → decompose → execute interactively | `<id | range | list> [--iter N | --iter-as-needed[=N]] [--steps <csv> | --from <step>] [--no-interactive]` |
| `/proj:prep-workflow` | proj | Run define → research → decompose interactively | `<id | range | list> [--iter N | --iter-as-needed[=N]] [--steps <csv> | --from <step>] [--no-interactive]` |
| `/proj:quick-workflow` | proj | Create a new todo and immediately run full-workflow on it | `<description> [--steps <csv>] [--from <step>] [--iter N] [--iter-as-needed[=N]]` |
| `/proj:save` | proj | Save session notes to project — appends to NOTES.md and writes a dated session file | none |
| `/proj:trello-sync` | proj | Bidirectional Trello sync for root todos | — |
| `/proj:extract-todos` | proj | Scan repo source files for TODO/FIXME comments and import as project todos | `[--dry-run]` |
| `/proj:agents-list` | proj | List all agent overrides for the active project | none |
| `/proj:agents-set` | proj | Set an agent override for a workflow step (define/research/decompose/execute) | `<step> <agent-name>` |
| `/proj:agents-remove` | proj | Remove an agent override for a step | `<step>` |
| `/proj:create-agent` | proj | Create a custom Claude Code agent file for a project workflow step | `[--global] [step] [agent-name]` |
| `/proj:agents-create-define` | proj | Create a custom agent file for the define (requirements) step | `[--global] [agent-name]` |
| `/proj:agents-create-research` | proj | Create a custom agent file for the research step | `[--global] [agent-name]` |
| `/proj:agents-create-decompose` | proj | Create a custom agent file for the decompose step | `[--global] [agent-name]` |
| `/proj:agents-create-execute` | proj | Create a custom agent file for the execute step | `[--global] [agent-name]` |
| `/proj:add-repo` | proj | Add a new directory or repository to the active project | `<path> [--label=<label>] [--reference] [--claudemd]` |
| `/proj:remove-repo` | proj | Remove a directory or repository from the active project by label | `<label>` |

### claude-helper skills

| Skill | Plugin | Description | Arguments |
|-------|--------|-------------|-----------|
| `/claude-helper:review-skill` | claude-helper | Review a single SKILL.md file across 10 quality dimensions | `<path-to-SKILL.md>` |
| `/claude-helper:review-agent` | claude-helper | Review a Claude subagent definition file | `<path-to-agent-file>` |
| `/claude-helper:review-all` | claude-helper | Batch-review all SKILL.md files under a directory (parallel agents, sorted by score) | `<directory> [--include-agents]` |
| `/claude-helper:resume-review` | claude-helper | Load a saved review file and continue from the first pending finding | `<path-to-review-file>` |
| `/claude-helper:review-to-todo` | claude-helper | Convert pending review findings into project todos interactively | `<path-to-review-file>` |

### worktree skills

| Skill | Plugin | Description | Arguments |
|-------|--------|-------------|-----------|
| `/worktree:setup` | worktree | Configure worktree plugin | none |
| `/worktree:add-repo` | worktree | Register base git repository | `[label] [path]` |
| `/worktree:create` | worktree | Create worktree from registered repo | `[repo-label] [branch]` |
| `/worktree:list` | worktree | List all worktrees | `[repo-label]` |
| `/worktree:remove` | worktree | Remove a worktree | `[path]` |
| `/worktree:prune` | worktree | Clean up stale worktree metadata | `[repo-label]` |

---

## Configuration

The `proj` plugin is configured via `~/.claude/proj.yaml`, written during `/proj:init-plugin`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tracking_dir` | string | `~/projects/tracking` | Root directory for all project tracking data |
| `projects_base_dir` | string | — | Base directory used when initializing new projects |
| `git_integration` | boolean | `true` | Enable git activity detection |
| `default_priority` | string | `medium` | Default todo priority (`low`/`medium`/`high`) |
| `permissions.auto_grant` | boolean | `true` | Auto-add Read/Edit rules for project directories |
| `permissions.auto_allow_mcps` | boolean | `true` | Auto-allow plugin MCP tools in `settings.json` |
| `permissions.investigation_tools` | list | `["grep","find","ls","cat","head","tail","wc","tree","du","file"]` | Bash tools granted scoped access via `proj_setup_permissions` |
| `todoist.enabled` | boolean | `false` | Enable Todoist bidirectional sync |
| `todoist.auto_sync` | boolean | `true` | Auto-sync todos on every proj command |
| `todoist.mcp_server` | string | `claude_ai_Todoist` | MCP server name for Todoist integration |
| `todoist.root_only` | boolean | `false` | Sync only root-level todos (no subtodos) to Todoist |
| `trello.enabled` | boolean | `false` | Enable Trello bidirectional sync |
| `trello.mcp_server` | string | `trello` | MCP server name for Trello integration |
| `trello.default_board_id` | string | — | Trello board ID to sync root todos to |
| `trello.list_mappings.created` | string | — | Trello list name for pending/in-progress todos |
| `trello.list_mappings.done` | string | — | Trello list name for completed todos |
| `trello.on_delete` | string | `archive` | What to do with Trello cards when todo is deleted (`archive` or `delete`) |
| `perms_integration` | boolean | `false` | Whether the `perms` plugin is installed |
| `worktree_integration` | boolean | `false` | Whether the `worktree` plugin is installed |

**Example `~/.claude/proj.yaml`:**

```yaml
version: 1
tracking_dir: ~/projects/tracking
git_integration: true
default_priority: medium
permissions:
  auto_grant: true
  auto_allow_mcps: true
  investigation_tools:
    - grep
    - find
    - ls
    - cat
    - head
    - tail
    - wc
    - tree
    - du
    - file
sync:
  todoist:
    enabled: true
    auto_sync: true
    mcp_server: claude_ai_Todoist
    root_only: false
  trello:
    enabled: false
    mcp_server: trello
    default_board_id: ""
    list_mappings:
      created: "In Progress"
      done: "Done"
    on_delete: archive
perms_integration: true
worktree_integration: true
```

---

## Workflow Diagrams

### Architecture Overview

Architecture overview — how each plugin fits into the marketplace.

```mermaid
flowchart TB
    subgraph marketplace["Marketplace: claude-project-manager"]
        direction TB

        subgraph perms_plugin["perms plugin"]
            direction LR
            perms_mcp["MCP Server<br/>perms_add_allow<br/>perms_remove_allow<br/>perms_add_mcp_allow<br/>perms_check<br/>perms_list"]
            perms_store[("settings.json<br/>~/.claude/settings.json")]
            perms_mcp --> perms_store
        end

        subgraph worktree_plugin["worktree plugin"]
            direction LR
            wt_mcp["MCP Server<br/>wt_create / wt_remove<br/>wt_list / wt_lock<br/>wt_add_repo"]
            wt_skills["Skills<br/>/worktree:setup<br/>/worktree:create<br/>/worktree:list"]
            wt_store[("worktree.yaml<br/>~/.claude/worktree.yaml")]
            wt_mcp --> wt_store
        end

        subgraph proj_plugin["proj plugin"]
            direction LR
            proj_mcp["MCP Server<br/>proj_init / proj_list<br/>todo_add / todo_complete<br/>notes_append<br/>git_detect_work<br/>config_load"]
            proj_skills["Skills<br/>/proj:init / /proj:todo<br/>/proj:full-workflow<br/>/proj:status / /proj:quick<br/>/proj:explore"]
            proj_hooks["Hooks<br/>PostCompact<br/>(auto session save)"]
            proj_store[("proj.yaml + tracking/<br/>~/.claude/proj.yaml<br/>~/projects/tracking/")]
            proj_mcp --> proj_store
        end

        subgraph helper_plugin["claude-helper plugin"]
            direction LR
            helper_skills["Skills only<br/>/claude-helper:review-skill<br/>/claude-helper:review-agent<br/>/claude-helper:review-all"]
        end
    end

    %% Dependencies
    proj_plugin -- "permissions mgmt" --> perms_plugin
    worktree_plugin -- "permissions mgmt" --> perms_plugin

    %% Styling
    style marketplace fill:#1a1a2e,stroke:#333,color:#fff
    style perms_plugin fill:#6366F1,stroke:#4338CA,color:#fff
    style worktree_plugin fill:#8B5CF6,stroke:#6D28D9,color:#fff
    style proj_plugin fill:#EC4899,stroke:#BE185D,color:#fff
    style helper_plugin fill:#6B7280,stroke:#4B5563,color:#fff

    style perms_mcp fill:#4F46E5,stroke:#3730A3,color:#fff
    style perms_store fill:#312E81,stroke:#1E1B4B,color:#fff

    style wt_mcp fill:#7C3AED,stroke:#5B21B6,color:#fff
    style wt_skills fill:#7C3AED,stroke:#5B21B6,color:#fff
    style wt_store fill:#4C1D95,stroke:#2E1065,color:#fff

    style proj_mcp fill:#DB2777,stroke:#9D174D,color:#fff
    style proj_skills fill:#DB2777,stroke:#9D174D,color:#fff
    style proj_hooks fill:#DB2777,stroke:#9D174D,color:#fff
    style proj_store fill:#831843,stroke:#500724,color:#fff

    style helper_skills fill:#4B5563,stroke:#374151,color:#fff
```

### Plugin Interaction

How the three MCP plugins interact during init and execution.

```mermaid
sequenceDiagram
    actor User
    participant CC as Claude Code
    participant proj as proj (MCP)
    participant wt as worktree (MCP)
    participant perms as perms (MCP)
    participant settings as settings.json

    rect rgb(230, 245, 255)
        Note over User, settings: Session Init — /proj:init-plugin
        User->>CC: /proj:init-plugin
        CC->>proj: config_init(project_dir)
        activate proj
        proj->>perms: perms_add_allow(project_dir)
        activate perms
        perms->>settings: Read current permissions
        settings-->>perms: permissions.allow[]
        perms->>settings: Write Read/Edit rules for project_dir
        perms-->>proj: OK
        deactivate perms
        proj->>perms: perms_add_mcp_allow("proj")
        activate perms
        perms->>settings: Add mcp__plugin_proj_proj__* wildcard
        perms-->>proj: OK
        deactivate perms
        proj-->>CC: Project initialized
        deactivate proj
    end

    rect rgb(235, 255, 235)
        Note over User, settings: Worktree Setup — /worktree:setup
        User->>CC: /worktree:setup
        CC->>wt: wt_add_repo(repo_path)
        activate wt
        wt->>perms: perms_add_allow(worktree_base)
        activate perms
        perms->>settings: Read current permissions
        settings-->>perms: permissions.allow[]
        perms->>settings: Write Read/Edit rules for worktree_base
        perms-->>wt: OK
        deactivate perms
        wt->>perms: perms_add_mcp_allow("worktree")
        activate perms
        perms->>settings: Add mcp__plugin_worktree_worktree__* wildcard
        perms-->>wt: OK
        deactivate perms
        wt-->>CC: Worktree repo registered
        deactivate wt
    end

    rect rgb(255, 245, 230)
        Note over User, settings: Execution — /proj:execute (multi-repo)
        User->>CC: /proj:execute todo_id
        CC->>proj: todo_get(todo_id)
        activate proj
        proj-->>CC: Todo with multi-repo context
        deactivate proj
        CC->>wt: wt_create(repo, branch)
        activate wt
        Note right of wt: git worktree add
        wt->>perms: perms_add_allow(new_worktree_path)
        activate perms
        perms->>settings: Write Read/Edit rules for worktree
        perms-->>wt: OK
        deactivate perms
        wt-->>CC: Worktree created at path
        deactivate wt
        CC->>proj: todo_update(todo_id, status=in_progress)
        activate proj
        proj-->>CC: Updated
        deactivate proj
        Note over CC: Execute work in isolated worktree
        CC->>proj: todo_complete(todo_id)
        activate proj
        proj-->>CC: Done
        deactivate proj
    end
```

### Full Workflow Lifecycle

The full-workflow lifecycle for a todo: define → research → decompose → execute.

```mermaid
flowchart TD
    %% Color definitions
    classDef user fill:#22C55E,stroke:#16A34A,color:#fff
    classDef claude fill:#4A9EED,stroke:#2563EB,color:#fff
    classDef proj fill:#EC4899,stroke:#DB2777,color:#fff
    classDef decision fill:#F59E0B,stroke:#D97706,color:#fff
    classDef skip fill:#94A3B8,stroke:#64748B,color:#fff

    %% Entry
    START(["/proj:full-workflow <id>"]):::proj
    START --> PARSE

    %% Step 1: Parse & Validate
    PARSE["1. Parse Arguments\n--steps, --from, --iter, --iter-as-needed\n--no-interactive"]:::proj
    PARSE --> MODE_CHECK{Input mode?}:::decision

    MODE_CHECK -->|"Single ID"| VALIDATE_TODO
    MODE_CHECK -->|"Range / Comma list"| RANGE_PATH

    VALIDATE_TODO["Validate todo exists\ntodo_get(id)"]:::proj
    VALIDATE_TODO --> LOAD_STEPS

    %% Step 2: Load Workflow Steps
    LOAD_STEPS["2. Load Step List\nfull-workflow.yaml\nDefault: define -> research -> decompose -> execute"]:::proj
    LOAD_STEPS --> APPLY_FLAGS

    APPLY_FLAGS{"--steps or\n--from given?"}:::decision
    APPLY_FLAGS -->|"--steps csv"| FILTER_STEPS["Filter & reorder\nto requested steps"]:::proj
    APPLY_FLAGS -->|"--from step"| SLICE_STEPS["Slice from step\nto end"]:::proj
    APPLY_FLAGS -->|"Neither"| FULL_STEPS["Use all 4 steps"]:::proj

    FILTER_STEPS --> SPLIT
    SLICE_STEPS --> SPLIT
    FULL_STEPS --> SPLIT

    %% Step 3: Split prep vs execute
    SPLIT["3. Split Steps\nprep_steps = steps minus execute\nhas_execute = execute in list?"]:::proj
    SPLIT --> ITER_LOOP

    %% Step 4: Iteration Loop
    ITER_LOOP["4. Iteration Loop\ni = 1 to N"]:::proj
    ITER_LOOP --> REFRESH_TREE

    REFRESH_TREE["4a. Refresh descendant list\ntodo_tree(id) -> flatten depth-first"]:::proj
    REFRESH_TREE --> PREP_STEPS

    %% Prep Steps Detail
    PREP_STEPS{"Next prep step?"}:::decision

    PREP_STEPS -->|"define"| DEFINE
    PREP_STEPS -->|"research"| RESEARCH
    PREP_STEPS -->|"decompose"| DECOMPOSE
    PREP_STEPS -->|"All prep done"| CONVERGENCE_CHECK

    %% Define
    DEFINE["Step: Define\nSequential & Interactive\nIterative Q&A with user\nWrites requirements.md"]:::user
    DEFINE --> PREP_STEPS

    %% Research
    RESEARCH["Step: Research\nParallel Task agents (1 per batch)\nCodebase exploration\nWrites research.md"]:::claude
    RESEARCH --> PREP_STEPS

    %% Decompose
    DECOMPOSE["Step: Decompose\nParallel Task agents (1 per batch)\nBreaks into sub-todos with deps\nRefreshes descendant list"]:::claude
    DECOMPOSE --> PREP_STEPS

    %% Convergence Check (between iterations)
    CONVERGENCE_CHECK{"4c. Last iteration?\n(i == N)"}:::decision
    CONVERGENCE_CHECK -->|"Yes"| EXECUTE_GATE
    CONVERGENCE_CHECK -->|"No"| ITER_MODE_CHECK

    ITER_MODE_CHECK{"--iter-as-needed?"}:::decision
    ITER_MODE_CHECK -->|"Yes"| ASSESS["assess_convergence(id)\nCheck define + research + decompose\nfor parent & all descendants"]:::proj
    ITER_MODE_CHECK -->|"No (fixed --iter)"| ITER_PROMPT

    ASSESS --> CONVERGED_CHECK{Converged?}:::decision

    CONVERGED_CHECK -->|"Overall converged"| CONVERGED_PROMPT
    CONVERGED_CHECK -->|"Not converged"| NOT_CONVERGED_PROMPT

    CONVERGED_PROMPT["Recommend stop\nShow 4 options:\n1. Proceed to execute\n2. Continue iteration\n3. Edit\n4. Stop"]:::user
    CONVERGED_PROMPT -->|"Proceed"| EXECUTE_GATE
    CONVERGED_PROMPT -->|"Continue"| ITER_LOOP
    CONVERGED_PROMPT -->|"Edit"| EDIT_ITER["Apply edits\nRe-run or update"]:::user
    CONVERGED_PROMPT -->|"Stop"| WORKFLOW_END
    EDIT_ITER --> CONVERGED_PROMPT

    NOT_CONVERGED_PROMPT["Recommend another iteration\nShow 3 options:\n1. Continue\n2. Edit\n3. Stop"]:::user
    NOT_CONVERGED_PROMPT -->|"Continue"| ITER_LOOP
    NOT_CONVERGED_PROMPT -->|"Edit"| EDIT_ITER2["Apply edits\nRe-run or update"]:::user
    NOT_CONVERGED_PROMPT -->|"Stop"| WORKFLOW_END
    EDIT_ITER2 --> NOT_CONVERGED_PROMPT

    ITER_PROMPT["Iteration prompt\n(3 options: continue/edit/stop)"]:::user
    ITER_PROMPT -->|"Continue"| ITER_LOOP
    ITER_PROMPT -->|"Stop"| WORKFLOW_END

    %% --no-interactive auto-progression
    subgraph NO_INTERACTIVE ["--no-interactive auto-progression"]
        direction TB
        NI_CONVERGED["Auto-proceed to execute"]:::skip
        NI_NOT_CONVERGED["Auto-continue next iteration"]:::skip
    end

    %% Step 5: Execute
    EXECUTE_GATE{"5. has_execute\nAND has_children?"}:::decision

    EXECUTE_GATE -->|"No children"| MANUAL_CHECK
    EXECUTE_GATE -->|"Children converged"| EXECUTE_ALL
    EXECUTE_GATE -->|"Children NOT converged\n(edge-case --steps)"| PARENT_EXEC_THEN_CHILDREN
    EXECUTE_GATE -->|"No execute step"| WORKFLOW_END

    %% Manual tag guard
    MANUAL_CHECK{"todo_check_executable\nManual tag?"}:::decision
    MANUAL_CHECK -->|"manual tagged"| MANUAL_STOP["Stop: manual tag guard\nSkip execute\nUser must execute manually"]:::skip
    MANUAL_CHECK -->|"Executable"| PARENT_EXEC

    PARENT_EXEC["5i. Parent Execute\nRead execute/SKILL.md\nImplement changes\ntodo_complete(id)"]:::claude
    PARENT_EXEC --> WORKFLOW_END

    %% Execute All path
    EXECUTE_ALL["5ii. Execute All (parent + children)\nidentify_batches for dependency order"]:::proj
    EXECUTE_ALL --> BATCH_EXEC

    BATCH_EXEC["For each batch:\nParallel Task agents\nCheck manual tag -> skip if manual\nExecute & complete each todo"]:::claude
    BATCH_EXEC --> AUTO_COMPLETE

    AUTO_COMPLETE{"All children\nexecuted?"}:::decision
    AUTO_COMPLETE -->|"0 manual-skipped"| AUTO_DONE["Auto-complete parent\ntodo_complete(parent_id)"]:::proj
    AUTO_COMPLETE -->|"Some manual-skipped"| NO_AUTO["Parent NOT auto-completed\nManual todos remain"]:::skip

    AUTO_DONE --> WORKFLOW_END
    NO_AUTO --> WORKFLOW_END

    %% Children workflow (edge-case)
    PARENT_EXEC_THEN_CHILDREN --> CHILDREN_WORKFLOW

    CHILDREN_WORKFLOW["6. Children Workflow (edge-case fallback)\nDefine each child (sequential, interactive)\nResearch all (parallel agents)\nDecompose each (sequential confirm)\nExecute all (parallel agents)"]:::claude
    CHILDREN_WORKFLOW --> WORKFLOW_END

    %% Range/batch path
    RANGE_PATH["Range/Batch Path\nAll steps run autonomously\nNo interactive prompts"]:::proj
    RANGE_PATH --> RANGE_BATCHES["identify_batches\nDependency-ordered batches"]:::proj
    RANGE_BATCHES --> RANGE_DEFINE

    RANGE_DEFINE{"define in steps\nAND interactive?"}:::decision
    RANGE_DEFINE -->|"Yes"| RANGE_DEFINE_SEQ["Phase A: Define\nSequential, interactive\nQ&A per todo"]:::user
    RANGE_DEFINE -->|"No"| RANGE_AGENTS

    RANGE_DEFINE_SEQ --> RANGE_AGENTS
    RANGE_AGENTS["Phase B: Remaining prep steps\nParallel agents per batch\n1 agent per todo"]:::claude
    RANGE_AGENTS --> RANGE_CONVERGE

    RANGE_CONVERGE{"--iter-as-needed\nConverged?"}:::decision
    RANGE_CONVERGE -->|"All converged / max iter"| RANGE_EXECUTE
    RANGE_CONVERGE -->|"Not converged"| RANGE_BATCHES

    RANGE_EXECUTE["Phase C: Execute\nParallel agents per batch\nManual-tagged todos skipped"]:::claude
    RANGE_EXECUTE --> RANGE_SUMMARY["Aggregated Summary\nPer-batch breakdown\nnotes_append()"]:::proj
    RANGE_SUMMARY --> WORKFLOW_END

    %% End
    WORKFLOW_END(["7. Workflow Complete\nSteps completed summary\nnotes_append()"]):::proj
```

### Plugin Installation Flow

How each plugin is installed and wired together during first-time setup.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#EC4899', 'primaryTextColor': '#fff', 'primaryBorderColor': '#DB2777', 'lineColor': '#6B7280', 'secondaryColor': '#6366F1', 'tertiaryColor': '#8B5CF6'}}}%%
flowchart TD
    U([User]):::user
    A["/plugin install proj"]:::user
    B["Claude Code fetches plugin\nfrom marketplace"]:::claude
    C["Registers MCP server\nin .mcp.json"]:::claude
    D["Copies skill files\nto cache"]:::claude
    E["Skills available as\n/proj:* commands"]:::claude
    F["/proj:init-plugin"]:::user
    G["Reads ~/.claude/proj.yaml\nconfiguration"]:::proj
    H["Writes permissions to\nsettings.json\n(Read + Edit rules)"]:::perms
    I["Project tracking directory\ninitialized"]:::proj
    J[/"Project ready for use"/]:::claude

    U --> A
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J

    classDef user fill:#22C55E,stroke:#16A34A,color:#fff
    classDef claude fill:#4A9EED,stroke:#2563EB,color:#fff
    classDef proj fill:#EC4899,stroke:#DB2777,color:#fff
    classDef perms fill:#6366F1,stroke:#4F46E5,color:#fff
    classDef worktree fill:#8B5CF6,stroke:#7C3AED,color:#fff
```

### Todo Lifecycle

The states a todo passes through from creation to completion, including requirements, research, and blocking relationships.

```mermaid
flowchart TD
    ADD(["/proj:todo add"]) --> P["🔲 pending"]
    P --> IP["🔄 in_progress"]
    P --> BL["⏸ blocked"]
    BL -->|"blocker completes"| P
    IP -->|"/proj:todo done"| D["✅ done"]

    P -.->|"define"| DEF["requirements.md"]
    P -.->|"research"| RES["research.md"]
    P -.->|"decompose"| DEC["sub-todos"]
    P -.->|"execute"| EX["implementation"]

    style ADD fill:#22C55E,stroke:#16A34A,color:#fff
    style P fill:#4A9EED,stroke:#2563EB,color:#fff
    style IP fill:#f59e0b,stroke:#d97706,color:#fff
    style BL fill:#6B7280,stroke:#4B5563,color:#fff
    style D fill:#22C55E,stroke:#16A34A,color:#fff
    style DEF fill:#f3f4f6,stroke:#d1d5db,color:#374151
    style RES fill:#f3f4f6,stroke:#d1d5db,color:#374151
    style DEC fill:#f3f4f6,stroke:#d1d5db,color:#374151
    style EX fill:#f3f4f6,stroke:#d1d5db,color:#374151
```

### Skill Invocation Architecture

How a skill invocation travels from the `/proj:<name>` command through the MCP server to tracking data.

```mermaid
sequenceDiagram
    actor User
    participant CC as Claude Code
    participant SK as Skill (SKILL.md)
    participant MCP as MCP Server (FastMCP)
    participant ST as Storage (YAML/JSON)

    User->>CC: /proj:status
    CC->>SK: Load SKILL.md from cache
    SK-->>CC: Instructions and tool list
    CC->>MCP: mcp__proj__proj_get_active
    MCP->>ST: Read meta.yaml
    ST-->>MCP: Project metadata
    MCP-->>CC: JSON metadata response
    CC->>MCP: mcp__proj__todo_list
    MCP->>ST: Read todos.yaml
    ST-->>MCP: Todo entries
    MCP-->>CC: Filtered todo list
    CC->>User: Formatted project status
```

### Project Session Flow

What happens automatically at session start, during a session, and at session end via hooks.

```mermaid
flowchart LR
    A([Claude Code\nstarts]):::claude
    B["SessionStart\nhook fires"]:::claude
    C["CLI detects active\nproject from CWD"]:::proj
    D["/proj:load\nalternative path"]:::user
    E["Builds context\nmeta + todos + notes + git"]:::proj
    F["Injects context\ninto system prompt"]:::claude
    G([User runs\nskills]):::user
    H["/proj:todo add\n/proj:status\n/proj:update\netc."]:::proj
    I["PreCompact hook\nfires"]:::claude
    J["Compacts context\nfor long sessions"]:::claude
    K["Session ends"]:::claude
    L["SessionEnd hook\nupdates timestamp"]:::proj

    A --> B
    B --> C
    D --> E
    C --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    K --> L

    classDef user fill:#22C55E,stroke:#16A34A,color:#fff
    classDef claude fill:#4A9EED,stroke:#2563EB,color:#fff
    classDef proj fill:#EC4899,stroke:#DB2777,color:#fff
```

### Todoist/Trello Sync Flow

Bidirectional sync flow for Todoist and Trello integrations.

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant S as proj Skill
    participant TdM as Todoist MCP
    participant TdS as Todoist Service
    participant TrM as Trello MCP
    participant TrS as Trello Service

    note over S: Sync happens at skill level,<br/>NOT in MCP server.<br/>root_only config limits scope<br/>to root todos only.

    rect rgb(40, 60, 90)
        note right of U: Todoist Sync (/proj:sync)

        note over U,TdS: 1. Local todo created -- push to Todoist
        U->>S: /proj:sync
        S->>S: Load todos (root_only filter)
        S->>TdM: add-tasks(title, project_id)
        TdM->>TdS: POST /tasks
        TdS-->>TdM: task_id
        TdM-->>S: task_id
        S->>S: Store todoist_task_id on local todo

        note over U,TdS: 2. Todoist task completed -- pull to local
        U->>S: /proj:sync
        S->>TdM: fetch-object(task_id)
        TdM->>TdS: GET /tasks/{id}
        TdS-->>TdM: task (is_completed=true)
        TdM-->>S: completed task
        S->>S: Mark local todo done

        note over U,TdS: 3. Title conflict resolution
        U->>S: /proj:sync
        S->>TdM: fetch-object(task_id)
        TdM-->>S: remote title + updated_at
        S->>S: Compare timestamps
        alt Local is newer
            S->>TdM: update-tasks(task_id, local title)
            TdM->>TdS: POST /tasks/{id}
        else Remote is newer
            S->>S: Update local todo title from remote
        end

        note over U,TdS: 4. Ghost detection -- archived local match
        U->>S: /proj:sync
        S->>S: Detect archived todo with todoist_task_id
        S->>TdM: complete-tasks(task_id)
        TdM->>TdS: POST /tasks/{id}/close
        TdS-->>TdM: 204 OK
    end

    rect rgb(50, 70, 50)
        note right of U: Trello Sync (/proj:trello-sync)

        note over U,TrS: 1. Root todo created -- push card
        U->>S: /proj:trello-sync
        S->>S: Load todos (root_only filter)
        S->>TrM: create_card(name, list="created")
        TrM->>TrS: POST /cards
        TrS-->>TrM: card_id
        TrM-->>S: card_id
        S->>S: Store trello_card_id on local todo

        note over U,TrS: 2. Todo completed -- move card
        U->>S: /proj:trello-sync
        S->>S: Detect completed todo with trello_card_id
        S->>TrM: update_card(card_id, list="done")
        TrM->>TrS: PUT /cards/{id}
        TrS-->>TrM: updated card
        TrM-->>S: OK

        note over U,TrS: 3. Todo deleted -- on_delete config
        U->>S: /proj:trello-sync
        S->>S: Detect deleted todo with trello_card_id
        alt on_delete = "archive"
            S->>TrM: archive_card(card_id)
            TrM->>TrS: PUT /cards/{id} closed=true
        else on_delete = "delete"
            S->>TrM: delete_card(card_id)
            TrM->>TrS: DELETE /cards/{id}
        end
        TrS-->>TrM: OK
        TrM-->>S: OK
    end
```

---

## Contributing

**Dev setup:**

```bash
cd plugins/proj/server
uv sync
```

**Run tests:**

```bash
uv run pytest tests/ -q
```

**Coverage threshold:** 72%

**Version bumps** must update both files together:
- `plugins/<name>/.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

**Skill files** live at `plugins/<name>/skills/<skill-name>/SKILL.md`.

This project is in early development. No PRs are being accepted at this time.

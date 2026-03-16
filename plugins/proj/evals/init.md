# E2E Eval: init

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/init/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

Note: This is an interactive skill. User answers to prompts should be simulated as specified in each scenario.

## Setup
- Ensure `~/.claude/proj.yaml` exists (run `/proj:init-plugin` with defaults if needed).
- `mkdir -p /tmp/claude-1000/eval-init`
- Ensure no project named `eval-test-init` exists: call `mcp__proj__proj_list` and verify it is absent (or archive it first with `mcp__proj__proj_archive`).

## Test Scenarios

### Scenario 1: Basic project init with new directory
- **Invocation**: Follow the skill instructions as if user said `/proj:init eval-test-init`
- **Simulated user answers**:
  - First content directory path: `/tmp/claude-1000/eval-init`
  - Label: `code`
  - Add another directory? (Enter to skip)
  - Description: `Test project for eval`
  - Tags: `eval,test`
  - Git integration: yes
  - Create CLAUDE.md: yes
  - (Answer no/defaults for permissions, zoxide, git tracking overrides)
- **Expected**: The skill flow results in:
  - `mcp__proj__config_load` called first.
  - `mcp__proj__proj_init` called with `name="eval-test-init"`, `dirs=[{"path": "/tmp/claude-1000/eval-init", "label": "code"}]`, `description="Test project for eval"`, `tags=["eval", "test"]`, `git_enabled=true`.
  - `mcp__proj__proj_load_session` called with `name="eval-test-init"`.
  - `mcp__proj__claudemd_write` called for `/tmp/claude-1000/eval-init` with content including `# eval-test-init`.
  - `mcp__proj__tracking_git_flush` called with `commit_message="Init: eval-test-init"`.
- **Assert**:
  - `mcp__proj__proj_list` includes `eval-test-init`.
  - `mcp__proj__proj_get` for `eval-test-init` returns repos with `[{"path": "/tmp/claude-1000/eval-init", "label": "code"}]`.
  - File `/tmp/claude-1000/eval-init/CLAUDE.md` exists (check with `Bash: test -f /tmp/claude-1000/eval-init/CLAUDE.md && echo exists`).
  - Output contains summary listing the directory.

### Scenario 2: Init with multiple directories
- **Invocation**: Follow the skill instructions as if user said `/proj:init eval-test-init-multi`
- **Simulated user answers**:
  - First content directory path: `/tmp/claude-1000/eval-init/dir1`
  - Label: `frontend`
  - Add another directory? `/tmp/claude-1000/eval-init/dir2`
  - Label: `backend`
  - Create directories when prompted: yes
  - Add another directory? (Enter to skip)
  - Description: `Multi-dir test`
  - Tags: `eval`
  - Git integration: no
  - CLAUDE.md: no for both
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_init` called with `dirs=[{"path": "/tmp/claude-1000/eval-init/dir1", "label": "frontend"}, {"path": "/tmp/claude-1000/eval-init/dir2", "label": "backend"}]`.
  - Directories created via `mkdir -p`.
- **Assert**:
  - `mcp__proj__proj_get` for `eval-test-init-multi` returns 2 repos with labels `frontend` and `backend`.
  - `Bash: test -d /tmp/claude-1000/eval-init/dir1 && echo exists` returns `exists`.
  - `Bash: test -d /tmp/claude-1000/eval-init/dir2 && echo exists` returns `exists`.

### Scenario 3: Duplicate label rejected
- **Invocation**: Follow the skill instructions as if user said `/proj:init eval-test-init-dup`
- **Simulated user answers**:
  - First directory: `/tmp/claude-1000/eval-init/dup1`, label: `code`
  - Add another directory: `/tmp/claude-1000/eval-init/dup2`, label: `code`
- **Expected**: The skill flow produces error message "Label 'code' already used. Choose a different label."
- **Assert**: The user is re-prompted for a new label. The duplicate is not accepted.

### Scenario 4: Init fails for existing project name
- **Invocation**: With project `eval-test-init` already created (from Scenario 1), follow the skill instructions as if user said `/proj:init eval-test-init` again with the same name
- **Expected**: The skill flow calls `mcp__proj__proj_init` which returns an error (project already exists). The error is displayed. No call to `proj_load_session`.
- **Assert**: Output contains an error about the project already existing.

## Cleanup
- `mcp__proj__proj_archive` for `eval-test-init`, `eval-test-init-multi`, and `eval-test-init-dup` (if created).
- `Bash: rm -rf /tmp/claude-1000/eval-init`

# E2E Eval: add-repo

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/add-repo/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Ensure `~/.claude/proj.yaml` exists.
- `mkdir -p /tmp/claude-1000/eval-add-repo/main /tmp/claude-1000/eval-add-repo/extra`
- Initialize a git repo in the extra dir: `cd /tmp/claude-1000/eval-add-repo/extra && git init`
- Create a test project and load it:
  - `mcp__proj__proj_init(name="eval-test-add-repo", dirs=[{"path": "/tmp/claude-1000/eval-add-repo/main", "label": "code"}])`
  - `mcp__proj__proj_load_session(name="eval-test-add-repo")`

## Test Scenarios

### Scenario 1: Add an existing directory (plain, no git)
- **Invocation**: `mkdir -p /tmp/claude-1000/eval-add-repo/docs`. Then follow the skill instructions as if user said `/proj:add-repo /tmp/claude-1000/eval-add-repo/docs --label=docs`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_get_active` called (returns `eval-test-add-repo`).
  - `mcp__proj__config_load` called.
  - Bash check: `test -d /tmp/claude-1000/eval-add-repo/docs` returns `exists`.
  - Bash check: `test -d /tmp/claude-1000/eval-add-repo/docs/.git` returns `plain`.
  - `mcp__proj__proj_add_repo` called with `repo_path="/tmp/claude-1000/eval-add-repo/docs"`, `label="docs"`, `claudemd=false`, `reference=false`.
  - `mcp__proj__proj_setup_permissions` called to refresh sandbox write paths.
  - `mcp__proj__tracking_git_flush` called with `commit_message="Add repo: docs"`.
  - Output includes confirmation: label `docs`, path, git repo: no, mode: writable.
- **Assert**:
  - `mcp__proj__proj_get` for `eval-test-add-repo` returns repos list containing both `code` and `docs`.
  - Output contains "No git repository detected".

### Scenario 2: Add a git repository
- **Invocation**: Follow the skill instructions as if user said `/proj:add-repo /tmp/claude-1000/eval-add-repo/extra --label=lib`
- **Expected**: The skill flow results in:
  - Bash check: `test -d /tmp/claude-1000/eval-add-repo/extra/.git` returns `git`.
  - `mcp__proj__proj_add_repo` called with `repo_path="/tmp/claude-1000/eval-add-repo/extra"`, `label="lib"`.
  - Output includes "Detected git repository" and confirmation with git repo: yes.
- **Assert**:
  - `mcp__proj__proj_get` returns repos list now containing `code`, `docs`, and `lib`.
  - Output contains "Detected git repository".

### Scenario 3: Add with --reference flag
- **Invocation**: `mkdir -p /tmp/claude-1000/eval-add-repo/ref`. Follow the skill instructions as if user said `/proj:add-repo /tmp/claude-1000/eval-add-repo/ref --label=reference --reference`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_add_repo` called with `reference=true`.
  - Output shows mode: `reference (read-only)`.
- **Assert**:
  - `mcp__proj__proj_get` returns the `reference` repo entry with `reference=true`.

### Scenario 4: Add non-existent path fails
- **Invocation**: Follow the skill instructions as if user said `/proj:add-repo /tmp/claude-1000/eval-add-repo/nonexistent --label=missing`
- **Expected**: The skill flow results in:
  - Bash check: `test -d /tmp/claude-1000/eval-add-repo/nonexistent` returns `missing`.
  - Output: "Path `/tmp/claude-1000/eval-add-repo/nonexistent` does not exist."
  - No call to `mcp__proj__proj_add_repo`.
- **Assert**:
  - `mcp__proj__proj_get` repos list is unchanged (no `missing` label).

### Scenario 5: No active project guard
- **Invocation**: Start a fresh session with no project loaded. Follow the skill instructions as if user said `/proj:add-repo /tmp/claude-1000/eval-add-repo/docs --label=docs`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_get_active` returns no active project.
  - Output: "No active project. Run /proj:load first."
  - No further tool calls.
- **Assert**: No changes to any project state.

## Cleanup
- `mcp__proj__proj_archive(name="eval-test-add-repo")`
- `Bash: rm -rf /tmp/claude-1000/eval-add-repo`

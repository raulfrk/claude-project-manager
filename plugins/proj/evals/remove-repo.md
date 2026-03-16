# E2E Eval: remove-repo

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/remove-repo/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

Note: This is an interactive skill. User answers to confirmation prompts should be simulated as specified in each scenario.

## Setup
- Ensure `~/.claude/proj.yaml` exists.
- `mkdir -p /tmp/claude-1000/eval-remove-repo/main /tmp/claude-1000/eval-remove-repo/extra /tmp/claude-1000/eval-remove-repo/ref`
- Create a test project with multiple repos and load it:
  - `mcp__proj__proj_init(name="eval-test-remove-repo", dirs=[{"path": "/tmp/claude-1000/eval-remove-repo/main", "label": "code"}, {"path": "/tmp/claude-1000/eval-remove-repo/extra", "label": "lib"}])`
  - `mcp__proj__proj_load_session(name="eval-test-remove-repo")`
  - `mcp__proj__proj_add_repo(repo_path="/tmp/claude-1000/eval-remove-repo/ref", label="reference", reference=true)`
- Verify project has 3 repos: `mcp__proj__proj_get(name="eval-test-remove-repo")` returns repos with labels `code`, `lib`, `reference`.

## Test Scenarios

### Scenario 1: Remove a writable repo (user confirms)
- **Invocation**: Follow the skill instructions as if user said `/proj:remove-repo lib`
- **Simulated user answers**: When asked for confirmation, answer "yes"
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_get_active` returns `eval-test-remove-repo`.
  - `mcp__proj__config_load` called.
  - `mcp__proj__proj_get` called, finds `lib` in repos list.
  - Confirmation prompt shows: label `lib`, path `/tmp/claude-1000/eval-remove-repo/extra`, type `writable`.
  - `mcp__proj__proj_remove_repo` called with `label="lib"`.
  - Permissions revocation attempted.
  - `mcp__proj__tracking_git_flush` called with `commit_message="Remove repo: lib"`.
  - Output: confirmation summary with remaining repos count = 2.
- **Assert**:
  - `mcp__proj__proj_get` returns repos with only `code` and `reference` labels.
  - Output contains "Remaining repos: 2".

### Scenario 2: Remove a reference repo (user confirms)
- **Invocation**: Follow the skill instructions as if user said `/proj:remove-repo reference`
- **Simulated user answers**: When asked for confirmation, answer "yes"
- **Expected**: The skill flow results in:
  - Confirmation prompt shows type `reference (read-only)`.
  - `mcp__proj__proj_remove_repo` called with `label="reference"`.
  - Output shows remaining repos: 1.
- **Assert**:
  - `mcp__proj__proj_get` returns repos with only `code` label.
  - Output contains "reference (read-only)" in the confirmation details.

### Scenario 3: Cannot remove last repo
- **Invocation**: Follow the skill instructions as if user said `/proj:remove-repo code` (only remaining repo)
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_get` returns 1 repo.
  - Output: "Cannot remove the last repo -- a project must have at least one repo. Use /proj:archive to remove the entire project instead."
  - No call to `mcp__proj__proj_remove_repo`.
- **Assert**:
  - `mcp__proj__proj_get` still returns `code` repo (unchanged).

### Scenario 4: Remove with non-existent label
- **Invocation**: Follow the skill instructions as if user said `/proj:remove-repo nonexistent-label`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_get` returns repos, none matching `nonexistent-label`.
  - Output: "No repo with label 'nonexistent-label' found in project 'eval-test-remove-repo'."
  - No call to `mcp__proj__proj_remove_repo`.
- **Assert**: Project repos are unchanged.

### Scenario 5: Remove cancelled by user
- **Invocation**: Re-add `lib` repo first: `mcp__proj__proj_add_repo(repo_path="/tmp/claude-1000/eval-remove-repo/extra", label="lib")`. Then follow the skill instructions as if user said `/proj:remove-repo lib`
- **Simulated user answers**: When asked for confirmation, answer "no"
- **Expected**: The skill flow results in:
  - Confirmation prompt is shown.
  - Output: "Cancelled."
  - No call to `mcp__proj__proj_remove_repo`.
- **Assert**:
  - `mcp__proj__proj_get` still includes `lib` in repos list.

### Scenario 6: No active project guard
- **Invocation**: Start a fresh session with no project loaded. Follow the skill instructions as if user said `/proj:remove-repo code`
- **Expected**: The skill flow results in:
  - `mcp__proj__proj_get_active` returns no active project.
  - Output: "No active project. Run /proj:load first."
- **Assert**: No changes to any project state.

## Cleanup
- `mcp__proj__proj_archive(name="eval-test-remove-repo")`
- `Bash: rm -rf /tmp/claude-1000/eval-remove-repo`

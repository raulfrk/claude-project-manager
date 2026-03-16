# E2E Eval: purge

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/purge/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

## Setup
- Call `mcp__plugin_proj_proj__config_load` to verify `archive.purge_after_days` is set. If not, call `mcp__plugin_proj_proj__config_update` to set `archive.purge_after_days=0` (immediate purge for testing).
- Call `mcp__plugin_proj_proj__proj_init` with `name="eval-test-purge"`, `path="/tmp/claude-1000/eval-purge"`, `git_enabled=false`
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-purge"`, `purgeable=true`

## Test Scenarios

### Scenario 1: Purge lists eligible candidates (dry run)
- **Invocation**: Follow the skill instructions as if user said `/proj:purge`
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__config_load` to confirm purge is configured. Calls `mcp__plugin_proj_proj__proj_purge_archive` without `confirm` (dry run). Returns at least `eval-test-purge` as a candidate. Displays candidates in a table with project name, archive date, and days since archived.
- **Assert**:
  - Output contains a table with `eval-test-purge`
  - Output contains "Purge these projects?" confirmation prompt
  - `mcp__plugin_proj_proj__proj_purge_archive` was called with `confirm=false`

### Scenario 2: Purge executes deletion on confirmation
- **Invocation**: Follow the skill instructions as if user said `/proj:purge` (answer "yes" when asked to confirm)
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__proj_purge_archive` with `confirm=true`. Project `eval-test-purge` is permanently deleted. Calls `mcp__plugin_proj_proj__tracking_git_flush` with `commit_message="Purge: archived projects"`.
- **Assert**:
  - `mcp__plugin_proj_proj__proj_purge_archive` was called with `confirm=true`
  - Call `mcp__plugin_proj_proj__proj_get` with `name="eval-test-purge"` returns an error (project not found)
  - `mcp__plugin_proj_proj__tracking_git_flush` was called

### Scenario 3: Purge with no eligible candidates
- **Invocation**: Follow the skill instructions as if user said `/proj:purge` (after all purgeable projects have been purged)
- **Expected**: The skill flow calls `mcp__plugin_proj_proj__proj_purge_archive` which returns empty candidates list. Displays "No projects eligible for purge." and stops.
- **Assert**:
  - Output contains "No projects eligible for purge"
  - No confirmation prompt is shown
  - `mcp__plugin_proj_proj__proj_purge_archive` is NOT called with `confirm=true`

### Scenario 4: Non-purgeable archived project is excluded
- **Invocation**: Create and archive a project with `purgeable=false`, then follow the skill instructions as if user said `/proj:purge`
- **Expected**: The non-purgeable project does NOT appear in the candidates list.
- **Assert**:
  - Call `mcp__plugin_proj_proj__proj_init` with `name="eval-test-purge-safe"`, `path="/tmp/claude-1000/eval-purge-safe"`, `git_enabled=false`
  - Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-purge-safe"`, `purgeable=false`
  - Call `mcp__plugin_proj_proj__proj_purge_archive` with `confirm=false` — result does NOT include `eval-test-purge-safe`
  - Call `mcp__plugin_proj_proj__proj_get` with `name="eval-test-purge-safe"` still returns the project (not purged)

## Cleanup
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-purge"` (if not already purged)
- Call `mcp__plugin_proj_proj__proj_archive` with `name="eval-test-purge-safe"` (if created)
- Run `rm -rf /tmp/claude-1000/eval-purge /tmp/claude-1000/eval-purge-safe`

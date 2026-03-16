# E2E Eval: init-plugin

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/init-plugin/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

Note: This is an interactive skill. User answers to prompts should be simulated as specified in each scenario.

## Setup
- Back up `~/.claude/proj.yaml` if it exists: `cp ~/.claude/proj.yaml ~/.claude/proj.yaml.bak`
- Remove `~/.claude/proj.yaml` to simulate first-time setup: `rm -f ~/.claude/proj.yaml`

## Test Scenarios

### Scenario 1: Fresh first-time setup with defaults
- **Invocation**: Follow the skill instructions as if user said `/proj:init-plugin`
- **Simulated user answers**:
  - Tracking directory: `~/projects/tracking`
  - Projects base directory: (blank)
  - Permissions: yes
  - MCP auto-allow: yes
  - Todoist sync: no
  - Git integration: yes
  - Git tracking: no
  - Zoxide integration: no
  - Default priority: medium
  - Archive purge: (blank)
  - perms plugin: no
  - worktree plugin: no
- **Expected**: The skill flow results in `mcp__proj__config_init` being called with:
  - `tracking_dir="~/projects/tracking"`
  - `projects_base_dir=null`
  - `auto_allow_mcps=true`
  - `todoist_enabled=false`
  - `git_enabled=true`
  - `git_tracking_enabled=false`
  - `zoxide_integration=false`
  - `default_priority="medium"`
  - `archive_purge_after_days=null`
  - `perms_integration=false`
  - `worktree_integration=false`
  - No `mcp__plugin_perms_perms__perms_batch_add_mcp_allow` call (perms not installed).
  - Confirmation message includes "proj plugin configured! Configuration saved to ~/.claude/proj.yaml".
- **Assert**:
  - `mcp__proj__config_load` returns a valid config with the above values.
  - File `~/.claude/proj.yaml` exists.
  - Output contains "Run /proj:init to start tracking your first project."

### Scenario 2: Reconfigure existing setup (user declines)
- **Invocation**: Follow the skill instructions as if user said `/proj:init-plugin` when `~/.claude/proj.yaml` already exists
- **Simulated user answers**: When asked "Do you want to reconfigure?", answer "no"
- **Expected**: No calls to `mcp__proj__config_init`. Output contains "Existing configuration kept -- no changes made."
- **Assert**:
  - `mcp__proj__config_load` returns the same config as before the invocation.
  - No MCP tool calls after `config_load`.

### Scenario 3: Full setup with perms and worktree plugins enabled
- **Invocation**: Remove `~/.claude/proj.yaml` first. Follow the skill instructions as if user said `/proj:init-plugin`
- **Simulated user answers**:
  - Tracking directory: `/tmp/claude-1000/eval-init-plugin/tracking`
  - Projects base directory: `/tmp/claude-1000/eval-init-plugin/projects`
  - Permissions: yes
  - MCP auto-allow: yes
  - Todoist sync: no
  - Git integration: yes
  - Git tracking: no
  - Zoxide integration: yes
  - Default priority: high
  - Archive purge: 30
  - perms plugin: yes
  - worktree plugin: yes
- **Expected**: The skill flow results in:
  - `mcp__proj__config_init` called with `projects_base_dir="/tmp/claude-1000/eval-init-plugin/projects"`, `zoxide_integration=true`, `default_priority="high"`, `archive_purge_after_days=30`, `perms_integration=true`, `worktree_integration=true`.
  - `mcp__plugin_perms_perms__perms_batch_add_mcp_allow` called with servers list containing: `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`, `"plugin_proj_proj"`, `"plugin_perms_perms"`, `"plugin_worktree_worktree"`.
  - `mcp__plugin_perms_perms__perms_add_allow` called with `entry="Bash(zoxide *)"`.
- **Assert**:
  - `mcp__proj__config_load` returns config with `perms_integration=true`, `worktree_integration=true`, `zoxide_integration=true`, `archive_purge_after_days=30`.

### Scenario 4: Setup with Todoist enabled
- **Invocation**: Remove `~/.claude/proj.yaml`. Follow the skill instructions as if user said `/proj:init-plugin`
- **Simulated user answers**:
  - Tracking directory: `~/projects/tracking`
  - Projects base directory: (blank)
  - Permissions: yes
  - MCP auto-allow: yes
  - Todoist sync: yes
  - Auto-sync: yes
  - Todoist MCP server: `claude_ai_Todoist`
  - Git integration: yes
  - Git tracking: no
  - Zoxide integration: no
  - Default priority: medium
  - Archive purge: (blank)
  - perms plugin: yes
  - worktree plugin: no
- **Expected**: The skill flow results in:
  - `mcp__proj__config_init` called with `todoist_enabled=true`, `todoist_mcp_server="claude_ai_Todoist"`.
  - `mcp__plugin_perms_perms__perms_batch_add_mcp_allow` called with servers list including `"claude_ai_Todoist"`.
- **Assert**:
  - `mcp__proj__config_load` returns config with `todoist.enabled=true`, `todoist.mcp_server="claude_ai_Todoist"`, `todoist.auto_sync=true`.

## Cleanup
- Restore original config: `cp ~/.claude/proj.yaml.bak ~/.claude/proj.yaml` (or remove if no backup existed)
- `rm -f ~/.claude/proj.yaml.bak`

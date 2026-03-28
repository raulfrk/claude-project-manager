---
name: team-status
description: Show active and recent teams, circuit breaker health, and per-agent status. Use when asked "team status", "show teams", or "proj:team-status".
allowed-tools: mcp__proj__config_load, mcp__proj__proj_session_context, Read, Bash
context: fork
agent: general-purpose
---

Show team status.

**1.** Call `mcp__proj__config_load` to check `team_mode.enabled`.
   - If not enabled, stop with: "Team mode is not enabled. Run `/proj:init-plugin` to enable it."

**2.** Call `mcp__proj__proj_session_context` to get project name and tracking_dir.

**3.** Read team state directory: `<tracking_dir>/<project>/.team-state/`
   - List all files matching `failed-teams.yaml` for recent failures
   - Read `<tracking_dir>/<project>/.team-state/circuit-breakers.yaml` for circuit breaker state
   - Read `<tracking_dir>/<project>/.team-state/orphaned-resources.yaml` for orphaned resources

**4.** Read active teams from `~/.claude/teams/` directory:
   - For each subdirectory, read `config.json` if it exists
   - Extract team name, description, and members list
   - For each member: show name, agentType (or model), and status (based on presence of inbox messages)
   - If no team directories or no config.json files found, show "No active teams"

**5.** Display formatted status:

### Team Mode Configuration
- **Enabled**: yes
- **Max agents**: {max_agents}
- **Trust level**: {trust_level} ({trust_name})

### Active Teams
| Team | Members | Description |
|------|---------|-------------|
| {team_name} | {member_count} agents | {description} |

For each active team, show per-agent status:

**{team_name}**
| Agent | Type | Model | Status |
|-------|------|-------|--------|
| {agent_name} | {agent_type} | {model} | active |

(If no active teams, show "No active teams.")

### Circuit Breaker Health
| Integration | State | Failures | Last Error | Status Code | Last Failure |
|-------------|-------|----------|------------|-------------|-------------|
| todoist | HEALTHY | 0 | — | — | — |
| trello | OPEN | 3 | timeout | 503 | 2026-03-27 |
| jira | HEALTHY | 0 | — | — | — |

(If no circuit breaker file exists, show "No circuit breaker data — all integrations healthy.")

### Orphaned Resources
(If `.team-state/orphaned-resources.yaml` exists, show recent entries. Otherwise "No orphaned resources.")

### Recent Team Activity
(If `.team-state/failed-teams.yaml` exists, show recent entries. Otherwise "No recent team activity.")

Suggested next: `1. /proj:status` -- full project overview

## Prerequisites

- Team mode must be enabled in config (`team_mode.enabled: true`).
- An active project must be loaded.

## Error Handling

- **Team mode not enabled**: displays "Team mode is not enabled. Run `/proj:init-plugin` to enable it." and stops.
- **No active project**: displays error from `proj_session_context` and stops.
- **Team state directory missing**: shows "No active teams" and "No recent team activity".

## Output

Formatted status with sections: Team Mode Configuration (enabled, max agents, trust level), Active Teams (table with members), per-agent status tables, Circuit Breaker Health, Orphaned Resources, and Recent Team Activity.

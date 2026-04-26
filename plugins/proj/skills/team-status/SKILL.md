---
name: team-status
description: Show active and recent teams, circuit breaker health, and per-agent status. Use when asked "team status", "show teams", or "proj:team-status".
allowed-tools: mcp__proj__config_load, mcp__proj__proj_session_context, Read, Bash
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Show team status.

**1.** `mcp__proj__config_load` → check `team_mode.enabled`.
 - Not enabled → stop: "Team mode is not enabled. Run `/proj:init-plugin` to enable it."

**2.** `mcp__proj__proj_session_context` → get project name, tracking_dir.

**3.** Read `<tracking_dir>/<project>/.team-state/`:
 - `failed-teams.yaml` for recent failures
 - `circuit-breakers.yaml` for circuit breaker state
 - `orphaned-resources.yaml` for orphaned resources

**4.** Read active teams from `~/.claude/teams/`:
 - Each subdir: read `config.json` if exists
 - Extract team name, desc, members
 - Each member: name, agentType/model, status (based on inbox msgs)
 - No team dirs/config → "No active teams"

**5.** Formatted output:

### Team Mode Config
- Enabled: yes
- Max agents: {max_agents}
- Trust level: {trust_level} ({trust_name})

### Active Teams
| Team | Members | Description |
|------|---------|-------------|
| {team_name} | {member_count} agents | {description} |

Per-agent status each active team:

**{team_name}**
| Agent | Type | Model | Status |
|-------|------|-------|--------|
| {agent_name} | {agent_type} | {model} | active |

(No active teams → "No active teams.")

### Circuit Breaker Health
| Integration | State | Failures | Last Error | Status Code | Last Failure |
|-------------|-------|----------|------------|-------------|-------------|
| todoist | HEALTHY | 0 | — | — | — |
| trello | OPEN | 3 | timeout | 503 | 2026-03-27 |
| jira | HEALTHY | 0 | — | — | — |

(No file → "No circuit breaker data — all integrations healthy.")

### Orphaned Resources
(File exists → show entries. Else "No orphaned resources.")

### Recent Team Activity
(File exists → show entries. Else "No recent team activity.")

Suggested next: `1. /proj:status` -- full project overview

## Prerequisites

- `team_mode.enabled: true` in config.
- Active project loaded.

## Err Handling

- Team mode off → "Team mode is not enabled. Run `/proj:init-plugin` to enable it." Stop.
- No active project → err from `proj_session_context`. Stop.
- Team state dir missing → "No active teams", "No recent team activity".

## Output

Formatted status w/ sections: Team Mode Config, Active Teams table, per-agent tables, Circuit Breaker Health, Orphaned Resources, Recent Team Activity.

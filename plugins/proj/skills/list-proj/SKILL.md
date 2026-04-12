---
name: list-proj
description: List all non-archived tracked projects. Use when the user says "list projects", "show projects", "what projects do I have", or invokes /proj:list-proj.
allowed-tools: mcp__proj__proj_list
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List all non-archived tracked projects.

1. `mcp__proj__proj_list` (no args — defaults non-archived).
2. Display result as-is.

## Prerequisites

Proj plugin configured (`~/.claude/proj.yaml` exists).

## Err Handling

No projects → empty list/msg. Config not found → show err, stop.

## Output

Non-archived projects w/ names + status.

Next: `1. /proj:load <name>` — load project for session

---
name: list-proj
description: List all non-archived tracked projects. Use when the user says "list projects", "show projects", "what projects do I have", or invokes /proj:list-proj.
allowed-tools: mcp__proj__proj_list
context: fork
agent: general-purpose
---

List all non-archived tracked projects.

**1.** Call `mcp__proj__proj_list` (no arguments — defaults to non-archived only).
**2.** Display the result as-is.

## Prerequisites

- Proj plugin must be configured (`~/.claude/proj.yaml` exists).

## Error Handling

- **No projects found**: displays an empty list or message indicating no tracked projects.
- **Config not found**: displays error from tool call and stops.

## Output

List of non-archived projects with names and status.

Suggested next: `1. /proj:load <name>` -- load a project for this session

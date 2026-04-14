---
shared: errors
---
> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

## Agent Escalation Protocol

Spawned agents lack user-facing tools. Bridge via structured return values.

Agent detects need for user input → return:

```json
{
  "status": "escalation_needed",
  "issue": "<question or decision needed>",
  "context": "<why this matters>",
  "options": ["opt1", "opt2"]
}
```

Parent reads Agent result → `AskUserQuestion` w/ options → spawns new Agent w/ resolution ctx + user's answer.

Use for: plan gaps, ambiguous reqs, architectural decisions, scope clarifications, edge cases not covered by reqs.

Agents must NOT improvise, guess, or auto-resolve when user input needed. Return escalation immediately.

### Plan Escalation

Agent researched + drafted impl plan → return:

```json
{
  "status": "plan_escalation",
  "plan": "<full plan content — Context, Files, Changes, Verification>"
}
```

Parent reads result → `EnterPlanMode` → writes plan file → `ExitPlanMode` → if approved, spawns new Agent w/ approved plan.

### Agent Prompt Inclusion

All agent spawn instructions MUST include:

```
If you encounter work outside approved plan or need user input:
return {status: "escalation_needed", issue: "<description>", options: [...]}
Do NOT improvise or auto-fix.

If you need plan approval:
return {status: "plan_escalation", plan: "<plan>"}
```

## Manual-Tagged Todo Handling

`todo_check_executable` → result starts w/ "⚠️" → display warning, **stop** (skip this todo).

Log: `⚠️ Todo <id> [manual] — skipped execute`.

In batch: collect `manual_skipped_ids = []`, exclude from all subsequent phases.

## Worktree Failure Handling

| Failure | During | Action |
|---------|--------|--------|
| `wt_create` fails | Setup (Phase 1.5) | Fall back to main for that todo, warn |
| Agent crashes in worktree | Execute (Phase 2) | Leave worktree intact for debugging, report in summary |
| Clean merge | Merge (Phase 2.5) | Commit, continue |
| Auto-resolvable conflict | Merge (Phase 2.5) | Apply per-file ours/theirs strategy, commit |
| Non-auto-resolvable conflict | Merge (Phase 2.5) | Prompt user: manual resolve or abort to serial queue |
| Post-merge test failure (1 merge) | Merge (Phase 2.5) | Revert merge, re-execute on main |
| Post-merge test failure (N merges) | Merge (Phase 2.5) | Git bisect to find breaking merge, offer revert |

`-X theirs` + `git rerere` intentionally NOT used.

## Agent Tool Availability

| Tool | Available in spawned agents? |
|------|------------------------------|
| AskUserQuestion | NO |
| EnterPlanMode / ExitPlanMode | NO |
| Read / Edit / Write / Bash / Glob / Grep | YES |
| Task tools (TaskCreate, TaskUpdate, etc.) | YES |
| MCP tools (proj, worktree, sandbox, router, etc.) | YES |

## Agent Fallback

If `subagent_type="<name>"` not found (agent .md missing/renamed):
1. Log warning via `notes_append`: "Agent definition '<name>' not found, falling back to general-purpose"
2. `Agent(subagent_type="general-purpose", prompt=<inline_fallback>)` w/ minimal role desc
3. Fallback prompts (one-line per agent):
   - `implementer`: "Implement approved plan. Read requirements + research, follow plan steps, write code + tests, commit w/ [todo-{id}] prefix."
   - `verification-fixer`: "Fix verification failures. Read report + todo ctx + reqs + plan. Apply targeted fixes, re-run tests."
   - `ambiguity-reviewer`: "Review requirements.md + research.md for undefined terms, handwavey claims, unmeasurable goals. Return JSON {agent, findings}."
   - `completeness-reviewer`: "Review requirements.md + research.md for missing failure modes, auth/security gaps, scope holes. Return JSON {agent, findings}."
   - `research-validator`: "Validate research.md file refs exist, option distinctness, risk realism. Return JSON {agent, findings}."
   - `file-path-verifier`: "Verify all file paths in plan resolve to existing files. Return JSON {agent, findings}."
   - `spec-plan-alignment`: "Compare plan against requirements.md acceptance criteria. Flag unaddressed criteria. Return JSON {agent, findings}."
   - `impact-scanner`: "Scan codebase for callers/consumers of files in plan. Flag potential breakage. Return JSON {agent, findings}."

## Common Error Conditions

- No active project → error, stop
- Todo not found → error from `todo_get`
- Manual-tagged → skip w/ warn (see above)
- Blocked todo → error, stop
- Invalid step name → error
- Stale checkpoint → ask restart or use stale
- No todo ID → `Todo ID required.` + usage
- Quality gate failure (define) → low-confidence display, Continue/Re-define/Stop
- Verification failures → combined report, Fix/Proceed/Skip
- Agent failures → report + log to `failed-agents.yaml`

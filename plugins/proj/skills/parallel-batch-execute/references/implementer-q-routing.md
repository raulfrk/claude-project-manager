# Implementer Q-Routing Rubric

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Q-routing model: parent absorbs, escalate ambiguity. Matches superpowers:subagent-driven-development behavior.

## Decision tree

Implementer Q arrives:

1. Q answerable from spec/plan/conversation ctx -> orchestrator answers; impl unblocks.
2. Q contradicts user-stated pref (e.g. user said "no abstractions"; impl asks "should I add base class") -> orchestrator answers "no" + reason; impl unblocks.
3. Genuinely ambiguous (multiple valid choices, no spec/plan signal) -> queue Q for batch flush.
4. Decision changes spec scope -> queue + flag as `scope-question` (will require user attention).

## Flush triggers (whichever first)

a) Pending buffer hits 4 Qs (AskUserQuestion max per managed rule 4).
b) All currently-active impls blocked on a Q (deadlock-avoid).
c) 30s elapsed since the *current* pending buffer's first Q (timer resets after each flush).

## Flush mechanic

Single `AskUserQuestion` call:

- Max 4 Qs per managed rule 4.
- Per-Q: rich context (which impl/todo asked, why ambiguous).
- Multi-choice when answer enumerable; "Other" for free-form.
- Relay each answer back to originating impl. Impl unblocks + continues.

## Anti-patterns

- Escalating Qs answerable from ctx (creates user fatigue).
- Allowing impl to proceed without an answer (breaks superpowers gate parity).
- Batching > 4 Qs into one ask (violates managed rule 4).
- Auto-answering ambiguous Qs from training priors (always escalate when unsure).

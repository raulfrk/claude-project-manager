# Plan-Execute Pattern Design for Agent Teams

## Context

The current execute/SKILL.md defines Phase 1/2/3 for ranges:
- **Phase 1** — Plan (sequential in main, user approves each plan)
- **Phase 2** — Execute (parallel Task agents, no todo_complete)
- **Phase 3** — Satisfaction check (sequential in main, satisfaction loops, todo_complete)

We need to choose a pattern that optimizes: user visibility/control, confirmation mechanics, latency, parallelism preservation, and implementation complexity.

---

## Pattern A: Sequential Plan, Parallel Execute

**Flow:**
1. Main conversation: plan todo 1 → user approves
2. Main conversation: plan todo 2 → user approves
3. Main conversation: plan todo N → user approves
4. All approved plans → spawn N parallel Task agents (execute all at once)
5. Main conversation: sequential satisfaction checks → todo_complete each

**Pros:**
- ✅ High user visibility & control — sees each plan before it's executed
- ✅ Confirmation is explicit and granular — one approval per plan
- ✅ Parallelism preserved — Phase 2 runs all agents concurrently
- ✅ Simple implementation — reuse existing Phase 1/2/3 structure
- ✅ Clear mental model — plan happens first, execution second

**Cons:**
- ⚠️ Latency: Phase 1 is sequential (N plan cycles × latency per plan)
- ⚠️ If user rejects a plan, main conversation is blocked until they revise or skip
- ⚠️ Context window: Phase 1 can grow large if many todos

**Implementation complexity:** Low — matches current SKILL.md structure

**Latency breakdown:**
- Phase 1: O(N × T_plan) where T_plan = plan mode time per todo
- Phase 2: O(T_exec_max) — all agents run in parallel
- Phase 3: O(N × T_satisfaction) — sequential satisfaction checks
- Total: O(N × T_plan + T_exec_max + N × T_satisfaction)

---

## Pattern B: Batch Plan, Batch Execute

**Flow:**
1. Main conversation: read all todos (no planning yet)
2. Main conversation: create a master plan covering the entire batch
   - "Here's what will change across all 5 todos: files X, Y, Z affected; todo 1 touches files X+Y, todo 2 touches Y+Z, etc."
   - User approves the entire master plan at once
3. Spawn N parallel Task agents with the master plan
4. Sequential satisfaction checks

**Pros:**
- ✅ Reduced latency in Phase 1 — one plan cycle instead of N
- ✅ User sees the full picture upfront — dependencies, file interactions
- ✅ Parallelism preserved
- ✅ Single approval gate (less friction if batch is coherent)

**Cons:**
- ⚠️ Master plan is harder to generate (cross-todo dependencies)
- ⚠️ Master plan approval is higher-stakes (reject and must replan entire batch)
- ⚠️ User control is coarser — all-or-nothing approval
- ⚠️ Complex to implement — needs new master-planning logic

**Implementation complexity:** High — requires cross-todo dependency analysis

**Latency breakdown:**
- Phase 1: O(T_master_plan) — single plan cycle
- Phase 2: O(T_exec_max)
- Phase 3: O(N × T_satisfaction)
- Total: O(T_master_plan + T_exec_max + N × T_satisfaction)

---

## Pattern C: Plan Agents with Approval Relay

**Flow:**
1. Main conversation spawns N parallel planning agents
   - Each agent plans one todo in isolation
   - Agents send `plan_approval_request` to lead with their plan
2. Lead collects all plans
3. Lead asks user: "Review these N plans" + presents all at once
4. User approves all or requests changes
5. After user approval: spawn N parallel execution agents
6. Sequential satisfaction checks

**Pros:**
- ✅ Lowest Phase 1 latency — N agents plan in parallel
- ✅ User sees all plans together (can spot cross-todo issues)
- ✅ High parallelism
- ✅ Lead acts as coordinator (explicit role)

**Cons:**
- ⚠️ Highest implementation complexity — need plan_approval_request relay + multi-agent coordination
- ⚠️ Context window risk — collecting N plans in lead thread
- ⚠️ Harder to debug — planning happens in agent threads
- ⚠️ User approval is batched (less granular control per todo)

**Implementation complexity:** Very High — new protocol (plan_approval_request), multi-agent coordination

**Latency breakdown:**
- Phase 1: O(T_plan_max) — agents plan in parallel, lead waits for slowest
- Phase 2: O(T_exec_max)
- Phase 3: O(N × T_satisfaction)
- Total: O(T_plan_max + T_exec_max + N × T_satisfaction)

---

## Pattern D: Hybrid (Auto-Approval + Complex-Review)

**Flow:**
1. Main conversation: analyze todo batch for complexity
   - "Simple" todos (small, isolated) → auto-approve → queue for Phase 2
   - "Complex" todos (large, cross-file, many changes) → require plan review
2. For complex todos: run Pattern A (sequential plan + user approval)
3. Once all approvals done: spawn parallel Task agents for all approved todos
4. Sequential satisfaction checks

**Pros:**
- ✅ Balances latency & control — simple todos don't block on planning
- ✅ User only reviews complex plans (less cognitive load)
- ✅ Parallelism preserved for execution
- ✅ Flexible — tunable simplicity heuristic

**Cons:**
- ⚠️ "Simple" heuristic is subjective & error-prone
- ⚠️ Risk: auto-approve a todo that needed review
- ⚠️ Implementation complexity — need classifier logic
- ⚠️ Harder to explain to user ("why was this auto-approved?")

**Implementation complexity:** Medium — need simplicity classifier + conditional approval

---

## Decision Matrix

| Pattern | Latency | User Control | Confirmation | Parallelism | Complexity | Risk |
|---------|---------|--------------|--------------|-------------|-----------|------|
| A       | Medium  | High         | Granular     | ✅ Yes     | Low       | Low  |
| B       | Low     | Medium       | Batched      | ✅ Yes     | High      | Med  |
| C       | Lowest  | Medium       | Batched      | ✅ Yes     | Very High | High |
| D       | Low-Med | High         | Hybrid       | ✅ Yes     | Medium    | Med  |

---

## Recommendation: **Pattern A (Sequential Plan, Parallel Execute)**

### Why Pattern A Wins

1. **Best fit for current codebase** — SKILL.md Phase 1/2/3 already structured this way
2. **User control is explicit** — each plan reviewed individually before execution
3. **Implementation is simple** — minimal new code, reuses existing patterns
4. **Latency is acceptable** — Phase 1 is sequential but relatively fast (planning is lighter than execution)
5. **Risk is low** — conservative approach, user sees everything
6. **Debugging is straightforward** — main conversation has full context

### Why Not the Others

- **Pattern B:** Higher complexity for marginal latency gain (Phase 1 bottleneck is small vs. Phase 2)
- **Pattern C:** Overkill complexity for agent teams that already specialize; planning is inherently sequential (need context from previous todos)
- **Pattern D:** Adds fragile heuristic logic; unclear when to auto-approve

---

## Winning Flow Details

### Phase 1: Sequential Planning (Main Conversation)

```
for each todo in range:
  1. Check executable (skip if manual)
  2. Get todo context
  3. EnterPlanMode → create plan → ExitPlanMode
  4. User reviews and approves (or requests changes)
  5. Store approved plan + context for Phase 2
```

**Confirmation Mechanics:**
- User sees plan output from ExitPlanMode
- Implicit approval if user doesn't object
- User can say "go ahead", "change X", or "skip this one"

**Latency:** ~5-10 min for N todos (assuming ~1 min per plan)

### Phase 2: Parallel Execution (Task Agents)

```
spawn N parallel Task agents:
  each agent receives:
    - todo details + status
    - requirements.md + research.md
    - parent context
    - APPROVED PLAN from Phase 1
    - mark in_progress
    - implement per plan (no modifications to plan)
    - do NOT mark complete
    - return implementation artifacts (code, test results, etc.)
```

**Parallelism:** All agents run concurrently, Phase 2 time = longest agent time

### Phase 3: Sequential Satisfaction (Main Conversation)

```
for each executed todo (excluding manual):
  1. Review agent's work
  2. Run satisfaction loop:
     - "Are you satisfied?"
     - If not: capture missing work → create new todo → run on new todo
     - Loop until satisfied
  3. Mark todo complete
  4. Sync to Todoist/Trello if enabled
```

**Confirmation Mechanics:**
- User reviews outcome and provides feedback
- Unsatisfied work spawns new todos (iterated execution)
- Explicit completion per todo

---

## Implementation Notes

### For the execute/SKILL.md Rewrite

1. **Keep Phase 1/2/3 structure** — don't over-engineer
2. **Store phase 1 artifacts** — make approved plans available to Phase 2 agents
   - Option: pass plans as Task agent parameters
   - Option: store in project context, agents fetch by todo_id
3. **Satisfy loop in Phase 3** — handle "not satisfied" case by creating new todos
4. **Git flush at end** — single commit with all Phase 2 work

### Key Behaviors

- **User doesn't need to approve each plan explicitly** — ExitPlanMode shows the plan, user's silence = approval (or user can object before Phase 2 starts)
- **No plan modifications in Phase 2** — agents follow the approved plan strictly
- **Phase 3 reuse** — satisfaction loop logic is already in SKILL.md step 5a-5c
- **Manual todos** — skip at Phase 2, note in Phase 3 summary

---

## Edge Cases & Handling

| Case | Handling |
|------|----------|
| User rejects a plan in Phase 1 | Stop Phase 1, ask for revision or skip; re-run Phase 1 for that todo |
| Agent fails in Phase 2 | Catch error, report in Phase 3, create "fix" todo or ask user |
| New todos created in Phase 3 satisfaction | Run on them with `/proj:execute <new_id> --iter 5` (respects iteration limit) |
| Blocked dependencies between todos | Phase 2 executes sequentially in dependency order; adjust agent parallelism |
| User wants to skip a todo after Phase 1 | Skip Phase 2 for that todo; Phase 3 summary notes it |

---

## Success Criteria

A successful implementation of Pattern A should:

1. ✅ All plans reviewed before any execution
2. ✅ Execution happens in parallel for independent todos
3. ✅ User can reject/modify plans before Phase 2 starts
4. ✅ Phase 3 satisfaction loop covers new-todo creation (iteration)
5. ✅ Latency is lower than sequential full-execution per todo
6. ✅ Code is maintainable (Phase 1/2/3 clearly separated)

# Bidirectional Sync: Proj Todos ↔ Claude Code Tasks

## Executive Summary

Design the full flow for syncing proj todos with Claude Code tasks:
- User invokes `/proj:execute 1-5` → execute/SKILL spawns Team
- Proj todos automatically mirrored as Claude Code tasks
- Teammates claim tasks and execute work
- Completion syncs back to proj todos
- Satisfaction loop handles missing work with new todos

**Key Decision: Bidirectional, Real-Time, Push-On-Event Sync**

---

## Context & Problem

### Current State
- **Proj**: Full project tracking system (todos.yaml, parent-child hierarchy, dependencies, Todoist/Trello sync)
- **Claude Code Tasks**: Lightweight task system (TaskCreate, TaskList, TaskUpdate, metadata)
- **Disconnect**: When executing batches with agents, no integration between proj todos and Claude Code tasks
  - Agents don't see proj context (requirements, research, parent)
  - Completion happens in agents but proj todos not updated
  - Satisfaction loop happens sequentially in main (slow for parallelism)

### What We Need
1. **Push todos → tasks** when Phase 1 ends (all plans approved)
2. **Agents claim tasks** and execute
3. **Sync completion back** to proj (including satisfaction status)
4. **Pull missing work** back as new proj todos (from satisfaction loop)
5. **One source of truth** — decide: proj owns todos, tasks are views? Or true bidirectional?

---

## Design: Bidirectional, Real-Time Sync

### Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **Direction** | Bidirectional | Agents see full context; satisfaction creates new tasks; unclear which system "owns" at runtime |
| **Timing** | Real-time (event-driven) | Push when Phase 1 ends, pull when agents report completion |
| **Sync Scope** | Todos (proj) ↔ Tasks (Claude Code) | Omit subtasks initially; sync root + independent batch |
| **Authority** | Proj is source of truth | Tasks are ephemeral views; proj owns state |
| **MCP Tool** | YES: `proj_sync_to_tasks()` | Encapsulate sync logic; reusable across skills |

### Sync Flow Overview

```
User: /proj:execute 1-5
  ↓
execute/SKILL Phase 1: Plan todos 1-5 (sequential)
  ↓
Phase 1 approved → Call proj_sync_to_tasks(task_ids=[1,2,3,4,5])
  │
  ├─→ Create 5 Claude Code tasks + metadata
  ├─→ Store task_id → todo_id mapping (in proj.metadata or task.metadata)
  ├─→ Teams agent spawned (can see all 5 tasks now)
  │
  └─→ TaskCreate for each todo
      {
        subject: "Todo 1: [title]",
        description: "Requirements: [snippet]\n\nResearch: [snippet]\n\nParent: [parent title]\n\nPlan: [approved plan]",
        metadata: { todo_id: "1", project: "claude-project-manager", sync_version: 1 }
      }

Phase 2: Teammates execute (parallel)
  ├─ Agent-1 claims task 1, executes
  ├─ Agent-2 claims task 2, executes (concurrent)
  └─ Agent-N claims task N, executes (concurrent)
  │
  └─→ Each agent on completion: TaskUpdate + proj_sync_from_tasks(task_id=N)
      (Marks proj todo in_progress → pulls completion status + artifacts)

Phase 3: Satisfaction checks (sequential, main conversation)
  ├─ Review each completed task
  ├─ User: "Are you satisfied?"
  │  └─ No → new todo created
  │     └─→ Call proj_sync_to_tasks() again for new todo (creates new task)
  └─ Mark todo complete + sync back
     └─→ proj_sync_from_tasks() confirms task is done
```

---

## Data Model

### Todo Fields (Proj)
```yaml
todo:
  id: "1"
  title: "Add --force flag"
  status: "pending|in_progress|completed"
  requirements: "Add flag to CLI..."
  research: "Flag pattern in argparse..."
  parent: "root"
  blocked_by: []
  priority: "p1"
  tags: ["backend"]

  # NEW: Sync metadata
  sync_metadata:
    synced_to_task: true
    task_id: "task-uuid-abc123"
    task_version: 1
    last_synced: "2026-03-26T14:30:00Z"
    approval_plan: "# Implementation Plan\nFiles: ..."  # from Phase 1 ExitPlanMode
```

### Task Fields (Claude Code)
```json
{
  "id": "task-uuid-abc123",
  "status": "pending|in_progress|completed",
  "subject": "Todo 1: Add --force flag",
  "description": "**Requirements:**\nAdd flag to CLI...\n\n**Research:**\nFlag pattern in argparse...\n\n**Parent:**\nRoot: Full project management\n\n**Approved Plan:**\n# Implementation Plan\nFiles to modify: ...",
  "owner": "agent-1",
  "blockedBy": [],
  "blocks": [],
  "metadata": {
    "todo_id": "1",
    "project_name": "claude-project-manager",
    "sync_version": 1,
    "approval_plan": "...",
    "code_changes": ["src/cli.py", "tests/test_cli.py"],  # populated after completion
    "satisfaction_status": "pending|satisfied|iterate",
    "artifacts": {
      "test_output": "12 tests passing...",
      "diff_summary": "12 insertions, 3 deletions"
    }
  }
}
```

---

## MCP Tool: `proj_sync_to_tasks()`

### Purpose
Bidirectional sync entry point. Manages creation, update, and deletion of Claude Code tasks from proj todos.

### Signature
```python
def proj_sync_to_tasks(
  project_name: str | None = None,  # infer from session or arg
  todo_ids: list[str] | None = None,  # specific todos to sync (default: all active)
  approval_plans: dict[str, str] | None = None,  # maps todo_id → approved plan (Phase 1)
  action: str = "sync"  # "sync" (create/update), "unsync" (delete tasks), "refresh" (update existing)
) -> dict:
  """
  Sync proj todos to Claude Code tasks.

  Returns:
  {
    "action": "sync|unsync|refresh",
    "synced": {
      "1": { "task_id": "uuid1", "task_status": "pending", "subject": "Todo 1: ..." },
      "2": { "task_id": "uuid2", "task_status": "pending", "subject": "Todo 2: ..." },
      ...
    },
    "created": ["uuid1", "uuid2"],
    "updated": ["uuid3"],
    "failed": [{ "todo_id": "5", "reason": "manual tag" }],
    "mapping": { "1": "uuid1", "2": "uuid2" }  # todo_id → task_id
  }
  """
```

### Implementation Steps

1. **Fetch todos**
   - If `todo_ids` provided: fetch those
   - Else: fetch all active (status="pending" or "in_progress")
   - Filter: skip manual-tagged todos

2. **Check existing sync**
   - For each todo: check `sync_metadata.task_id`
   - If task exists: TaskUpdate (refresh mode)
   - If not: TaskCreate

3. **Build task description**
   ```
   **Requirements:**
   {requirements.md excerpt, first 500 chars}

   **Research:**
   {research.md excerpt, first 500 chars}

   **Parent:**
   {parent.title} (if parent exists)

   **Approved Plan:**
   {approval_plans[todo_id] if provided, else "Plan available after Phase 1"}
   ```

4. **Create/Update tasks**
   - TaskCreate with subject, description, metadata
   - Store returned task_id in todo.sync_metadata.task_id
   - Update sync_metadata fields

5. **Return mapping**
   - Return dict of todo_id → task_id mappings

### Error Handling

- **Manual todo**: Log warning, skip
- **Task creation fails**: Return in "failed", continue with others
- **Permission denied**: Fail fast (perms issue, not sync issue)

---

## MCP Tool: `proj_sync_from_tasks()`

### Purpose
Pull completion status and artifacts back from Claude Code tasks to proj todos.

### Signature
```python
def proj_sync_from_tasks(
  task_ids: list[str] | None = None,  # specific tasks to sync back
  project_name: str | None = None,
  pull_artifacts: bool = True  # include code_changes, test results
) -> dict:
  """
  Sync Claude Code task completion back to proj todos.

  Returns:
  {
    "synced": {
      "1": {
        "todo_id": "1",
        "task_id": "uuid1",
        "task_status": "completed",
        "artifacts": { "code_changes": [...], "test_output": "..." }
      },
      ...
    },
    "todo_status_updates": {
      "1": "in_progress"  # based on task status
    },
    "failed": []
  }
  """
```

### Implementation Steps

1. **Fetch tasks** by task_id or by metadata.todo_id
2. **For each task**:
   - Extract metadata.todo_id
   - Find corresponding proj todo
   - If task.status == "completed":
     - Store artifacts in todo metadata
     - Set todo.status = "in_progress" (ready for Phase 3 satisfaction)
   - Return artifacts + todo_id mapping

3. **Persist**:
   - Call `todo_update` for each todo (update sync_metadata, status)

---

## Agent Execution Pattern (Phase 2)

### How Agents See Tasks

Each agent receives a task with full context in `description`:

```
**Requirements:**
Add --force flag to delete command...

**Research:**
Argparse patterns: use add_argument with action="store_true"...

**Parent:**
Implement CLI improvements

**Approved Plan:**
Files to modify:
  - src/cli.py (add --force flag, lines 45-48)
  - tests/test_cli.py (add parametrized test)

Implementation order:
  1. Modify parser (src/cli.py)
  2. Update handler logic
  3. Write tests
  4. Manual test
```

### How Agents Update Completion

```
Agent executes todo 1:
  1. Mark task in_progress (TaskUpdate)
  2. Call proj_sync_from_tasks(task_ids=["uuid1"])
     → sets proj todo to "in_progress"
  3. Implement per approved plan
  4. On completion:
     - TaskUpdate with:
       * status = "completed"
       * metadata.code_changes = ["src/cli.py", "tests/test_cli.py"]
       * metadata.artifacts.test_output = "12 tests passing"
  5. Call proj_sync_from_tasks(task_ids=["uuid1"]) again
     → pulls task completion, marks proj todo "in_progress" (ready for Phase 3)
```

### Task Ownership

- **Task owner**: Agent ID (set by TeamCreate or agent assignment)
- **Task blockedBy**: Infer from proj todo.blocked_by (optional; agents can ignore)
- **Task blocks**: Infer from dependent todos (optional)

---

## Phase 3: Satisfaction Loop with New Tasks

### Satisfaction in Main Conversation

```
Phase 3 executes sequentially in main:

For each completed task:
  1. TaskGet to fetch latest state
  2. Review: code_changes, test_output, artifacts
  3. Ask user: "Satisfied?"

  If satisfied:
    - Mark proj todo complete
    - TaskUpdate(task, status="completed")
    - Call proj_sync_from_tasks() to finalize

  If not satisfied:
    - Capture missing work from user
    - Create new proj todo (child of original)
    - Call proj_sync_to_tasks([new_todo_id])
      → creates new Claude Code task
    - If user wants, agent can claim new task and execute
    - Loop satisfaction again on new task
```

### New Todos from Satisfaction

```python
# User says: "Not satisfied, needs error handling for edge case X"
new_todo = todo_add_child(
  parent_id="1",
  title="Add error handling for edge case X"
)

# Sync new todo to task
result = proj_sync_to_tasks(
  todo_ids=[new_todo.id],
  approval_plans={new_todo.id: "Plan TBD or auto-generated"}
)

# Now the new task exists; agents can claim it
```

---

## Handling Edge Cases

### Case 1: Task Completed Before Phase 3
- Agent marks task as completed
- proj_sync_from_tasks() pulls status, marks proj todo "in_progress"
- Phase 3: proceeds normally

### Case 2: Agent Fails Mid-Execution
- Task left in "in_progress"
- Phase 3: prompt user "Task stuck in progress, create recovery todo?"
- Option: mark task completed, create new recovery todo

### Case 3: User Modifies Plan Mid-Phase-2
- Task description is stale
- Phase 3: TaskUpdate can refresh description (but don't invalidate agent work)
- Decision: disallow mid-phase modifications (tell user to create new todo)

### Case 4: Multiple Agents Claim Same Task
- Claude Code task system handles via owner field
- Proj: don't worry (agent coordination is their problem)
- First agent to claim wins; second sees "owned by Agent-N"

### Case 5: New Todos Created During Phase 3
- proj_sync_to_tasks() called for each new todo
- If Phase 2 agents still running: they won't see new tasks (sequential Phase 3)
- Decision: new tasks created in Phase 3 are NOT auto-executed (tell user to `/proj:execute <id>` manually if wanted)

---

## Success Criteria

### Sync Completeness
- ✅ All non-manual active todos synced to tasks at Phase 1 end
- ✅ Task descriptions include requirements, research, parent, approved plan
- ✅ Agents can read full context from task description
- ✅ Metadata maps todos ↔ tasks bidirectionally

### Execution
- ✅ Agents can TaskGet to fetch task details
- ✅ Agents can TaskUpdate to mark progress
- ✅ Completion syncs back to proj todos
- ✅ New tasks created for satisfaction loop misses

### Satisfaction
- ✅ Phase 3 reviews task artifacts (code_changes, test_output)
- ✅ Unsatisfied work → new todos → new tasks
- ✅ Loop until all tasks satisfied

### Implementation Complexity
- ✅ `proj_sync_to_tasks()` < 100 lines
- ✅ `proj_sync_from_tasks()` < 100 lines
- ✅ No schema changes to existing proj or task systems (only metadata)
- ✅ execute/SKILL updates minimal (call sync at Phase 1 end, Phase 3 start/end)

---

## Integration with execute/SKILL

### Phase 1 End (Sequential)
```python
# After all plans approved:
sync_result = proj_sync_to_tasks(
  project_name=active_project,
  todo_ids=approved_todo_ids,
  approval_plans=plans_dict  # { "1": plan1, "2": plan2, ... }
)

# Log: "Created 5 Claude Code tasks"
# Task IDs available for Phase 2
```

### Phase 2 Start (Parallel)
```python
# For each approved todo, spawn agent with:
todo_details = {
  "id": "1",
  "title": "...",
  "sync_metadata": {
    "task_id": sync_result.mapping["1"]  # from Phase 1 sync
  }
}

# Agent instructions:
# "Task {task_id} is ready. Execute per the approved plan."
```

### Phase 2 Agent (Parallel)
```python
# Agent receives task_id in metadata
task = TaskGet(id=metadata.task_id)
# Task.description has full context

# On completion:
TaskUpdate(id=task_id, status="completed", metadata={...artifacts...})
proj_sync_from_tasks(task_ids=[task_id])  # update proj todo
```

### Phase 3 Start (Sequential)
```python
# Refresh all tasks to get latest metadata
for todo_id in completed_todos:
  task_id = todo.sync_metadata.task_id
  task = TaskGet(id=task_id)
  artifacts = task.metadata.artifacts

  # Review and satisfy
```

### Phase 3 Satisfaction (Sequential)
```python
# If not satisfied:
new_todo = todo_add_child(parent_id=todo_id, title=feedback)

# Sync new todo
proj_sync_to_tasks(todo_ids=[new_todo.id])

# New task created; visible to teams or user can re-execute manually
```

---

## TaskCreate Description Format (Critical)

### Question: What Goes in Task Description?

**Bad** (too terse):
```
Execute Todo 1: Add --force flag
```

**Good** (full context):
```
**Requirements:**
Add a --force flag to the delete command to force-delete without confirmation.

**Research:**
Argparse patterns for boolean flags: use add_argument('--force', action='store_true').

**Parent:**
Implement CLI improvements

**Approved Plan:**

## Implementation Plan

Files to modify:
- src/cli.py (add --force flag to argument parser, ~3 lines)
- tests/test_cli.py (add parametrized test for force={True, False}, ~5 lines)

Implementation order:
1. Modify parser (line 45-48)
2. Update handler logic to check force flag
3. Write parametrized tests
4. Manual test: python cli.py delete --force

Testing approach:
- Unit test: parametrized delete handler with force=True|False
- Integration test: CLI invocation with --force flag
```

**Format**:
```
**Requirements:**
{first 400 chars of requirements.md}

**Research:**
{first 400 chars of research.md}

**Parent:**
{parent.title if exists}

**Approved Plan:**
{approval_plan (full, from Phase 1 ExitPlanMode)}
```

**Why This Works**:
- Agents see the "why" (requirements + research)
- Agents see the "how" (approved plan with file list, order, testing)
- Parent context prevents isolation
- Agents don't need to fetch proj context externally

---

## Teammate Access to Proj Context

### How Agents Get Context
1. **At task creation**: Full context in task.description
2. **At task execution**: TaskGet fetches task details (no proj system calls needed)
3. **On completion**: Store artifacts in task.metadata, proj_sync_from_tasks() pulls them

### Do Agents Need Proj MCP Tools?
- **NO** for reading context (task description has everything)
- **YES** for creating new todos in satisfaction loop
- **Decision**: Agents DON'T call proj tools directly
  - Main conversation (Phase 3) creates new todos
  - Main conversation calls proj_sync_to_tasks() for each new todo
  - Agents only interact with task system

### Can Teammates See Proj Notes?
- Task description has requirements + research (key parts)
- Full NOTES.md not in task (too verbose)
- Decision: if agent needs full notes, Phase 3 can provide via message

---

## Metadata Design: One Source of Truth

### Proj (Source of Truth)
```yaml
todo:
  id: "1"
  title: "Add --force flag"
  sync_metadata:
    synced_to_task: true
    task_id: "uuid-abc123"
    task_version: 1
    approval_plan: "# Implementation Plan..."
    last_synced: "2026-03-26T14:30:00Z"
```

### Claude Code Task (View/Ephemeral)
```json
{
  "metadata": {
    "todo_id": "1",
    "project_name": "claude-project-manager",
    "sync_version": 1,
    "satisfaction_status": "pending|satisfied|iterate",
    "approval_plan": "# Implementation Plan...",
    "code_changes": ["src/cli.py", "tests/test_cli.py"],
    "artifacts": {
      "test_output": "...",
      "diff_summary": "..."
    }
  }
}
```

**Why This Design**:
- Proj is persistent (todos.yaml)
- Tasks are ephemeral (can be deleted, re-created)
- Metadata maps them; if task deleted, recreate from proj

---

## Summary: Winning Approach

| Aspect | Choice | Why |
|--------|--------|-----|
| **Direction** | Bidirectional | Agents update tasks; Phase 3 creates new tasks from feedback |
| **Timing** | Push on Phase 1 end, pull on completion | Event-driven, no polling |
| **Authority** | Proj is source of truth | Persistent; tasks are views |
| **Context** | Full in task description | Agents don't need proj calls |
| **New Todos** | Created in Phase 3 main conversation | Keeps Phase 3 sequential and clear |
| **Sync Tools** | YES: `proj_sync_to_tasks()` + `proj_sync_from_tasks()` | Encapsulated, reusable, low complexity |
| **Satisfaction** | Main conversation reviews task artifacts | Sequential, user-driven |

**Latency**: Minimal
- Phase 1: +1 sync call (all at once)
- Phase 2: No impact (agents work in parallel)
- Phase 3: +1 sync call per new todo (only on dissatisfaction)

**Complexity**: Low
- execute/SKILL: 3 sync calls (Phase 1 end, Phase 2 agents, Phase 3 feedback)
- New MCP tools: ~150 lines total
- Metadata: no schema changes, just new optional fields

**User Visibility**: High
- Tasks visible in Claude Code task system
- Teammates can see full context in task description
- Satisfaction loop transparent (new tasks created as needed)

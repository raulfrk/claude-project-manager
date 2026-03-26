# Sync Tool Implementation Specification

## Overview

Two new MCP tools in the proj plugin:
1. `proj_sync_to_tasks()` — Push proj todos to Claude Code tasks
2. `proj_sync_from_tasks()` — Pull Claude Code task completion back to proj

Both tools are utility functions, not skills (no user interaction).

---

## Tool 1: `proj_sync_to_tasks()`

### Purpose
Create or update Claude Code tasks mirroring proj todos. Called at Phase 1 end to set up task environment for agents.

### Signature
```python
def proj_sync_to_tasks(
    project_name: str | None = None,
    todo_ids: list[str] | None = None,
    approval_plans: dict[str, str] | None = None,
    action: str = "sync",
    force_refresh: bool = False
) -> dict:
    """
    Sync proj todos to Claude Code tasks.

    Args:
        project_name: Active project (default: from session)
        todo_ids: List of todo IDs to sync (default: all active, non-manual)
        approval_plans: Dict mapping todo_id → approved plan text from Phase 1
        action: "sync" (create/update), "unsync" (delete), "refresh" (update only)
        force_refresh: Ignore existing sync_metadata, recreate all tasks

    Returns:
        {
            "action": "sync|unsync|refresh",
            "synced_count": N,
            "created": ["uuid1", "uuid2", ...],
            "updated": ["uuid3", ...],
            "deleted": ["uuid4", ...],
            "failed": [
                {
                    "todo_id": "1",
                    "reason": "manual tag",
                    "error": "..."
                }
            ],
            "mapping": {
                "1": "uuid-abc123",
                "2": "uuid-xyz789",
                ...
            }
        }
    """
```

### Implementation Algorithm

```python
def proj_sync_to_tasks(project_name=None, todo_ids=None, approval_plans=None, action="sync", force_refresh=False):
    # 1. Load project context
    if not project_name:
        project_name = get_active_project()

    project = proj_get(project_name)

    # 2. Determine which todos to sync
    if todo_ids is None:
        todos = todo_list(project_name, status="active")  # pending + in_progress
        todo_ids = [t["id"] for t in todos]
    else:
        todos = [todo_get(project_name, id) for id in todo_ids]

    # 3. Filter manual-tagged todos
    todos = [t for t in todos if "manual" not in t.get("tags", [])]

    created = []
    updated = []
    deleted = []
    failed = []
    mapping = {}

    # 4. For each todo, create or update task
    for todo in todos:
        try:
            # Check if already synced
            sync_meta = todo.get("sync_metadata", {})
            existing_task_id = sync_meta.get("task_id")

            # Build task description
            description = build_task_description(todo, approval_plans)

            # Build metadata
            metadata = {
                "todo_id": todo["id"],
                "project_name": project_name,
                "sync_version": 1,
                "satisfaction_status": "pending",
                "approval_plan": approval_plans.get(todo["id"], "TBD"),
                "code_changes": [],
                "artifacts": {
                    "test_output": "",
                    "diff_summary": ""
                }
            }

            if action == "unsync" and existing_task_id:
                # Delete task
                task_delete(existing_task_id)
                deleted.append(existing_task_id)

                # Update todo: remove sync_metadata
                todo_update(project_name, todo["id"], sync_metadata=None)

            elif action == "refresh" or action == "sync":
                if existing_task_id and not force_refresh:
                    # Update existing task
                    task_update(
                        existing_task_id,
                        description=description,
                        metadata=metadata
                    )
                    updated.append(existing_task_id)
                    mapping[todo["id"]] = existing_task_id

                else:
                    # Create new task
                    subject = f"Todo {todo['id']}: {todo['title']}"
                    task = task_create(
                        subject=subject,
                        description=description,
                        metadata=metadata
                    )
                    task_id = task["id"]
                    created.append(task_id)

                    # Update todo: store sync_metadata
                    new_sync_meta = {
                        "synced_to_task": True,
                        "task_id": task_id,
                        "task_version": 1,
                        "approval_plan": approval_plans.get(todo["id"], "TBD"),
                        "last_synced": current_iso_timestamp()
                    }
                    todo_update(project_name, todo["id"], sync_metadata=new_sync_meta)

                    mapping[todo["id"]] = task_id

        except Exception as e:
            failed.append({
                "todo_id": todo["id"],
                "reason": "sync_error",
                "error": str(e)
            })

    return {
        "action": action,
        "synced_count": len(created) + len(updated),
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "failed": failed,
        "mapping": mapping
    }


def build_task_description(todo, approval_plans):
    """Build Claude Code task description from proj todo."""

    # Fetch requirements and research if available
    req_path = f"{todo_dir(todo['id'])}/requirements.md"
    research_path = f"{todo_dir(todo['id'])}/research.md"

    requirements = read_file_excerpt(req_path, 400) if file_exists(req_path) else "[None provided]"
    research = read_file_excerpt(research_path, 400) if file_exists(research_path) else "[None provided]"

    # Parent context
    parent_title = todo.get("parent", "")
    if parent_title and parent_title != "root":
        parent_context = f"Parent: {parent_title}"
    else:
        parent_context = ""

    # Approval plan
    approval_plan = approval_plans.get(todo["id"], "Plan available after Phase 1")

    # Build description
    parts = [
        f"**Requirements:**\n{requirements}",
        f"\n\n**Research:**\n{research}",
    ]

    if parent_context:
        parts.append(f"\n\n**Parent:**\n{parent_context}")

    parts.append(f"\n\n**Approved Plan:**\n{approval_plan}")

    return "".join(parts)


def read_file_excerpt(path, max_chars):
    """Read first max_chars of file."""
    try:
        with open(path, "r") as f:
            content = f.read(max_chars)
            if len(content) == max_chars:
                return content + "..."
            return content
    except:
        return "[File not found]"
```

### Error Handling

| Error | Handling |
|-------|----------|
| Manual-tagged todo | Skip with warning, continue |
| Task creation fails | Add to "failed", continue |
| Project not found | Fail fast |
| Approval plans missing | Use "Plan TBD" in description |
| Proj todo not found | Skip with warning |

### Usage in execute/SKILL

**At Phase 1 end:**
```python
# Phase 1: all plans approved

approved_plans = {
    "1": "# Implementation Plan\nFiles: src/cli.py...",
    "2": "# Implementation Plan\nFiles: ...",
    # ... all approved todos
}

sync_result = proj_sync_to_tasks(
    project_name=active_project,
    todo_ids=approved_todo_ids,
    approval_plans=approved_plans,
    action="sync"
)

if sync_result["failed"]:
    log(f"Warning: {len(sync_result['failed'])} todos failed to sync")

log(f"Synced {sync_result['synced_count']} todos to Claude Code tasks")
task_mapping = sync_result["mapping"]  # todo_id → task_id

# Phase 2 uses task_mapping to spawn agents
```

---

## Tool 2: `proj_sync_from_tasks()`

### Purpose
Pull Claude Code task completion back to proj todos. Called by agents after execution and by Phase 3 for satisfaction.

### Signature
```python
def proj_sync_from_tasks(
    task_ids: list[str] | None = None,
    project_name: str | None = None,
    pull_artifacts: bool = True,
    update_todo_status: bool = True
) -> dict:
    """
    Sync Claude Code task completion back to proj todos.

    Args:
        task_ids: List of task IDs to sync back (default: all synced tasks in project)
        project_name: Active project (default: from session)
        pull_artifacts: Include code_changes, test results in return value
        update_todo_status: Update proj todo status based on task status

    Returns:
        {
            "synced_count": N,
            "synced": {
                "1": {
                    "todo_id": "1",
                    "task_id": "uuid-abc123",
                    "task_status": "completed|in_progress|pending",
                    "artifacts": {
                        "code_changes": ["src/cli.py", "tests/test_cli.py"],
                        "test_output": "12 tests passing",
                        "diff_summary": "12 insertions, 3 deletions"
                    },
                    "satisfaction_status": "pending"
                }
            },
            "failed": [
                {
                    "task_id": "uuid-def456",
                    "reason": "todo not found",
                    "error": "..."
                }
            ]
        }
    """
```

### Implementation Algorithm

```python
def proj_sync_from_tasks(task_ids=None, project_name=None, pull_artifacts=True, update_todo_status=True):
    # 1. Load project context
    if not project_name:
        project_name = get_active_project()

    project = proj_get(project_name)

    # 2. Determine which tasks to sync
    if task_ids is None:
        # Find all tasks that have todo_id in metadata (synced to this project)
        all_tasks = task_list()  # Get all tasks in session
        task_ids = [
            t["id"] for t in all_tasks
            if t.get("metadata", {}).get("project_name") == project_name
        ]

    synced = {}
    failed = []

    # 3. For each task, pull completion status back to todo
    for task_id in task_ids:
        try:
            task = task_get(task_id)
            metadata = task.get("metadata", {})
            todo_id = metadata.get("todo_id")

            if not todo_id:
                failed.append({
                    "task_id": task_id,
                    "reason": "no_todo_id",
                    "error": "Task metadata missing todo_id"
                })
                continue

            # Fetch proj todo
            todo = todo_get(project_name, todo_id)

            # Extract artifacts from task metadata
            artifacts = metadata.get("artifacts", {})
            code_changes = metadata.get("code_changes", [])
            satisfaction_status = metadata.get("satisfaction_status", "pending")

            # Update todo status based on task status
            new_todo_status = todo["status"]
            if task["status"] == "completed":
                new_todo_status = "in_progress"  # Ready for Phase 3 satisfaction
            elif task["status"] == "in_progress":
                new_todo_status = "in_progress"

            # Prepare sync metadata update
            sync_meta = todo.get("sync_metadata", {})
            sync_meta.update({
                "task_version": sync_meta.get("task_version", 1) + 1,
                "last_synced": current_iso_timestamp(),
                "task_status": task["status"],
                "satisfaction_status": satisfaction_status,
                "artifacts": {
                    "code_changes": code_changes,
                    "test_output": artifacts.get("test_output", ""),
                    "diff_summary": artifacts.get("diff_summary", "")
                }
            })

            # Update proj todo
            if update_todo_status:
                todo_update(
                    project_name,
                    todo_id,
                    status=new_todo_status,
                    sync_metadata=sync_meta
                )
            else:
                todo_update(project_name, todo_id, sync_metadata=sync_meta)

            synced[todo_id] = {
                "todo_id": todo_id,
                "task_id": task_id,
                "task_status": task["status"],
                "artifacts": artifacts if pull_artifacts else {},
                "satisfaction_status": satisfaction_status
            }

        except Exception as e:
            failed.append({
                "task_id": task_id,
                "reason": "sync_error",
                "error": str(e)
            })

    return {
        "synced_count": len(synced),
        "synced": synced,
        "failed": failed
    }
```

### Error Handling

| Error | Handling |
|-------|----------|
| Task not found | Add to "failed", continue |
| Todo not found (via todo_id in task metadata) | Add to "failed", continue |
| Task metadata missing todo_id | Add to "failed", continue |
| Proj sync fails | Add to "failed", continue |

### Usage in execute/SKILL

**By agents after execution:**
```python
# Agent completes todo 1

# TaskUpdate: mark complete, set artifacts
task_update(task_id, status="completed", metadata={
    "code_changes": ["src/cli.py", "tests/test_cli.py"],
    "artifacts": {
        "test_output": "12 tests passing...",
        "diff_summary": "12 insertions, 3 deletions"
    },
    "satisfaction_status": "pending"
})

# Sync back to proj
result = proj_sync_from_tasks(task_ids=[task_id])
# Returns: todo 1 now status="in_progress", sync_metadata updated with artifacts
```

**In Phase 3 for satisfaction:**
```python
# Phase 3: review completed todos

for todo_id in completed_todos:
    task_id = todo.sync_metadata.task_id

    # Pull latest task state
    result = proj_sync_from_tasks(task_ids=[task_id], pull_artifacts=True)

    # Review artifacts
    todo_sync = result["synced"][todo_id]
    print(f"Code changes: {todo_sync['artifacts']['code_changes']}")
    print(f"Tests: {todo_sync['artifacts']['test_output']}")

    # Ask satisfaction
    # ... (existing Phase 3 loop)
```

---

## Integration with execute/SKILL

### Full Flow with Sync Calls

**Phase 1: Sequential Planning**
```
for todo_id in todo_ids:
  - get context
  - EnterPlanMode
  - create plan
  - ExitPlanMode
  - [user approves]
  - store plan in approved_plans[todo_id]

# Phase 1 complete
```

**Between Phase 1 and 2: SYNC PUSH**
```
sync_result = proj_sync_to_tasks(
    project_name=active_project,
    todo_ids=approved_todo_ids,
    approval_plans=approved_plans
)
# Creates N Claude Code tasks, returns mapping: todo_id → task_id
```

**Phase 2: Parallel Agent Execution**
```
for (todo_id, task_id) in sync_result.mapping.items():
    agent = spawn_agent(
        todo_id=todo_id,
        task_id=task_id,
        task_details=task_get(task_id)  # Agent reads full context
    )

# All agents run in parallel
results = wait_for_all(agents)

# Agents call proj_sync_from_tasks() on completion
```

**Phase 3: Sequential Satisfaction**
```
for todo_id in completed_todos:
    task_id = todo.sync_metadata.task_id

    # Refresh task state
    result = proj_sync_from_tasks(task_ids=[task_id])

    # Review
    artifacts = result.synced[todo_id]["artifacts"]
    print(f"Code: {artifacts['code_changes']}")

    # Satisfaction check
    if user_satisfied:
        todo_complete(todo_id)
        task_update(task_id, status="completed")
    else:
        # User feedback → create new todo
        new_todo = todo_add_child(parent_id=todo_id, title=feedback)

        # Sync new todo
        new_sync = proj_sync_to_tasks(
            todo_ids=[new_todo.id],
            approval_plans={}  # Plan TBD
        )

        # New task created; Phase 3 continues (or user can re-execute)
```

---

## Considerations & Tradeoffs

### One Source of Truth: Proj
- **Pro**: Persistent, canonical state
- **Con**: Tasks become ephemeral (can be deleted, recreated)
- **Tradeoff**: Acceptable for team execution (tasks are work-in-progress)

### Metadata Design
- **Pro**: No schema changes to existing proj or task systems
- **Con**: Duplicates some data (approval plan stored in both)
- **Tradeoff**: Acceptable for sync robustness (decoupled systems)

### Real-Time vs. Polling
- **Pro**: Event-driven, immediate sync
- **Con**: Requires explicit calls at known points
- **Tradeoff**: Acceptable (Phase 1 end, Phase 2 completion, Phase 3 feedback)

### Agents Don't Call Proj Tools
- **Pro**: Keeps agents decoupled, simpler Agent code
- **Con**: Main conversation handles all todo creation
- **Tradeoff**: Acceptable (Phase 3 is sequential anyway)

### Task Description Size
- **Pro**: Full context in one place
- **Con**: Description can be large (~2-5KB per task)
- **Tradeoff**: Acceptable (Claude Code tasks can handle this)

---

## Testing Strategy

### Unit Tests
- `test_proj_sync_to_tasks()`: verify task creation, metadata, description format
- `test_proj_sync_from_tasks()`: verify artifact pulling, status updates

### Integration Tests
- End-to-end: execute Phase 1 → sync → agent execution → sync back → satisfaction

### Edge Cases
- Manual-tagged todos (skip, no task created)
- Task creation fails (added to failed list, continue)
- Existing sync_metadata (update mode, don't recreate)
- New todos from satisfaction (sync, create new tasks)

---

## Summary

| Aspect | Spec |
|--------|------|
| **Tool 1** | `proj_sync_to_tasks()` — Create/update tasks from todos |
| **Tool 2** | `proj_sync_from_tasks()` — Pull completion back to todos |
| **Location** | `plugins/proj/server/server/` (new module: `sync.py`) |
| **Schema** | Metadata-only (no breaking changes) |
| **Calls** | 3 per execute run (Phase 1 end, Phase 2 agents, Phase 3 feedback) |
| **Complexity** | ~200 lines total code |
| **Error Handling** | Graceful (failed items logged, continue) |
| **Testing** | Unit + integration tests needed |

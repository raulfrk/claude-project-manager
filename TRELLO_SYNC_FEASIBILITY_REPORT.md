# Trello Sync Unified Tool Feasibility Report

**Investigation Date**: 2026-03-29
**Todo**: 376
**Question**: Can a single MCP tool handle the ENTIRE Trello sync (fetch → diff → execute → write local state) and return just a summary + structured error list?

---

## VERDICT: **FEASIBLE WITH MAJOR ARCHITECTURAL CONSTRAINTS**

The unified approach is technically feasible **but creates tight coupling and violates the plugin architecture's separation of concerns**. Not recommended for production.

---

## EXECUTIVE SUMMARY

### Current Architecture (Multi-Tool Flow)
```
Skill: /proj:trello-sync
  → /proj:trello-fetch (fetch Trello state)
  → /proj:trello-diff  (compute diff, optional auto-apply of pulls)
  → /proj:trello-push  (execute Trello API operations)
  → /proj:trello-link  (link returned IDs, flush git)
  5 separate MCP tool calls, model orchestrates + validates
```

### Proposed Single-Tool Flow
```
New tool: trello_unified_sync(project_name, dry_run=False, retry_failures=[])
  ✓ Fetch Trello card state (calls trello plugin internally)
  ✓ Compute diff against local todos (compute_diff() from proj)
  ✓ Execute all Trello API operations (batch_update_checklist_items, create_checklist, etc.)
  ✓ Write local state updates to proj tracking dir (todos.yaml, meta.yaml)
  ✓ Return: {summary, errors_by_category, linked_ids, sync_state_snapshots}
```

**Key Trade-off**: Moves complexity from Claude (model-orchestrated) to MCP server (tool-orchestrated). Reduces tool calls from 5→1, but:
- Increases server-side logic complexity (error recovery, retry, transactionality)
- Requires inter-plugin socket communication (proj ↔ trello) inside a tool
- Blocks on all Trello API operations before returning (no streaming feedback)
- Makes debugging harder when things fail mid-operation

---

## DETAILED ANALYSIS

### 1. Can a Single Tool Call All Trello APIs AND Write Local Proj State?

**SHORT ANSWER**: Yes, with socket-based inter-plugin communication.

#### Current Inter-Plugin Communication Pattern

The system uses **Unix domain sockets** for plugin-to-plugin communication:

**Direction 1: Proj → Trello (Hooks)**
- `proj` plugin registers hooks in `~/.claude/hooks.yaml`
- When a `proj` tool runs, the hook dispatcher sends a POST to the `trello` plugin socket at `/tmp/claude-cpm-trello-<pid>.sock`
- Example hook: `todo_add` → triggers `trello_add_card_hook` on trello plugin

**Direction 2: Trello → Proj (Missing, Would Require New Pattern)**
- Currently trello plugin is **read-only** in terms of proj state
- Trello tools (from `plugins/trello/server/server/tools/cards.py`) only call the Trello HTTP API
- They have NO way to write back to proj's `todos.yaml` or `meta.yaml`

#### Obstacle #1: Trello Plugin Cannot Write to Proj State

**Root Cause**: Trello plugin doesn't import or have write access to proj's storage module.

```python
# Current: plugins/trello/server/server/tools/cards.py
from server.lib.client import get_client()  # ← Trello HTTP client only
# ✗ No: from ../../../proj/server/server/lib import storage
```

**Why This Matters**:
- `apply_changes()` in `proj/tools/trello_sync.py` (line 734) loads/modifies/saves todos and meta
- It's tightly coupled to proj's storage layer: `storage.load_todos()`, `storage.save_todos()`, `storage.load_meta()`, `storage.save_meta()`
- Trello plugin cannot replicate this without importing proj's code → **breaks plugin isolation**

**Solution Options**:
1. **Socket-based RPC**: Trello calls back to proj's new tool like `proj_write_todo_state(todos_json, meta_json)` via socket
2. **Shared storage layer**: Move `storage.py` to a common location (`plugins/_shared/storage/`) → both plugins import it
3. **Single plugin**: Merge trello and proj into one — **not acceptable**

#### Obstacle #2: Transactionality Across Plugins

If the unified tool:
1. Executes 50 Trello API calls (create/update/delete items)
2. 15 succeed, 35 fail with rate limits / network errors
3. Tries to write local state for only the 15 that succeeded

**Problem**: If the write fails (disk full, permission error), you've already sent changes to Trello but can't record them locally.

**Current mitigation**: Each tool is small and idempotent. If `trello-push` fails halfway through, the model can retry and the `trello_sync_state` snapshots (recorded by `apply_changes()`) let the next run detect what's already been synced.

**Unified tool mitigation**: Would need:
- Two-phase commit (collect all operations, validate, execute, then write all at once)
- Rollback capability (undo Trello changes if local write fails) — **very hard**
- Or accept eventual consistency and rely on next sync to fix orphaned links

#### Obstacle #3: Batching & Rate Limits

Trello API has **per-second rate limits**: ~10 calls/sec for a token.

**Current flow**:
- `/proj:trello-push` uses `batch_update_checklist_items()` which loops and retries with exponential backoff
- Model can see partial progress and decide whether to retry

**Unified tool**:
- Would need to implement same retry logic internally
- If it hits a rate limit at call #35 of 60, it blocks and returns an error
- Model cannot see which 35 succeeded unless we return detailed failure lists
- Next invocation must have a retry mechanism

---

### 2. Inter-Plugin Communication Mechanisms

#### A. Socket-Based RPC (Current Pattern for Proj→Trello via Hooks)

**How it works now**:
```
Proj tool executes
  ↓
Hook dispatcher (in proj) intercepts
  ↓
POST to `trello` plugin socket with {tool: "trello_add_checklist_item_hook", params: {...}}
  ↓
Trello plugin's FastMCP server receives, executes hook tool
  ↓
Response returned via socket
```

**For Trello→Proj**:
```
Trello tool (in unified_sync) needs to update todos
  ↓
Calls a new proj tool via socket: POST {tool: "proj_write_todos_state", params: {...}}
  ↓
Proj plugin's FastMCP server executes
  ↓
Updates todos.yaml, meta.yaml
  ↓
Response returned
```

**Pros**:
- Maintains plugin isolation (no shared code)
- Reuses existing socket infrastructure
- Async-compatible (FastMCP runs on asyncio)

**Cons**:
- Extra latency (socket round-trip for each write operation)
- Complex error handling (socket timeout, deserialization failure)
- Debugging is harder (errors happen in two places)
- If one plugin crashes, the other hangs waiting for response

**Code location**: Socket logic is in `plugins/_shared/hook_dispatch/dispatch.py` and each plugin's `main.py` calls `enable_hook_dispatch(mcp)`.

#### B. Shared Storage Module (Alternative)

Move `plugins/proj/server/server/lib/storage.py` to `plugins/_shared/storage.py`.

Both proj and trello import it:
```python
from ..._shared.storage import load_todos, save_todos, load_meta, save_meta
```

**Pros**:
- No socket overhead
- Direct function calls (faster)
- Simpler error handling

**Cons**:
- Both plugins now depend on a shared module
- If shared module changes, both plugins must be updated
- Storage becomes "public API" — harder to refactor later
- Configuration loading (cfg object) must be consistent across plugins

---

### 3. Data Input & Output Schema

#### Input: What the Unified Tool Needs

```python
@app.tool(description="...")
def trello_unified_sync(
    project_name: str | None = None,
    dry_run: bool = False,
    retry_failures: list[dict] | None = None,  # For resuming from errors
) -> str:
    """
    Unified Trello sync: fetch → diff → push → write in one call.

    Args:
      project_name: Active project or explicit name. If None, uses session active.
      dry_run: If True, compute diff and return plan without executing Trello/local writes.
      retry_failures: [{"type": "item_update", "item_id": "...", "checklist_id": "..."}]
                      Re-attempt failed operations from a previous run.

    Returns JSON with structure below.
    """
```

#### Output: Success Response

```json
{
  "status": "success",
  "project_name": "my-project",
  "duration_seconds": 4.2,
  "summary": {
    "fetched": {
      "checklists_count": 3,
      "items_count": 12,
      "card_valid": true
    },
    "diff": {
      "pull_create_count": 2,
      "pull_complete_count": 1,
      "push_create_checklist_count": 1,
      "push_update_item_count": 5,
      "push_delete_item_count": 0,
      "conflict_count": 0
    },
    "executed": {
      "trello_api_calls": 9,
      "trello_api_calls_failed": 0,
      "local_todos_created": 2,
      "local_todos_updated": 5,
      "local_todos_completed": 1
    }
  },
  "changes": {
    "linked_ids": [
      {"todo_id": "2.1", "trello_item_id": "6123abc", "trello_checklist_id": "..."},
      ...
    ],
    "created_todos": ["3.1", "3.2"],
    "sync_state_updated": 8  // todos with trello_sync_state recorded
  },
  "dry_run": false
}
```

#### Output: Partial Failure Response

```json
{
  "status": "partial_success",
  "project_name": "my-project",
  "summary": {
    "fetched": {...},
    "diff": {...},
    "executed": {
      "trello_api_calls": 15,
      "trello_api_calls_failed": 3,
      "local_todos_created": 2,
      "local_todos_updated": 4  // 5 planned, 1 failed
    }
  },
  "errors": [
    {
      "phase": "trello_push",
      "operation": "batch_update_checklist_items",
      "error": "HTTP 429 Too Many Requests",
      "retryable": true,
      "retry_payload": {
        "type": "batch_update_checklist_items",
        "card_id": "...",
        "updates": [
          {"checklist_id": "...", "item_id": "...", "name": "..."},
          ...
        ]
      }
    },
    {
      "phase": "local_write",
      "operation": "save_todos",
      "error": "Permission denied: /home/raul/.../todos.yaml",
      "retryable": false,
      "details": "Could not write local state. Trello changes were made but not reflected locally."
    }
  ],
  "resume_token": "retry_id_20260329_143000_abc123"
}
```

#### Retry Format

After a partial failure, the model can invoke:

```json
{
  "retry_failures": [
    {
      "operation": "batch_update_checklist_items",
      "card_id": "...",
      "updates": [...]
    },
    {
      "operation": "save_todos",
      "todos_json": "{...}"
    }
  ]
}
```

The tool replays only the failed operations and returns a fresh status response.

---

### 4. Async & Concurrency Considerations

#### Current Batching in Trello Plugin

```python
# plugins/trello/server/server/tools/cards.py, line 78-103
def batch_create_cards(cards: list[dict[str, str]]) -> str:
    for idx, card in enumerate(cards):
        try:
            created = client.post("/cards", params=params)
            successes.append(created)
        except Exception as exc:
            failures.append({...})
    return json.dumps({"successes": successes, "failures": failures})
```

**Issue**: Sequential loop, no parallelization.

#### Unified Tool Requirements

For 50+ Trello operations in a single sync, sequential execution would:
- Take ~10 seconds (assuming 200ms per call)
- Hit rate limits easily
- Block the model for the entire duration

**Solution**: Use async/await + concurrency limits

```python
import asyncio
from collections import deque

async def batch_operations(operations, max_concurrent=3, max_retries=3):
    """
    Execute operations with concurrency limit and exponential backoff.
    """
    results = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def execute_one(op):
        async with semaphore:
            for attempt in range(max_retries):
                try:
                    result = await client.post_async(...)
                    return {"status": "success", "result": result}
                except RateLimitError:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
                except Exception as e:
                    return {"status": "error", "error": str(e), "retryable": is_retryable(e)}

    tasks = [execute_one(op) for op in operations]
    results = await asyncio.gather(*tasks)
    return results
```

**Tradeoff**: Async execution means:
- Must refactor Trello client (`client.post()` → `client.post_async()`)
- FastMCP already runs on asyncio, so this is feasible
- Need to manage connection pooling carefully

**Current status**: Not implemented in trello plugin. Trello client is synchronous HTTP.

---

### 5. Can Trello Plugin Call Into Proj's Compute Functions?

**Question**: If trello plugin calls `compute_diff()` to generate the plan, can it then execute and apply in one go?

**Answer**: **Highly constrained, requires significant refactoring**.

#### Current Coupling

`compute_diff()` (line 215, `proj/tools/trello_sync.py`) assumes:
- `cfg` object with proj config
- `name` project name
- Reads local todos via `storage.load_todos(cfg, name)` (proj's storage)
- Reads archived todos (proj-specific history)

```python
def compute_diff(
    trello_card_json: str,
    cfg: Any,
    name: str,
) -> TrelloSyncPlan:
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)
    archived = storage.load_archived_todos(cfg, name)
    # ... rest of diff logic ...
```

**To make this callable from trello plugin**:
- Trello would need to import proj's storage module (`from proj.lib import storage`)
- Or call a proj socket tool: `proj_compute_trello_diff(trello_card_json, project_name)` → returns plan
- Or move `compute_diff()` to shared code (`_shared/trello_sync_logic.py`)

**Recommendation**: If building a unified tool in proj plugin (not trello), you can call `compute_diff()` directly since it's already there. The unified tool lives in proj, not trello.

---

## RECOMMENDED DESIGN: Unified Sync Tool in Proj Plugin

Instead of putting the unified tool in the trello plugin, **put it in the proj plugin** (`plugins/proj/server/server/tools/trello_sync.py`). This:

1. ✓ Has direct access to `compute_diff()`, `apply_changes()`, storage
2. ✓ Already imports trello MCP tools via the client
3. ✓ Minimal architectural disruption
4. ✓ Can call Trello operations via the trello plugin's existing tools (batch_update_checklist_items, etc.)

### New Tool Signature

```python
@app.tool(description="...")
def proj_trello_full_sync(
    project_name: str | None = None,
    dry_run: bool = False,
    retry_failures: list[dict] | None = None,
) -> str:
    """
    One-shot Trello sync: fetch Trello state, compute diff, execute all
    operations (push to Trello + local writes), return summary.

    Returns detailed summary with structured error list for retryable failures.
    """
    # 1. Get project & config
    result = require_project(project_name)
    cfg, proj_name = result
    meta = storage.load_meta(cfg, proj_name)

    # 2. Fetch Trello card state
    try:
        card = fetch_trello_card(meta.trello_card_id, cfg.trello)
        card_json = json.dumps(card)
    except Exception as e:
        return json.dumps({"status": "error", "phase": "fetch", "error": str(e)})

    # 3. Compute diff (local function, no socket needed)
    plan = compute_diff(card_json, cfg, proj_name)

    if dry_run:
        return json.dumps({"status": "success", "dry_run": True, "plan": plan.to_dict()})

    # 4. Execute pushes to Trello (batch operations with retry logic)
    push_results = execute_trello_operations(plan, cfg, meta)  # see schema below

    # 5. Handle failures from push phase
    if push_results["failed"]:
        return json.dumps({
            "status": "partial_success",
            "phase": "trello_push",
            "errors": push_results["errors"],
            "retry_token": push_results["retry_token"],
        })

    # 6. Link Trello IDs from push results
    link_data = build_link_data(push_results["linked_ids"])

    # 7. Apply local changes (create todos, update metadata, record sync state)
    counts = apply_changes(plan, link_data, cfg, proj_name)

    # 8. Return success summary
    return json.dumps({
        "status": "success",
        "summary": {...},
        "changes": {...},
    })
```

### Input Schema

```json
{
  "project_name": "my-project",
  "dry_run": false,
  "retry_failures": [
    {
      "operation_type": "batch_update_checklist_items",
      "card_id": "...",
      "updates": [
        {
          "checklist_id": "...",
          "item_id": "...",
          "state": "complete"
        }
      ]
    },
    {
      "operation_type": "batch_create_cards",
      "cards": [...]
    }
  ]
}
```

### Output Schema (Detailed)

```json
{
  "status": "success|partial_success|error",
  "project_name": "my-project",
  "timestamp": "2026-03-29T14:30:00Z",

  "summary": {
    "phase": "fetch|diff|execute_push|apply_local",
    "execution_time_ms": 4200,

    "fetch": {
      "card_found": true,
      "checklists_count": 3,
      "items_count": 12
    },

    "diff": {
      "pull_create_count": 2,
      "pull_update_count": 0,
      "pull_complete_count": 1,
      "pull_reopen_count": 0,
      "pull_create_root_count": 0,
      "push_create_checklist_count": 1,
      "push_create_item_count": 3,
      "push_update_item_count": 2,
      "push_complete_item_count": 1,
      "push_delete_item_count": 0,
      "push_rename_checklist_count": 0,
      "conflict_count": 0
    },

    "execution": {
      "trello_operations_planned": 10,
      "trello_operations_succeeded": 10,
      "trello_operations_failed": 0,
      "trello_api_calls": 12,
      "local_todos_created": 2,
      "local_todos_updated": 0,
      "local_todos_completed": 1,
      "trello_ids_linked": 5
    }
  },

  "errors": [
    {
      "operation_type": "batch_update_checklist_items",
      "error_code": "rate_limit",
      "error_message": "HTTP 429: Too Many Requests",
      "retryable": true,
      "retry_payload": {
        "card_id": "...",
        "updates": [...]
      },
      "failed_count": 2,
      "index_in_batch": [5, 7]
    }
  ],

  "retry_token": "sync_20260329_143000_xyz789",
  "dry_run": false
}
```

---

## COMPARISON: Current vs. Unified Approach

| Aspect | Current (5 Tools) | Unified (1 Tool) |
|--------|------------------|-----------------|
| **Tool calls** | 5 (fetch, diff, push, link, git) | 1 |
| **Latency** | ~2–4 sec (sequential) | ~2–4 sec (async batching) |
| **Error recovery** | Model decides, can retry specific steps | Tool handles retries, model sees final state |
| **Transactionality** | High (each tool is atomic) | Lower (partial failures need careful handling) |
| **Debugging** | Easier (each tool is small) | Harder (complex state machine inside tool) |
| **Code complexity** | Simpler (each tool is independent) | Higher (batching, async, retry logic) |
| **Rate limiting** | Implicit (model slows down) | Explicit (tool has backoff logic) |
| **Interruptibility** | Yes (model can stop after any step) | No (tool runs to completion or failure) |
| **Works with plan mode** | Yes (`--iter` retries whole flow) | Unclear (plan can't dynamically adjust mid-tool) |

---

## MAIN OBSTACLES

### 1. **Plugin Isolation**: Trello → Proj State Write
- **Problem**: Trello plugin has no way to write to proj's todos.yaml
- **Mitigation**: Either socket-based RPC or shared storage module
- **Feasibility**: Difficult but doable

### 2. **Transactionality**: Partial Failures
- **Problem**: If 10/20 Trello ops succeed and local write fails, state is inconsistent
- **Mitigation**: Two-phase commit, rollback, or accept eventual consistency
- **Feasibility**: Accept eventual consistency (next sync will fix it)

### 3. **Async/Concurrency**: Rate Limits
- **Problem**: Current trello client is synchronous; unified tool needs async batching
- **Mitigation**: Refactor to `asyncio`-based client
- **Feasibility**: Feasible but requires trello plugin changes

### 4. **Retryability**: Structured Errors
- **Problem**: If operation #35 of 60 fails, how does model know which to retry?
- **Mitigation**: Return `{"failed_operations": [...], "retry_token": "..."}` structure
- **Feasibility**: Straightforward (follow pattern from existing batch tools)

### 5. **Plan Mode Compatibility**: Mid-Execution Adjustment
- **Problem**: If tool is running inside a plan and hits an error, can't pause for user input
- **Mitigation**: Tool must either (a) auto-recover, (b) return detailed errors and let model try again, or (c) keep separate steps for user review
- **Feasibility**: Recommend keeping separate `/proj:trello-push` for user review of operations before execution

---

## RECOMMENDATION

### BUILD: Unified Sync Tool in Proj Plugin (proj_trello_full_sync)

**Why**:
1. Single point of truth (proj plugin)
2. Direct access to compute_diff() and apply_changes()
3. Minimal new code (reuse existing functions)
4. Cleaner for batch/automated workflows

**Constraints**:
1. **Must include structured retry format** — if X operations fail, return `{failed_operations, retry_token}`
2. **Must implement async batching** in trello client calls — limit concurrency to respect rate limits
3. **Should keep separate push step optional** — for workflows where user wants to review before applying
4. **Accept eventual consistency** — if local write fails after Trello push, next sync will detect orphaned links

**Not Recommended**: Merging trello plugin into proj plugin or forcing trello plugin to write proj state via socket.

---

## IMPLEMENTATION ROADMAP

If proceeding with unified tool in proj:

### Phase 1: Add Tool Signature & Error Format
- New tool: `proj_trello_full_sync(project_name, dry_run, retry_failures)`
- Define input/output schemas (JSON)

### Phase 2: Implement Core Logic
- Reuse `compute_diff()` (already exists)
- Implement `execute_trello_operations()` — calls batch tools with retry logic
- Reuse `apply_changes()` (already exists)
- Implement retry handler

### Phase 3: Add Async Batching (Optional but Recommended)
- Refactor trello client to support `async` calls
- Add concurrency limiter (max 3–5 concurrent calls)
- Add exponential backoff for rate limits

### Phase 4: Update Skills
- `/proj:trello-sync` can now call `proj_trello_full_sync` directly (skip sub-skills)
- Or keep sub-skills for granular control + plan mode
- Consider adding `/proj:trello-full-sync` as alternative to multi-step version

---

## FINAL VERDICT

**Feasible: YES**

**Production-Ready: CONDITIONAL**
- Requires careful error handling and retry logic
- Suitable for automated/batch workflows
- Less suitable for interactive workflows requiring mid-execution user review
- Recommended to keep the current multi-step approach for plan mode and user control

**Recommendation**: Build the unified tool as an **optional** alternative path for power users / automation, but don't replace the current multi-step flow by default.

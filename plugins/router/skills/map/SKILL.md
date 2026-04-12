---
name: map
description: Generate an interactive HTML visualization of the hook network. Shows hooks as a directed graph with condition-status color coding.
allowed-tools: mcp__plugin_router_router__router_list_tool, Read, Bash
argument-hint: "[--output <path>]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Gen hook network visualization: $ARGUMENTS

**1.** Parse args

Extract `--output <path>` from $ARGUMENTS. Default: `/tmp/hooks-map.html`.

**2.** Load hook data

`mcp__plugin_router_router__router_list_tool` (no args) → all registered hooks. Each hook: `id`, `trigger_tool`, `target_tool`, `server`, `blocking`, `verification`, `condition`, `condition_status` (`always`/`active`/`inactive`/`runtime`), `param_mapping`.

`condition_status` pre-computed by hooks server — use directly for color coding, never recompute.

**3.** Read condition ctx

Read `~/.claude/proj.yaml` for enabled integrations. Already reflected in `condition_status` from step 2; include config for detail panel display.

**4.** Gen HTML

Self-contained HTML via vis.js Network from CDN (`https://unpkg.com/vis-network/standalone/umd/vis-network.min.js`).

**Graph structure:**

**Nodes** — one per unique tool name across all hooks (trigger or target):

| Role | Shape | Background | Text |
|------|-------|-----------|------|
| Trigger only | `box` | `#3498db` (blue) | white |
| Target only | `ellipse` | `#27ae60` (green) | white |
| Both | `box` | `#8e44ad` (purple) | white |

- Label: tool name w/ `mcp__` prefix stripped
- Size: proportional to degree (hooks where tool appears)

**Edges** — one per hook, directed trigger → target:

| `condition_status` | Color | Meaning |
|-------------------|------------|---------|
| `always` | `#aaaaaa` (gray) | No condition — always fires |
| `active` | `#2ecc71` (green) | Condition currently true |
| `inactive` | `#e74c3c` (red) | Condition currently false |
| `runtime` | `#f39c12` (amber) | Runtime-injected terms (`project.*`/`todo.*`), can't evaluate statically |

- Label: hook `id` (hover; inline if <15 edges)
- Style: `blocking: true` → solid; `blocking: false` → dashed
- Arrow on target end
- Multiple hooks between same pair → separate parallel edges (`smooth.type: 'curvedCW'` w/ incrementing `roundness`)

**Verification hooks**: `verification: true` → `#9b59b6` (purple) edge color despite `condition_status`.

**Node border override** — colored border (3px) based on highest-severity `condition_status` among all hooks touching node. Priority: `inactive` (red `#e74c3c`) > `runtime` (amber `#f39c12`) > verification (purple `#9b59b6`) > `active` (green `#2ecc71`) > `always` (gray `#aaaaaa`). Role-based fill preserved.

**Detail panel:**
Click edge → sidebar: Hook ID, condition string, condition_status, blocking, verification, param_mapping (fmt JSON), server.

**Cycle detection:**
DFS on directed graph after building node/edge data. Cycle found → fixed yellow banner: `⚠ Cycle detected in hook graph` (no exact path needed).

**Legend:**
Bottom-right box: node shapes/colors (trigger, target, dual-role); edge colors (always, active, inactive, runtime, verification); edge styles (solid=blocking, dashed=non-blocking).

**Footer:**
`Generated: <ISO datetime>`

**Defaults:**
Pan/zoom/drag enabled (vis.js defaults). Title: "Hook Network -- claude-project-manager"

## HTML Template

Exact structure below. All CSS/JS inline or CDN — no external file deps.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hook Network — claude-project-manager</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }

    /* Cycle warning banner — hidden by default, shown by JS if cycle detected */
    #cycle-banner { display: none; background: #f39c12; color: #000; text-align: center; padding: 8px; font-weight: 600; }

    /* Main layout */
    #container { display: flex; flex: 1; overflow: hidden; }
    #graph { flex: 1; }

    /* Detail sidebar — hidden by default, shown on edge click */
    #sidebar { width: 360px; background: #16213e; border-left: 1px solid #333; padding: 20px; overflow-y: auto; display: none; flex-direction: column; gap: 12px; }
    #sidebar.open { display: flex; }
    #sidebar h2 { font-size: 16px; color: #fff; border-bottom: 1px solid #444; padding-bottom: 8px; }
    #sidebar .field { margin-bottom: 8px; }
    #sidebar .field-label { font-size: 11px; text-transform: uppercase; color: #888; letter-spacing: 0.5px; }
    #sidebar .field-value { font-size: 14px; margin-top: 2px; }
    #sidebar .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    #sidebar .badge-active { background: #2ecc71; color: #000; }
    #sidebar .badge-inactive { background: #e74c3c; color: #fff; }
    #sidebar .badge-runtime { background: #f39c12; color: #000; }
    #sidebar .badge-always { background: #aaaaaa; color: #000; }
    #sidebar .badge-verification { background: #9b59b6; color: #fff; }
    #sidebar pre { background: #0d1b2a; padding: 10px; border-radius: 4px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; }
    #sidebar .close-btn { align-self: flex-end; cursor: pointer; background: none; border: 1px solid #555; color: #ccc; padding: 4px 10px; border-radius: 4px; }

    /* Empty state */
    #empty-state { display: none; flex: 1; justify-content: center; align-items: center; font-size: 18px; color: #888; }

    /* Legend */
    #legend { position: fixed; bottom: 16px; right: 16px; background: rgba(22,33,62,0.95); border: 1px solid #444; border-radius: 8px; padding: 14px 18px; font-size: 12px; line-height: 1.8; z-index: 10; }
    #legend h3 { font-size: 13px; margin-bottom: 6px; color: #fff; }
    .legend-item { display: flex; align-items: center; gap: 8px; }
    .legend-swatch { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
    .legend-line { width: 24px; height: 0; border-top: 3px solid; display: inline-block; }
    .legend-line.dashed { border-top-style: dashed; }

    /* Footer */
    #footer { text-align: center; font-size: 11px; color: #555; padding: 6px; background: #111; }
  </style>
</head>
<body>
  <div id="cycle-banner">⚠ Cycle detected in hook graph</div>
  <div id="container">
    <div id="graph"></div>
    <div id="empty-state">No hooks registered</div>
    <div id="sidebar">
      <button class="close-btn" onclick="closeSidebar()">✕</button>
      <h2 id="sidebar-title">Hook Detail</h2>
      <div id="sidebar-content"></div>
    </div>
  </div>
  <div id="legend">
    <h3>Legend</h3>
    <b>Nodes</b>
    <div class="legend-item"><span class="legend-swatch" style="background:#3498db"></span> Trigger</div>
    <div class="legend-item"><span class="legend-swatch" style="background:#27ae60; border-radius:50%"></span> Target</div>
    <div class="legend-item"><span class="legend-swatch" style="background:#8e44ad"></span> Both</div>
    <b style="margin-top:6px;display:block;">Edges</b>
    <div class="legend-item"><span class="legend-line" style="border-color:#aaaaaa"></span> always</div>
    <div class="legend-item"><span class="legend-line" style="border-color:#2ecc71"></span> active</div>
    <div class="legend-item"><span class="legend-line" style="border-color:#e74c3c"></span> inactive</div>
    <div class="legend-item"><span class="legend-line" style="border-color:#f39c12"></span> runtime</div>
    <div class="legend-item"><span class="legend-line" style="border-color:#9b59b6"></span> verification</div>
    <b style="margin-top:6px;display:block;">Style</b>
    <div class="legend-item"><span class="legend-line" style="border-color:#ccc"></span> blocking</div>
    <div class="legend-item"><span class="legend-line dashed" style="border-color:#ccc"></span> non-blocking</div>
  </div>
  <div id="footer">Generated: {{ISO_DATETIME}}</div>

  <script>
    // ── Embedded data blob (injected by the skill at generation time) ──
    // hooksData: array of hook objects from router_list_tool
    const hooksData = {{HOOKS_JSON}};

    // ── Empty-state check ──
    if (hooksData.length === 0) {
      document.getElementById('empty-state').style.display = 'flex';
      document.getElementById('graph').style.display = 'none';
      document.getElementById('legend').style.display = 'none';
    } else {
      buildGraph();
    }

    function buildGraph() {
      // ── Build node and edge sets ──
      const toolRoles = {};  // toolName → { trigger: bool, target: bool, statuses: [] }
      const edges = [];
      const pairCount = {};  // "from→to" → count (for parallel edge curvature)

      const STATUS_COLORS = {
        always: '#aaaaaa', active: '#2ecc71', inactive: '#e74c3c', runtime: '#f39c12'
      };
      const STATUS_PRIORITY = { inactive: 4, runtime: 3, active: 1, always: 0 };
      const VERIFICATION_COLOR = '#9b59b6';
      const VERIFICATION_PRIORITY = 2;

      hooksData.forEach((hook, i) => {
        const trigger = hook.trigger_tool;
        const target = hook.target_tool;

        // Track roles
        if (!toolRoles[trigger]) toolRoles[trigger] = { trigger: false, target: false, statuses: [] };
        if (!toolRoles[target]) toolRoles[target] = { trigger: false, target: false, statuses: [] };
        toolRoles[trigger].trigger = true;
        toolRoles[target].target = true;

        const effectiveStatus = hook.verification ? 'verification' : hook.condition_status;
        toolRoles[trigger].statuses.push(effectiveStatus);
        toolRoles[target].statuses.push(effectiveStatus);

        // Parallel edge curvature
        const pairKey = trigger + '→' + target;
        pairCount[pairKey] = (pairCount[pairKey] || 0);
        const roundness = pairCount[pairKey] * 0.15;
        pairCount[pairKey]++;

        const edgeColor = hook.verification ? VERIFICATION_COLOR : (STATUS_COLORS[hook.condition_status] || '#aaaaaa');
        const isSparse = hooksData.length < 15;

        edges.push({
          id: 'edge-' + i,
          from: trigger,
          to: target,
          label: isSparse ? hook.id : undefined,
          title: hook.id,
          arrows: 'to',
          color: { color: edgeColor, highlight: edgeColor, hover: edgeColor },
          dashes: !hook.blocking,
          smooth: { type: 'curvedCW', roundness: roundness },
          // Stash hook data for sidebar
          hookData: hook
        });
      });

      // ── Build node array ──
      const nodes = Object.entries(toolRoles).map(([tool, role]) => {
        const label = tool.replace(/^mcp__/, '');
        const isTrigger = role.trigger;
        const isTarget = role.target;
        const isBoth = isTrigger && isTarget;

        let shape, bgColor;
        if (isBoth) { shape = 'box'; bgColor = '#8e44ad'; }
        else if (isTrigger) { shape = 'box'; bgColor = '#3498db'; }
        else { shape = 'ellipse'; bgColor = '#27ae60'; }

        // Degree-based sizing
        const degree = role.statuses.length;
        const size = 20 + degree * 5;

        // Border color from highest-severity status
        let maxPriority = -1;
        let borderColor = bgColor;
        role.statuses.forEach(s => {
          const p = s === 'verification' ? VERIFICATION_PRIORITY : (STATUS_PRIORITY[s] || 0);
          if (p > maxPriority) {
            maxPriority = p;
            borderColor = s === 'verification' ? VERIFICATION_COLOR : (STATUS_COLORS[s] || bgColor);
          }
        });

        return {
          id: tool, label, shape, size,
          color: { background: bgColor, border: borderColor, highlight: { background: bgColor, border: '#fff' } },
          borderWidth: 3,
          font: { color: '#fff', size: 13 }
        };
      });

      // ── Cycle detection (DFS) ──
      const adj = {};
      hooksData.forEach(h => {
        if (!adj[h.trigger_tool]) adj[h.trigger_tool] = [];
        adj[h.trigger_tool].push(h.target_tool);
      });
      let hasCycle = false;
      const visited = new Set(), recStack = new Set();
      function dfs(node) {
        visited.add(node); recStack.add(node);
        for (const nb of (adj[node] || [])) {
          if (recStack.has(nb)) { hasCycle = true; return; }
          if (!visited.has(nb)) dfs(nb);
          if (hasCycle) return;
        }
        recStack.delete(node);
      }
      Object.keys(adj).forEach(n => { if (!visited.has(n)) dfs(n); });
      if (hasCycle) document.getElementById('cycle-banner').style.display = 'block';

      // ── Initialize vis.js Network ──
      const container = document.getElementById('graph');
      const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
      const options = {
        physics: {
          solver: 'forceAtlas2Based',
          forceAtlas2Based: { gravitationalConstant: -80, centralGravity: 0.01, springLength: 150, springConstant: 0.04 },
          stabilization: { iterations: 200 }
        },
        interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true, dragNodes: true },
        edges: { font: { size: 10, color: '#999', strokeWidth: 0 }, width: 2 },
        nodes: { font: { multi: false } }
      };
      const network = new vis.Network(container, data, options);

      // ── Edge click → sidebar ──
      network.on('click', function(params) {
        if (params.edges.length === 1 && params.nodes.length === 0) {
          const edgeId = params.edges[0];
          const edge = data.edges.get(edgeId);
          if (edge && edge.hookData) showSidebar(edge.hookData);
        } else {
          closeSidebar();
        }
      });
    }

    // ── Sidebar logic ──
    function showSidebar(hook) {
      const sb = document.getElementById('sidebar');
      const content = document.getElementById('sidebar-content');
      const badgeClass = hook.verification ? 'badge-verification'
        : 'badge-' + (hook.condition_status || 'always');
      const statusLabel = hook.verification ? 'verification' : (hook.condition_status || 'always');

      const triggerLabel = hook.trigger_tool.replace(/^mcp__/, '');
      const targetLabel = hook.target_tool.replace(/^mcp__/, '');

      content.innerHTML = `
        <div class="field"><div class="field-label">Hook ID</div><div class="field-value">${hook.id}</div></div>
        <div class="field"><div class="field-label">Flow</div><div class="field-value">${triggerLabel} → ${targetLabel}</div></div>
        <div class="field"><div class="field-label">Server</div><div class="field-value">${hook.server || '—'}</div></div>
        <div class="field"><div class="field-label">Condition</div><div class="field-value">${hook.condition || 'none (always)'}</div></div>
        <div class="field"><div class="field-label">Condition Status</div><div class="field-value"><span class="badge ${badgeClass}">${statusLabel}</span></div></div>
        <div class="field"><div class="field-label">Blocking</div><div class="field-value">${hook.blocking ? 'Yes' : 'No'}</div></div>
        <div class="field"><div class="field-label">Verification</div><div class="field-value">${hook.verification ? 'Yes' : 'No'}</div></div>
        <div class="field"><div class="field-label">Param Mapping</div><pre>${JSON.stringify(hook.param_mapping || {}, null, 2)}</pre></div>
        ${hook.feedback_tool ? '<div class="field"><div class="field-label">Feedback Tool</div><div class="field-value">' + hook.feedback_tool + '</div></div>' : ''}
        <div class="field"><div class="field-label">Source</div><div class="field-value">${triggerLabel}</div></div>
      `;
      document.getElementById('sidebar-title').textContent = 'Hook: ' + hook.id;
      sb.classList.add('open');
    }

    function closeSidebar() {
      document.getElementById('sidebar').classList.remove('open');
    }
  </script>
</body>
</html>
```

### Data fmt

`{{HOOKS_JSON}}` replaced w/ JSON-serialized array from `router_list_tool`. Element shape:

```json
{
  "id": "hook-id-string",
  "trigger_tool": "mcp__plugin_proj_proj__todo_complete",
  "target_tool": "mcp__plugin_todoist_todoist__todoist_complete_task_hook",
  "server": "todoist",
  "blocking": false,
  "verification": false,
  "condition": "sync.todoist.enabled and todo.todoist_task_id",
  "condition_status": "runtime",
  "param_mapping": { "source.todo_id": "todo_id" },
  "feedback_tool": null
}
```

`{{ISO_DATETIME}}` replaced w/ cur ISO 8601 datetime (e.g. `2026-04-02T14:30:00Z`).

### Gen notes

- Embed hooks array directly as `const hooksData = [...]` — no `JSON.parse()` on string
- `hookData` property on each vis.js edge stores orig hook for sidebar
- Parallel edges between same pair → incrementing `roundness` on `smooth.type: 'curvedCW'`
- Sidebar param_mapping displayed as fmt JSON (not YAML — JSON native to browser)
- Cycle detection DFS runs on directed adjacency list before network init

**5.** Write file

Write gen HTML to output path via Bash.

**6.** Print result

`Done: Hook network visualization written to <path>`
Open: `open <path>` (macOS) or `xdg-open <path>` (Linux)

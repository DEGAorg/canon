# Automation Panel Spec

Rebuild the right-pane "status" section as a focused **Automation** panel:
one consolidated widget with a live DAG diagram of the current strategy
flow and a streaming logs tab, swapping default focus as the run progresses.

## Background

Today the automation surface in canon-tui is split and confused:

- `PANEL_ROUTES["status"]` (`project_state_pane.py:148`) aliases to the Board
  tab — unrelated to automation.
- Two near-duplicate widgets exist: `builder_view.py` and `automation_view.py`.
  The only difference is status-color palettes and the presence of `PipelineView`
  in `BuilderView`.
- `pipeline_view.py` is a fixed linear strip of bordered boxes. It cannot
  express branching, fan-in, parallelism, or gate nodes.
- Diagram and logs are crammed into one scrollable view; neither gets enough room.

Source of truth for the flow is `.canon/flow.json`, written by dega-core
(`canon/templates/runner.ts` → `updateFlow(active, completed)`), seeded
verbatim from `canon/templates/strategies/<name>/flow.json` by
`canon/commands/canon-start.md`. The runner mutates only `active` and
`completed`; `steps` and `labels` are owned by the strategy template and
never reshaped at runtime.

## Goals

- A single **Automation** right-pane section replacing the current State/Builder
  section (`SECTION_STATE`).
- Layout-agnostic DAG renderer: linear flows render as a line; branching flows
  render as a real graph — same code path.
- Tabs that match user intent across the lifecycle: diagram while planning,
  logs while running. Switch automatically once; never fight the user after.
- Additive schema: strategy templates opt into branching by declaring `nodes`
  and `edges` in their own `flow.json`. Runner stays untouched for v1.

## Non-goals (v1)

- Per-node timestamps or durations beyond what is derivable session-locally
  from tracking when `active` changes. (Core extension tracked in
  `docs/core-extension-flow-timestamps.md`.)
- Any runner change in dega-core.
- An Artifacts tab.
- Mouse-driven graph editing.
- Failure/skip/retried node states beyond the three derivable states
  (`done`, `running`, `pending`).

---

## Flow.json schema extension

Strategy templates may add two new fields to their `flow.json`. Both are
optional. Existing strategies keep working without changes.

```jsonc
{
  // Existing — never mutated by runner.ts.
  "steps":     ["init", "scaffold", "strategy", "develop"],
  "labels":    [["init", "Init"], ["scaffold", "Scaffold"], ...],

  // Existing — runner mutates only these two.
  "active":    "strategy",
  "completed": ["init", "scaffold"],

  // NEW — authored once in strategies/<name>/flow.json.
  // Runner never touches these fields.
  "nodes": [
    {"id": "init",     "label": "Init",     "type": "build"},
    {"id": "scaffold", "label": "Scaffold", "type": "build"},
    {"id": "research", "label": "Research", "type": "build"},
    {"id": "strategy", "label": "Strategy", "type": "gate"},
    {"id": "develop",  "label": "Develop",  "type": "build"}
  ],
  "edges": [
    {"from": "init",     "to": "scaffold"},
    {"from": "init",     "to": "research"},
    {"from": "scaffold", "to": "strategy"},
    {"from": "research", "to": "strategy"},
    {"from": "strategy", "to": "develop"}
  ]
}
```

### Node fields

| Field          | Required | Description |
|----------------|----------|-------------|
| `nodes[].id`   | yes      | Unique. Should match an entry in `steps`, but may introduce derived sub-nodes for complex branches. |
| `nodes[].label`| yes      | Display string. Falls back to `id` if absent. |
| `nodes[].type` | no       | `"build"` (default) · `"gate"` · `"deploy"` · `"review"` |

### Edge fields

| Field         | Required | Description |
|---------------|----------|-------------|
| `edges[].from`| yes      | Source node `id`. |
| `edges[].to`  | yes      | Target node `id`. |

### Fallback (no `nodes`/`edges`)

Renderer synthesizes a linear DAG from `steps`: one node per step, edges
between consecutive pairs. Old strategies render correctly inside the new
panel without any file changes.

### Status derivation (TUI-side, no runner change)

| Condition in `flow.json`   | Status    | Card border |
|----------------------------|-----------|-------------|
| `id ∈ completed`           | `done`    | `$success`  |
| `id == active`             | `running` | `$accent`   |
| otherwise                  | `pending` | `$surface-lighten-2` (dim) |

Failure and skip states are reserved for v2 (runner enrichment).

---

## `FlowState` dataclass extension

File: `src/toad/widgets/canon_state.py`

```python
@dataclass(frozen=True)
class FlowNode:
    id: str
    label: str
    type: str = "build"          # build | gate | deploy | review

@dataclass(frozen=True)
class FlowEdge:
    from_id: str
    to_id: str

@dataclass(frozen=True)
class FlowState:
    steps:     tuple[str, ...]                   = ()
    labels:    tuple[tuple[str, str], ...]       = ()
    active:    str                               = ""
    completed: tuple[str, ...]                   = ()
    # NEW — optional; absent means linear fallback
    nodes:     tuple[FlowNode, ...]              = ()
    edges:     tuple[FlowEdge, ...]              = ()

    def node_status(self, node_id: str) -> str:
        """Derive status from active/completed — no runner change needed."""
        if node_id in self.completed:
            return "done"
        if node_id == self.active:
            return "running"
        return "pending"

    def effective_nodes(self) -> tuple[FlowNode, ...]:
        """Return declared nodes or synthesize linear fallback from steps."""
        if self.nodes:
            return self.nodes
        return tuple(
            FlowNode(id=s, label=self._label_for(s))
            for s in self.steps
        )

    def effective_edges(self) -> tuple[FlowEdge, ...]:
        """Return declared edges or synthesize linear chain from steps."""
        if self.edges:
            return self.edges
        return tuple(
            FlowEdge(from_id=self.steps[i], to_id=self.steps[i + 1])
            for i in range(len(self.steps) - 1)
        )

    def _label_for(self, step: str) -> str:
        for k, v in self.labels:
            if k == step:
                return v
        return step.replace("_", " ").title()
```

Update `_parse_flow()` to populate `nodes` and `edges` when present:

```python
def _parse_flow(data: dict) -> FlowState:
    nodes = tuple(
        FlowNode(
            id=n["id"],
            label=n.get("label", n["id"]),
            type=n.get("type", "build"),
        )
        for n in data.get("nodes", [])
    )
    edges = tuple(
        FlowEdge(from_id=e["from"], to_id=e["to"])
        for e in data.get("edges", [])
    )
    labels_raw = data.get("labels", {})
    labels = tuple((str(k), str(v)) for k, v in labels_raw.items())
    return FlowState(
        steps=tuple(data.get("steps", [])),
        labels=labels,
        active=data.get("active", ""),
        completed=tuple(data.get("completed", [])),
        nodes=nodes,
        edges=edges,
    )
```

---

## Panel structure

```
┌─ Automation ───────────────────────────────────────────────┐
│ ▶ strategy · step 3 of 5 · 4m elapsed           [SECTION]  │  ← header strip (1 line)
├────────────────────────────────────────────────────────────┤
│ ▌Diagram│ Logs                                             │  ← TabbedContent
├────────────────────────────────────────────────────────────┤
│                                                            │
│   ◉ init ─┬─► ◉ scaffold ─┐                               │
│           │               ├─► ◐ strategy ─► ○ develop     │
│           └─► ◉ research ─┘                               │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Header strip

`Static` widget, `height: 1`, always visible above `TabbedContent`. Updates
on every state poll (~5s). Content:

```
▶ strategy · step 3 of 5 · 4m elapsed
```

- **Phase icon + name:** `▶` for running phases (`is_run_phase`), `◈` for build
  phases. Phase name from `state.phase`.
- **Position:** `step N of M` where `N = len(flow.completed) + 1` (clamped to M),
  `M = len(flow.steps)`.
- **Elapsed:** see [Elapsed timing](#elapsed-timing) below.
- **Empty state:** `[dim]No automation running[/]` when `state.phase == ""`.

Phase icon mapping:

| Condition           | Icon |
|---------------------|------|
| `state.is_run_phase`| `▶`  |
| `state.is_build_phase`| `◈` |
| no phase            | `○`  |

### Elapsed timing

`state.json` and `flow.json` contain no start timestamps in v1. The panel
tracks elapsed time session-locally:

```python
class AutomationPanel(Widget):
    _active_since: datetime | None = None
    _last_active: str = ""          # previous flow.active value

    def watch_state(self, state: CanonState) -> None:
        flow = state.flow
        if flow and flow.active != self._last_active:
            self._active_since = datetime.now(timezone.utc)
            self._last_active = flow.active
        self._refresh_header(state)
```

`_format_elapsed(dt)` returns `"4m elapsed"` / `"12s elapsed"` / `"1h 4m elapsed"`.
Resets to zero on TUI restart — acceptable for v1. Persistent timestamps
require a core extension (see `docs/core-extension-flow-timestamps.md`).

---

## Textual widget hierarchy

```
AutomationPanel (Widget)
├── Static #automation-header        height: 1
└── TabbedContent #automation-tabs
    ├── TabPane "Diagram" (id: tab-diagram)
    │   └── HorizontalScroll #dag-scroll
    │       └── AutomationDag #automation-dag  (can_focus=True)
    │           └── Horizontal #dag-canvas
    │               ├── Vertical .dag-layer      (layer 0)
    │               │   └── DagNode .dag-node    (can_focus=True)
    │               ├── Static .dag-arrow " → "
    │               ├── Vertical .dag-layer      (layer 1, multi-node)
    │               │   ├── DagNode .dag-node
    │               │   └── DagNode .dag-node
    │               ├── Static .dag-arrow " → "
    │               └── Vertical .dag-layer      (layer 2)
    │                   └── DagNode .dag-node
    └── TabPane "Logs" (id: tab-logs)
        └── VerticalScroll #automation-logs
            └── Static .log-line  (×N, latest first)
```

### `AutomationPanel`

```python
class AutomationPanel(Widget):
    """Top-level automation section: header strip + diagram/logs tabs."""

    state: reactive[CanonState] = reactive(CanonState, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("", id="automation-header")
        with TabbedContent(id="automation-tabs"):
            with TabPane("Diagram", id="tab-diagram"):
                with HorizontalScroll(id="dag-scroll"):
                    yield AutomationDag(id="automation-dag")
            with TabPane("Logs", id="tab-logs"):
                with VerticalScroll(id="automation-logs"):
                    yield Static(
                        "[dim]Waiting for logs…[/]",
                        id="automation-logs-empty",
                    )
```

State arrives via `CanonStateWidget.CanonStateUpdated` message. Panel sets
`self.state = event.state` in the message handler; `watch_state()` drives
all child updates.

```python
    def on_canon_state_widget_canon_state_updated(
        self, event: CanonStateWidget.CanonStateUpdated
    ) -> None:
        self.state = event.state

    def watch_state(self, state: CanonState) -> None:
        self._maybe_auto_switch(state)
        self._refresh_header(state)
        self.query_one(AutomationDag).update_state(state)
        self._refresh_logs(state)
```

### Auto-switch behavior

```python
    _user_picked_tab: bool = False

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        self._user_picked_tab = True

    def _maybe_auto_switch(self, state: CanonState) -> None:
        if self._user_picked_tab:
            return
        tabs = self.query_one("#automation-tabs", TabbedContent)
        if state.is_run_phase and tabs.active != "tab-logs":
            tabs.active = "tab-logs"
            self._user_picked_tab = True   # switch once only
        elif state.is_build_phase and tabs.active != "tab-diagram":
            tabs.active = "tab-diagram"
```

Note: setting `tabs.active` in `watch_state()` fires
`TabbedContent.TabActivated`, which would set `_user_picked_tab = True`.
Guard by checking that `_user_picked_tab` is set **after** the programmatic
switch, not before. Use `_auto_switching: bool` flag to distinguish:

```python
    _auto_switching: bool = False

    def _maybe_auto_switch(self, state: CanonState) -> None:
        if self._user_picked_tab:
            return
        tabs = self.query_one("#automation-tabs", TabbedContent)
        target = "tab-logs" if state.is_run_phase else "tab-diagram"
        if tabs.active != target:
            self._auto_switching = True
            tabs.active = target
            self._auto_switching = False
            if state.is_run_phase:
                self._user_picked_tab = True  # only lock after run transition

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        if not self._auto_switching:
            self._user_picked_tab = True
```

### Logs refresh

Extracted directly from `automation_view.py` + `builder_view.py`. Logs scroll
is rebuilt on every state update using the remove-children + mount-all pattern
(same as `PipelineView.render_flow`). Cap at 50 lines, newest first.

```python
    async def _refresh_logs(self, state: CanonState) -> None:
        scroll = self.query_one("#automation-logs", VerticalScroll)
        await scroll.remove_children()

        if not state.logs:
            await scroll.mount(
                Static("[dim]Waiting for logs…[/]", id="automation-logs-empty")
            )
            return

        now = datetime.now(timezone.utc)
        recent = state.logs[-MAX_LOG_LINES:]
        widgets = [Static(_render_log(e, now=now), classes="log-line") for e in reversed(recent)]
        await scroll.mount_all(widgets)
        scroll.scroll_home(animate=False)
```

`_render_log` and `_format_friendly_timestamp` are moved from `builder_view.py`
into `automation_panel.py`. The `METRIC_LABEL_ALIASES` dict moves too.

---

## `AutomationDag` widget

File: `src/toad/widgets/automation_dag.py`

```python
class AutomationDag(Widget, can_focus=True):
    """Layout-agnostic DAG renderer. Inputs: FlowState. No teardown on updates."""
```

### DAG layout algorithm

1. **Build adjacency:** from `flow.effective_edges()`.
2. **Topological layer assignment:** longest-path-from-root. BFS from all roots
   (nodes with no incoming edges). Each node's layer = max(parent layers) + 1.
3. **Within-layer ordering:** preserve declaration order from `flow.effective_nodes()`.
4. **Render columns:** one `Vertical .dag-layer` per layer. Between adjacent
   layers, one `Static .dag-arrow`. All columns inside a `Horizontal #dag-canvas`.
5. **Horizontal scroll:** `HorizontalScroll` wraps the canvas in the parent.
   Card min-width is 14 cols; arrow is 3 cols. Scroll kicks in automatically
   when total width exceeds pane width.

### Update strategy

On first mount or when node topology changes (step set changes — new
automation started), rebuild the full widget tree:

```python
    async def _rebuild(self, flow: FlowState) -> None:
        canvas = self.query_one("#dag-canvas", Horizontal)
        await canvas.remove_children()
        layers = _compute_layers(flow)  # list[list[str]] — ordered by layer index
        widgets: list[Widget] = []
        for i, layer_ids in enumerate(layers):
            if i > 0:
                widgets.append(Static(" → ", classes="dag-arrow"))
            layer = Vertical(classes="dag-layer")
            for node_id in layer_ids:
                node = _find_node(flow, node_id)
                widgets.append(
                    DagNode(node, flow.node_status(node_id), classes="dag-node")
                )
            # Mount nodes into layer after collecting; then add layer
            # (actual mounting order: layer widget holds nodes)
        await canvas.mount_all(widgets)
```

On subsequent state updates where topology is unchanged, only mutate CSS
classes on existing `DagNode` widgets — no teardown:

```python
    def update_state(self, state: CanonState) -> None:
        flow = state.flow
        if flow is None:
            self._show_placeholder()
            return

        if self._topology_changed(flow):
            self.call_after_refresh(self._rebuild, flow)
            self._current_steps = flow.steps
            return

        # Fast path: update status without rebuilding
        for node_widget in self.query(DagNode):
            new_status = flow.node_status(node_widget.node_id)
            node_widget.set_status(new_status)
```

### `DagNode` widget

```python
class DagNode(Widget, can_focus=True):
    """A single node card in the DAG. Border color = status."""

    NODE_ICONS: dict[str, str] = {
        "build":  "▶",
        "gate":   "◆",
        "deploy": "⬆",
        "review": "◎",
    }

    DEFAULT_CSS = """
    DagNode {
        width: auto;
        min-width: 14;
        height: 5;
        border: round $surface-lighten-2;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    DagNode.status-done    { border: round $success; }
    DagNode.status-running { border: round $accent; text-style: bold; }
    DagNode.status-pending { border: round $surface-lighten-2; color: $text-muted; }
    DagNode:focus          { border: round $warning; }
    DagNode .node-title    { height: 1; content-align: left middle; }
    DagNode .node-status   { height: 1; color: $text-muted; }
    """

    def __init__(self, node: FlowNode, status: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.node_id = node.id
        self._node = node
        self._status = status

    def compose(self) -> ComposeResult:
        icon = self.NODE_ICONS.get(self._node.type, "▶")
        yield Static(f"{icon} {self._node.label}", classes="node-title")
        yield Static(self._status_line(), classes="node-status")

    def _status_line(self) -> str:
        return {
            "done":    "✓ done",
            "running": "◐ running",
            "pending": "○ pending",
        }.get(self._status, self._status)

    def set_status(self, status: str) -> None:
        self.remove_class("status-done", "status-running", "status-pending")
        self.add_class(f"status-{status}")
        self._status = status
        self.query_one(".node-status", Static).update(self._status_line())
```

### Keyboard navigation

Defined on `AutomationDag`:

```python
    BINDINGS = [
        Binding("j", "next_sibling",  "Next node",     show=False),
        Binding("k", "prev_sibling",  "Prev node",     show=False),
        Binding("l", "next_layer",    "Next layer",    show=False),
        Binding("h", "prev_layer",    "Prev layer",    show=False),
        Binding("enter", "focus_logs","Filter logs",   show=True),
    ]
```

`action_focus_logs` posts `AutomationDag.NodeSelected(node_id)` which
`AutomationPanel` catches to switch to the Logs tab and apply a node filter.
The Logs tab clears the filter with `Escape`.

---

## CSS — `AutomationPanel.DEFAULT_CSS`

```css
AutomationPanel {
    height: 1fr;
}
AutomationPanel #automation-header {
    height: 1;
    padding: 0 1;
    background: $surface;
    color: $text-muted;
}
AutomationPanel #automation-tabs {
    height: 1fr;
}
AutomationPanel #dag-scroll {
    height: 1fr;
}
AutomationPanel #dag-canvas {
    height: auto;
    align: left top;
}
AutomationPanel .dag-layer {
    width: auto;
    height: auto;
    align: left top;
}
AutomationPanel .dag-arrow {
    width: 3;
    height: 5;
    content-align: center middle;
    color: $text-muted;
}
AutomationPanel #automation-logs {
    height: 1fr;
}
AutomationPanel .log-line {
    padding: 0 1;
    height: auto;
}
AutomationPanel .empty-state {
    color: $text-muted;
    text-style: italic;
    padding: 2 1;
    text-align: center;
}
```

---

## Naming and cleanup

Per the "replace, don't deprecate" rule — no aliases, no shims.

### `project_state_pane.py`

- Rename `SECTION_STATE` label from `"State"` to `"Automation"` in
  `_SECTIONS` (line ~121).
- Replace the existing `TabPane("State", id="tab-builder")` / `BuilderView`
  mount at line ~459-466 with `TabPane("Automation", id="tab-automation")` /
  `AutomationPanel`.
- In `PANEL_ROUTES` (line ~133-165):
  - Remove: `"status": (SECTION_PLANNING, "tab-tasks")` (line 148)
  - Remove: `"state": (SECTION_STATE, "tab-builder")` (line 149)
  - Remove: `"builder": (SECTION_STATE, "tab-builder")` (line 150)
  - Add: `"automation": (SECTION_STATE, "tab-automation")`

### `conversation.py` — `_PANEL_KEYWORDS`

Replace line 167:
```python
(("build state", "builder", "run state", "the state"), "state"),
```
With:
```python
(("automation", "the automation", "run state", "build state"), "automation"),
```

### Files to delete

| File | Replaced by |
|------|-------------|
| `src/toad/widgets/builder_view.py` | `automation_panel.py` (log render + metrics extracted) |
| `src/toad/widgets/automation_view.py` | `automation_panel.py` |
| `src/toad/widgets/pipeline_view.py` | `automation_dag.py` (linear fallback handles this) |

Confirm no other files import these before deleting:

```bash
rg "builder_view|automation_view|pipeline_view" src/ --type py
```

---

## Files touched

### canon-tui

| File | Change |
|------|--------|
| `src/toad/widgets/automation_panel.py` | **NEW** — `AutomationPanel`, log render, header logic |
| `src/toad/widgets/automation_dag.py` | **NEW** — `AutomationDag`, `DagNode`, layout algorithm |
| `src/toad/widgets/canon_state.py` | Extend `FlowState` with `FlowNode`, `FlowEdge`, `effective_nodes()`, `effective_edges()`, `node_status()` |
| `src/toad/widgets/project_state_pane.py` | Replace `tab-builder`/`BuilderView` with `tab-automation`/`AutomationPanel`; update `PANEL_ROUTES` |
| `src/toad/widgets/conversation.py` | Update `_PANEL_KEYWORDS` line 167 |
| `src/toad/widgets/builder_view.py` | **DELETE** |
| `src/toad/widgets/automation_view.py` | **DELETE** |
| `src/toad/widgets/pipeline_view.py` | **DELETE** (after verify) |
| `tools/verify-tui.py` | Add `--widget automation-dag` and `--widget automation-panel` harnesses |

### claude-code-config

| File | Change |
|------|--------|
| `canon/templates/strategies/<name>/flow.json` | Add `nodes` + `edges` for strategies that want branching. Linear strategies: no change. |
| `canon/templates/runner.ts` | **None.** |
| `canon/commands/canon-start.md` | **None.** |

---

## Verification

```bash
# Confirm old files are no longer imported anywhere
rg "builder_view|automation_view|pipeline_view" src/ --type py

# Headless widget renders
uv run python tools/verify-tui.py --widget automation-dag     # 3 fixtures
uv run python tools/verify-tui.py --widget automation-panel   # auto-switch assertion

# Lint + types
ruff check src/toad/widgets/automation_panel.py src/toad/widgets/automation_dag.py
ty check src/toad/widgets/automation_panel.py src/toad/widgets/automation_dag.py

# Full test suite
pytest -q tests/
```

### `tools/verify-tui.py` fixtures for `--widget automation-dag`

1. **Linear** — `steps`-only `flow.json`, 4 nodes, active = node 2. Assert 4 layers,
   node 2 has `status-running` class.
2. **Fan-out / fan-in** — explicit `nodes`/`edges` with 2 parallel branches converging.
   Assert middle layer has 2 nodes; edge count is 4; gate node is pending.
3. **Mixed** — sequential + one branch fork mid-flow. Assert correct layer count and
   that all nodes are reachable by keyboard navigation.

### `tools/verify-tui.py` fixture for `--widget automation-panel`

- Mount with `phase="scaffold"` → assert active tab is `tab-diagram`.
- Simulate state update with `phase="run"` → assert tab switches to `tab-logs`
  **exactly once**, and that a second state update does not switch back.

---

## v2 follow-ups

- **Runner enrichment** — runner writes `active_since` ISO timestamp to
  `flow.json` so elapsed time persists across TUI restarts. Spec in
  `docs/core-extension-flow-timestamps.md`.
- **Failure/skip states** — runner writes explicit `failed` / `skipped` sets.
  Adds red and grey borders to `DagNode.set_status()`.
- **Edge labels** — `annotation` field on edges for conditionals. Renderer
  renders label inline between arrow glyphs.
- **Mini-map** — thin overview strip for DAGs wider than pane width.
- **Artifacts tab** — third tab listing per-step output files (requires core
  to enumerate artifacts in `state.json`).

"""AutomationDag — layout-agnostic DAG renderer for automation flow."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from toad.widgets.canon_state import FlowEdge, FlowNode, FlowState

log = logging.getLogger(__name__)

_NODE_ICONS: dict[str, str] = {
    "build":  "▶",
    "gate":   "◆",
    "deploy": "⬆",
    "review": "◎",
    "setup":  "⚙",
    "config": "◎",
    "runner": "◐",
    "wallet": "◈",
}

_STATUS_LINES: dict[str, str] = {
    "done":    "✓ done",
    "running": "◐ running",
    "pending": "○ pending",
}


def _compute_layers(
    nodes: tuple[FlowNode, ...],
    edges: tuple[FlowEdge, ...],
) -> list[list[str]]:
    """Assign each node to a column via longest-path-from-root (BFS).

    Returns an ordered list of layers; each layer is a list of node IDs
    in declaration order.
    """
    if not nodes:
        return []

    children: dict[str, list[str]] = {n.id: [] for n in nodes}
    parents: dict[str, list[str]] = {n.id: [] for n in nodes}
    for e in edges:
        if e.from_id in children and e.to_id in parents:
            children[e.from_id].append(e.to_id)
            parents[e.to_id].append(e.from_id)

    # Longest path from any root (nodes with no incoming edges)
    layer: dict[str, int] = {}
    queue: list[str] = []
    for n in nodes:
        if not parents[n.id]:
            layer[n.id] = 0
            queue.append(n.id)

    # If every node has parents (cycle / disconnected), fall back to declaration order
    if not queue:
        return [[n.id for n in nodes]]

    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1
        for child in children[current]:
            new_layer = layer[current] + 1
            if child not in layer or layer[child] < new_layer:
                layer[child] = new_layer
                queue.append(child)

    # Nodes not reached (disconnected) get appended at the end
    for n in nodes:
        if n.id not in layer:
            layer[n.id] = max(layer.values(), default=0) + 1

    max_layer = max(layer.values())
    node_order = {n.id: i for i, n in enumerate(nodes)}
    result: list[list[str]] = [[] for _ in range(max_layer + 1)]
    for node_id, layer_idx in sorted(layer.items(), key=lambda x: node_order.get(x[0], 0)):
        result[layer_idx].append(node_id)

    return [layer_ids for layer_ids in result if layer_ids]


class DagNode(Widget, can_focus=True):
    """Single bordered card representing one node in the DAG."""

    DEFAULT_CSS = """
    DagNode {
        width: auto;
        min-width: 14;
        height: 5;
        border: round $surface-lighten-2;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    DagNode.status-done    { border: round $success; color: $success; }
    DagNode.status-running { border: round $accent; color: $accent; text-style: bold; }
    DagNode.status-pending { border: round $surface-lighten-2; color: $text-muted; }
    DagNode:focus          { border: double $warning; }
    DagNode .node-title    { height: 1; content-align: left middle; }
    DagNode .node-status   { height: 1; color: $text-muted; }
    """

    def __init__(self, node: FlowNode, status: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.node_id = node.id
        self._node = node
        self._status = status

    def compose(self) -> ComposeResult:
        icon = _NODE_ICONS.get(self._node.type, "▶")
        yield Static(f"{icon} {self._node.label}", classes="node-title")
        yield Static(
            _STATUS_LINES.get(self._status, self._status),
            classes="node-status",
            id=f"node-status-{self.node_id}",
        )

    def set_status(self, status: str) -> None:
        if status == self._status:
            return
        self._status = status
        self.remove_class("status-done", "status-running", "status-pending")
        self.add_class(f"status-{status}")
        try:
            self.query_one(f"#node-status-{self.node_id}", Static).update(
                _STATUS_LINES.get(status, status)
            )
        except Exception:
            pass


class DagLayer(Widget):
    """Vertical column holding one or more DagNode cards."""

    DEFAULT_CSS = """
    DagLayer {
        width: auto;
        height: auto;
        align: left top;
    }
    """

    def __init__(self, nodes: list[tuple[FlowNode, str]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._node_data = nodes

    def compose(self) -> ComposeResult:
        for node, status in self._node_data:
            yield DagNode(
                node,
                status,
                id=f"dag-node-{node.id}",
                classes=f"dag-node status-{status}",
            )


class AutomationDag(Widget, can_focus=True):
    """Layout-agnostic DAG renderer.

    Accepts a ``FlowState`` and renders bordered node cards arranged in
    topological layers with arrows between them. Handles both linear and
    branching graphs via the same code path.

    Keyboard navigation: h/l between layers, j/k between siblings.
    Enter posts ``NodeSelected`` to filter the Logs tab.
    """

    class NodeSelected(Message):
        """Posted when the user presses Enter on a focused node."""

        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    BINDINGS = [
        Binding("h", "prev_layer",   "Prev layer",  show=False),
        Binding("l", "next_layer",   "Next layer",  show=False),
        Binding("k", "prev_sibling", "Prev node",   show=False),
        Binding("j", "next_sibling", "Next node",   show=False),
        Binding("enter", "select",   "Filter logs", show=True),
    ]

    DEFAULT_CSS = """
    AutomationDag {
        height: auto;
        width: auto;
    }
    AutomationDag #dag-canvas {
        height: auto;
        width: auto;
        align: left top;
    }
    AutomationDag .dag-arrow {
        width: 3;
        height: 5;
        content-align: center middle;
        color: $text-muted;
    }
    AutomationDag .dag-empty {
        color: $text-muted;
        text-style: italic;
        padding: 2 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_steps: tuple[str, ...] = ()
        self._layers: list[list[str]] = []
        self._focused_layer: int = 0
        self._focused_index: int = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="dag-canvas"):
            yield Static(
                "[dim]Waiting for automation…[/]",
                classes="dag-empty",
                id="dag-placeholder",
            )

    def update_state(self, state: object) -> None:
        """Receive new CanonState and update the diagram."""
        from toad.widgets.canon_state import CanonState
        if not isinstance(state, CanonState):
            return
        flow = state.flow
        if flow is None or not flow.steps:
            self._show_placeholder()
            return

        topology_changed = flow.steps != self._current_steps
        if topology_changed:
            self._current_steps = flow.steps
            self.call_after_refresh(self._rebuild, flow)
        else:
            self._update_statuses(flow)

    def _show_placeholder(self) -> None:
        canvas = self.query_one("#dag-canvas", Horizontal)
        try:
            canvas.query_one("#dag-placeholder")
        except Exception:
            self.call_after_refresh(self._reset_to_placeholder)

    def _reset_to_placeholder(self) -> None:
        canvas = self.query_one("#dag-canvas", Horizontal)
        canvas.remove_children()
        canvas.mount(
            Static(
                "[dim]Waiting for automation…[/]",
                classes="dag-empty",
                id="dag-placeholder",
            )
        )
        self._layers = []
        self._current_steps = ()

    async def _rebuild(self, flow: FlowState) -> None:
        """Full widget-tree rebuild when topology changes."""
        nodes = flow.effective_nodes()
        edges = flow.effective_edges()
        self._layers = _compute_layers(nodes, edges)

        nodes_by_id = {n.id: n for n in nodes}
        canvas = self.query_one("#dag-canvas", Horizontal)
        await canvas.remove_children()

        if not self._layers:
            await canvas.mount(
                Static(
                    "[dim]No flow data[/]",
                    classes="dag-empty",
                    id="dag-placeholder",
                )
            )
            return

        to_mount: list[Widget] = []
        for i, layer_ids in enumerate(self._layers):
            if i > 0:
                to_mount.append(Static(" → ", classes="dag-arrow"))
            layer_nodes = [
                (nodes_by_id[nid], flow.node_status(nid))
                for nid in layer_ids
                if nid in nodes_by_id
            ]
            to_mount.append(DagLayer(layer_nodes, classes="dag-layer"))

        await canvas.mount_all(to_mount)
        # Don't auto-focus the first node on rebuild — focusing a node
        # inside a hidden TabPane causes TabbedContent to switch to that
        # tab. The user can press Tab/click to give focus, then h/j/k/l
        # to navigate.
        self._focused_layer = 0
        self._focused_index = 0

    def _update_statuses(self, flow: FlowState) -> None:
        """Fast path: mutate CSS classes on existing DagNode widgets."""
        for node_widget in self.query(DagNode):
            node_widget.set_status(flow.node_status(node_widget.node_id))

    def _focus_node(self, layer_idx: int, sibling_idx: int) -> None:
        if not self._layers:
            return
        layer_idx = max(0, min(layer_idx, len(self._layers) - 1))
        layer = self._layers[layer_idx]
        sibling_idx = max(0, min(sibling_idx, len(layer) - 1))
        self._focused_layer = layer_idx
        self._focused_index = sibling_idx
        node_id = layer[sibling_idx]
        try:
            node = self.query_one(f"#dag-node-{node_id}", DagNode)
            node.focus()
        except Exception:
            pass

    def action_next_layer(self) -> None:
        self._focus_node(self._focused_layer + 1, self._focused_index)

    def action_prev_layer(self) -> None:
        self._focus_node(self._focused_layer - 1, self._focused_index)

    def action_next_sibling(self) -> None:
        self._focus_node(self._focused_layer, self._focused_index + 1)

    def action_prev_sibling(self) -> None:
        self._focus_node(self._focused_layer, self._focused_index - 1)

    def action_select(self) -> None:
        if not self._layers:
            return
        try:
            layer = self._layers[self._focused_layer]
            node_id = layer[self._focused_index]
            self.post_message(self.NodeSelected(node_id))
        except IndexError:
            pass

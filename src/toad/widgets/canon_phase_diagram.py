"""CanonPhaseDiagram — system diagram for the canon pipeline phases.

Constructed with a mode (``"build"`` or ``"live"``) and renders the
corresponding topology:

- **build** — init → scaffold → strategy → develop → run (5 nodes).
  Node status derived from CanonState.phase.

- **live** — Awaiting Funds → Funds Detected → Onboarding → Ready →
  Running Live. Status derived from CanonState.status (live sub-states
  written by canon-live-readiness.sh).

AutomationPanel mounts two instances and toggles their visibility.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import HorizontalScroll
from textual.reactive import reactive
from textual.widget import Widget

from toad.widgets.automation_dag import AutomationDag
from toad.widgets.canon_state import CanonState, FlowEdge, FlowNode, FlowState

# --- Build-mode topology ----------------------------------------------------
BUILD_ORDER: tuple[str, ...] = ("init", "scaffold", "strategy", "develop", "run")

_BUILD_NODES: tuple[FlowNode, ...] = (
    FlowNode(id="init",     label="Canon",    type="setup"),
    FlowNode(id="scaffold", label="Scaffold", type="build"),
    FlowNode(id="strategy", label="Strategy", type="config"),
    FlowNode(id="develop",  label="Develop",  type="build"),
    FlowNode(id="run",      label="Dry Run",  type="runner"),
)

_BUILD_EDGES: tuple[FlowEdge, ...] = (
    FlowEdge("init",     "scaffold"),
    FlowEdge("scaffold", "strategy"),
    FlowEdge("strategy", "develop"),
    FlowEdge("develop",  "run"),
)

# --- Live-mode topology -----------------------------------------------------
LIVE_ORDER: tuple[str, ...] = (
    "awaiting", "detected", "onboard", "ready", "live",
)

_LIVE_NODES: tuple[FlowNode, ...] = (
    FlowNode(id="awaiting", label="Awaiting", type="setup"),
    FlowNode(id="detected", label="Detected", type="config"),
    FlowNode(id="onboard",  label="Onboard",  type="build"),
    FlowNode(id="ready",    label="Ready",    type="config"),
    FlowNode(id="live",     label="Live",     type="deploy"),
)

_LIVE_EDGES: tuple[FlowEdge, ...] = (
    FlowEdge("awaiting", "detected"),
    FlowEdge("detected", "onboard"),
    FlowEdge("onboard",  "ready"),
    FlowEdge("ready",    "live"),
)

# Maps canon-live-readiness.sh status values to live node IDs.
_STATUS_TO_LIVE_NODE: dict[str, str] = {
    "deposit-pending": "awaiting",
    "funds-detected":  "detected",
    "onboarding":      "onboard",
    "ready":           "ready",
    "running":         "live",
    "timeout":         "awaiting",
}


def _synthesize_build_flow(state: CanonState) -> FlowState:
    """Translate CanonState.phase → FlowState for the build diagram."""
    phase = state.phase
    status = state.status

    try:
        current_idx = BUILD_ORDER.index(phase)
    except ValueError:
        current_idx = -1

    completed: list[str] = []
    active: str = ""

    for nid in BUILD_ORDER:
        node_idx = BUILD_ORDER.index(nid)
        if node_idx < current_idx:
            completed.append(nid)
        elif node_idx == current_idx:
            if status == "complete":
                completed.append(nid)
            else:
                active = nid

    return FlowState(
        steps=BUILD_ORDER,
        active=active,
        completed=tuple(completed),
        nodes=_BUILD_NODES,
        edges=_BUILD_EDGES,
    )


def _synthesize_live_flow(state: CanonState) -> FlowState:
    """Translate CanonState.status → FlowState for the live diagram."""
    active_node = _STATUS_TO_LIVE_NODE.get(state.status, "")

    try:
        active_idx = LIVE_ORDER.index(active_node) if active_node else -1
    except ValueError:
        active_idx = -1

    completed: list[str] = []
    active: str = ""

    for nid in LIVE_ORDER:
        node_idx = LIVE_ORDER.index(nid)
        if node_idx < active_idx:
            completed.append(nid)
        elif node_idx == active_idx:
            active = nid

    return FlowState(
        steps=LIVE_ORDER,
        active=active,
        completed=tuple(completed),
        nodes=_LIVE_NODES,
        edges=_LIVE_EDGES,
    )


class CanonPhaseDiagram(Widget):
    """System diagram for the canon pipeline.

    Constructed with ``mode="build"`` or ``mode="live"``. AutomationPanel
    mounts two — one for each mode — and toggles visibility based on
    the current canon state.
    """

    state: reactive[CanonState] = reactive(  # type: ignore[assignment]
        CanonState, always_update=True
    )

    DEFAULT_CSS = """
    CanonPhaseDiagram {
        height: auto;
        width: 1fr;
    }
    CanonPhaseDiagram #phases-scroll {
        height: auto;
        max-height: 8;
    }
    CanonPhaseDiagram #phases-dag {
        height: auto;
        width: auto;
    }
    """

    def __init__(self, *, mode: str = "build", **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if mode not in ("build", "live"):
            raise ValueError(f"mode must be 'build' or 'live', got {mode!r}")
        self._mode = mode

    def compose(self) -> ComposeResult:
        with HorizontalScroll(id="phases-scroll"):
            yield AutomationDag(id="phases-dag")

    def watch_state(self, state: CanonState) -> None:
        if self._mode == "live":
            flow = _synthesize_live_flow(state)
        else:
            flow = _synthesize_build_flow(state)
        synthetic = CanonState(
            phase=state.phase,
            status=state.status,
            flow=flow,
        )
        self.query_one("#phases-dag", AutomationDag).update_state(synthetic)

"""Tests for canon state, flow state, and automation panel helpers.

Verifies:
- CanonState dataclass and _parse_state with mock .canon/state.json data
- FlowState extensions: nodes/edges, effective_nodes/edges, node_status
- Phase transitions: build phases, run phase, develop→run switch
- Error state handling
- Log rendering (automation_panel._render_log)
- Graceful empty state when no data
"""

from __future__ import annotations

import json

import pytest

from toad.widgets.canon_state import (
    ALL_PHASES,
    BUILD_PHASES,
    FlowEdge,
    FlowNode,
    FlowState,
    RUN_PHASES,
    CanonState,
    CanonStateWidget,
    LogEntry,
    _parse_flow,
    _parse_state,
)


# ------------------------------------------------------------------
# Fixtures — mock state.json payloads
# ------------------------------------------------------------------


def _build_state(
    *,
    phase: str = "develop",
    status: str = "active",
    iteration: int = 3,
    error: str | None = None,
    logs: list[dict] | None = None,
    metrics: dict | None = None,
) -> dict:
    payload: dict = {
        "phase": phase,
        "status": status,
        "iteration": iteration,
    }
    if error is not None:
        payload["error"] = error
    if logs is not None:
        payload["logs"] = logs
    if metrics is not None:
        payload["metrics"] = metrics
    return payload


# ------------------------------------------------------------------
# CanonState / _parse_state
# ------------------------------------------------------------------


class TestCanonStateDataclass:
    def test_defaults(self):
        s = CanonState()
        assert s.phase == ""
        assert s.status == ""
        assert s.iteration == 0
        assert s.error is None
        assert s.logs == ()
        assert s.metrics == ()

    @pytest.mark.parametrize("phase", sorted(BUILD_PHASES))
    def test_is_build_phase(self, phase: str):
        s = CanonState(phase=phase)
        assert s.is_build_phase is True
        assert s.is_run_phase is False

    def test_is_run_phase(self):
        s = CanonState(phase="run")
        assert s.is_run_phase is True
        assert s.is_build_phase is False

    def test_unknown_phase_is_neither(self):
        s = CanonState(phase="unknown")
        assert s.is_build_phase is False
        assert s.is_run_phase is False

    def test_phase_sets_are_disjoint(self):
        assert BUILD_PHASES & RUN_PHASES == set()
        assert BUILD_PHASES | RUN_PHASES == ALL_PHASES


class TestParseState:
    def test_minimal_payload(self):
        state = _parse_state({})
        assert state.phase == ""
        assert state.status == ""
        assert state.iteration == 0
        assert state.error is None
        assert state.logs == ()
        assert state.metrics == ()

    def test_full_build_payload(self):
        raw = _build_state(
            phase="scaffold",
            status="active",
            iteration=2,
            logs=[
                {"level": "info",  "message": "Starting scaffold", "timestamp": "2026-03-30T10:00:00Z"},
                {"level": "warn",  "message": "Slow network",      "timestamp": "2026-03-30T10:00:01Z"},
            ],
        )
        state = _parse_state(raw)
        assert state.phase == "scaffold"
        assert state.status == "active"
        assert state.iteration == 2
        assert state.is_build_phase is True
        assert len(state.logs) == 2
        assert state.logs[0].level == "info"
        assert state.logs[1].message == "Slow network"

    def test_run_phase_with_metrics(self):
        raw = _build_state(
            phase="run", status="running", iteration=1,
            metrics={"requests": "142", "errors": "3"},
        )
        state = _parse_state(raw)
        assert state.is_run_phase is True
        assert ("requests", "142") in state.metrics
        assert ("errors", "3") in state.metrics

    def test_error_state(self):
        raw = _build_state(phase="develop", status="error", error="Build failed")
        state = _parse_state(raw)
        assert state.status == "error"
        assert state.error == "Build failed"

    def test_logs_missing_fields_default(self):
        raw = _build_state(logs=[{"message": "bare log"}])
        state = _parse_state(raw)
        assert state.logs[0].level == "info"
        assert state.logs[0].timestamp == ""
        assert state.logs[0].message == "bare log"

    def test_metrics_values_coerced_to_str(self):
        raw = _build_state(phase="run", status="running", metrics={"count": 42})
        state = _parse_state(raw)
        assert ("count", "42") in state.metrics

    def test_roundtrip_through_json(self):
        raw = _build_state(phase="init", status="active", iteration=1,
                           logs=[{"level": "debug", "message": "boot"}])
        state = _parse_state(json.loads(json.dumps(raw)))
        assert state.phase == "init"
        assert state.logs[0].level == "debug"


# ------------------------------------------------------------------
# FlowState extensions
# ------------------------------------------------------------------


class TestFlowStateNodeStatus:
    def test_completed_node_is_done(self):
        flow = FlowState(steps=("a", "b"), active="b", completed=("a",))
        assert flow.node_status("a") == "done"

    def test_active_node_is_running(self):
        flow = FlowState(steps=("a", "b"), active="b", completed=("a",))
        assert flow.node_status("b") == "running"

    def test_pending_node(self):
        flow = FlowState(steps=("a", "b", "c"), active="a", completed=())
        assert flow.node_status("c") == "pending"

    def test_done_takes_priority_over_active(self):
        # completed should win even if active is also set (shouldn't happen, but defensive)
        flow = FlowState(steps=("a",), active="a", completed=("a",))
        assert flow.node_status("a") == "done"


class TestFlowStateEffectiveNodes:
    def test_declared_nodes_returned_as_is(self):
        nodes = (FlowNode("x", "X", "build"), FlowNode("y", "Y", "gate"))
        flow = FlowState(steps=("x", "y"), nodes=nodes)
        assert flow.effective_nodes() == nodes

    def test_fallback_synthesizes_from_steps(self):
        flow = FlowState(steps=("init", "develop"), labels=(("init", "Init"), ("develop", "Develop")))
        eff = flow.effective_nodes()
        assert len(eff) == 2
        assert eff[0].id == "init"
        assert eff[0].label == "Init"
        assert eff[1].id == "develop"
        assert eff[1].label == "Develop"

    def test_fallback_label_titlizes_step_id(self):
        flow = FlowState(steps=("my_step",))
        eff = flow.effective_nodes()
        assert eff[0].label == "My Step"

    def test_empty_steps_returns_empty(self):
        flow = FlowState()
        assert flow.effective_nodes() == ()


class TestFlowStateEffectiveEdges:
    def test_declared_edges_returned_as_is(self):
        edges = (FlowEdge("a", "b"), FlowEdge("b", "c"))
        flow = FlowState(steps=("a", "b", "c"), edges=edges)
        assert flow.effective_edges() == edges

    def test_fallback_synthesizes_linear_chain(self):
        flow = FlowState(steps=("a", "b", "c"))
        eff = flow.effective_edges()
        assert len(eff) == 2
        assert eff[0] == FlowEdge("a", "b")
        assert eff[1] == FlowEdge("b", "c")

    def test_single_step_no_edges(self):
        flow = FlowState(steps=("only",))
        assert flow.effective_edges() == ()

    def test_empty_steps_no_edges(self):
        flow = FlowState()
        assert flow.effective_edges() == ()


class TestParseFlowWithNodes:
    def test_parse_nodes_and_edges(self):
        data = {
            "steps": ["init", "run"],
            "labels": {},
            "active": "run",
            "completed": ["init"],
            "nodes": [
                {"id": "init", "label": "Init", "type": "build"},
                {"id": "run",  "label": "Run",  "type": "gate"},
            ],
            "edges": [{"from": "init", "to": "run"}],
        }
        flow = _parse_flow(data)
        assert len(flow.nodes) == 2
        assert flow.nodes[0].id == "init"
        assert flow.nodes[1].type == "gate"
        assert len(flow.edges) == 1
        assert flow.edges[0].from_id == "init"
        assert flow.edges[0].to_id == "run"

    def test_parse_missing_nodes_gives_empty(self):
        data = {"steps": ["a", "b"], "labels": {}, "active": "a", "completed": []}
        flow = _parse_flow(data)
        assert flow.nodes == ()
        assert flow.edges == ()

    def test_node_missing_id_skipped(self):
        data = {
            "steps": [], "labels": {}, "active": "", "completed": [],
            "nodes": [{"label": "No ID"}],
        }
        flow = _parse_flow(data)
        assert flow.nodes == ()

    def test_edge_missing_fields_skipped(self):
        data = {
            "steps": [], "labels": {}, "active": "", "completed": [],
            "edges": [{"from": "a"}],  # missing "to"
        }
        flow = _parse_flow(data)
        assert flow.edges == ()


# ------------------------------------------------------------------
# Phase transitions
# ------------------------------------------------------------------


class TestPhaseTransitions:
    @pytest.mark.parametrize(
        ("from_phase", "to_phase", "expect_build", "expect_run"),
        [
            ("init",     "scaffold", True,  False),
            ("scaffold", "strategy", True,  False),
            ("strategy", "develop",  True,  False),
            ("develop",  "run",      False, True),
        ],
    )
    def test_transition(self, from_phase, to_phase, expect_build, expect_run):
        new = CanonState(phase=to_phase)
        assert new.is_build_phase is expect_build
        assert new.is_run_phase is expect_run

    def test_develop_to_run_switches_section(self):
        old = CanonState(phase="develop")
        new = CanonState(phase="run")
        assert old.is_build_phase is True
        assert new.is_run_phase is True


# ------------------------------------------------------------------
# Log rendering (automation_panel)
# ------------------------------------------------------------------


class TestLogRendering:
    """automation_panel._render_log produces correct Rich markup."""

    def test_message_present(self):
        from toad.widgets.automation_panel import _render_log
        entry = LogEntry(level="info", message="hello")
        assert "hello" in _render_log(entry)

    def test_error_level_red(self):
        from toad.widgets.automation_panel import _render_log
        assert "[red bold]" in _render_log(LogEntry(level="error", message="fail"))

    def test_warn_level_yellow(self):
        from toad.widgets.automation_panel import _render_log
        assert "[yellow]" in _render_log(LogEntry(level="warn", message="heads up"))

    def test_warning_alias_yellow(self):
        from toad.widgets.automation_panel import _render_log
        assert "[yellow]" in _render_log(LogEntry(level="warning", message="w"))

    def test_debug_level_dim(self):
        from toad.widgets.automation_panel import _render_log
        assert "[dim]" in _render_log(LogEntry(level="debug", message="trace"))

    def test_unknown_level_white(self):
        from toad.widgets.automation_panel import _render_log
        assert "[white]" in _render_log(LogEntry(level="custom", message="msg"))

    def test_no_timestamp_no_dim_prefix(self):
        from toad.widgets.automation_panel import _render_log
        rendered = _render_log(LogEntry(level="info", message="no ts"))
        # Timestamp markup only present when timestamp is non-empty
        assert "10]" not in rendered


# ------------------------------------------------------------------
# Error state
# ------------------------------------------------------------------


class TestErrorState:
    def test_error_state_from_json(self):
        raw = _build_state(phase="develop", status="error", error="Compile failed",
                           logs=[{"level": "error", "message": "exit 1"}])
        state = _parse_state(raw)
        assert state.status == "error"
        assert state.error == "Compile failed"
        assert state.logs[0].level == "error"

    def test_error_none_when_absent(self):
        assert _parse_state(_build_state(phase="run", status="running")).error is None

    def test_error_in_run_phase(self):
        state = _parse_state(_build_state(phase="run", status="error", error="Timeout"))
        assert state.is_run_phase is True
        assert state.error == "Timeout"


# ------------------------------------------------------------------
# CanonStateWidget messages
# ------------------------------------------------------------------


class TestCanonStateWidgetMessages:
    def test_detected_is_message(self):
        from textual.message import Message
        assert isinstance(CanonStateWidget.CanonStateDetected(), Message)

    def test_updated_carries_state(self):
        state = CanonState(phase="run", status="running")
        msg = CanonStateWidget.CanonStateUpdated(state)
        assert msg.state is state
        assert msg.state.phase == "run"


# ------------------------------------------------------------------
# ProjectStatePane — automation section registered
# ------------------------------------------------------------------


class TestProjectStatePaneSections:
    def test_automation_section_registered(self):
        import inspect
        from toad.widgets.project_state_pane import ProjectStatePane
        source = inspect.getsource(ProjectStatePane)
        assert "Automation" in source or "automation" in source

    def test_automation_route_exists(self):
        from toad.widgets.project_state_pane import PANEL_ROUTES
        assert "automation" in PANEL_ROUTES

    def test_status_route_removed(self):
        from toad.widgets.project_state_pane import PANEL_ROUTES
        assert "status" not in PANEL_ROUTES

    def test_canon_state_widget_mounted(self):
        import inspect
        from toad.widgets.project_state_pane import ProjectStatePane
        assert "CanonStateWidget" in inspect.getsource(ProjectStatePane)


# ------------------------------------------------------------------
# Graceful empty state
# ------------------------------------------------------------------


class TestGracefulEmptyState:
    def test_empty_parse(self):
        assert _parse_state({}) == CanonState()

    def test_empty_state_is_neither_build_nor_run(self):
        state = CanonState()
        assert state.is_build_phase is False
        assert state.is_run_phase is False

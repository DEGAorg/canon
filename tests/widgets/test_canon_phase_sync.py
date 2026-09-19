"""File updates open Automation and continue updating without stealing focus."""
import json

import pytest
from textual import on
from textual.app import App, ComposeResult

from toad.screens.main import MainScreen
from toad.widgets.automation_panel import AutomationPanel
from toad.widgets.canon_state import CanonStateWidget
from toad.widgets.project_state_pane import ProjectStatePane


@pytest.mark.asyncio
async def test_phase_files_open_panel_and_metrics_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr("toad.widgets.canon_state.POLL_INTERVAL", 0.05)
    class Host(App):
        _canon_phase = ""
        split_enabled = False
        _forward_canon_state = MainScreen._forward_canon_state
        _show_section_tab = MainScreen._show_section_tab
        action_show_automation = MainScreen.action_show_automation

        def compose(self) -> ComposeResult:
            yield ProjectStatePane(project_path=tmp_path, id="project_state_pane")

        @on(CanonStateWidget.CanonStateUpdated)
        async def update_state(self, event):
            await MainScreen._on_canon_updated(self, event)

    app = Host()
    state_dir = tmp_path / ".canon"
    async with app.run_test(size=(140, 45)) as pilot:
        assert not app.split_enabled
        state_dir.mkdir()
        state_path = state_dir / "state.json"
        state_path.write_text(json.dumps({"phase": "develop", "status": "running"}))
        await pilot.pause(0.15)
        assert app.split_enabled
        pane = app.query_one(ProjectStatePane)
        assert pane.query_one("#section-state").display
        assert app.query_one(AutomationPanel).state.phase == "develop"
        pane.show_single_section("section-context")
        state_path.write_text(json.dumps({
            "phase": "develop", "status": "running", "metrics": {"cycles": 2}
        }))
        await pilot.pause(0.15)
        assert not pane.query_one("#section-state").display
        assert ("cycles", "2") in app.query_one(AutomationPanel).state.metrics
        state_path.write_text(json.dumps({"phase": "run", "status": "executing"}))
        await pilot.pause(0.15)
        assert pane.query_one("#section-state").display
        assert app.query_one(AutomationPanel).state.phase == "run"


@pytest.mark.asyncio
async def test_socket_inspects_current_screen():
    from textual.widgets import Static
    from toad.socket_controller import _dispatch

    class Host(App):
        def compose(self) -> ComposeResult:
            yield Static("before", id="status")

    app = Host()
    async with app.run_test():
        result = await _dispatch(app, {"cmd": "query", "selector": "#status"})
        assert result["widgets"][0]["id"] == "status"
        assert result["widgets"][0]["text"] == "before"
        result = await _dispatch(app, {"cmd": "snapshot"})
        assert any(w["id"] == "status" for w in result["widgets"])
        result = await _dispatch(app, {
            "cmd": "update", "selector": "#status", "text": "after"
        })
        assert result == {"ok": True}
        assert str(app.screen.query_one("#status", Static).content) == "after"

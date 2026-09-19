"""Phase diagrams reflect runner lifecycle without inventing completion."""
import pytest

from toad.widgets.canon_phase_diagram import _synthesize_build_flow, _synthesize_live_flow
from toad.widgets.canon_state import CanonState


@pytest.mark.parametrize('status,expected', [
    ('executing', 'running'), ('running', 'running'), ('stopped', 'stopped'),
    ('idle', 'stopped'), ('error', 'error'),
])
@pytest.mark.parametrize('phase,synthesize', [('run', _synthesize_build_flow),
                                            ('live', _synthesize_live_flow)])
def test_runner_lifecycle(status, expected, phase, synthesize):
    flow = synthesize(CanonState(phase=phase, status=status))
    node = 'run' if phase == 'run' else 'live'
    assert flow.node_status(node) == expected
    assert len(flow.completed) == 4


def test_completed_dry_run_remains_done():
    flow = _synthesize_build_flow(CanonState(phase='run', status='complete'))
    assert flow.node_status('run') == 'done'


@pytest.mark.asyncio
async def test_diagram_updates_running_to_stopped():
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    from toad.widgets.automation_dag import DagNode
    from toad.widgets.canon_phase_diagram import CanonPhaseDiagram

    class DiagramApp(App):
        def compose(self) -> ComposeResult:
            yield CanonPhaseDiagram(mode='build')

    app = DiagramApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        diagram = app.query_one(CanonPhaseDiagram)
        diagram.state = CanonState(phase='run', status='executing')
        await pilot.pause()
        node = next(node for node in app.query(DagNode) if node.node_id == 'run')
        assert node.has_class('status-running')
        diagram.state = CanonState(phase='run', status='stopped')
        await pilot.pause()
        assert node.has_class('status-stopped')
        assert not node.has_class('status-running')
        assert 'stopped' in str(node.query_one('#node-status-run', Static).content)

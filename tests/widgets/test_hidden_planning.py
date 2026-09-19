"""Hidden planning widgets must not leak into the default project panel."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import TabbedContent

from toad.widgets.project_state_pane import ProjectStatePane


@pytest.mark.asyncio
async def test_context_hides_plan_and_unlisted_planning_content(tmp_path):
    class Host(App):
        def compose(self) -> ComposeResult:
            yield ProjectStatePane(project_path=tmp_path)

    app = Host()
    async with app.run_test(size=(120, 40)) as pilot:
        pane = app.query_one(ProjectStatePane)
        pane.display = True
        pane.styles.width = "1fr"
        pane.show_single_section("section-context")
        await pilot.pause()
        tabs = pane.query_one("#tabs-context", TabbedContent)
        assert tabs.active == "tab-files"
        assert not tabs.get_tab("tab-plan").display
        assert not pane.query_one("#section-planning").display
        assert pane.query_one("#tab-files").is_on_screen
        pane.show_single_section("section-state")
        await pilot.pause()
        assert not pane.query_one("#section-planning").is_on_screen

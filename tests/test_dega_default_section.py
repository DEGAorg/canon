"""The project-panel shortcut opens DEGA and closes on a second press."""

from unittest.mock import Mock

from toad.screens.main import MainScreen


def test_project_shortcut_opens_dega_then_closes():
    screen = Mock(split_enabled=False)
    pane = screen.query_one.return_value
    MainScreen.action_toggle_project_state(screen)
    assert screen.split_enabled
    pane.show_single_section.assert_called_once_with("section-dega")
    MainScreen.action_toggle_project_state(screen)
    pane.hide_all_sections.assert_called_once()

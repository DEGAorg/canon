"""Signing out requires a deliberate confirmation."""

from unittest.mock import Mock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from toad.extensions.dega_panel.auth_store import AuthState, Session
from toad.extensions.dega_panel.logout_confirm import LogoutConfirm
from toad.extensions.dega_panel.pane import DegaPane


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["escape", "cancel-logout", "confirm-logout"])
async def test_logout_confirmation(action, monkeypatch):
    clear = Mock()
    monkeypatch.setattr("toad.extensions.dega_panel.pane.clear_auth", clear)

    class Host(App):
        def compose(self) -> ComposeResult:
            yield Button("Account")

    app = Host()
    state = AuthState(session=Session("test-token", "test-user", "test@example.test"))
    pane = Mock(auth=state, app=app)
    pane._confirm_logout = lambda confirmed: DegaPane._confirm_logout(pane, confirmed)
    async with app.run_test() as pilot:
        DegaPane.action_logout(pane)
        await pilot.pause()
        assert isinstance(app.screen, LogoutConfirm)
        assert app.focused.id == "cancel-logout"
        clear.assert_not_called()
        if action == "escape":
            await pilot.press("escape")
        else:
            await pilot.click(f"#{action}")
        await pilot.pause()
        assert clear.call_count == (1 if action == "confirm-logout" else 0)
        assert pane.auth.is_logged_in == (action != "confirm-logout")

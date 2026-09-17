from unittest.mock import Mock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Link

from toad.extensions.dega_panel.auth_view import AuthBar, FlowStatus, run_device_login
from toad.extensions.dega_panel.device_client import DeviceClient


class LoginApp(App):
    login_requests = 0

    def compose(self) -> ComposeResult:
        yield AuthBar()

    def on_auth_bar_login_requested(self, event):
        self.login_requests += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("keyboard", [False, True])
@pytest.mark.parametrize("width", [40, 80])
async def test_pairing_url_opens_in_browser(monkeypatch, keyboard, width):
    app = LoginApp()
    open_url = Mock()
    monkeypatch.setattr(app, "open_url", open_url)
    url = "https://agents.example.test/device?source=canon&next=%2Faccount"
    async with app.run_test(size=(width, 24)) as pilot:
        bar = app.query_one(AuthBar)
        bar.set_status(FlowStatus(phase="waiting", user_code="ABCD-1234", verification_uri=url))
        await pilot.pause()
        link = app.query_one("#auth-verification-link", Link)
        assert link.display
        assert link.region.right <= width
        assert bar.region.bottom >= link.region.bottom
        if keyboard:
            link.focus()
            await pilot.press("enter")
        else:
            assert await pilot.click(link)
        open_url.assert_called_once_with(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("keyboard", [False, True])
async def test_sign_in_is_clickable_and_controls_follow_flow(keyboard):
    app = LoginApp()
    async with app.run_test() as pilot:
        bar = app.query_one(AuthBar)
        button = app.query_one("#btn-login", Button)
        assert button.display
        if keyboard:
            button.focus()
            await pilot.press("enter")
        else:
            assert await pilot.click(button)
        assert app.login_requests == 1
        for phase in ("connecting", "connected", "error", "idle"):
            bar.set_status(FlowStatus(phase=phase))
            assert button.display == (phase in {"idle", "error"})
            link = app.query_one("#auth-verification-link", Link)
            assert not link.display
            assert link.url == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ["/device", "https://login.example.test/device"])
async def test_pairing_accepts_relative_and_absolute_urls(monkeypatch, uri):
    client = DeviceClient(base_url="https://api.example.test")

    async def request_code():
        return {"user_code": "ABCD-1234", "device_code": "test-device", "verification_uri": uri}

    async def poll_token(*args, **kwargs):
        kwargs["on_pending"]()
        raise RuntimeError("end test before approval")

    monkeypatch.setattr(client, "request_code", request_code)
    monkeypatch.setattr(client, "poll_token", poll_token)
    statuses = []
    await run_device_login(client, statuses.append, lambda *_: None)
    waiting = [status for status in statuses if status.phase == "waiting"]
    expected = uri if uri.startswith("https://") else "https://api.example.test/device"
    assert len(waiting) == 2
    assert all(status.verification_uri == expected for status in waiting)

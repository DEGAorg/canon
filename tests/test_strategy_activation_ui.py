"""Activation requires a deliberate confirmation before any purchase request."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static
from toad.extensions.dega_panel import access_grants, utility


@pytest.mark.asyncio
async def test_activation_cancel_never_spends_and_confirmation_caches_grant(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(access_grants, "ACCESS_FILE", tmp_path / "access.json")
    monkeypatch.setattr(access_grants, "load_auth", lambda: SimpleNamespace(
        session=SimpleNamespace(user_id="test", session_token="fixture")))
    decision = {"state": "activation_required", "alternatives": [{
        "id": "arbiter-silver", "allOf": [{"elementType": "silver", "count": 1}],
        "durationSeconds": 86400, "scope": "strategy", "deficits": [],
    }]}
    monkeypatch.setattr(utility, "backend_eligibility", AsyncMock(return_value=decision))
    remote = AsyncMock(return_value={"grant": {
        "id": "purchased", "scope": "strategy", "strategyKey": "arbiter",
        "activatedAt": now.isoformat(), "expiresAt": (now+timedelta(days=1)).isoformat(),
    }, "serverTime": now.isoformat()})
    monkeypatch.setattr(access_grants, "_request", remote)

    class Host(App):
        def compose(self) -> ComposeResult:
            yield utility.UtilityView(SimpleNamespace(elements={}))

    app = Host()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#activate-access")
        await pilot.pause()
        assert isinstance(app.screen, utility._AccessConfirm)
        remote.assert_not_called()
        await pilot.click("#cancel")
        await pilot.pause()
        remote.assert_not_called()
        await pilot.click("#activate-access")
        await pilot.pause()
        await pilot.click("#activate")
        await pilot.pause()
        assert remote.await_count == 1
        assert access_grants.cached_grant("arbiter") is not None
        assert "Access active until" in str(app.query_one("#op-status", Static).render())


@pytest.mark.asyncio
async def test_active_access_sync_failure_is_displayed(monkeypatch):
    monkeypatch.setattr(utility, "backend_eligibility", AsyncMock(
        return_value={"state": "active"}))
    monkeypatch.setattr(utility, "ensure_access", AsyncMock(
        side_effect=utility.StrategyAccessError("Access service unavailable; retry")))

    class Host(App):
        def compose(self) -> ComposeResult:
            yield utility.UtilityView(SimpleNamespace(elements={}))

    app = Host()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#activate-access")
        await pilot.pause()
        assert "Access service unavailable" in str(
            app.query_one("#op-status", Static).render())


@pytest.mark.parametrize("width", [60, 106])
async def test_access_copy_button_and_real_signal_visibility(monkeypatch, tmp_path, width):
    from textual.widgets import Button, DataTable

    monkeypatch.setattr(utility, "backend_eligibility", AsyncMock(return_value={
        "state": "activation_required", "alternatives": [],
    }))

    class Host(App):
        def compose(self) -> ComposeResult:
            yield utility.UtilityView(SimpleNamespace(elements={}))

    app = Host()
    async with app.run_test(size=(width, 42)) as pilot:
        await pilot.pause()
        view = app.query_one(utility.UtilityView)
        table = view.query_one("#detail-table", DataTable)
        button = view.query_one("#activate-access", Button)
        assert button.variant == "primary"
        assert str(button.label) == "Activate access"
        assert "ACCESS" not in str(view.query_one("#detail-rule", Static).render())
        assert not table.display and table.row_count == 0
        view._access[view._selected] = {"state": "active"}
        view.refresh_detail()
        assert not table.display
        build = utility.BUILDS_BY_KEY[view._selected]
        view.runner_lines = [f'{build.name}: MOMENTUM LAG: "Market A" moved 4¢']
        view.refresh_detail()
        assert table.display and table.row_count == 1
        view.runner_lines = []
        view.refresh_detail()
        assert not table.display and table.row_count == 0
        view._access[view._selected] = {"state": "activation_required"}
        view.refresh_detail()
        await pilot.pause()
        app.save_screenshot(str(tmp_path / f"strategy-{width}.svg"))


def test_elements_bar_does_not_expose_synthetic_address_or_repeat_email():
    from toad.extensions.dega_panel.auth_store import AuthState, Session
    from toad.extensions.dega_panel.pane import ElementsBar

    auth = AuthState(
        session=Session("test-token", "test-user", "person@example.test"),
        addresses=["synthetic:person@example.test"],
    )
    bar = ElementsBar(SimpleNamespace(elements={"Silver Test": 1}, auth=auth))
    rendered = bar.render()
    assert "synthetic" not in rendered
    assert "person@example.test" not in rendered
    assert "1 total" in rendered and "Silver Test" in rendered

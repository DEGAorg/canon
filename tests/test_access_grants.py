"""Local-first access, explicit purchases and account separation."""
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from toad.extensions.dega_panel import access_grants as access
from toad.extensions.dega_panel.strategy_access import StrategyAccessError


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(access, "ACCESS_FILE", tmp_path / "access.json")
    monkeypatch.setattr(access, "_api_base", lambda: "https://api.test")
    session = SimpleNamespace(user_id="alice", session_token="secret-test")
    monkeypatch.setattr(access, "load_auth", lambda: SimpleNamespace(session=session))
    now = time.time()
    response = {"grant": {"id": "grant-1", "scope": "strategy", "strategyKey": "arbiter",
        "activatedAt": stamp(now-10), "expiresAt": stamp(now+100)}, "serverTime": stamp(now)}
    return session, response


@pytest.mark.asyncio
async def test_valid_local_window_never_calls_remote(state, monkeypatch):
    _, response = state
    access._store_response(access._identity()[0], response)
    remote = AsyncMock(side_effect=AssertionError("Unexpected network call"))
    monkeypatch.setattr(access, "_request", remote)
    assert (await access.ensure_access("arbiter")).id == "grant-1"
    remote.assert_not_called()
    assert access.ACCESS_FILE.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_expiry_fetches_new_grant_without_purchase(state, monkeypatch):
    _, response = state
    expired = {**response, "serverTime": stamp(time.time()+200)}
    access._store_response(access._identity()[0], expired)
    remote = AsyncMock(return_value=response)
    monkeypatch.setattr(access, "_request", remote)
    assert (await access.ensure_access("arbiter")).id == "grant-1"
    remote.assert_awaited_once_with("GET", "/strategies/access", params={"key": "arbiter"})


@pytest.mark.asyncio
async def test_missing_access_and_account_switch_fail_closed(state, monkeypatch):
    session, response = state
    access._store_response(access._identity()[0], response)
    session.user_id = "bob"
    remote = AsyncMock(return_value={"grant": None})
    monkeypatch.setattr(access, "_request", remote)
    with pytest.raises(StrategyAccessError):
        await access.ensure_access("arbiter")
    assert remote.await_count == 1


@pytest.mark.asyncio
async def test_retry_keeps_purchase_idempotency_key(state, monkeypatch):
    _, response = state
    remote = AsyncMock(side_effect=[StrategyAccessError("timeout"), response])
    monkeypatch.setattr(access, "_request", remote)
    with pytest.raises(StrategyAccessError):
        await access.activate_access("arbiter")
    await access.activate_access("arbiter")
    assert remote.call_args_list[0].kwargs == remote.call_args_list[1].kwargs


@pytest.mark.asyncio
async def test_diamond_cache_covers_other_strategies(state, monkeypatch):
    _, response = state
    response["grant"].update(scope="all_strategies", strategyKey=None)
    access._store_response(access._identity()[0], response)
    remote = AsyncMock(side_effect=AssertionError("Unexpected request"))
    monkeypatch.setattr(access, "_request", remote)
    assert (await access.ensure_access("ivee")).scope == "all_strategies"


@pytest.mark.asyncio
async def test_corrupt_cache_resynchronizes(state, monkeypatch):
    _, response = state
    access.ACCESS_FILE.write_text('{"https://api.test|alice":null}')
    monkeypatch.setattr(access, "_request", AsyncMock(return_value=response))
    assert (await access.ensure_access("arbiter")).id == "grant-1"


@pytest.mark.asyncio
async def test_both_launch_paths_block_without_access_before_spawning(state, monkeypatch):
    from toad.extensions.dega_panel import runner

    monkeypatch.setattr(access, "_request", AsyncMock(return_value={"grant": None}))
    spawn = AsyncMock(side_effect=AssertionError("Must not spawn without access"))
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(StrategyAccessError):
        await runner.StrategyRunner("arbiter").start(confirmed=True)
    with pytest.raises(StrategyAccessError):
        await runner.run_strategy("arbiter", confirmed=True)
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_clock_rollback_requires_remote_recovery(state, monkeypatch):
    _, response = state
    access._store_response(access._identity()[0], response)
    saved_now = time.time()
    monkeypatch.setattr(access.time, "time", lambda: saved_now - 60)
    remote = AsyncMock(return_value={"grant": None})
    monkeypatch.setattr(access, "_request", remote)
    with pytest.raises(StrategyAccessError):
        await access.ensure_access("arbiter")
    remote.assert_awaited_once()


@pytest.mark.asyncio
async def test_slot_activation_retains_purchase_reference_on_retry(state, monkeypatch):
    _, response = state
    remote = AsyncMock(side_effect=[StrategyAccessError("timeout"), response])
    monkeypatch.setattr(access, "_request", remote)
    with pytest.raises(StrategyAccessError):
        await access.activate_access("arbiter", purchase_id="purchase-1")
    await access.activate_access("arbiter", purchase_id="purchase-1")
    assert remote.call_args_list[0].kwargs == remote.call_args_list[1].kwargs
    assert remote.call_args.kwargs["json"]["purchaseId"] == "purchase-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("use_slot", [True, False])
async def test_confirmation_distinguishes_slots_from_new_spending(use_slot):
    from textual.app import App
    from textual.widgets import Button, Label
    from toad.extensions.dega_panel.utility import _AccessConfirm

    app = App()
    async with app.run_test() as pilot:
        app.push_screen(_AccessConfirm("2 selections, 1825 days", use_slot=use_slot))
        await pilot.pause()
        labels = " ".join(str(label.render()) for label in app.screen.query(Label))
        button = app.screen.query_one("#activate", Button)
        if use_slot:
            assert "No Element is consumed" in labels
            assert str(button.label) == "Use purchased slot"
        else:
            assert "share a timer starting now" in labels
            assert str(button.label) == "Consume and activate"

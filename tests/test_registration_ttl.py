"""Registration expiry behavior across the in-memory model, RPC and UI."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.widgets import Button, Static

from toad.extensions.dega_panel import registration_renewal, registry_client
from toad.extensions.dega_panel.chat import ChatView, RenewRegistration
from toad.extensions.dega_panel.registration import RenewalQuote
from toad.extensions.dega_panel.registry_client import (
    ChainRegistry,
    RegistryClient,
    RegistryError,
    TestRegistry as MemoryRegistry,
    load_persisted_nodes,
    persist_nodes,
)
from tests import test_chat_ui

ChatApp = test_chat_ui.ChatApp


@pytest.fixture
def wallet_dir(monkeypatch, tmp_path):
    return test_chat_ui.wallet_dir.__wrapped__(monkeypatch, tmp_path)


@pytest.fixture
def memory(monkeypatch):
    now = [1000]
    monkeypatch.setattr(registry_client, "_ensure_owner_wallet", lambda: "wallet")
    client = RegistryClient(
        backend="test", fee_weega=10, registration_ttl=100, clock=lambda: now[0]
    )
    client.open_node("alice", b"a" * 32)
    return client, now


def test_expiry_hides_discovery_but_preserves_renewal_identity(memory):
    client, now = memory
    assert client.resolve_member("alice")["username"] == "alice"
    now[0] = 1100
    assert client.resolve_member("alice") == {}
    assert client.resolve_pubkey("alice") == b""
    assert client.username_for_pubkey(b"a" * 32) == ""
    assert client.node_owner("alice") == ""
    assert client.member_addresses("alice") == []
    assert client.username_of_owner("wallet") == ""
    assert client.username_taken("alice")
    status = client.registration_status()
    assert status.username == "alice" and not status.active
    client.renew_node(client.renewal_quote())
    assert client.registration_status().expires_at == 1200
    assert client.resolve_member("alice")["pubkey"] == b"a" * 32


def test_config_changes_only_affect_future_periods_and_stale_terms_fail(memory):
    client, now = memory
    quote = client.renewal_quote()
    client._sim.set_registration_ttl(200)
    assert client.registration_status().expires_at == 1100
    with pytest.raises(RegistryError, match="terms changed"):
        client.renew_node(quote)
    quote = client.renewal_quote()
    client.renew_node(quote)
    assert client.registration_status().expires_at == 1300
    with pytest.raises(RegistryError, match="changed"):
        client.renew_node(quote)


def test_persistence_does_not_restart_registration_timer(memory, tmp_path):
    client, now = memory
    path = persist_nodes(client._sim, tmp_path / "registry.json")
    restored = load_persisted_nodes(path)
    assert restored.registration_of_owner("wallet").expires_at == 1100
    assert restored._nodes["alice"].nostr_pubkey == b"a" * 32
    assert not restored.is_active("alice")


def test_status_rpc_failure_is_not_unregistered():
    chain = ChainRegistry.__new__(ChainRegistry)
    chain._contract = Mock()
    chain._contract.functions.registrationOfOwner.return_value.call.side_effect = OSError("offline")
    with pytest.raises(RegistryError, match="Cannot check registration"):
        chain.registration_of_owner("0x" + "11" * 20)
    chain._contract.functions.fee.return_value.call.side_effect = OSError("offline")
    with pytest.raises(RegistryError, match="Cannot read registration fee"):
        chain.fee()


@pytest.mark.asyncio
async def test_ui_expired_recovery_cancel_then_renew(wallet_dir, memory):
    client, now = memory
    now[0] = 1100
    app = ChatApp(wallet_dir)
    async with app.run_test(size=(100, 38)) as pilot:
        view = app.query_one(ChatView)
        view._registry = client
        await view.ensure_chat_ready()
        await pilot.pause()
        assert view._my_username == "alice"
        status = view.query_one("#registration-status", Static)
        assert "Expired" in str(status.render())
        assert view.query_one("#btn-renew-registration", Button).display
        await pilot.click("#btn-renew-registration")
        await pilot.pause()
        assert isinstance(app.screen, RenewRegistration)
        await pilot.click("#cancel-renew")
        await pilot.pause()
        assert client.registration_status().expires_at == 1100
        await pilot.click("#btn-renew-registration")
        await pilot.pause()
        await pilot.click("#confirm-renew")
        await pilot.pause()
        assert client.registration_status().expires_at == 1200
        assert "Active" in str(status.render())


@pytest.mark.asyncio
async def test_ui_rpc_failure_keeps_identity_and_blocks_registration(wallet_dir, memory):
    client, _ = memory
    app = ChatApp(wallet_dir)
    async with app.run_test(size=(60, 38)) as pilot:
        view = app.query_one(ChatView)
        view._registry = client
        await view.ensure_chat_ready()
        client.registration_status = Mock(side_effect=RegistryError("RPC unavailable"))
        await view._resume_node()
        await view.rebuild()
        await pilot.pause()
        assert view._my_username == "alice"
        assert "Unable to check" in str(view.query_one("#registration-status", Static).render())
        assert view.query_one("#btn-renew-registration", Button).disabled
        assert view.query_one("#btn-retry-registration", Button).display


def test_failed_or_malformed_pending_renewal_never_signs_again(tmp_path, monkeypatch):
    monkeypatch.setattr(registration_renewal, "CANON_DIR", tmp_path)
    chain = SimpleNamespace(_w3=Mock(), _registry="0x123", _sender="0x456")
    chain._w3.eth.chain_id = 31337
    path = registration_renewal._pending_path(chain)
    path.parent.mkdir()
    path.write_text("{broken")
    quote = RenewalQuote(MemoryRegistry().registration_of_owner("wallet"), 0, 100, 18)
    with pytest.raises(RegistryError, match="Cannot prepare renewal"):
        registration_renewal.renew_on_chain(chain, quote)
    chain._w3.eth.send_raw_transaction.assert_not_called()

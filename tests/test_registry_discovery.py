"""Behavioral coverage for chain-scoped contact discovery and storage."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Button, Static

from toad.extensions.dega_panel.chat import ChooseContact, default_offline
from toad.extensions.dega_panel.chat_contact import (
    active_node, add_my_node, contacts, remember_binding, remember_contact,
)
from toad.extensions.dega_panel.registry_discovery import (
    ContactBinding, DiscoveryResult, discover_contacts,
)


def provider(*, key=b"a" * 32, absent=False, failure=False):
    def resolve(name):
        if failure:
            raise OSError("RPC unavailable")
        return None if absent else {"username": name, "wallet": "owner", "pubkey": key}

    return lambda: SimpleNamespace(network="preview", registry="registry", resolve_member=resolve)


def test_both_namespaces_preserved_and_case_and_dots_unchanged():
    result = discover_contacts(" A.b.dega ", providers=[
        ("ethereum", provider()), ("cardano", provider()),
    ])
    assert len(result.matches) == 2
    assert [binding.username for binding in result.matches] == ["A.b", "A.b"]
    assert result.matches[0].contact_id != result.matches[1].contact_id
    assert not result.failures


@pytest.mark.parametrize("second", [provider(failure=True), provider(key=b"bad")])
def test_failure_is_incomplete_search_even_with_one_match(second):
    result = discover_contacts("alice", providers=[
        ("ethereum", provider()), ("cardano", second),
    ])
    assert len(result.matches) == 1
    assert len(result.failures) == 1
    assert "Cardano" in result.failures[0]


def test_absent_registry_does_not_create_phantom_match():
    result = discover_contacts("alice", providers=[("cardano", provider(absent=True))])
    assert result == DiscoveryResult((), ())


def test_bindings_survive_restart_without_owner_deduplication(tmp_path):
    path = tmp_path / "contacts.json"
    binding = ContactBinding("cardano", "preview", "policy", "A.b", "owner", b"a" * 32)
    for candidate in [binding, replace(binding, network="local"),
                      replace(binding, registry="another"), replace(binding, chain="ethereum")]:
        remember_binding(candidate, path=path)
    stored = contacts(path)
    assert len(stored) == 4
    assert len({contact["id"] for contact in stored}) == 4
    assert all(contact["pubkey"] == (b"a" * 32).hex() for contact in stored)
    assert all(contact["verified"] for contact in stored)
    add_my_node("A.b.dega", path=path)
    assert active_node(path) == "A.b"


def test_inbound_nostr_contact_is_explicitly_unverified(tmp_path):
    path = tmp_path / "contacts.json"
    remember_contact("sender", pubkey=b"a" * 32, path=path)
    assert contacts(path)[0]["verified"] is False
    assert "chain" not in contacts(path)[0]


def test_cardano_uses_online_nostr_transport(monkeypatch):
    monkeypatch.setenv("DEGA_CHAT_BACKEND", "cardano")
    assert not default_offline()


@pytest.mark.asyncio
async def test_choice_modal_shows_incomplete_search_and_requires_button():
    binding = ContactBinding("cardano", "preview", "policy", "alice", "owner", b"a" * 32)
    result = DiscoveryResult((binding,), ("Ethereum lookup unavailable",))
    app = App()
    chosen = []
    async with app.run_test() as pilot:
        app.push_screen(ChooseContact(result), chosen.append)
        await pilot.pause()
        assert not chosen
        assert any("Incomplete search" in str(item.render()) for item in app.screen.query(Static))
        assert "Cardano" in str(app.screen.query_one("#binding-0", Button).label)
        await pilot.click("#binding-0")
        assert chosen == [binding]


@pytest.mark.asyncio
async def test_ambiguous_choice_cancel_never_selects_first():
    binding = ContactBinding("ethereum", "1", "registry", "alice", "owner", b"a" * 32)
    app = App()
    chosen = []
    async with app.run_test() as pilot:
        app.push_screen(ChooseContact(DiscoveryResult(
            (binding, replace(binding, chain="cardano")), ())), chosen.append)
        await pilot.pause()
        await pilot.press("escape")
        assert chosen == [None]


def test_cardano_wallet_profile_uses_cached_public_sender(monkeypatch):
    from toad.extensions.dega_panel.chat import ChatView

    def unexpected_wallet_read():
        raise AssertionError("Cardano profile must not read an Ethereum signing wallet")

    monkeypatch.setattr("toad.extensions.dega_panel.chat.configured_wallet_address",
                        unexpected_wallet_read)
    view = SimpleNamespace(_offline=False, _registry_backend="cardano",
                           _cardano_wallet=None,
                           _snapshot_cache={"sender": "owner-hash",
                                            "funding_address": "addr_test1public"})
    assert ChatView._wallet(view) == "addr_test1public"
    view._snapshot_cache = None
    assert ChatView._wallet(view) == "Not configured"


def test_slow_provider_preserves_fast_match_as_explicit_partial_result(monkeypatch):
    from threading import Event

    release = Event()
    started = Event()

    def slow_lookup(name):
        started.set()
        release.wait(timeout=5)
        return {"username": name, "wallet": "owner", "pubkey": b"b" * 32}

    def slow():
        return SimpleNamespace(network="preview", registry="policy", resolve_member=slow_lookup)
    monkeypatch.setattr("toad.extensions.dega_panel.registry_discovery.DISCOVERY_TIMEOUT_SECONDS",
                        0.1)
    try:
        result = discover_contacts("alice", providers=[
            ("cardano", slow), ("ethereum", provider()),
        ])
        assert started.is_set()
        assert len(result.matches) == 1
        assert result.matches[0].chain == "ethereum"
        assert result.failures == ("Cardano lookup timed out; retry discovery",)
    finally:
        release.set()


@pytest.mark.parametrize("selected", [None, "cardano"])
def test_configured_missing_manifest_is_an_incomplete_search(tmp_path, monkeypatch, selected):
    from toad.extensions.dega_panel import registry_discovery, auth_store
    from toad.extensions.dega_panel.cardano_config import CardanoConfig

    monkeypatch.delenv("CANON_CARDANO_DEPLOYMENT", raising=False)
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    manifest = tmp_path / ("cardano/deployment.json" if selected else "custom.json")
    config = CardanoConfig("Mainnet", tmp_path / "wallet", manifest, selected)
    monkeypatch.setattr(registry_discovery, "load_cardano_config", lambda: config)
    monkeypatch.setattr(registry_discovery, "EthereumDiscovery", provider())
    monkeypatch.setattr(
        "toad.extensions.dega_panel.cardano_registry.load_cardano_config", lambda: config,
    )
    result = discover_contacts("alice")
    assert len(result.matches) == 1
    assert result.matches[0].chain == "ethereum"
    assert result.failures == ("Cardano lookup unavailable or invalid; retry discovery",)

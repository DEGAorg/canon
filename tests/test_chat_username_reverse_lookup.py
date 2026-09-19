"""Reverse lookup: inbound DM sender pubkey -> registered username.dega.

Guards the feature where a recipient can see the sender's on-chain username
even when they never invited/resolved them (DegaChatRegistry.usernameForPubkey,
surfaced as RegistryClient.username_for_pubkey).
"""
from toad.extensions.dega_panel.registry_client import RegistryClient

PUB_A = bytes(range(32))          # 0x00..0x1f
PUB_B = bytes(range(32, 64))     # 0x20..0x3f


def _registry_with_nodes() -> RegistryClient:
    reg = RegistryClient(backend="test")
    # Seed via the simulated direct backend with DISTINCT owner wallets so both
    # registrations are allowed (the facade's open_node is one-node-per-wallet
    # on a single shared owner, which would reject a second node).
    sim = reg._sim
    assert sim is not None
    sim.open_node("alice", "0x" + "1" * 40, nostr_pubkey=PUB_A)
    sim.open_node("bob", "0x" + "2" * 40, nostr_pubkey=PUB_B)
    return reg


def test_reverse_lookup_resolves_registered_sender():
    reg = _registry_with_nodes()
    assert reg.username_for_pubkey(PUB_A) == "alice"
    assert reg.username_for_pubkey(PUB_B) == "bob"


def test_reverse_lookup_accepts_hex_string():
    reg = _registry_with_nodes()
    assert reg.username_for_pubkey(PUB_A.hex()) == "alice"
    assert reg.username_for_pubkey("0x" + PUB_B.hex()) == "bob"


def test_reverse_lookup_empty_for_unknown_pubkey():
    reg = _registry_with_nodes()
    unknown = bytes(range(100, 132))
    assert reg.username_for_pubkey(unknown) == ""


def test_reverse_lookup_empty_for_no_pubkey():
    reg = _registry_with_nodes()
    assert reg.username_for_pubkey(b"") == ""
    assert reg.username_for_pubkey("") == ""


def test_open_node_persists_pubkey_for_reverse_lookup():
    reg = RegistryClient(backend="test")
    pub = bytes([0xA0] * 32)
    reg.open_node("newbie", nostr_pubkey=pub)
    assert reg.username_for_pubkey(pub) == "newbie"
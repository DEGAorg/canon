"""Ownership proof must fail before any approval when the active key is unavailable."""

from unittest.mock import Mock

import pytest
from nostr_sdk import Keys

from toad.extensions.dega_panel.registration_proof import registration_proof
from toad.extensions.dega_panel.registry_client import ChainRegistry, RegistryError


@pytest.mark.parametrize("secret", [None, "different", "01", "00" * 32, "ff" * 32, "invalid"])
def test_missing_invalid_or_mismatched_secret_never_approves_fee(secret):
    client = object.__new__(ChainRegistry)
    client.username_taken = Mock(return_value=False)
    client._ensure_fee_approved = Mock()
    client._sender = "0x" + "1" * 40
    client._registry = "0x" + "2" * 40
    client._w3 = Mock()
    client._w3.eth.chain_id = 1
    identity = Keys.generate()
    if secret == "different":
        secret = Keys.generate().secret_key().to_hex()
    with pytest.raises(RegistryError, match="signing key"):
        client.open_node("alice", identity.public_key().to_hex(), nostr_secret=secret)
    client._ensure_fee_approved.assert_not_called()


def test_proof_requires_matching_x_only_identity():
    identity = Keys.generate()
    with pytest.raises(ValueError, match="does not match"):
        registration_proof(
            identity.secret_key().to_hex(), b"invalid", wallet="0x" + "1" * 40,
            username="alice", chain_id=1, registry="0x" + "2" * 40,
        )

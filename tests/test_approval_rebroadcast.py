"""Approval recovery remains usable after rejected or externally replaced sends."""

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from web3 import Web3
from web3.exceptions import TransactionNotFound

from toad.extensions.dega_panel import approval_transaction as approval
from toad.extensions.dega_panel.registry_client import ChainRegistry, RegistryError


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "CANON_DIR", tmp_path)
    client = object.__new__(ChainRegistry)
    client._w3 = MagicMock()
    client._account = MagicMock()
    client._contract = MagicMock()
    client._registry = "0x2222222222222222222222222222222222222222"
    client._sender = "0x1111111111111111111111111111111111111111"
    client._w3.eth.chain_id = 1
    client._contract.functions.degaToken.return_value.call.return_value = (
        "0x3333333333333333333333333333333333333333"
    )
    raw = b"identical-signed-approval"
    client._account.sign_transaction.return_value = SimpleNamespace(
        hash=Web3.keccak(raw), raw_transaction=raw,
    )
    return client


def reject_initial_send(client):
    """Model an RPC refusing an approval before its transaction enters the pool."""
    client._w3.eth.send_raw_transaction.side_effect = ValueError("insufficient funds")
    with pytest.raises(RegistryError):
        approval.submit_approval(client, {"nonce": 7})
    assert approval.pending_path(client).exists()
    client._w3.eth.send_raw_transaction.side_effect = None
    client._w3.eth.get_transaction_receipt.side_effect = TransactionNotFound("not found")
    client._w3.eth.get_transaction.side_effect = TransactionNotFound("not found")


def test_funding_then_restart_rebroadcasts_identical_signed_bytes(registry):
    reject_initial_send(registry)
    restarted = object.__new__(ChainRegistry)
    restarted.__dict__.update(registry.__dict__)
    restarted._w3.eth.get_transaction_count.return_value = 7
    restarted._w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    approval.confirm_pending(restarted)

    registry._account.sign_transaction.assert_called_once()
    assert registry._w3.eth.send_raw_transaction.call_args_list == [
        call(b"identical-signed-approval"), call(b"identical-signed-approval"),
    ]
    assert not approval.pending_path(restarted).exists()


def test_mined_replacement_with_allowance_skips_further_approval(registry):
    reject_initial_send(registry)
    registry._w3.eth.get_transaction_count.return_value = 8
    token = registry._w3.eth.contract.return_value
    token.functions.allowance.return_value.call.return_value = 100

    registry._ensure_fee_approved(fee=100)

    token.functions.approve.assert_not_called()
    registry._account.sign_transaction.assert_called_once()
    registry._w3.eth.send_raw_transaction.assert_called_once()
    registry._w3.eth.wait_for_transaction_receipt.assert_not_called()
    assert not approval.pending_path(registry).exists()


def test_consumed_nonce_without_allowance_allows_new_approval(registry):
    reject_initial_send(registry)
    registry._w3.eth.get_transaction_count.return_value = 8
    registry._w3.eth.get_transaction_receipt.side_effect = [
        TransactionNotFound("not found"), {"status": 1},
    ]
    registry._w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}
    registry._w3.eth.max_priority_fee = 1_000_000_000
    registry._w3.eth.get_block.return_value = {"baseFeePerGas": 1_000_000_000}
    token = registry._w3.eth.contract.return_value
    token.functions.allowance.return_value.call.side_effect = [0, 100]
    token.functions.approve.return_value.build_transaction.return_value = {"nonce": 8}

    registry._ensure_fee_approved(fee=100)

    token.functions.approve.assert_called_once_with(registry._registry, 100)
    assert registry._account.sign_transaction.call_args_list == [
        call({"nonce": 7}), call({"nonce": 8}),
    ]
    assert registry._w3.eth.send_raw_transaction.call_count == 2
    assert not approval.pending_path(registry).exists()


def test_replacement_during_initial_submit_does_not_authorize_registration(registry):
    registry._w3.eth.get_transaction_count.side_effect = [7, 8]
    registry._w3.eth.get_transaction_receipt.side_effect = TransactionNotFound("missing")
    registry._w3.eth.max_priority_fee = 1_000_000_000
    registry._w3.eth.get_block.return_value = {"baseFeePerGas": 1_000_000_000}
    token = registry._w3.eth.contract.return_value
    token.functions.allowance.return_value.call.return_value = 0
    token.functions.approve.return_value.build_transaction.return_value = {"nonce": 7}

    with pytest.raises(RegistryError, match="without sufficient allowance"):
        registry._ensure_fee_approved(fee=100)

    registry._account.sign_transaction.assert_called_once()
    assert not approval.pending_path(registry).exists()

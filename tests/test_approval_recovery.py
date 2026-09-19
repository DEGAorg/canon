"""Approval retries preserve the original transaction across client restarts."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from web3 import Web3
from web3.exceptions import TimeExhausted, TransactionNotFound

from toad.extensions.dega_panel import approval_transaction as approval
from toad.extensions.dega_panel.registry_client import RegistryError


@pytest.fixture
def chain(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "CANON_DIR", tmp_path)
    client = SimpleNamespace(
        _w3=MagicMock(), _account=MagicMock(), _registry="0xregistry", _sender="0xsender",
    )
    client._w3.eth.chain_id = 1
    client._w3.eth.get_transaction_receipt.side_effect = TransactionNotFound("missing")
    client._w3.eth.get_transaction_count.return_value = 0
    client._account.sign_transaction.return_value = SimpleNamespace(
        hash=Web3.keccak(b"signed-test-transaction"), raw_transaction=b"signed-test-transaction",
    )
    return client


def test_timeout_retry_confirms_original_without_signing_again(chain):
    chain._w3.eth.wait_for_transaction_receipt.side_effect = TimeExhausted()
    with pytest.raises(RegistryError, match="still unconfirmed"):
        approval.submit_approval(chain, {"nonce": 0})
    assert approval.pending_path(chain).stat().st_mode & 0o777 == 0o600
    restarted = SimpleNamespace(**vars(chain))
    restarted._w3.eth.wait_for_transaction_receipt.side_effect = None
    restarted._w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}
    approval.confirm_pending(restarted)
    chain._account.sign_transaction.assert_called_once()
    chain._w3.eth.send_raw_transaction.assert_called_once()
    assert not approval.pending_path(chain).exists()


def test_uncertain_broadcast_keeps_record(chain):
    chain._w3.eth.send_raw_transaction.side_effect = OSError("connection lost")
    with pytest.raises(RegistryError, match="broadcast uncertain"):
        approval.submit_approval(chain, {"nonce": 0})
    assert approval.pending_path(chain).exists()


def test_reverted_approval_clears_record_and_fails(chain):
    chain._w3.eth.wait_for_transaction_receipt.return_value = {"status": 0}
    with pytest.raises(RegistryError, match="reverted"):
        approval.submit_approval(chain, {"nonce": 0})
    assert not approval.pending_path(chain).exists()


def test_malformed_record_fails_closed(chain):
    path = approval.pending_path(chain)
    path.parent.mkdir(parents=True)
    path.write_text("not json")
    with pytest.raises(RegistryError, match="record is preserved"):
        approval.confirm_pending(chain)
    assert path.exists()
    chain._account.sign_transaction.assert_not_called()
    chain._w3.eth.send_raw_transaction.assert_not_called()


def test_corrupt_signed_bytes_never_broadcast(chain):
    approval.save_pending(
        approval.pending_path(chain),
        approval.PendingApproval("0x" + "ab" * 32, 0, "0x1234"),
    )
    chain._w3.eth.get_transaction.side_effect = TransactionNotFound("missing")
    with pytest.raises(RegistryError, match="record is preserved"):
        approval.confirm_pending(chain)
    chain._w3.eth.send_raw_transaction.assert_not_called()
    assert approval.pending_path(chain).exists()


def test_rpc_error_does_not_mean_transaction_missing(chain):
    chain._w3.eth.wait_for_transaction_receipt.side_effect = TimeExhausted()
    with pytest.raises(RegistryError):
        approval.submit_approval(chain, {"nonce": 0})
    chain._w3.eth.send_raw_transaction.reset_mock()
    chain._w3.eth.get_transaction_receipt.side_effect = OSError("RPC down")
    with pytest.raises(RegistryError, match="record is preserved"):
        approval.confirm_pending(chain)
    chain._w3.eth.send_raw_transaction.assert_not_called()
    assert approval.pending_path(chain).exists()

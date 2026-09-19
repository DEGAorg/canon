"""Registration fee safety with RPC and signing mocked at their boundaries."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from toad.extensions.dega_panel.registry_client import ChainRegistry


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ChainRegistry:
    monkeypatch.setattr("toad.extensions.dega_panel.registry_client.CANON_DIR", tmp_path)
    registry = object.__new__(ChainRegistry)
    registry._w3 = MagicMock()
    registry._account = MagicMock()
    registry._sender = "0x1111111111111111111111111111111111111111"
    registry._registry = "0x2222222222222222222222222222222222222222"
    registry._contract = MagicMock()
    registry._contract.functions.degaToken.return_value.call.return_value = (
        "0x3333333333333333333333333333333333333333"
    )
    registry._submit_approval_mock = MagicMock()
    monkeypatch.setattr(
        "toad.extensions.dega_panel.approval_transaction.confirm_pending", MagicMock(),
    )
    monkeypatch.setattr(
        "toad.extensions.dega_panel.approval_transaction.submit_approval",
        registry._submit_approval_mock,
    )
    return registry


@pytest.mark.parametrize("rpc_tip", [0, 1, 999_999_999, 1_000_000_000])
def test_fee_floor_prevents_zero_tip(registry: ChainRegistry, rpc_tip: int) -> None:
    registry._w3.eth.max_priority_fee = rpc_tip
    registry._w3.eth.get_block.return_value = {"baseFeePerGas": 2_000_000_000}

    assert registry._transaction_fees() == {
        "maxPriorityFeePerGas": 1_000_000_000,
        "maxFeePerGas": 5_000_000_000,
    }


def test_fee_keeps_higher_rpc_tip(registry: ChainRegistry) -> None:
    registry._w3.eth.max_priority_fee = 3_000_000_000
    registry._w3.eth.get_block.return_value = {"baseFeePerGas": 10_000_000_000}

    assert registry._transaction_fees() == {
        "maxPriorityFeePerGas": 3_000_000_000,
        "maxFeePerGas": 23_000_000_000,
    }


@pytest.mark.parametrize("allowance", [100, 101])
def test_existing_allowance_does_not_submit_approval(
    registry: ChainRegistry, allowance: int,
) -> None:
    token = registry._w3.eth.contract.return_value
    token.functions.allowance.return_value.call.return_value = allowance

    registry._ensure_fee_approved(fee=100)

    token.functions.allowance.assert_called_once_with(registry._sender, registry._registry)
    token.functions.approve.assert_not_called()
    registry._account.sign_transaction.assert_not_called()
    registry._submit_approval_mock.assert_not_called()


def test_insufficient_allowance_approves_exact_fee(registry: ChainRegistry) -> None:
    token = registry._w3.eth.contract.return_value
    token.functions.allowance.return_value.call.side_effect = [99, 100]
    registry._w3.eth.max_priority_fee = 0
    registry._w3.eth.get_block.return_value = {"baseFeePerGas": 2_000_000_000}

    registry._ensure_fee_approved(fee=100)

    token.functions.approve.assert_called_once_with(registry._registry, 100)
    registry._submit_approval_mock.assert_called_once()

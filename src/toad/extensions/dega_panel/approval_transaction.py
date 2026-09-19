"""Persist signed approvals for safe rebroadcast and receipt recovery."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from eth_typing import HexStr
from web3 import Web3
from web3.types import TxReceipt
from web3.exceptions import TimeExhausted, TransactionNotFound

from toad.extensions.dega_panel.auth_store import CANON_DIR

if TYPE_CHECKING:
    from toad.extensions.dega_panel.registry_client import ChainRegistry


@dataclass(frozen=True)
class PendingApproval:
    tx_hash: str
    nonce: int
    raw_transaction: str


def pending_path(chain: ChainRegistry) -> Path:
    """Scope approval recovery to the chain, registry and signer."""
    scope = f"{chain._w3.eth.chain_id}-{chain._registry.lower()}-{chain._sender.lower()}"
    return CANON_DIR / "registration-approvals" / f"{scope}.json"


def save_pending(path: Path, pending: PendingApproval) -> None:
    """Record the signed identifier atomically before broadcasting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(asdict(pending), output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def _recover_receipt(chain: ChainRegistry, pending: PendingApproval) -> TxReceipt | None:
    """Resolve a mined/replaced nonce or rebroadcast the identical transaction."""
    tx_hash = HexStr(pending.tx_hash)
    try:
        return chain._w3.eth.get_transaction_receipt(tx_hash)
    except TransactionNotFound:
        pass
    # A consumed nonce cannot execute again. The caller rechecks allowance,
    # whether the replacement approved the token, reverted, or cancelled.
    if chain._w3.eth.get_transaction_count(chain._sender, "latest") > pending.nonce:
        return None
    try:
        chain._w3.eth.get_transaction(tx_hash)
    except TransactionNotFound:
        raw = Web3.to_bytes(hexstr=HexStr(pending.raw_transaction))
        if Web3.to_hex(Web3.keccak(raw)) != pending.tx_hash:
            raise ValueError("Saved approval bytes do not match its transaction hash")
        chain._w3.eth.send_raw_transaction(raw)
    return chain._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)


def confirm_pending(chain: ChainRegistry) -> None:
    """Resolve or rebroadcast the saved approval without signing again."""
    from toad.extensions.dega_panel.registry_client import RegistryError

    path = pending_path(chain)
    if not path.exists():
        return
    try:
        pending = PendingApproval(**json.loads(path.read_text()))
        receipt = _recover_receipt(chain, pending)
    except TimeExhausted as exc:
        raise RegistryError(
            f"Approval {pending.tx_hash} is still unconfirmed. Retry checks the same transaction; "
            "no new approval is signed. A pending low-fee transaction may need a wallet speed-up."
        ) from exc
    except Exception as exc:
        raise RegistryError(
            "Cannot confirm the saved approval. Check the RPC and retry; "
            "the approval record is preserved to prevent duplicate transactions."
        ) from exc
    path.unlink()
    if receipt is not None and receipt.get("status") != 1:
        raise RegistryError(f"Approval {pending.tx_hash} reverted; no registration was submitted")


def submit_approval(chain: ChainRegistry, tx: dict) -> None:
    """Persist a signed approval hash, broadcast once, then confirm it."""
    from toad.extensions.dega_panel.registry_client import RegistryError

    signed = chain._account.sign_transaction(tx)
    pending = PendingApproval(
        Web3.to_hex(signed.hash), tx["nonce"], Web3.to_hex(signed.raw_transaction),
    )
    save_pending(pending_path(chain), pending)
    try:
        chain._w3.eth.send_raw_transaction(signed.raw_transaction)
    except Exception as exc:
        raise RegistryError(
            f"Approval broadcast uncertain ({pending.tx_hash}). Retry recovers the same transaction; "
            "no additional approval will be signed."
        ) from exc
    confirm_pending(chain)

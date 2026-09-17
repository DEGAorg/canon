"""Persist signed renewal transactions before broadcast for safe retry/restart."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from eth_typing import HexStr
from web3 import Web3
from web3.types import TxParams, TxReceipt
from web3.exceptions import TransactionNotFound

from toad.extensions.dega_panel.auth_store import CANON_DIR
from toad.extensions.dega_panel.registration import RenewalQuote
from toad.extensions.dega_panel.registry_client import RegistryError

if TYPE_CHECKING:
    from pathlib import Path

    from toad.extensions.dega_panel.registry_client import ChainRegistry


@dataclass(frozen=True)
class PendingRenewal:
    raw_transaction: str
    tx_hash: str
    nonce: int


def _pending_path(chain: ChainRegistry) -> Path:
    scope = f"{chain._w3.eth.chain_id}-{chain._registry.lower()}-{chain._sender.lower()}"
    return CANON_DIR / "registration-renewals" / f"{scope}.json"


def _save(path: Path, pending: PendingRenewal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(asdict(pending), output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def _prepare(chain: ChainRegistry, quote: RenewalQuote) -> PendingRenewal:
    if not quote.registration.username:
        raise RegistryError("Register a username before renewing")
    if quote.registration.owner.lower() != chain._sender.lower():
        raise RegistryError("Use the registered wallet to renew")
    if quote.fee:
        chain._ensure_fee_approved(quote.fee)
    args = [quote.registration.username, quote.registration.expires_at, quote.fee, quote.duration]
    tx = chain._contract.functions.renewNode(*args).build_transaction(
        TxParams(
            {
                "from": chain._sender,
                "nonce": chain._next_nonce(),
                "gas": chain._estimate_gas("renewNode", args),
            }
        )
    )
    signed = chain._account.sign_transaction(tx)
    return PendingRenewal(
        Web3.to_hex(signed.raw_transaction), Web3.to_hex(signed.hash), tx["nonce"]
    )


def _receipt(chain: ChainRegistry, pending: PendingRenewal) -> TxReceipt:
    try:
        return chain._w3.eth.get_transaction_receipt(HexStr(pending.tx_hash))
    except TransactionNotFound:
        try:
            chain._w3.eth.get_transaction(HexStr(pending.tx_hash))
        except TransactionNotFound:
            if chain._w3.eth.get_transaction_count(chain._sender, "latest") > pending.nonce:
                _pending_path(chain).unlink()
                raise RegistryError(
                    "Renewal transaction replaced; refresh registration before retrying"
                )
            chain._w3.eth.send_raw_transaction(
                Web3.to_bytes(hexstr=HexStr(pending.raw_transaction))
            )
        return chain._w3.eth.wait_for_transaction_receipt(HexStr(pending.tx_hash), timeout=120)


def renew_on_chain(chain: ChainRegistry, quote: RenewalQuote) -> dict:
    """Resume a pending renewal or durably record one before any broadcast.

    A network failure keeps the exact signed transaction for retry. No new
    renewal is signed until the previous receipt has been resolved.
    """
    try:
        path = _pending_path(chain)
        if path.exists():
            pending = PendingRenewal(**json.loads(path.read_text()))
        else:
            pending = _prepare(chain, quote)
            _save(path, pending)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryError("Cannot prepare renewal; check wallet, RPC and local storage") from exc
    try:
        receipt = _receipt(chain, pending)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryError(
            f"Renewal not confirmed ({pending.tx_hash}). Retry to check the same transaction."
        ) from exc
    if receipt["status"] not in (0, 1):
        raise RegistryError(f"Unknown renewal receipt for {pending.tx_hash}; retry")
    path.unlink()
    if receipt["status"] == 0:
        raise RegistryError("Renewal reverted; refresh fee, duration and balance before retrying")
    return {"status": "ok", "confirmed": True, "tx_hash": pending.tx_hash}

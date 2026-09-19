#!/usr/bin/env python3
"""Read-only check of the $DEGA token decimals against the real Sepolia deploy.

Exercises the real `ChainRegistry.token_decimals()` (no signer needed for reads)
and compares it with a raw `degaToken()` + `decimals()` call, then formats the
registry fee with the on-chain precision.

Usage: uv run python tools/e2e_fee_decimals_real.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toad.extensions.dega_panel.chat_protocol import format_dega_amount  # noqa: E402
from toad.extensions.dega_panel.registry_client import ChainRegistry  # noqa: E402

RPC = os.environ.get("DEGA_CHAT_RPC", "https://ethereum-sepolia-rpc.publicnode.com")
REGISTRY = os.environ.get("DEGA_CHAT_REGISTRY", "0x5FF86634Af51a5016065e2572dF67eB5270e4Fbc")
# Read-only: the key is never used to sign anything in this script.
DUMMY_KEY = "0x" + "11" * 32

TOKEN_ABI = [
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}],
     "stateMutability": "view", "type": "function"},
]


def main() -> int:
    reg = ChainRegistry(rpc=RPC, registry=REGISTRY, private_key=DUMMY_KEY)

    onchain_decimals = reg.token_decimals()
    fee = reg.fee()
    if onchain_decimals is None:
        print("token decimals unreadable from the contract -> FAIL")
        return 1
    formatted = format_dega_amount(fee, decimals=onchain_decimals)

    token_addr = reg._contract.functions.degaToken().call()
    token = reg._w3.eth.contract(address=reg._w3.to_checksum_address(token_addr), abi=TOKEN_ABI)
    raw_decimals = int(token.functions.decimals().call())

    print(f"registry      : {REGISTRY}")
    print(f"degaToken     : {token_addr}")
    print(f"decimals raw  : {raw_decimals}")
    print(f"decimals code : {onchain_decimals}")
    print(f"fee (base)    : {fee}")
    print(f"fee formatted : {formatted} $DEGA")

    ok_cache = reg.token_decimals() == onchain_decimals
    ok_match = onchain_decimals == raw_decimals
    ok_fee = fee == 0 or formatted not in ("0", "")

    print()
    print(f"  [{'PASS' if ok_match else 'FAIL'}] code matches on-chain decimals()")
    print(f"  [{'PASS' if ok_cache else 'FAIL'}] value is cached (stable across calls)")
    print(f"  [{'PASS' if ok_fee else 'FAIL'}] fee formats to a non-zero value")
    print()
    if ok_match and ok_cache and ok_fee:
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())

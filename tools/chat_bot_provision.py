#!/usr/bin/env python3
"""Provision the DEGA chat BOT: an isolated wallet + on-chain node.

The bot is a SECOND chat identity (Pavel's wallet already owns `pedro.dega`,
and the registry enforces ONE node per wallet). This creates a dedicated
`~/.canon/bot/` config dir with:

- wallet.env            -> a fresh EVM private key (0600)
- identity.json         -> the persistent Nostr identity (derived from the key)
- env                   -> DEga_chat RPC/registry/token + bot username

Then it:
1. mints MockDEGA to the bot (public `mint`, so it's free)
2. funds gas ETH from the main wallet (only if the bot lacks it)
3. opens the bot's node on-chain (registers `username + nostr pubkey`)
4. prints the bot's resolved username + wallet + pubkey

Idempotent: re-running detects an existing wallet/node and skips re-creation.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

CANON = Path(os.path.expanduser("~/.canon"))
BOT_DIR = CANON / "bot"
BOT_WALLET = BOT_DIR / "wallet.env"
BOT_ENV = BOT_DIR / "env"
BOT_IDENTITY = BOT_DIR / "identity.json"

# Default bot handle (bare, no .dega). Change here or override via argv.
BOT_USERNAME = os.environ.get("DEGA_BOT_USERNAME", "bot")

from web3 import Web3

from toad.extensions.dega_panel.registry_client import (
    _read_chat_env_key,
    ChainRegistry,
    canonical_username,
    display_name,
    validate_username,
)

REGISTRY_ABI = [
    {"constant": True, "inputs": [], "name": "fee", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "ownerAddr", "type": "address"}], "name": "usernameOfOwner", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "username", "type": "string"}], "name": "usernameTaken", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
]
TOKEN_ABI = [
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "mint", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]


def _read_wallet(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("WALLET_PRIVATE_KEY="):
            return line.split("=", 1)[1].strip().removeprefix("0x")
    return None


def _write_wallet(path: Path, pk: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"WALLET_PRIVATE_KEY={pk}\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _write_bot_env(username: str) -> None:
    data = {
        "username": canonical_username(username),
        "rpc": _read_chat_env_key("DEGA_CHAT_RPC"),
        "registry": _read_chat_env_key("DEGA_CHAT_REGISTRY"),
        "token": _read_chat_env_key("DEGA_CHAT_TOKEN"),
    }
    BOT_ENV.parent.mkdir(parents=True, exist_ok=True)
    BOT_ENV.write_text(json.dumps(data, indent=2), encoding="utf-8")
    BOT_ENV.chmod(0o600)


async def main() -> int:
    username = validate_username(BOT_USERNAME)
    rpc = _read_chat_env_key("DEGA_CHAT_RPC")
    registry_addr = _read_chat_env_key("DEGA_CHAT_REGISTRY")
    token_addr = _read_chat_env_key("DEGA_CHAT_TOKEN")
    if not (rpc and registry_addr and token_addr):
        print("Missing DEGA_CHAT_* in ~/.canon/dega-chat.env", file=sys.stderr)
        return 2

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    reg = w3.eth.contract(address=Web3.to_checksum_address(registry_addr), abi=REGISTRY_ABI)
    tok = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=TOKEN_ABI)

    # 1) bot wallet (reuse if exists)
    pk = _read_wallet(BOT_WALLET)
    created_wallet = False
    if not pk:
        pk = "0x" + os.urandom(32).hex()
        _write_wallet(BOT_WALLET, pk)
        created_wallet = True
    bot_acct = w3.eth.account.from_key(pk)
    print(f"[bot] wallet {'CREATED' if created_wallet else 'reused'} = {bot_acct.address}")

    # is it already a node owner?
    owned = reg.functions.usernameOfOwner(bot_acct.address).call()
    if owned:
        print(f"[bot] already owns node '{owned}' — nothing to open")
        _write_bot_env(owned)
        print(f"RESULT username={owned}")
        print(f"RESULT wallet={bot_acct.address}")
        return 0

    # check username not taken
    if reg.functions.usernameTaken(canonical_username(username)).call():
        print(f"[bot] username '{username}.dega' already taken — pick DEGA_BOT_USERNAME", file=sys.stderr)
        return 2

    # 2) fund MockDEGA (mint is public & free)
    dec = tok.functions.decimals().call()
    bal = tok.functions.balanceOf(bot_acct.address).call()
    fee = reg.functions.fee().call()

    # 2) fund ETH gas from the main wallet if the bot can't afford gas
    gas_price = w3.eth.gas_price
    bot_eth = w3.eth.get_balance(bot_acct.address)
    gas_budget = int(gas_price * 1_000_000)  # ~1M gas headroom
    if bot_eth < gas_budget:
        main_pk = _read_wallet(CANON / "wallet.env")
        if not main_pk:
            print("[bot] no main wallet key to fund gas — fund the bot ETH manually", file=sys.stderr)
            return 2
        main = w3.eth.account.from_key(main_pk)
        val = gas_budget + int(0.0001 * 10**18)
        avail = w3.eth.get_balance(main.address)
        if avail < val:
            print(f"[bot] main wallet lacks ETH to fund (avail {avail / 1e18:.6f})", file=sys.stderr)
            return 2
        tx = {"to": bot_acct.address, "value": val, "gas": 21_000,
              "nonce": w3.eth.get_transaction_count(main.address),
              "chainId": w3.eth.chain_id,
              "gasPrice": gas_price}
        s = main.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(s.raw_transaction)
        w3.eth.wait_for_transaction_receipt(h, timeout=60)
        print(f"[bot] funded {val / 1e18:.4f} ETH gas from main wallet")
    else:
        print(f"[bot] has enough ETH for gas")

    # 3) fund MockDEGA (mint is public & free) once the bot can pay gas.
    # Use raw token units (the contract transfers `fee` raw units via
    # transferFrom); mint a generous fixed amount so the fee is always covered.
    if bal < fee:
        mint_amt = int(10**21)  # plenty of raw DEGA
        tx = tok.functions.mint(bot_acct.address, mint_amt).build_transaction(
            {"from": bot_acct.address, "nonce": w3.eth.get_transaction_count(bot_acct.address), "gas": 120_000}
        )
        signed = bot_acct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(h, timeout=60)
        print(f"[bot] minted {mint_amt} raw DEGA")
    else:
        print(f"[bot] already has DEGA balance")

    # 4) open the node on-chain (registers username + derived nostr pubkey)
    # The chain backend derives the Nostr identity from THIS wallet key.
    bot_identity_file = str(BOT_IDENTITY)
    chain = ChainRegistry(rpc=rpc, registry=registry_addr, private_key=pk)
    try:
        # derive nostr pubkey from the wallet key the same way the chat identity does
        os.environ["DEGA_CHAT_PK"] = pk
        from toad.extensions.dega_panel.chat_identity import load_or_create_identity
        keys, _ = load_or_create_identity(path=bot_identity_file, signer_key=pk)
        pub_hex = keys.public_key().to_hex()
        # persist bot env BEFORE open so the resident script knows the handle
        _write_bot_env(username)
        res = chain.open_node(
            username, nostr_pubkey=pub_hex, nostr_secret=keys.secret_key().to_hex()
        )
        print(f"[bot] opened node {display_name(username)} tx={res.get('tx_hash', '')[:16]}…")
    except Exception as exc:
        print(f"[bot] open_node failed: {exc}", file=sys.stderr)
        return 1

    _write_bot_env(username)
    print(f"RESULT username={username}")
    print(f"RESULT wallet={bot_acct.address}")
    print(f"RESULT pubkey={pub_hex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

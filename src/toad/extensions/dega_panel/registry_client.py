"""Client for the DegaChatRegistry smart contract, from the TUI.

The contract lives in `contracts/DegaChatRegistry.sol` and manages the
fee-gated chat nodes on-chain (+ $DEGA ERC-20 transfer for the fee). This
module is the Python side that the Textual ChatView talks to.

Backends:
- ``test`` (internal test backend): an in-memory faithful re-implementation
  of the contract's state machine, so the whole chat works offline and is
  unit-testable with zero chain/infra. Great for demos, CI and the transparent
  fee gate.
- ``canon-cli``: real on-chain path. Signing/sending uses the wallet that lives
  in **DEGA Core** (`canon-cli`), never stored here. Wired but not exercised
  until a chain endpoint is configured; `open_node` returns a "requires canon-cli"
  stub that the UI renders as pending.

Both backends honour the same invariant: a node opens only when the (configurable)
fee is paid, username is unique and <= 15 chars, and membership is capped.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from web3.types import Nonce, TxParams

from toad.extensions.dega_panel.auth_store import CANON_DIR
from toad.extensions.dega_panel.chat_protocol import DEGA_DECIMALS, format_dega_amount
from toad.extensions.dega_panel.registration import Registration, RenewalQuote
from toad.extensions.dega_panel.gating import chat_fee_weega, max_users_per_node

_DEGA_CHAT_ENV = CANON_DIR / "dega-chat.env"

log = logging.getLogger(__name__)

def _read_chat_env_key(name: str) -> str | None:
    if not _DEGA_CHAT_ENV.exists():
        return None
    try:
        for line in _DEGA_CHAT_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    except OSError:
        return None
    return None

# On-chain backend uses web3 (EVM). Imported lazily in ChainRegistry so the
# test/offline path keeps working even if web3 is missing.
try:  # pragma: no cover - import-time optional
    from web3 import Web3
    from web3.exceptions import ContractLogicError
except Exception:  # noqa: BLE001 - web3 optional unless "chain" backend used
    Web3 = None  # type: ignore[assignment,misc]  # Optional runtime import.
    ContractLogicError = Exception  # type: ignore[assignment,misc]

MAX_USERNAME = 15
VALID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


class RegistryError(Exception):
    """Raised on any registry violation (duplicate username, full node, fee)."""


@dataclass
class Node:
    username: str
    owner: str
    opened_at: int = 0
    expires_at: int = 0
    members: list[str] = field(default_factory=list)
    nostr_pubkey: bytes = b""


def canonical_username(name: str) -> str:
    """Normalize an input to a bare username (no the dialog's `.dega` TLD)."""
    name = name.strip().removesuffix(".dega").strip()
    return name


def validate_username(name: str) -> str:
    """Validate the public handle format `usuario.dega`.

    The UI can let people type `usuario` or `usuario.dega`, but the visible
    handle is always `usuario.dega` and the bare name must still satisfy the
    length/character rules.
    """
    canon = canonical_username(name)
    if not (1 <= len(canon) <= MAX_USERNAME):
        raise RegistryError(f"username must be 1–{MAX_USERNAME} chars")
    if not all(c in VALID_CHARS for c in canon):
        raise RegistryError("username: only letters, digits, '.', '_' and '-'")
    return canon


def display_name(canon: str) -> str:
    """Render the public `usuario.dega` handle."""
    return f"{canon}.dega"


class TestRegistry:
    """Offline, faithful model of DegaChatRegistry — no chain required.

    Mirrors the contract one-to-one so behaviour is identical (and testable)
    before any real deployment.
    """

    def __init__(self, *, fee_weega: int | None = None, max_users: int | None = None,
                 registration_ttl: int = 30 * 86400,
                 clock: Callable[[], float] = time.time) -> None:
        self.fee_weega = chat_fee_weega() if fee_weega is None else fee_weega
        self.max_users = max_users_per_node() if max_users is None else max_users
        self.set_registration_ttl(registration_ttl)
        self._clock = clock
        self._nodes: dict[str, Node] = {}
        self._owner: str = "registry:owner"
        self._owner_to_username: dict[str, str] = {}

    # --- reads (mirror contract view fns) -----------------------------------
    def fee(self) -> int:
        return self.fee_weega

    def max_users_per_node(self) -> int:
        return self.max_users

    def node_owner(self, username: str) -> str:
        node = self._nodes.get(canonical_username(username))
        return node.owner if node and self.is_active(username) else ""

    def is_member(self, username: str, who: str) -> bool:
        node = self._nodes.get(canonical_username(username))
        return bool(node and self.is_active(username) and who in node.members)

    def member_count(self, username: str) -> int:
        node = self._nodes.get(canonical_username(username))
        return len(node.members) if node and self.is_active(username) else 0

    def username_taken(self, username: str) -> bool:
        return canonical_username(username) in self._nodes

    def username_of_owner(self, owner: str) -> str:
        name = self._owner_to_username.get(owner, "")
        return name if self.is_active(name) else ""

    def set_registration_ttl(self, duration: int) -> None:
        if duration <= 0:
            raise RegistryError("Registration duration must be positive")
        self.registration_ttl = duration

    def is_active(self, username: str) -> bool:
        node = self._nodes.get(canonical_username(username))
        return bool(node and self._clock() < node.expires_at)

    def registration_of_owner(self, owner: str) -> Registration:
        name = self._owner_to_username.get(owner, "")
        node = self._nodes.get(name, Node("", ""))
        return Registration(name, node.owner, node.opened_at, node.expires_at,
                            len(node.members), self.is_active(name), int(self._clock()))

    def renew_node(self, quote: RenewalQuote, payer: str, *, pay: bool = True) -> None:
        node = self._nodes.get(quote.registration.username)
        if node is None or node.owner != payer:
            raise RegistryError("Only the registered wallet can renew")
        if node.expires_at != quote.registration.expires_at:
            raise RegistryError("Registration changed; refresh before renewing")
        if self.fee() > quote.fee or self.registration_ttl != quote.duration:
            raise RegistryError("Renewal terms changed; review them again")
        if self.fee() and not pay:
            raise RegistryError("Renewal fee required")
        node.expires_at = max(node.expires_at, int(self._clock())) + self.registration_ttl

    # --- writes (mirror contract txns) --------------------------------------
    def open_node(self, username: str, payer: str, *, pay: bool = True, nostr_pubkey: bytes | str = b"") -> Node:
        canon = validate_username(username)
        if payer in self._owner_to_username:
            raise RegistryError("owner already has node")
        if canon in self._nodes:
            raise RegistryError(f"username {display_name(canon)} is already taken")
        if self.fee_weega > 0 and not pay:
            raise RegistryError(
                f"fee of {format_dega_amount(self.fee_weega)} $DEGA is required to open this node"
            )
        if isinstance(nostr_pubkey, str):
            nostr_pubkey = bytes.fromhex(nostr_pubkey.removeprefix("0x"))
        if len(nostr_pubkey) not in (0, 32):
            raise RegistryError("nostr pubkey must be 32 bytes")
        if nostr_pubkey and any(n.nostr_pubkey == nostr_pubkey for n in self._nodes.values()):
            raise RegistryError("pubkey already registered")
        now = int(self._clock())
        node = Node(username=canon, owner=payer, opened_at=now,
                    expires_at=now + self.registration_ttl,
                    members=[payer], nostr_pubkey=nostr_pubkey)
        self._nodes[canon] = node
        self._owner_to_username[payer] = canon
        return node

    def invite(self, username: str, member: str) -> Node:
        canon = canonical_username(username)
        node = self._nodes.get(canon)
        if not node or not self.is_active(canon):
            raise RegistryError(f"node {display_name(canon)} is not open")
        if member in node.members:
            raise RegistryError("already a member")
        if len(node.members) + 1 > self.max_users:
            raise RegistryError(f"node is full (max {self.max_users})")
        node.members.append(member)
        return node

    def set_fee(self, fee_weega: int) -> None:
        self.fee_weega = max(0, int(fee_weega))

    def set_max_users(self, cap: int) -> None:
        self.max_users = max(1, int(cap))


_REGISTRY_ABI = [  # minimal IERC-ABI for DegaChatRegistry (view + write fns we use)
    {"constant": True, "inputs": [], "name": "fee", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [], "name": "degaToken", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [], "name": "maxUsersPerNode", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "username", "type": "string"}], "name": "nodeOwnerOf", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "ownerAddr", "type": "address"}], "name": "usernameOfOwner", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "username", "type": "string"}, {"name": "who", "type": "address"}], "name": "isMemberOf", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "username", "type": "string"}], "name": "memberCountOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "username", "type": "string"}, {"name": "index", "type": "uint256"}], "name": "members", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "name", "type": "string"}], "name": "resolveNostrPubkey", "outputs": [{"name": "", "type": "bytes"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "pubkey", "type": "bytes"}], "name": "usernameForPubkey", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"constant": True, "inputs": [{"name": "name", "type": "string"}], "name": "usernameTaken", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {
        "inputs": [
            {"name": "username", "type": "string"},
            {"name": "nostrPubkey", "type": "bytes"},
            {"name": "proof", "type": "bytes"},
        ],
        "name": "openNode", "outputs": [], "stateMutability": "nonpayable", "type": "function",
    },
    {"anonymous": False, "inputs": [
        {"indexed": True, "internalType": "string", "name": "username", "type": "string"},
        {"indexed": True, "internalType": "address", "name": "nodeOwner", "type": "address"},
        {"indexed": False, "internalType": "bytes", "name": "nostrPubkey", "type": "bytes"},
        {"indexed": False, "internalType": "uint256", "name": "feePaid", "type": "uint256"},
        {"indexed": False, "internalType": "uint256", "name": "at", "type": "uint256"},
        {"indexed": False, "name": "expiresAt", "type": "uint256"}],
     "name": "NodeOpened", "type": "event"},
    {"constant": False, "inputs": [{"name": "username", "type": "string"}, {"name": "member", "type": "address"}], "name": "invite", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"type": "function", "name": "registrationTTL", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "isActive", "stateMutability": "view",
     "inputs": [{"name": "name", "type": "string"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "registrationOfOwner", "stateMutability": "view",
     "inputs": [{"name": "wallet", "type": "address"}],
     "outputs": [
         {"name": "username", "type": "string"}, {"name": "nodeOwner", "type": "address"},
         {"name": "openedAt", "type": "uint256"}, {"name": "expiresAt", "type": "uint256"},
         {"name": "memberCount", "type": "uint256"}, {"name": "active", "type": "bool"},
         {"name": "checkedAt", "type": "uint256"}]},
    {"type": "function", "name": "renewNode", "stateMutability": "nonpayable",
     "inputs": [{"name": "username", "type": "string"},
                {"name": "expectedExpiresAt", "type": "uint256"},
                {"name": "maxFee", "type": "uint256"},
                {"name": "expectedTTL", "type": "uint256"}], "outputs": []},
]


class ChainRegistry:
    """Real on-chain backend for DegaChatRegistry via web3 (EVM).

    Talks to the production registry on Ethereum mainnet by default. RPC URL,
    contract address and signer come from env so keys are never hardcoded:

    - ``DEGA_CHAT_RPC`` — JSON-RPC endpoint (defaults to a public Ethereum mainnet RPC).
    - ``DEGA_CHAT_REGISTRY`` — the DegaChatRegistry address.
    - ``DEGA_CHAT_PK`` — the signer private key. Falls back to reading
      ``~/.canon/wallet.env`` (``WALLET_PRIVATE_KEY``, the DEGA Core burner).
    """

    def __init__(
        self,
        *,
        rpc: str | None = None,
        registry: str | None = None,
        private_key: str | None = None,
    ) -> None:
        if Web3 is None:
            raise RegistryError("web3 not installed; run `uv add web3` for the chain backend")
        self._rpc = (
            rpc or _read_chat_env_key("DEGA_CHAT_RPC")
            or os.environ.get("DEGA_CHAT_RPC") or _DEFAULT_MAINNET_RPC
        )
        self._registry = (
            registry or _read_chat_env_key("DEGA_CHAT_REGISTRY")
            or os.environ.get("DEGA_CHAT_REGISTRY") or _DEFAULT_MAINNET_REGISTRY
        )
        self._pk = private_key or _read_chat_env_key("DEGA_CHAT_PK") or os.environ.get("DEGA_CHAT_PK") or _read_wallet_env_key()
        self._token_decimals: int | None = None
        if not self._pk:
            raise RegistryError("chain backend needs a signer key (DEGA_CHAT_PK or ~/.canon/wallet.env)")
        self._w3 = Web3(Web3.HTTPProvider(self._rpc, request_kwargs={"timeout": 20}))
        if not self._w3.is_connected():
            raise RegistryError(f"cannot reach chain RPC {self._rpc}")
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(self._registry), abi=_REGISTRY_ABI
        )
        self._account = self._w3.eth.account.from_key(self._pk)
        self._sender = self._account.address

    # --- reads -------------------------------------------------------------
    def _view(self, fn, default):
        """Safe view read: a revert/error on a ``view`` means "absent", not a
        crash. The deployed registry can revert reads (e.g. ``usernameOfOwner``
        when the owner has no node) where the local source returns empty; treat
        any read failure as the safe default so a revert never kills the TUI."""
        try:
            return fn.call()
        except Exception:  # noqa: BLE001 - ContractLogicError, Web3RPCError, ...
            return default

    def fee(self) -> int:
        try:
            return int(self._contract.functions.fee().call())
        except Exception as exc:
            raise RegistryError("Cannot read registration fee; check RPC and retry") from exc

    def registration_of_owner(self, owner: str) -> Registration:
        """Read authoritative status including expired registrations.

        RPC errors are unknown status, never an absent registration.
        """
        try:
            raw = self._contract.functions.registrationOfOwner(
                Web3.to_checksum_address(owner)).call()
            return Registration(*raw)
        except Exception as exc:
            raise RegistryError(
                "Cannot check registration; check RPC and use the TTL registry address"
            ) from exc

    def renewal_quote(self) -> RenewalQuote:
        from toad.extensions.dega_panel.registration_renewal import _pending_path

        try:
            return RenewalQuote(self.registration_of_owner(self._sender), self.fee(),
                                int(self._contract.functions.registrationTTL().call()),
                                self.token_decimals(), pending=_pending_path(self).exists())
        except RegistryError:
            raise
        except Exception as exc:
            raise RegistryError("Cannot read renewal terms; check RPC and retry") from exc

    def renew_node(self, quote: RenewalQuote) -> dict:
        """Submit or recover one renewal without signing a second purchase."""
        from toad.extensions.dega_panel.registration_renewal import renew_on_chain

        return renew_on_chain(self, quote)

    def token_decimals(self) -> int | None:
        """Read the token precision, caching only successful RPC responses.

        A failed read leaves the scale unknown so the UI shows base units and
        the next refresh retries. Zero is a valid precision and is cached.
        """
        if self._token_decimals is not None:
            return self._token_decimals
        try:
            token_addr = self._view(self._contract.functions.degaToken, "")
            if not token_addr or int(token_addr, 16) == 0:
                return None
            token_abi = [
                {"constant": True, "inputs": [], "name": "decimals",
                 "outputs": [{"name": "", "type": "uint8"}],
                 "stateMutability": "view", "type": "function"},
            ]
            token = self._w3.eth.contract(
                address=Web3.to_checksum_address(token_addr), abi=token_abi
            )
            raw = self._view(token.functions.decimals, None)
            if raw is not None:
                self._token_decimals = int(raw)
        except Exception:  # noqa: BLE001 - RPC errors leave the scale unknown
            log.warning("could not read token decimals from %s; will retry", self._registry)
        return self._token_decimals

    def max_users_per_node(self) -> int:
        return int(self._view(self._contract.functions.maxUsersPerNode, 0))

    def node_owner(self, username: str) -> str:
        addr = self._view(self._contract.functions.nodeOwnerOf(canonical_username(username)), "")
        if not addr or int(addr, 16) == 0:
            return ""
        return Web3.to_checksum_address(addr)

    def username_of_owner(self, owner: str) -> str:
        """Return the username already owned by ``owner`` (or empty string)."""
        # The registry contract is the source of truth. Do not reconstruct this
        # from NodeOpened logs: public RPCs can omit/fail log ranges, and that
        # makes the UI think the wallet has no node even though openNode reverts
        # with "owner already has node".
        return str(self._view(
            self._contract.functions.usernameOfOwner(Web3.to_checksum_address(owner)),
            "",
        )).strip()

    def is_member(self, username: str, who: str) -> bool:
        return bool(self._view(
            self._contract.functions.isMemberOf(
                canonical_username(username), Web3.to_checksum_address(who)
            ),
            False,
        ))

    def member_count(self, username: str) -> int:
        return int(self._view(
            self._contract.functions.memberCountOf(canonical_username(username)), 0
        ))

    def member_addresses(self, username: str) -> list[str]:
        """List the member wallet addresses of a node (owner + invited)."""
        canon = canonical_username(username)
        count = int(self._view(self._contract.functions.memberCountOf(canon), 0))
        out: list[str] = []
        for i in range(min(count, 100)):
            addr = self._view(self._contract.functions.members(canon, i), "")
            if addr:
                out.append(Web3.to_checksum_address(addr))
        return out

    def username_taken(self, username: str) -> bool:
        return bool(self._view(
            self._contract.functions.usernameTaken(canonical_username(username)), False
        ))

    def resolve_pubkey(self, username: str) -> bytes:
        """Resolve ``name`` or ``name.dega`` to the stored Nostr public key."""
        raw = self._view(
            self._contract.functions.resolveNostrPubkey(canonical_username(username)), b""
        )
        return bytes(raw or b"")

    def username_for_pubkey(self, pubkey: bytes | str) -> str:
        """Reverse lookup: the bare username registered for a Nostr pubkey.

        Lets the chat label an inbound DM's sender by their on-chain name even
        when you have never invited/resolved them. Returns "" when the pubkey
        has no registration on this registry.
        """
        raw: bytes
        if isinstance(pubkey, str):
            raw = bytes.fromhex(pubkey.removeprefix("0x"))
        else:
            raw = pubkey
        if not raw:
            return ""
        return str(self._view(
            self._contract.functions.usernameForPubkey(raw), "",
        )).strip()

    def resolve_member(self, username: str) -> dict:
        """Resolve a user by name -> their Nostr pubkey AND wallet (node owner).

        Used by the \"invite by name\" UI: we need the pubkey to E2E them and the
        wallet address for the on-chain membership. Returns ``{}`` for a name
        that isn't registered.
        """
        canon = canonical_username(username)
        if not self._contract.functions.isActive(canon).call():
            return {}
        pub = self.resolve_pubkey(canon)
        owner = self._contract.functions.nodeOwnerOf(canon).call()
        return {"username": canon, "pubkey": pub, "wallet": owner}

    # --- writes (signed txns) ----------------------------------------------
    def open_node(
        self, username: str, nostr_pubkey: bytes | str | None = None,
        *, nostr_secret: str | None = None,
    ) -> dict:
        canon = validate_username(username)
        if self.username_taken(canon):
            raise RegistryError(f"username {display_name(canon)} is already taken")
        if isinstance(nostr_pubkey, str):
            root = nostr_pubkey[2:] if nostr_pubkey.startswith("0x") else nostr_pubkey
            nostr_pubkey = bytes.fromhex(root)
        elif nostr_pubkey is None:
            nostr_pubkey = b""
        from toad.extensions.dega_panel.registration_proof import registration_proof

        if not nostr_secret:
            raise RegistryError("The active local Nostr signing key is required for registration")
        try:
            proof = registration_proof(
                nostr_secret, nostr_pubkey, wallet=self._sender, username=canon,
                chain_id=self._w3.eth.chain_id, registry=self._registry,
            )
        except ValueError as exc:
            raise RegistryError(str(exc)) from exc
        # If the fee is >0, the contract burns the approved DEGA from the sender.
        # The client must approve the token first; otherwise openNode reverts.
        if self.fee() > 0:
            self._ensure_fee_approved()
        tx = self._contract.functions.openNode(canon, nostr_pubkey, proof).build_transaction(
            TxParams({"from": self._sender, "nonce": self._next_nonce(),
                      "gas": self._estimate_gas("openNode", [canon, nostr_pubkey, proof]),
                      **self._transaction_fees()})
        )
        return self._send(tx, {"action": "open_node", "username": display_name(canon)})

    def _estimate_gas(self, fn_name: str, args: list) -> int:
        """Estimate gas for a write fn, with headroom for the fee+reverse mapping.

        Fixed caps (300k) under-estimate openNode once it stores both the nostr
        pubkey AND the reverse pubkey->username mapping plus a transferFrom fee.
        estimate_gas returns the real cost; we bump it ~1.5x or floor 300k so a
        transient block variance never reverts the tx.
        """
        fn = getattr(self._contract.functions, fn_name)
        try:
            est = fn(*args).estimate_gas({"from": self._sender})
        except Exception:  # noqa: BLE001 - RPC estimate failure; fall back to a cap
            est = 300_000
        return max(int(est * 1.5), 300_000)

    def _ensure_fee_approved(self, fee: int | None = None) -> None:
        """Approve $DEGA for the registry fee if there is no allowance yet."""
        from toad.extensions.dega_panel.approval_transaction import (
            confirm_pending, submit_approval,
        )

        confirm_pending(self)
        token_addr = self._contract.functions.degaToken().call()
        token_abi = [
            {"inputs": [{"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"}],
             "name": "allowance", "outputs": [{"name": "", "type": "uint256"}],
             "stateMutability": "view", "type": "function"},
            {"constant": False, "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
             "name": "approve", "outputs": [{"name": "", "type": "bool"}],
             "stateMutability": "nonpayable", "type": "function"},
        ]
        token = self._w3.eth.contract(address=Web3.to_checksum_address(token_addr),
                                      abi=token_abi)
        fee = self.fee() if fee is None else fee
        if int(token.functions.allowance(self._sender, self._registry).call()) >= fee:
            return
        tx = token.functions.approve(self._registry, fee).build_transaction(
            TxParams({"from": self._sender, "nonce": self._next_nonce(), "gas": 100_000,
                      **self._transaction_fees()})
        )
        submit_approval(self, tx)
        if int(token.functions.allowance(self._sender, self._registry).call()) < fee:
            raise RegistryError(
                "Approval resolved without sufficient allowance. Retry approval before registering; "
                "no registration transaction was submitted."
            )

    def invite(self, username: str, member: str) -> dict:
        canon = canonical_username(username)
        tx = self._contract.functions.invite(
            canon, Web3.to_checksum_address(member)
        ).build_transaction(
            TxParams({"from": self._sender, "nonce": self._next_nonce(),
                      "gas": self._estimate_gas(
                          "invite", [canon, Web3.to_checksum_address(member)]),
                      **self._transaction_fees()})
        )
        return self._send(tx, {"action": "invite", "username": display_name(canon), "member": member})

    def _transaction_fees(self) -> dict[str, int]:
        """Give EIP-1559 transactions a positive tip and base-fee headroom."""
        block = self._w3.eth.get_block("latest")
        priority = max(int(self._w3.eth.max_priority_fee), 1_000_000_000)
        return {"maxPriorityFeePerGas": priority,
                "maxFeePerGas": 2 * int(block["baseFeePerGas"]) + priority}

    def _next_nonce(self) -> Nonce:
        return self._w3.eth.get_transaction_count(self._sender, "pending")

    def _send(self, tx: TxParams, meta: dict) -> dict:
        signed = self._account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.get("status") == 0:
            # La tx revertió en cadena: intentamos recuperar el motivo exacto con
            # un eth_call contra el estado previo al bloque de la tx.
            reason = self._revert_reason(tx, receipt.get("blockNumber"))
            action = meta.get("action", "tx")
            who = meta.get("username", "")
            tx_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
            self._append_tx_log(action, who, tx_hex, reason or "unknown revert reason")
            friendly = self._friendly_revert_message(reason) if reason else None
            if friendly:
                raise RegistryError(
                    f"transaction reverted on chain ({action} for {who}): {friendly}. "
                    f"See ~/.canon/execution/dega-chat.log for the full RPC/contract trace"
                )
            raise RegistryError(
                f"transaction reverted on chain ({action} for {who}): unknown revert reason"
            )
        return {
            "status": "ok",
            "tx_hash": Web3.to_hex(tx_hash),
            "confirmed": True,
            **meta,
        }

    def _append_tx_log(self, action: str, who: str, tx_hash: str, reason: str) -> None:
        log_dir = CANON_DIR / "execution"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "dega-chat.log"
            stamp = datetime.now().isoformat(timespec="seconds")
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} {action} {who} {tx_hash} {reason}\n")
        except OSError:
            pass

    def _revert_reason(self, tx: TxParams, block_number: int | None) -> str | None:
        block: str | int
        if block_number is None:
            block = "latest"
        else:
            block = max(int(block_number) - 1, 0)
        try:
            self._w3.eth.call(tx, block_identifier=block)
        except Exception as exc:  # noqa: BLE001 - web3 raises several exception types
            raw = exc.args[0] if getattr(exc, "args", None) else str(exc)
            if isinstance(raw, (tuple, list)) and raw:
                text = next((str(item).strip() for item in raw if str(item).strip()), "")
            else:
                text = str(raw).strip()
            if not text:
                return None
            prefixes = (
                "execution reverted: ",
                "execution reverted",
                "Transaction reverted: ",
                "Transaction reverted",
                "ContractLogicError: ",
            )
            for prefix in prefixes:
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
                    break
            return text or None
        return None

    def _friendly_revert_message(self, reason: str) -> str:
        low = reason.lower()
        if "insufficient balance" in low:
            return "your wallet does not have enough DEGA to pay the fee"
        if "fee transfer failed" in low or "allowance" in low or "not approved" in low:
            return "the registry does not have enough allowance to collect the fee"
        if "invalid username" in low:
            return "the username must be 1–15 characters and use only letters, numbers, dot, underscore, or hyphen"
        if "username taken" in low:
            return "that username is already taken"
        if "bad nostr pubkey" in low:
            return "the Nostr key is not in the expected format (32 bytes / 64 hex)"
        if "node full" in low:
            return "that node has reached its member limit"
        if "node not open" in low:
            return "that node does not exist yet"
        if "already member" in low:
            return "that wallet is already a member of the node"
        return reason


_DEFAULT_MAINNET_RPC = "https://ethereum-rpc.publicnode.com"
_DEFAULT_MAINNET_REGISTRY = "0x4c698AC2f25dD82386658080223583e0EEbB523f"


def _read_wallet_env_key() -> str | None:
    """Read WALLET_PRIVATE_KEY from ~/.canon/wallet.env (DEGA Core burner wallet)."""
    wallet = CANON_DIR / "wallet.env"
    if not wallet.exists():
        return None
    try:
        for line in wallet.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("WALLET_PRIVATE_KEY="):
                key = line.split("=", 1)[1].strip()
                return key.removeprefix("0x")
    except OSError:
        return None
    return None


def _ensure_owner_wallet() -> str:
    """Resolve the on-chain payer address from DEGA Core, or a dev placeholder.

    Real signing is owned by ``canon-cli`` in DEGA Core; this returns the wallet
    address when a wallet exists, else a throwaway address for the sim path.
    """
    wallet = CANON_DIR / "wallet.env"
    if wallet.exists():
        # WALLET_PRIVATE_KEY on disk; we only surface an address stub here.
        return "0xcanonwallet"
    return "0x00000000000000000000000000000000000000dEga1"


class RegistryClient:
    """High-level facade the ChatView uses. Backend-selected on construction.

    Backends:
    - ``test`` (default): in-memory TestRegistry — offline, testable.
    - ``chain``: real on-chain via ChainRegistry (web3 → Ethereum mainnet by default).
    - ``canon-cli``: reserved (DEGA Core signing); currently returns 'pending'.
    """

    def __init__(self, *, backend: str = "test", **kw) -> None:
        if backend not in ("test", "chain", "canon-cli"):
            raise RegistryError(f"unknown backend: {backend!r}")
        self._backend = backend
        self._sim = TestRegistry(**kw) if backend == "test" else None
        self._chain = ChainRegistry(**kw) if backend == "chain" else None

    def fee_weega(self) -> int:
        if self._chain:
            return self._chain.fee()
        return self._sim.fee() if self._sim else 0

    def _sender_address(self) -> str:
        if self._chain:
            return self._chain._sender
        return _ensure_owner_wallet()

    def fee_degas(self) -> str:
        """Human fee. Never guesses the token scale: if the contract's decimals
        could not be read, the amount is shown in base units instead."""
        fee = self.fee_weega()
        decimals = self.fee_decimals()
        if decimals is None:
            return f"{fee} weega"
        return format_dega_amount(fee, decimals=decimals)

    def fee_decimals(self) -> int | None:
        """Token decimals for the fee display.

        Read from the registry's token on the chain backend; ``None`` when the
        contract cannot be read (never a guessed scale). The local/test backend
        keeps the documented default.
        """
        if self._chain:
            return self._chain.token_decimals()
        return DEGA_DECIMALS

    def open_node(
        self, username: str, nostr_pubkey: bytes | str | None = None,
        *, nostr_secret: str | None = None,
    ) -> dict:
        canon = validate_username(username)
        owner = self._sender_address() if self._chain else _ensure_owner_wallet()
        if self.username_of_owner(owner):
            raise RegistryError("owner already has node")
        if self._chain:
            return self._chain.open_node(canon, nostr_pubkey=nostr_pubkey, nostr_secret=nostr_secret)
        if self._backend == "canon-cli":
            # Real path: canon-cli signs+submits. UI marks 'pending' until a hook
            # confirms the tx.
            return {"status": "pending", "username": display_name(canon)}
        payer = _ensure_owner_wallet()
        pub = nostr_pubkey or b""
        if isinstance(pub, str):
            root = pub[2:] if pub.startswith("0x") else pub
            pub = bytes.fromhex(root)
        assert self._sim is not None
        self._sim.open_node(canon, payer, nostr_pubkey=pub)
        return {"status": "opened", "username": display_name(canon), "owner": payer}

    def resolve_pubkey(self, username: str) -> bytes:
        """Resolve ``name`` / ``name.dega`` to its account's Nostr pubkey."""
        if self._chain:
            return self._chain.resolve_pubkey(username)
        if self._sim:
            node = self._sim._nodes.get(canonical_username(username), Node("", ""))
            return node.nostr_pubkey if self._sim.is_active(username) else b""
        return b""

    def username_for_pubkey(self, pubkey: bytes | str) -> str:
        """Reverse lookup: the registered bare username for a Nostr pubkey.

        Used to label inbound DMs from people we never invited (chain backend
        queries the registry; test backend mirrors the seeded registration).
        """
        if self._chain:
            return self._chain.username_for_pubkey(pubkey)
        if self._sim:
            raw: bytes
            if isinstance(pubkey, str):
                raw = bytes.fromhex(pubkey.removeprefix("0x"))
            else:
                raw = pubkey
            for n, node in self._sim._nodes.items():
                if node.nostr_pubkey == raw and self._sim.is_active(n):
                    return n
        return ""

    def username_taken(self, username: str) -> bool:
        """True if ``name``/``name.dega`` is already registered on-chain/in-sim."""
        if self._chain:
            return self._chain.username_taken(username)
        return self._sim.username_taken(username) if self._sim else False

    def username_of_owner(self, owner: str) -> str:
        """Return the single node username owned by ``owner`` if any."""
        if self._chain:
            return self._chain.username_of_owner(owner)
        if self._sim:
            return self._sim.username_of_owner(owner)
        return ""

    def node_owner(self, username: str) -> str:
        """Owner wallet of a node username (empty if not registered)."""
        if self._chain:
            return self._chain.node_owner(username)
        if self._sim:
            return self._sim.node_owner(username)
        return ""

    def member_addresses(self, username: str) -> list[str]:
        """List the member wallets of a node (owner + invited)."""
        if self._chain:
            return self._chain.member_addresses(username)
        if self._sim:
            node = self._sim._nodes.get(canonical_username(username))
            return list(node.members) if node and self._sim.is_active(username) else []
        return []

    def node_members(self, username: str) -> list[dict]:
        """Members of ``username``'s node as [{wallet}], ready for the contacts UI."""
        return [{"wallet": w} for w in self.member_addresses(username)]

    def resolve_member(self, username: str) -> dict:
        """Resolve ``name``/``name.dega`` to {username, pubkey, wallet} if registered."""
        if self._chain:
            return self._chain.resolve_member(username)
        if self._sim:
            node = self._sim._nodes.get(canonical_username(username))
            if not node or not self._sim.is_active(username):
                return {}
            return {"username": node.username, "pubkey": bytes(node.nostr_pubkey or b""),
                    "wallet": node.owner}
        return {}

    def invite(self, username: str, member: str) -> dict:
        canon = canonical_username(username)
        if self._chain:
            return self._chain.invite(canon, member)
        if self._backend == "canon-cli":
            return {"status": "pending", "username": display_name(canon)}
        assert self._sim is not None
        node = self._sim.invite(canon, member)
        return {"status": "invited", "username": display_name(canon), "members": len(node.members)}

    def is_member(self, username: str, who: str) -> bool:
        if self._chain:
            return self._chain.is_member(username, who)
        return self._sim.is_member(username, who) if self._sim else False

    def registration_status(self) -> Registration:
        """Return the signing wallet's registration, including expired nodes."""
        owner = self._sender_address()
        if self._chain:
            return self._chain.registration_of_owner(owner)
        if self._sim:
            return self._sim.registration_of_owner(owner)
        raise RegistryError("Registration status requires a chain or test backend")

    def renewal_quote(self) -> RenewalQuote:
        if self._chain:
            return self._chain.renewal_quote()
        if self._sim:
            return RenewalQuote(self.registration_status(), self._sim.fee(),
                                self._sim.registration_ttl, DEGA_DECIMALS)
        raise RegistryError("Renewal requires a chain or test backend")

    def renew_node(self, quote: RenewalQuote) -> dict:
        if self._chain:
            return self._chain.renew_node(quote)
        if self._sim:
            self._sim.renew_node(quote, self._sender_address())
            return {"status": "ok", "confirmed": True}
        raise RegistryError("Renewal requires a chain or test backend")

    def state_snapshot(self) -> dict:
        """For the UI header: fee, cap, and the node I own (if any)."""
        if self._chain:
            sender = self._chain._sender
            owned = self._chain.username_of_owner(sender)
            return {
                "backend": self._backend,
                "registry": self._chain._registry,
                "sender": sender,
                "fee_weega": self._chain.fee(),
                "fee_decimals": self._chain.token_decimals(),
                "max_users": self._chain.max_users_per_node(),
                "my_nodes": [owned] if owned else [],
            }
        if not self._sim:
            return {"backend": self._backend}
        owner = _ensure_owner_wallet()
        mine = [n for n in self._sim._nodes.values() if n.owner == owner]
        return {
            "backend": self._backend,
            "fee_weega": self._sim.fee(),
            "fee_decimals": DEGA_DECIMALS,
            "max_users": self._sim.max_users,
            "my_nodes": [n.username for n in mine],
        }


def load_persisted_nodes(path: Path | None = None) -> TestRegistry:
    """Hydrate a TestRegistry from a JSON file (idempotent local cache)."""
    p = path or CANON_DIR / "chat-registry.json"
    reg = TestRegistry()
    if not p.exists():
        return reg
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return reg
    reg.set_registration_ttl(int(data["registration_ttl"]))
    reg.set_fee(int(data.get("fee_weega", 0)))
    reg.set_max_users(int(data.get("max_users", 10)))
    for raw in data.get("nodes", []):
        canon = canonical_username(raw["username"])
        node = reg._nodes.setdefault(
            canon,
            Node(username=canon, owner=raw["owner"],
                 opened_at=raw["opened_at"], expires_at=raw["expires_at"],
                 nostr_pubkey=bytes.fromhex(raw["nostr_pubkey"]), members=list(raw["members"])),
        )
        reg._owner_to_username[node.owner] = canon
    return reg


def persist_nodes(reg: TestRegistry, path: Path | None = None) -> Path:
    p = path or CANON_DIR / "chat-registry.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "registration_ttl": reg.registration_ttl,
        "fee_weega": reg.fee(),
        "max_users": reg.max_users,
        "nodes": [
            {"username": n.username, "owner": n.owner, "members": n.members,
             "opened_at": n.opened_at, "expires_at": n.expires_at,
             "nostr_pubkey": n.nostr_pubkey.hex()}
            for n in reg._nodes.values()
        ],
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p
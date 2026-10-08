"""Read-only, chain-scoped discovery of Nostr contact bindings."""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
import json
import logging
import os
from typing import Protocol

from toad.extensions.dega_panel.registry_client import (
    RegistryError, Web3, _DEFAULT_MAINNET_REGISTRY, _DEFAULT_MAINNET_RPC,
    _REGISTRY_ABI, _read_chat_env_key, validate_username,
)

from toad.extensions.dega_panel.registry_types import ResolvedMember
from toad.extensions.dega_panel.cardano_config import load_cardano_config
from toad.extensions.dega_panel import auth_store


log = logging.getLogger(__name__)
DISCOVERY_TIMEOUT_SECONDS = 25.0


class DiscoveryProvider(Protocol):
    network: str
    registry: str

    def resolve_member(self, username: str) -> ResolvedMember | None: ...


@dataclass(frozen=True)
class ContactBinding:
    chain: str
    network: str
    registry: str
    username: str
    owner: str
    nostr_pubkey: bytes

    @property
    def contact_id(self) -> str:
        return json.dumps([self.chain, self.network, self.registry, self.username],
                          separators=(",", ":"))

    @property
    def badge(self) -> str:
        return f"{self.chain.capitalize()} · {self.network}"


@dataclass(frozen=True)
class DiscoveryResult:
    matches: tuple[ContactBinding, ...]
    failures: tuple[str, ...]


class EthereumDiscovery:
    """Read Ethereum registrations without opening or loading a signing wallet."""

    def __init__(self) -> None:
        rpc = (_read_chat_env_key("DEGA_CHAT_RPC") or os.environ.get("DEGA_CHAT_RPC")
               or _DEFAULT_MAINNET_RPC)
        self.registry = (_read_chat_env_key("DEGA_CHAT_REGISTRY")
                         or os.environ.get("DEGA_CHAT_REGISTRY") or _DEFAULT_MAINNET_REGISTRY)
        if Web3 is None:
            raise RegistryError("Ethereum discovery requires web3")
        self._web3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
        self.network = str(self._web3.eth.chain_id)
        self.registry = Web3.to_checksum_address(self.registry)
        self._contract = self._web3.eth.contract(address=self.registry, abi=_REGISTRY_ABI)

    def resolve_member(self, username: str) -> ResolvedMember | None:
        """Read all binding fields strictly; RPC failures never mean absence."""
        functions = self._contract.functions
        if not functions.isActive(username).call():
            return None
        return {"username": username, "wallet": functions.nodeOwnerOf(username).call(),
                "pubkey": bytes(functions.resolveNostrPubkey(username).call())}


def discover_contacts(
    username: str, *,
    providers: Sequence[tuple[str, Callable[[], DiscoveryProvider]]] | None = None,
) -> DiscoveryResult:
    """Search every configured registry, retaining incomplete-search failures.

    Args:
        username: Bare name or public .dega handle.
        providers: Optional chain/provider factories for isolated callers and tests.
    """
    canon = validate_username(username)
    if providers is None:
        configured: list[tuple[str, Callable[[], DiscoveryProvider]]] = [
            ("ethereum", EthereumDiscovery),
        ]
        config = load_cardano_config()
        configured_cardano = (
            os.environ.get("CANON_CARDANO_DEPLOYMENT")
            or config.registration_backend == "cardano"
            or config.deployment != auth_store.CANON_DIR / "cardano/deployment.json"
            or config.deployment.is_file()
        )
        if configured_cardano:
            from toad.extensions.dega_panel.cardano_registry import CardanoRegistry

            configured.append(("cardano", CardanoRegistry))
        providers = configured
    matches: list[ContactBinding] = []
    failures: list[str] = []
    executor = ThreadPoolExecutor(max_workers=max(1, len(providers)))
    pending = [(chain, executor.submit(_resolve_contact, canon, chain, factory))
               for chain, factory in providers]
    try:
        done, _ = wait([future for _, future in pending], timeout=DISCOVERY_TIMEOUT_SECONDS)
        for chain, future in pending:
            if future not in done:
                failures.append(f"{chain.capitalize()} lookup timed out; retry discovery")
                continue
            try:
                binding = future.result()
                if binding is not None:
                    matches.append(binding)
            except Exception:
                log.warning("registry_discovery_failed", extra={"chain": chain})
                failures.append(
                    f"{chain.capitalize()} lookup unavailable or invalid; retry discovery"
                )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return DiscoveryResult(tuple(matches), tuple(failures))


def _resolve_contact(
    canon: str, chain: str, factory: Callable[[], DiscoveryProvider],
) -> ContactBinding | None:
    provider = factory()
    member = provider.resolve_member(canon)
    if member is None or not member:
        return None
    pubkey = member["pubkey"]
    if not isinstance(pubkey, bytes) or len(pubkey) != 32:
        raise RegistryError("Registration has no valid 32-byte Nostr key")
    return ContactBinding(chain, provider.network, provider.registry,
                          canon, member["wallet"], pubkey)

"""Bounded JSON subprocess bridge to the Cardano registry companion."""

from __future__ import annotations

import json
import time
from threading import Lock
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from toad.extensions.dega_panel.registration import Registration, RenewalQuote
from toad.extensions.dega_panel.cardano_config import CardanoConfig, load_cardano_config
from toad.extensions.dega_panel.cardano_runtime import (
    CardanoOperationError, CardanoWallet, ExpiredRegistrationTerms, call_cardano,
    ensure_cardano_wallet, resolve_cardano_cli,
)
from toad.extensions.dega_panel.registry_types import ResolvedMember
from toad.extensions.dega_panel.registry_client import RegistryError, validate_username


def _decimal(value: Any) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("expected nonnegative decimal string")
    return int(value)


def _validate_terms(operation: str, result: dict[str, Any]) -> None:
    _decimal(result["feeAmount"])
    if _decimal(result["ttlMs"]) <= 0 or not isinstance(result["stateRef"], str):
        raise ValueError("invalid terms")
    if operation == "status":
        if not 1 <= int(result["maxUsers"]) <= 10:
            raise ValueError("invalid membership cap")
    else:
        CardanoRecord.parse(result["record"])
        _decimal(result["checkedAtMs"])


def _validate_result(operation: str, result: dict[str, Any]) -> None:
    """Reject malformed successful responses before facade code consumes them."""
    if operation == "pending.status":
        if result["pending"] is not None and not isinstance(result["pending"], dict):
            raise ValueError("invalid pending transaction")
    elif operation == "wallet.status":
        if len(bytes.fromhex(result["owner"])) != 28:
            raise ValueError("invalid owner")
    elif operation in ("status", "quote"):
        _validate_terms(operation, result)
    elif operation in ("register", "renew", "invite", "retry"):
        if (
            result["status"] not in ("submitted", "confirmed")
            or len(bytes.fromhex(result["txHash"])) != 32
        ):
            raise ValueError("invalid transaction result")


@dataclass(frozen=True)
class CardanoRecord:
    name: str
    owner: str
    nostr_key: bytes
    opened_ms: int
    expires_ms: int
    members: tuple[str, ...]

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> CardanoRecord:
        """Parse a companion record at the process boundary."""
        try:
            name = validate_username(raw["name"])
            owner = raw["owner"]
            key = bytes.fromhex(raw["nostrKey"])
            opened, expires = int(raw["openedMs"]), int(raw["expiresMs"])
            members = tuple(raw["members"])
            hashes = (owner, *members)
            valid_hashes = all(isinstance(v, str) and len(bytes.fromhex(v)) == 28 for v in hashes)
            if not valid_hashes or len(key) != 32 or opened < 0 or expires <= opened:
                raise ValueError("invalid record fields")
            if not members or members[0] != owner or len(set(members)) != len(members):
                raise ValueError("invalid membership")
            return cls(name, owner, key, opened, expires, members)
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryError("Cardano companion returned a malformed registration") from exc

    def registration(self, checked_ms: int) -> Registration:
        return Registration(
            self.name,
            self.owner,
            self.opened_ms // 1000,
            self.expires_ms // 1000,
            len(self.members),
            checked_ms < self.expires_ms,
            checked_ms // 1000,
            self.expires_ms,
            checked_ms,
        )


class CardanoRegistry:
    """Read public state without a wallet; use a local signer only for mutations."""

    def __init__(
        self,
        *,
        deployment: str | None = None,
        cli: str | None = None,
        wallet_path: str | None = None,
    ) -> None:
        config = load_cardano_config()
        self.deployment = deployment or str(config.deployment)
        self.wallet_path = wallet_path or str(config.wallet_path)
        if not Path(self.deployment).is_file():
            raise RegistryError(
                "Cardano registry not deployed or configured. Your wallet can still receive funds."
            )
        try:
            manifest = json.loads(Path(self.deployment).read_text())
            self.network = manifest["network"]
            self.registry = manifest["policyId"]
            if (
                self.network not in ("Preview", "Mainnet")
                or len(bytes.fromhex(self.registry)) != 28
            ):
                raise ValueError("invalid deployment")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise RegistryError(
                "Invalid Cardano deployment manifest; expected Preview or Mainnet"
            ) from exc
        if deployment is None and self.network != config.network:
            raise RegistryError("Cardano deployment network does not match wallet configuration")
        if deployment and self.network != config.network and not wallet_path:
            from toad.extensions.dega_panel import auth_store

            self.wallet_path = str(auth_store.CANON_DIR / "cardano/wallets" / self.network.lower())
        self.cli = resolve_cardano_cli(cli)
        self._wallet_descriptor: CardanoWallet | None = None
        self._status_cache: dict[str, Any] | None = None
        self._status_read_at = 0.0
        self._status_generation = 0
        self._status_lock = Lock()
        self._quotes: dict[int, tuple[RenewalQuote, dict[str, Any]]] = {}

    def _call(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {
            "operation": operation,
            "deployment": self.deployment,
            "network": self.network,
            **({"walletPath": self.wallet_path} if operation in (
                "wallet.status", "pending.status", "register", "renew", "invite", "retry",
            ) else {}),
            "payload": payload or {},
        }
        result = call_cardano(self.cli, request)
        try:
            _validate_result(operation, result)
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryError("Cardano companion returned an invalid response") from exc
        return result

    def _lookup(self, operation: str, payload: dict[str, Any]) -> tuple[CardanoRecord | None, int]:
        raw = self._call(operation, payload)
        try:
            checked = int(raw["checkedAtMs"])
            record = raw["record"]
            if checked < 0 or (record is not None and not isinstance(record, dict)):
                raise ValueError("invalid lookup")
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryError("Cardano companion returned an invalid lookup") from exc
        return (CardanoRecord.parse(record) if record is not None else None), checked

    def _record(self, name: str, *, include_expired: bool = False) -> CardanoRecord | None:
        record, checked = self._lookup(
            "resolve",
            {
                "name": validate_username(name),
                "includeExpired": include_expired,
            },
        )
        return record if record and (include_expired or checked < record.expires_ms) else None

    def resolve_member(self, name: str) -> ResolvedMember | None:
        record = self._record(name)
        if record is None:
            return None
        return {"username": record.name, "pubkey": record.nostr_key, "wallet": record.owner}

    def reverse_lookup(self, pubkey: bytes | str) -> str | None:
        key = pubkey.hex() if isinstance(pubkey, bytes) else pubkey.removeprefix("0x")
        record, checked = self._lookup("reverse", {"nostrKey": key})
        return record.name if record and checked < record.expires_ms else None

    def resolve_pubkey(self, name: str) -> bytes:
        record = self._record(name)
        return record.nostr_key if record else b""

    def username_for_pubkey(self, pubkey: bytes | str) -> str:
        return self.reverse_lookup(pubkey) or ""

    def username_taken(self, name: str) -> bool:
        return self._record(name, include_expired=True) is not None

    def node_owner(self, name: str) -> str:
        record = self._record(name)
        return record.owner if record else ""

    def member_addresses(self, name: str) -> list[str]:
        record = self._record(name)
        return list(record.members) if record else []

    def is_member(self, name: str, member: str) -> bool:
        return member in self.member_addresses(name)

    def registration_of_owner(self, owner: str) -> Registration:
        record, checked = self._lookup("owner", {"owner": owner})
        return (
            record.registration(checked)
            if record
            else Registration("", "", 0, 0, 0, False, checked // 1000)
        )

    def username_of_owner(self, owner: str) -> str:
        registration = self.registration_of_owner(owner)
        return registration.username if registration.active else ""

    @property
    def _sender(self) -> str:
        return self.wallet().owner

    def wallet(self) -> CardanoWallet:
        """Read or initialize this network's persistent wallet once, without a provider."""
        if self._wallet_descriptor is None:
            config = CardanoConfig(self.network, Path(self.wallet_path), Path(self.deployment))
            self._wallet_descriptor = ensure_cardano_wallet(
                config=config, cli=self.cli, persist=False)
        return self._wallet_descriptor

    def _status(self, *, fresh: bool = False) -> dict[str, Any]:
        with self._status_lock:
            return self._read_status(fresh=fresh)

    def _read_status(self, *, fresh: bool) -> dict[str, Any]:
        if (not fresh and self._status_cache is not None
                and time.monotonic() - self._status_read_at < 180):
            return self._status_cache
        generation = self._status_generation
        result = self._call("status", {"owner": self._sender})
        try:
            record = result["record"]
            checked = _decimal(result["checkedAtMs"])
            if record is not None:
                parsed = CardanoRecord.parse(record)
                if parsed.owner != self._sender:
                    raise ValueError("status belongs to another wallet")
                registration = parsed.registration(checked)
            else:
                registration = Registration("", "", 0, 0, 0, False, checked // 1000)
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryError("Cardano companion returned an invalid owner status") from exc
        if generation != self._status_generation:
            raise RegistryError("Cardano state changed during lookup; refresh registration")
        self._status_read_at = time.monotonic()
        self._status_cache = {**result, "registration": registration,
                              "read_at": self._status_read_at}
        return self._status_cache

    def registration_status(self) -> Registration:
        """Reuse the passive authenticated snapshot; expiry remains checked against time in UI."""
        status = self._status()
        registration = status["registration"]
        checked_ms = int(status["checkedAtMs"]) + int(
            (time.monotonic() - status["read_at"]) * 1000)
        expires_ms = registration.expires_at_ms or 0
        return replace(registration, checked_at=checked_ms // 1000, checked_at_ms=checked_ms,
                       active=registration.active and checked_ms < expires_ms)

    def state_snapshot(self) -> dict[str, Any]:
        """Aggregate wallet registration and terms in one rate-limited public state read."""
        status = self._status()
        wallet = self.wallet()
        registration = self.registration_status()
        return {"backend": "cardano", "registry": self.registry, "network": self.network,
                "sender": wallet.owner, "funding_address": wallet.address,
                "fee_weega": int(status["feeAmount"]), "fee_decimals": 8,
                "max_users": int(status["maxUsers"]),
                "my_nodes": [registration.username] if registration.active else []}

    @property
    def _registry(self) -> str:
        return self.registry

    def fee(self) -> int:
        return int(self._call("status")["feeAmount"])

    def token_decimals(self) -> int:
        return 8

    def max_users_per_node(self) -> int:
        return int(self._call("status")["maxUsers"])

    def _pending_for(self, operation: str, name: str, nostr_key: str | None = None) -> bool:
        pending = self._call("pending.status").get("pending")
        if pending is None:
            return False
        if not isinstance(pending, dict) or pending.get("policyId") != self.registry:
            raise RegistryError("Pending transaction belongs to another Cardano registry")
        if pending.get("operation") != operation or pending.get("name") != name:
            raise RegistryError(
                "Use the Cardano companion retry command to resolve the pending operation"
            )
        if nostr_key is not None and pending.get("nostrKey") != nostr_key:
            raise RegistryError("Pending registration uses another Nostr identity")
        return True

    def renewal_quote(self) -> RenewalQuote:
        registration = self.registration_of_owner(self._sender)
        if self._pending_for("renew", registration.username):
            quote = RenewalQuote(registration, 0, 0, 8, pending=True)
            self._quotes = {id(quote): (quote, {})}
            return quote
        raw = self._call("quote", {"name": registration.username})
        record = CardanoRecord.parse(raw["record"])
        if record.owner != registration.owner or record.name != registration.username:
            raise RegistryError("Cardano renewal quote belongs to another registration")
        registration = record.registration(int(raw["checkedAtMs"]))
        quote = RenewalQuote(registration, int(raw["feeAmount"]), int(raw["ttlMs"]) // 1000, 8)
        self._quotes = {id(quote): (quote, raw)}
        return quote

    def _confirmed(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Wait for inclusion without treating successful submission as a failure."""
        self._status_generation += 1
        self._status_cache = None
        try:
            result = self._call(operation, payload)
            result = self._wait_for_confirmation(result)
        finally:
            self._status_generation += 1
            self._status_cache = None
        confirmed = result["status"] == "confirmed"
        return {"status": "ok" if confirmed else "pending", "confirmed": confirmed,
                "tx_hash": result["txHash"]}

    def _wait_for_confirmation(self, result: dict[str, Any]) -> dict[str, Any]:
        """Reconcile the saved transaction for up to eight spaced observations."""
        tx_hash = result["txHash"]
        for _ in range(8):
            if result["status"] == "confirmed":
                return result
            time.sleep(15)
            try:
                observed = self._call("retry", {})
            except CardanoOperationError as exc:
                if exc.code not in {
                    "PROVIDER_UNAVAILABLE", "PROVIDER_RATE_LIMIT", "STALE_CHAIN_TIP",
                    "SUBMISSION_FAILED", "TRANSACTION_TIMING",
                }:
                    raise
                continue
            if observed["txHash"] != tx_hash:
                raise RegistryError("Cardano confirmation returned a different transaction")
            result = observed
        return result

    def renew_node(self, quote: RenewalQuote) -> dict[str, Any]:
        saved = self._quotes.get(id(quote))
        if saved is None or saved[0] is not quote:
            raise RegistryError("Refresh Cardano renewal terms before paying")
        if quote.pending:
            if not self._pending_for("renew", quote.registration.username):
                raise RegistryError("Pending renewal changed; refresh registration status")
            return self._confirmed("retry", {})
        raw = saved[1]
        return self._confirmed(
            "renew",
            {
                "name": quote.registration.username,
                "stateRef": raw["stateRef"],
                "maxFee": str(quote.fee),
                "expectedTtlMs": raw["ttlMs"],
                "expectedExpiryMs": raw["record"]["expiresMs"],
            },
        )

    def _registration_terms(
        self, original: ExpiredRegistrationTerms | None,
    ) -> dict[str, str]:
        terms = self._call("status")
        if original is None:
            return {"stateRef": terms["stateRef"], "maxFee": terms["feeAmount"],
                    "expectedTtlMs": terms["ttlMs"]}
        if (int(terms["feeAmount"]) > int(original["maxFee"])
                or int(terms["ttlMs"]) != int(original["expectedTtlMs"])):
            raise CardanoOperationError(
                "TERMS_CHANGED", "Registration terms changed; review the fee and duration again"
            )
        return {"stateRef": terms["stateRef"], **original}

    def open_node(
        self,
        username: str,
        *,
        nostr_pubkey: bytes | str | None = None,
        nostr_secret: str | None = None,
    ) -> dict[str, Any]:
        from nostr_sdk import Keys  # type: ignore[import-untyped]  # SDK has no typing metadata.

        if not nostr_secret:
            raise RegistryError("Cardano registration requires the current Nostr identity proof")
        key = nostr_pubkey.hex() if isinstance(nostr_pubkey, bytes) else nostr_pubkey
        try:
            derived_key = Keys.parse(nostr_secret).public_key().to_hex()
        except Exception as exc:
            raise RegistryError("Invalid local Nostr signing identity") from exc
        if key is not None and key != derived_key:
            raise RegistryError("Nostr public key does not match the signing identity")
        key = derived_key
        original_terms: ExpiredRegistrationTerms | None = None
        if self._pending_for("register", validate_username(username), key):
            try:
                return self._confirmed("retry", {})
            except CardanoOperationError as exc:
                if exc.code != "PENDING_EXPIRED":
                    raise
                if exc.details is None:
                    raise RegistryError(
                        "Expired registration terms unavailable; review registration before retrying"
                    ) from exc
                original_terms = exc.details
        terms = self._registration_terms(original_terms)
        return self._confirmed(
            "register",
            {
                "name": validate_username(username),
                **terms,
                "nostrSecret": nostr_secret,
                "nostrKey": key,
            },
        )

    def invite(self, name: str, member: str) -> dict[str, Any]:
        terms = self._call("status")
        return self._confirmed(
            "invite",
            {"name": validate_username(name), "member": member, "stateRef": terms["stateRef"]},
        )

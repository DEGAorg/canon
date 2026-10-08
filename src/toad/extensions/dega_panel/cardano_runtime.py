"""Locate the installed companion and obtain only its public wallet descriptor."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, TypedDict

from toad.extensions.dega_panel import auth_store
from toad.extensions.dega_panel.cardano_config import (
    CardanoConfig, load_cardano_config, persist_default_config,
)
from toad.extensions.dega_panel.registry_client import RegistryError


class ExpiredRegistrationTerms(TypedDict):
    maxFee: str
    expectedTtlMs: str


def _expiry_terms(raw: Any) -> ExpiredRegistrationTerms | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("invalid expired registration terms")
    fee, ttl = raw["maxFee"], raw["expectedTtlMs"]
    if not all(isinstance(value, str) and value.isascii() and value.isdecimal()
               for value in (fee, ttl)) or int(ttl) <= 0:
        raise ValueError("invalid expired registration terms")
    return {"maxFee": fee, "expectedTtlMs": ttl}


class CardanoOperationError(RegistryError):
    """A structured companion failure whose code controls safe recovery behavior."""

    def __init__(
        self, code: str, message: str, *, details: ExpiredRegistrationTerms | None = None,
    ) -> None:
        self.code = code
        self.details = details
        super().__init__(f"Cardano {code}: {message}")


@dataclass(frozen=True)
class CardanoWallet:
    network: str
    address: str
    owner: str


def resolve_cardano_cli(override: str | None = None) -> str:
    """Locate a built companion without installing dependencies or using the working directory."""
    explicit = override or os.environ.get("CANON_CARDANO_CLI")
    candidates = ([Path(explicit).expanduser()] if explicit else [
        auth_store.CANON_DIR / "cardano/runtime/dist/cli.js",
        Path(__file__).resolve().parents[4] / "cardano/client/dist/cli.js",
    ])
    for candidate in candidates:
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
    raise RegistryError(
        "Cardano runtime unavailable. Install it with python -m toad.cardano_install, then retry."
    )


def call_cardano(cli: str, request: dict[str, Any], *, timeout: int = 120) -> dict[str, Any]:
    """Run a bounded local companion request and parse its structured envelope."""
    try:
        process = subprocess.run(["node", cli], input=json.dumps(request), text=True,
                                 capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RegistryError("Cardano operation timed out; retry the saved transaction") from exc
    except OSError as exc:
        raise RegistryError(
            "Cannot start Cardano companion; check Node and CLI installation"
        ) from exc
    try:
        response = json.loads(process.stdout)
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise ValueError("invalid envelope")
        if not response["ok"]:
            error = response["error"]
            code, message = error["code"], error["message"]
            if not isinstance(code, str) or not code or not isinstance(message, str):
                raise ValueError("invalid operation error")
            details = _expiry_terms(error.get("details")) if code == "PENDING_EXPIRED" else None
            raise CardanoOperationError(code, message, details=details)
        if process.returncode or not isinstance(response.get("result"), dict):
            raise ValueError("invalid result")
        return response["result"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RegistryError("Cardano companion returned an invalid response") from exc


def ensure_cardano_wallet(
    *, config: CardanoConfig | None = None, cli: str | None = None, persist: bool = True,
) -> CardanoWallet:
    """Ensure the persistent wallet offline through TypeScript, returning only public data."""
    settings = config or load_cardano_config()
    runtime = resolve_cardano_cli(cli)
    if persist:
        persist_default_config(settings)
    result = call_cardano(runtime, {
        "operation": "wallet.ensure", "network": settings.network,
        "walletPath": str(settings.wallet_path), "payload": {},
    }, timeout=30)
    try:
        network, address, owner = result["network"], result["address"], result["owner"]
        prefix = "addr1" if settings.network == "Mainnet" else "addr_test1"
        if (network != settings.network or not isinstance(address, str)
                or not address.startswith(prefix) or len(bytes.fromhex(owner)) != 28):
            raise ValueError("invalid public wallet")
        return CardanoWallet(network, address, owner)
    except (KeyError, ValueError, TypeError) as exc:
        raise RegistryError("Cardano companion returned an invalid public wallet") from exc

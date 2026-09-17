"""Persistent Nostr identity + chat alias for the DEGA/Canon chat.

The chat's E2E identity is a Nostr keypair. `ChatNode` can generate a fresh
one, but that would change the user's pubkey every session — breaking the
on-chain binding `usuario.dega <-> pubkey` that `resolveNostrPubkey` relies on
(others look up your name to get the pubkey they DM you with). So we persist
the generated nsec to `~/.canon/chat-identity.json` (mode 0600) and reuse it.
The same file also remembers the user's chat alias (`username`) so reopening
the panel can resume the node idempotently. The store holds a private key, so
it is chmod-0600 and never leaves the machine. Textual-free, unit-testable.

Layout: ``{"secret_key_nsec": "nsec1...", "username": "carlos"}``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from eth_account import Account

from toad.extensions.dega_panel.auth_store import CANON_DIR
from toad.extensions.dega_panel.registry_client import _read_chat_env_key, canonical_username

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from nostr_sdk import Keys  # type: ignore[import-untyped]  # SDK ships no typing metadata.

IDENTITY_FILE = CANON_DIR / "chat-identity.json"


def _identity_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("DEGA_CHAT_IDENTITY_FILE")
    return Path(env) if env else IDENTITY_FILE


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError, TypeError):
        return {}


def _read_nsec(path: Path) -> str | None:
    nsec = _load(path).get("secret_key_nsec")
    return nsec if isinstance(nsec, str) and nsec else None


def resolve_identity_secret_key(
    *,
    path: str | Path | None = None,
    signer_key: str | None = None,
) -> str | None:
    """Resolve the chat identity secret key using the documented precedence.

    Precedence:
    1. explicit signer_key argument
    2. ~/.canon/dega-chat.env (DEGA_CHAT_PK) — same file/precedence the registry uses
    3. DEGA_CHAT_PK process env
    4. ~/.canon/wallet.env WALLET_PRIVATE_KEY
    5. persisted ~/.canon/chat-identity.json secret_key_nsec
    """
    p = _identity_path(path)
    if signer_key:
        return signer_key
    # The registry reads DEGA_CHAT_PK from ~/.canon/dega-chat.env first; the chat
    # identity must resolve the SAME key or the wallet <-> pubkey binding breaks.
    file_key = _read_chat_env_key("DEGA_CHAT_PK")
    if file_key:
        return file_key
    env_key = os.environ.get("DEGA_CHAT_PK")
    if env_key:
        return env_key
    wallet_key = _wallet_env_key()
    if wallet_key:
        return wallet_key
    cached = _load(p).get("secret_key_nsec")
    return cached if isinstance(cached, str) and cached else None


def configured_wallet_address() -> str | None:
    """Read the configured signing address without contacting the blockchain.

    Returns:
        The public wallet address, or None if no signing key is configured.

    Raises:
        ValueError: The configured signing key is invalid.
    """
    key = _read_chat_env_key("DEGA_CHAT_PK") or os.environ.get("DEGA_CHAT_PK") or _wallet_env_key()
    if not key:
        return None
    try:
        return Account.from_key(key).address
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid chat wallet key; check your local wallet configuration") from exc


def load_or_create_identity(
    *, path: str | Path | None = None, keys: "type[Keys] | None" = None,
    signer_key: str | None = None
) -> "tuple[Keys, bool]":
    """Return a (Keys, created) pair for the user's stable Nostr identity.

    The identity is **deterministically derived from the on-chain signer key**
    (the same secp256k1 private key that pays the fee / is the node owner), so
    `wallet <-> nostr pubkey <-> nombre.dega` are one key — the contract stores
    the pubkey of the wallet that owns the node. If ``signer_key`` (or env
    ``DEGA_CHAT_PK`` / ``~/.canon/wallet.env``) is present it is used directly;
    otherwise a fresh keypair is generated and persisted (atomic, 0600).
    """
    if keys is None:
        from nostr_sdk import Keys as NostrKeys

        keys = NostrKeys
    p = _identity_path(path)
    sk = resolve_identity_secret_key(path=p, signer_key=signer_key)
    if sk:
        sk = sk[2:] if sk.startswith("0x") else sk
        try:
            return keys.parse(sk), False  # type: ignore[return-value]
        except Exception:  # noqa: BLE001 - bad key -> fall through to persisted
            pass
    # 2) Reuse a persisted identity if present.
    data = _load(p)
    cached = data.get("secret_key_nsec")
    if isinstance(cached, str) and cached:
        try:
            return keys.parse(cached), False  # type: ignore[return-value]
        except Exception:  # noqa: BLE001 - corrupt/foreign key -> regenerate
            pass
    # 3) Fresh keypair, persisted so it stays stable across sessions.
    fresh = keys.generate()  # type: ignore[attr-defined]
    nsec = fresh.secret_key().to_bech32()
    data["secret_key_nsec"] = nsec
    _write(p, data)
    return fresh, True  # type: ignore[return-value]


def _wallet_env_key() -> str | None:
    """Read WALLET_PRIVATE_KEY from ~/.canon/wallet.env (DEGA Core burner wallet)."""
    wallet = CANON_DIR / "wallet.env"
    if not wallet.exists():
        return None
    try:
        for line in wallet.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("WALLET_PRIVATE_KEY="):
                return line.split("=", 1)[1].strip().removeprefix("0x")
    except OSError:
        return None
    return None


def load_username(*, path: str | Path | None = None) -> str | None:
    """Return the persisted chat alias (bare name, no .dega), if any."""
    u = _load(_identity_path(path)).get("username")
    return u if isinstance(u, str) and u else None


def save_username(username: str, *, path: str | Path | None = None) -> None:
    """Persist the user's chat alias so reopening can resume the node."""
    p = _identity_path(path)
    data = _load(p)
    data["username"] = canonical_username(username)
    _write(p, data)


def clear_identity(*, path: str | Path | None = None) -> None:
    """Remove the stored identity (logout / refresh)."""
    p = _identity_path(path)
    if p.exists():
        p.unlink()


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)

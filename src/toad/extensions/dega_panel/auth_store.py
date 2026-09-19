"""Local, offline credential store for the DEGA panel.

Canon is offline-first: the only network moment is the device-flow login. After
that, the session token and the elements snapshot live on disk so the panel works
disconnected. This module is deliberately free of Textual so it is unit-testable.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

CANON_DIR = Path.home() / ".canon"
AUTH_FILE = CANON_DIR / "auth.json"
ELEMENTS_FILE = CANON_DIR / "elements.json"

# Directory mode is 0700, files 0600: holds a session token.
_DIR_MODE = 0o700
_FILE_MODE = 0o600


@dataclass
class Session:
    """What /device/token returns plus the email we can re-derive."""

    session_token: str
    user_id: str
    email: str
    display_name: str = ""


@dataclass
class AuthState:
    """The panel's auth snapshot, persisted and reloaded across runs."""

    session: Session | None = None
    elements: dict[str, int] = field(default_factory=dict)
    total_elements: int = 0
    addresses: list[str] = field(default_factory=list)
    elements_error: str | None = None

    @property
    def is_logged_in(self) -> bool:
        return self.session is not None

    def to_dict(self) -> dict:
        return {
            "session": asdict(self.session) if self.session else None,
            "elements": self.elements,
            "total_elements": self.total_elements,
            "addresses": self.addresses,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuthState":
        s = data.get("session")
        session = None
        if s:
            session = Session(
                session_token=s.get("session_token", ""),
                user_id=s.get("user_id", ""),
                email=s.get("email", ""),
                display_name=s.get("display_name", ""),
            )
        return cls(
            session=session,
            elements=data.get("elements", {}) or {},
            total_elements=data.get("total_elements", 0) or 0,
            addresses=data.get("addresses", []) or [],
        )


CHAT_ENV_TEMPLATE = """\
# DEGA Canon configuration (created on first run — edit then keep).
# This file overrides the in-code defaults, so a fresh install has a single
# plug-and-play point to point the panel at your chain + backend.
#
# ---------------------------------------------------------------------------
# DEGA Encore backend (login / device flow / strategy delivery)
# ---------------------------------------------------------------------------
# Base URL of the agents backend. In-code default is local dev
# (http://127.0.0.1:4000); point this at the deployed environment so login and
# the protected strategy archive work:
#   prod  https://ai-agents-api.degaplatform.com
#   local http://127.0.0.1:4000
DEGA_API_URL=https://ai-agents-api.degaplatform.com
#
# ---------------------------------------------------------------------------
# Chat registry (open node, pay fee, invite members)
# ---------------------------------------------------------------------------
# Chain backend: 'chain' = real on-chain (EVM). 'test'/'simulated' = offline demo.
DEGA_CHAT_BACKEND=chain
#
# Ethereum mainnet JSON-RPC endpoint (chain ID 1).
DEGA_CHAT_RPC=https://ethereum-rpc.publicnode.com
#
# Production DegaChatRegistry: renewable registrations, one node per address.
DEGA_CHAT_REGISTRY=0x4c698AC2f25dD82386658080223583e0EEbB523f
#
# Token and registration terms are read from the registry, not configured here.
# Deployment terms: 6,719,270 DEGA, 365 days, 10 members per node.
#
# Signer private key. One key = one address = one chat node (the contract
# enforces one node per address). Leave your OWN key here, never a shared one.
# Falls back to ~/.canon/wallet.env (WALLET_PRIVATE_KEY).
DEGA_CHAT_PK=
"""


def chat_env_path() -> Path:
    """Path to the panel's config file (~/.canon/dega-chat.env)."""
    return CANON_DIR / "dega-chat.env"


def read_dega_env(name: str) -> str | None:
    """Read a key from ~/.canon/dega-chat.env (first match wins, skips comments)."""
    p = chat_env_path()
    if not p.exists():
        return None
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    except OSError:
        return None
    return None


def _ensure_dir() -> None:
    CANON_DIR.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    try:
        os.chmod(CANON_DIR, _DIR_MODE)
    except OSError:
        pass
    # Seed production defaults on first run; preserve existing user configuration.
    env_path = CANON_DIR / "dega-chat.env"
    if not env_path.exists():
        env_path.write_text(CHAT_ENV_TEMPLATE, encoding="utf-8")
        try:
            os.chmod(env_path, _FILE_MODE)
        except OSError:
            pass


def save_auth(state: AuthState) -> None:
    """Persist the full auth snapshot to ~/.canon/auth.json."""
    _ensure_dir()
    tmp = AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    os.chmod(tmp, _FILE_MODE)
    tmp.replace(AUTH_FILE)


def load_auth() -> AuthState:
    """Read the snapshot back. Returns a fresh empty state if absent/corrupt."""
    if not AUTH_FILE.exists():
        return AuthState()
    try:
        return AuthState.from_dict(json.loads(AUTH_FILE.read_text(encoding="utf-8")))
    except (ValueError, OSError, TypeError, KeyError):
        return AuthState()


def clear_auth() -> None:
    """Remove the session (logout). Elements snapshot is kept."""
    if AUTH_FILE.exists():
        AUTH_FILE.unlink()


def save_elements(elements: dict[str, int], total: int, addresses: list[str]) -> None:
    """Keep the elements snapshot separately for offline catalogue gating."""
    _ensure_dir()
    tmp = ELEMENTS_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"elements": elements, "total_elements": total, "addresses": addresses},
            indent=2,
        ),
        encoding="utf-8",
    )
    os.chmod(tmp, _FILE_MODE)
    tmp.replace(ELEMENTS_FILE)

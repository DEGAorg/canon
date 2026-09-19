"""Persistent chat contacts + my nodes for the DEGA/Canon TUI.

The on-chain registry stores members as wallet addresses. To show a usable
contact list and let one user open multiple nodes, this module keeps a local
directory keyed by wallet -> {username, pubkey} (learned when we invite/resolve
someone) plus the list of node aliases this user has opened. Textual-free,
unit-testable. File mode 0600 (no secrets beyond what's on-chain, but keep it
tight).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from toad.extensions.dega_panel.auth_store import CANON_DIR, _ensure_dir

CONTACTS_FILE = CANON_DIR / "chat-contacts.json"


def _path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("DEGA_CHAT_CONTACTS_FILE")
    return Path(env) if env else CONTACTS_FILE


def _load(path: Path) -> dict:
    if not path.exists():
        return {"contacts": {}, "my_nodes": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        data.setdefault("contacts", {})
        data.setdefault("my_nodes", [])
        return data
    except (ValueError, OSError, TypeError):
        return {"contacts": {}, "my_nodes": []}


def _write(path: Path, data: dict) -> None:
    _ensure_dir()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def remember_contact(wallet: str, *, username: str = "", pubkey: bytes = b"",
                     path: str | Path | None = None) -> dict:
    """Learn a contact from a resolved/invited member."""
    data = _load(_path(path))
    key = wallet.lower()
    existing = data["contacts"].get(key, {})
    if username:
        existing["username"] = username
    if pubkey:
        existing["pubkey"] = bytes(pubkey).hex()
    data["contacts"][key] = existing
    _write(_path(path), data)
    return data["contacts"][key]


def contacts(path: str | Path | None = None) -> list[dict]:
    """List known contacts as [{wallet, username, pubkey_hex}] (stable order)."""
    data = _load(_path(path))
    out = []
    for wallet, meta in data["contacts"].items():
        out.append({"wallet": wallet, "username": meta.get("username", ""),
                    "pubkey": meta.get("pubkey", "")})
    return out


def add_my_node(username: str, *, path: str | Path | None = None) -> list[str]:
    """Register the single node alias this user has opened."""
    p = _path(path)
    data = _load(p)
    canon = username.split(".")[0]
    data["my_nodes"] = [canon]
    data["active_node"] = canon
    _write(p, data)
    return [canon]


def my_nodes(path: str | Path | None = None) -> list[str]:
    """The node aliases this user has opened."""
    return list(_load(_path(path)).get("my_nodes", []) or [])


def set_active_node(username: str, *, path: str | Path | None = None) -> None:
    """Remember the currently active node alias (idempotent)."""
    p = _path(path)
    data = _load(p)
    data["active_node"] = username.split(".")[0]
    _write(p, data)


def active_node(path: str | Path | None = None) -> str | None:
    return _load(_path(path)).get("active_node") or None


def clear_contacts(*, path: str | Path | None = None) -> None:
    """Clear the local contact directory while keeping node history intact."""
    p = _path(path)
    data = _load(p)
    data["contacts"] = {}
    _write(p, data)

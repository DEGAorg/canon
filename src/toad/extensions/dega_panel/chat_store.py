"""Local, persistent inbox store for the P2P chat.

The client decision is that Nostr DMs live in the relay (unlimited history) and
are not synced across devices. For the offline/sim path (and as a local cache)
we also keep a small on-disk inbox so a chat session isn't lost on app restart.
This module is deliberately Textual-free so it is unit-testable.

Contents are stored as ciphertext only (NIP-44 E2E already happened at the
transport layer); this store never sees or persists plaintext. The layout is
keyed by the *owner* pubkey so different identities never interleave, and each
message is deduplicated by its event id / a fingerprint to survive redundant
fetches and relay replays.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from toad.extensions.dega_panel.auth_store import CANON_DIR, _ensure_dir

DEFAULT_INBOX_FILE = CANON_DIR / "chat-inbox.json"


def _inbox_path(path: str | Path | None) -> Path:
    """Resolve the store path, honouring an env override (for tests)."""
    if path is not None:
        return Path(path)
    env = os.environ.get("DEGA_CHAT_INBOX_FILE")
    return Path(env) if env else DEFAULT_INBOX_FILE


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def load_inbox(owner_pubkey: str, path: str | Path | None = None) -> list[dict]:
    """Return the persisted DMs addressed to ``owner_pubkey``.

    Each item: ``{"id": fingerprint, "from": sender_hex, "cipher": str,
    "time": str}``. ``id`` is the dedup key.
    """
    data = _load(_inbox_path(path))
    return list(data.get(owner_pubkey, []) or [])


def append_messages(
    owner_pubkey: str,
    messages: list[dict],
    *,
    path: str | Path | None = None,
) -> Path:
    """Persist ``messages`` for an owner, deduping by the ``id`` field.

    Ignores messages without an ``id``. Writes atomically (tmp + replace), 0600.
    """
    if not messages:
        return _inbox_path(path)
    p = _inbox_path(path)
    _ensure_dir()
    data = _load(p)
    seen = {m["id"] for m in data.get(owner_pubkey, [])}
    bucket = data.setdefault(owner_pubkey, [])
    added = 0
    for m in messages:
        mid = m.get("id")
        if not mid or mid in seen:
            continue
        bucket.append(
            {
                "id": mid,
                "from": m.get("from", ""),
                "cipher": m.get("cipher", ""),
                "time": m.get("time", ""),
            }
        )
        seen.add(mid)
        added += 1
    if not added:
        return p
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)
    return p


def clear_inbox(owner_pubkey: str, *, path: str | Path | None = None) -> Path:
    """Remove an owner's stored DMs (e.g. logout). Returns the store path."""
    p = _inbox_path(path)
    if not p.exists():
        return p
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return p
    data.pop(owner_pubkey, None)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)
    return p
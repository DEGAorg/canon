from __future__ import annotations

import json

from toad.extensions.dega_panel import chat_identity, registry_client
from toad.extensions.dega_panel.chat_identity import resolve_identity_secret_key


def _isolate(monkeypatch, tmp_path, *, chat_env_key: str | None = None):
    """Point CANON_DIR/dega-chat.env at temp files so the real ones are not read."""
    canon_dir = tmp_path / ".canon"
    canon_dir.mkdir()
    monkeypatch.setattr(chat_identity, "CANON_DIR", canon_dir)
    if chat_env_key is not None:
        chat_env = canon_dir / "dega-chat.env"
        chat_env.write_text(f"DEGA_CHAT_PK={chat_env_key}\n", encoding="utf-8")
    monkeypatch.setattr(registry_client, "_DEGA_CHAT_ENV", canon_dir / "dega-chat.env")
    return canon_dir


def test_resolve_identity_prefers_explicit_signer_key(tmp_path, monkeypatch) -> None:
    canon_dir = _isolate(monkeypatch, tmp_path, chat_env_key="file-key")
    (canon_dir / "chat-identity.json").write_text(json.dumps({"secret_key_nsec": "cached"}), encoding="utf-8")
    monkeypatch.setenv("DEGA_CHAT_PK", "env-key")
    assert resolve_identity_secret_key(path=canon_dir / "chat-identity.json", signer_key="explicit") == "explicit"


def test_resolve_identity_reads_dega_chat_env(tmp_path, monkeypatch) -> None:
    """The registry reads DEGA_CHAT_PK from dega-chat.env; chat identity must match."""
    canon_dir = _isolate(monkeypatch, tmp_path, chat_env_key="file-key")
    (canon_dir / "wallet.env").write_text("WALLET_PRIVATE_KEY=wallet-key\n", encoding="utf-8")
    monkeypatch.setenv("DEGA_CHAT_PK", "env-key")
    assert resolve_identity_secret_key(path=canon_dir / "chat-identity.json") == "file-key"


def test_resolve_identity_prefers_env_over_wallet_and_cache(tmp_path, monkeypatch) -> None:
    canon_dir = _isolate(monkeypatch, tmp_path)
    (canon_dir / "wallet.env").write_text("WALLET_PRIVATE_KEY=wallet-key\n", encoding="utf-8")
    (canon_dir / "chat-identity.json").write_text(json.dumps({"secret_key_nsec": "cached"}), encoding="utf-8")
    monkeypatch.setenv("DEGA_CHAT_PK", "env-key")
    assert resolve_identity_secret_key(path=canon_dir / "chat-identity.json") == "env-key"


def test_resolve_identity_uses_wallet_before_cached_identity(tmp_path, monkeypatch) -> None:
    canon_dir = _isolate(monkeypatch, tmp_path)
    (canon_dir / "wallet.env").write_text("WALLET_PRIVATE_KEY=wallet-key\n", encoding="utf-8")
    (canon_dir / "chat-identity.json").write_text(json.dumps({"secret_key_nsec": "cached"}), encoding="utf-8")
    monkeypatch.delenv("DEGA_CHAT_PK", raising=False)
    assert resolve_identity_secret_key(path=canon_dir / "chat-identity.json") == "wallet-key"


def test_resolve_identity_falls_back_to_cached_identity(tmp_path, monkeypatch) -> None:
    canon_dir = _isolate(monkeypatch, tmp_path)
    (canon_dir / "chat-identity.json").write_text(json.dumps({"secret_key_nsec": "cached"}), encoding="utf-8")
    monkeypatch.delenv("DEGA_CHAT_PK", raising=False)
    assert resolve_identity_secret_key(path=canon_dir / "chat-identity.json") == "cached"


def test_wallet_key_keeps_leading_zeros(tmp_path, monkeypatch) -> None:
    """A hex key starting with 0 must not be truncated (lstrip('0x') bug)."""
    canon_dir = _isolate(monkeypatch, tmp_path)
    key = "0" + "a" * 63
    assert len(key) == 64
    (canon_dir / "wallet.env").write_text(f"WALLET_PRIVATE_KEY=0x{key}\n", encoding="utf-8")
    monkeypatch.delenv("DEGA_CHAT_PK", raising=False)
    resolved = resolve_identity_secret_key(path=canon_dir / "chat-identity.json")
    assert resolved == key, f"expected the full 64-char key, got {len(resolved or '')} chars"


def test_dega_chat_env_key_keeps_leading_zeros(tmp_path, monkeypatch) -> None:
    canon_dir = _isolate(monkeypatch, tmp_path, chat_env_key="0" + "b" * 63)
    monkeypatch.delenv("DEGA_CHAT_PK", raising=False)
    assert resolve_identity_secret_key(path=canon_dir / "chat-identity.json") == "0" + "b" * 63

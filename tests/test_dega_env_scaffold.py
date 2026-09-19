"""The panel autogenerates ~/.canon/dega-chat.env on first run.

Verifies the seeded template carries the backend URL and the current registry
(defaults a fresh install points at the deployed backend/prod and Ethereum mainnet),
that it is idempotent (never overwrites an existing file), and that the resolver
reads keys back from it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from toad.extensions.dega_panel import auth_store


@pytest.fixture
def canon_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    return tmp_path


def test_seeds_env_template_on_first_run(canon_dir: Path) -> None:
    auth_store._ensure_dir()
    env = canon_dir / "dega-chat.env"
    text = env.read_text(encoding="utf-8")
    assert "DEGA_API_URL=https://ai-agents-api.degaplatform.com" in text
    assert "DEGA_CHAT_REGISTRY=0x4c698AC2f25dD82386658080223583e0EEbB523f" in text
    assert "DEGA_CHAT_RPC=https://ethereum-rpc.publicnode.com" in text
    assert auth_store.read_dega_env("DEGA_CHAT_PK") == ""
    assert auth_store.read_dega_env("DEGA_CHAT_TOKEN") is None
    assert env.stat().st_mode & 0o777 == 0o600
    # env resolution reads the seeded value
    assert auth_store.read_dega_env("DEGA_API_URL") == "https://ai-agents-api.degaplatform.com"


def test_does_not_overwrite_existing_env(canon_dir: Path) -> None:
    env = canon_dir / "dega-chat.env"
    env.write_text("DEGA_CHAT_REGISTRY=0xabc\n", encoding="utf-8")
    auth_store._ensure_dir()
    assert env.read_text(encoding="utf-8") == "DEGA_CHAT_REGISTRY=0xabc\n"


def test_read_dega_env_skips_comments_and_blanks(canon_dir: Path) -> None:
    env = canon_dir / "dega-chat.env"
    env.write_text(
        "# a comment\n\nDEGA_API_URL=https://prod.example\nDEGA_CHAT_BACKEND=chain\n",
        encoding="utf-8",
    )
    assert auth_store.read_dega_env("DEGA_API_URL") == "https://prod.example"
    assert auth_store.read_dega_env("DEGA_CHAT_BACKEND") == "chain"
    assert auth_store.read_dega_env("DEGA_CHAT_PK") is None


def test_read_dega_env_missing_file_returns_none(canon_dir: Path) -> None:
    assert auth_store.read_dega_env("DEGA_API_URL") is None

@pytest.mark.parametrize("configuration", ["defaults", "generated", "environment", "file", "explicit"])
def test_chain_connection_configuration(
    canon_dir: Path, monkeypatch: pytest.MonkeyPatch, configuration: str,
) -> None:
    """Select the expected chain without network access or a real signer."""
    from unittest.mock import MagicMock

    from toad.extensions.dega_panel import registry_client

    monkeypatch.setattr(registry_client, "_DEGA_CHAT_ENV", canon_dir / "dega-chat.env")
    monkeypatch.setattr(registry_client, "_read_wallet_env_key", lambda: None)
    for key in ("DEGA_CHAT_RPC", "DEGA_CHAT_REGISTRY", "DEGA_CHAT_PK"):
        monkeypatch.delenv(key, raising=False)
    web3 = MagicMock()
    web3.to_checksum_address.side_effect = lambda address: address
    monkeypatch.setattr(registry_client, "Web3", web3)
    expected_rpc = "https://ethereum-rpc.publicnode.com"
    expected_registry = "0x4c698AC2f25dD82386658080223583e0EEbB523f"
    options = {"private_key": "mock-signer-never-used"}
    if configuration == "generated":
        auth_store._ensure_dir()
    if configuration in {"environment", "file", "explicit"}:
        expected_rpc, expected_registry = "https://env.example", "environment-registry"
        monkeypatch.setenv("DEGA_CHAT_RPC", expected_rpc)
        monkeypatch.setenv("DEGA_CHAT_REGISTRY", expected_registry)
    if configuration in {"file", "explicit"}:
        expected_rpc, expected_registry = "https://file.example", "file-registry"
        (canon_dir / "dega-chat.env").write_text(
            f"DEGA_CHAT_RPC={expected_rpc}\nDEGA_CHAT_REGISTRY={expected_registry}\n",
            encoding="utf-8",
        )
    if configuration == "explicit":
        expected_rpc, expected_registry = "https://explicit.example", "explicit-registry"
        options.update(rpc=expected_rpc, registry=expected_registry)
    registry_client.ChainRegistry(**options)
    web3.HTTPProvider.assert_called_once_with(expected_rpc, request_kwargs={"timeout": 20})
    web3.return_value.eth.contract.assert_called_once_with(
        address=expected_registry, abi=registry_client._REGISTRY_ABI,
    )
    web3.return_value.eth.send_raw_transaction.assert_not_called()

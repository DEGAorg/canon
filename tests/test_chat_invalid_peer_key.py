"""Regression: sending to a peer whose pubkey is not a valid curve point.

Observed in the field: a node registered with a placeholder/dummy pubkey
(e.g. 000102…1f = bytes(range(32))) resolves fine, but NIP-44 encryption
fails at the secp256k1 lift with NostrSdkError('malformed public key').
The TUI must surface a clear error (NostrError) instead of letting the
worker crash with a raw NostrSdkError.
"""
from __future__ import annotations

import asyncio

import pytest

from toad.extensions.dega_panel.chat_protocol import (
    NostrError,
    make_node,
    parse_public_key,
)

# The exact placeholder that broke the field send.
DUMMY = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"


def test_parse_public_key_rejects_empty() -> None:
    with pytest.raises(NostrError, match="missing public key"):
        parse_public_key("")


def test_parse_public_key_rejects_garbage() -> None:
    with pytest.raises(NostrError, match="invalid public key"):
        parse_public_key("not-hex-at-all")


def test_send_to_placeholder_pubkey_raises_nostr_error() -> None:
    """The dummy key parses as 32-byte hex but is not a valid curve point."""

    async def _run() -> None:
        me = make_node(offline=True)
        with pytest.raises(NostrError, match="invalid peer key"):
            await me.send_encrypted(DUMMY, "hola")

    asyncio.run(_run())
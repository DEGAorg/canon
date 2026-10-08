"""Public member resolution contract shared by registry implementations."""

from typing import TypedDict


class ResolvedMember(TypedDict):
    """An active registry identity with an owner and its Nostr messaging key."""

    username: str
    wallet: str
    pubkey: bytes

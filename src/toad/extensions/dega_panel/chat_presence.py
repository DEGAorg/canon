"""Opt-in, expiring public Nostr presence for registered Canon chat identities."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from collections.abc import Callable

from nostr_sdk import (  # type: ignore[import-untyped]  # SDK has no typing metadata.
    Client, Event, EventBuilder, Filter, Kind, PublicKey, ReqTarget, SingleLetterTag, Tag, Timestamp,
)

from toad.extensions.dega_panel.auth_store import CANON_DIR
from toad.extensions.dega_panel.chat_protocol import ChatNode

logger = logging.getLogger(__name__)
PRESENCE_FILE = CANON_DIR / "chat-presence.json"
KIND = 30315
STATUS_TYPE = "canon-presence"
LIFETIME = 90
HEARTBEAT_INTERVAL = 30
POLL_INTERVAL = 15
MAX_CLOCK_SKEW = 15


def _preferences(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items() if isinstance(value, bool)}
    except (OSError, ValueError) as exc:
        logger.warning("Cannot read presence preferences", extra={"error_type": type(exc).__name__})
        return {}


def sharing_enabled(pubkey: str, path: Path | None = None) -> bool:
    """Return the explicit sharing preference for this identity; default off."""
    return _preferences(path or PRESENCE_FILE).get(pubkey, False)


def save_sharing(pubkey: str, enabled: bool, path: Path | None = None) -> None:
    """Persist the identity's opt-in without storing any private keys."""
    target = path or PRESENCE_FILE
    data = _preferences(target)
    data[pubkey] = enabled
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(".tmp")
    with open(temporary, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        os.chmod(temporary, 0o600)
        json.dump(data, output)
    temporary.replace(target)


def online_until(events: list[Event], authors: set[str], now: int) -> dict[str, int]:
    """Validate signed presence events and return their bounded expiration times."""
    online: dict[str, int] = {}
    for event in events:
        author = event.author().to_hex()
        if author not in authors or event.kind().as_u16() != KIND or not event.verify():
            continue
        expires = _expiration(event, now)
        if expires is not None:
            online[author] = max(online.get(author, 0), expires)
    return online


def _single_tag(event: Event, name: str) -> str | None:
    vectors = (tag.to_vec() for tag in event.tags())
    tags = [tag for tag in vectors if tag and tag[0] == name]
    return tags[0][1] if len(tags) == 1 and len(tags[0]) == 2 else None


def _expiration(event: Event, now: int) -> int | None:
    if _single_tag(event, "d") != STATUS_TYPE or event.content() != "online":
        return None
    expiration = _single_tag(event, "expiration")
    if expiration is None:
        return None
    try:
        expires = int(expiration)
    except ValueError:
        return None
    created = event.created_at().as_secs()
    if created > now + MAX_CLOCK_SKEW or not now < expires <= created + LIFETIME:
        return None
    return expires


def _contact_keys(authors: set[str]) -> list[PublicKey]:
    keys = []
    for author in sorted(authors):
        try:
            keys.append(PublicKey.parse(author))
        except Exception:  # noqa: BLE001 - malformed saved contact key, not a transport failure.
            continue
    return keys


class PresenceClient:
    """Exchange presence through the same relays and signing identity as chat."""

    def __init__(self, node: ChatNode) -> None:
        self.node = node
        self.last_published = float("-inf")

    def event(self, now: int) -> Event:
        """Create a signed NIP-38 status with NIP-40 expiration."""
        unsigned = (
            EventBuilder(Kind(KIND), "online")
            .custom_created_at(Timestamp.from_secs(now))
            .tags([
                Tag.parse(["d", STATUS_TYPE]),
                Tag.parse(["expiration", str(now + LIFETIME)]),
            ])
            .finalize_unsigned(self.node._keys.public_key())
        )
        return self.node._keys.sign_event(unsigned)

    async def refresh(self, authors: set[str], *, share: Callable[[], bool]) -> dict[str, int]:
        """Read fresh contact presence, optionally publishing our own heartbeat.

        Failures return unknown presence and are retried by the next UI poll.
        Cancellation propagates after disconnecting the transport.
        """
        keys = _contact_keys(authors)
        if not keys and not share():
            return {}
        client = self.node._client()
        try:
            await self.node._connect(client, timeout=10)
            return await self._exchange(client, keys, share)
        except Exception as exc:  # noqa: BLE001 - transient relay errors must not stop chat.
            logger.warning("Presence refresh failed", extra={"error_type": type(exc).__name__})
            return {}
        finally:
            try:
                await asyncio.wait_for(client.disconnect(), timeout=5)
            except Exception as exc:  # noqa: BLE001 - cleanup must preserve cancellation.
                logger.warning("Presence disconnect failed", extra={"error_type": type(exc).__name__})

    async def _exchange(
        self, client: Client, keys: list[PublicKey], share: Callable[[], bool]
    ) -> dict[str, int]:
        if share() and time.monotonic() - self.last_published >= HEARTBEAT_INTERVAL:
            await asyncio.wait_for(client.send_event(self.event(int(time.time()))), timeout=10)
            self.last_published = time.monotonic()
        if not keys:
            return {}
        query = (
            Filter().kind(Kind(KIND)).authors(keys)
            .custom_tag(SingleLetterTag.from_byte(ord("d")), STATUS_TYPE)
            .since(Timestamp.from_secs(max(0, int(time.time()) - LIFETIME)))
        )
        events = await asyncio.wait_for(client.fetch_events(ReqTarget.auto([query])), timeout=10)
        return online_until(events, {key.to_hex() for key in keys}, int(time.time()))

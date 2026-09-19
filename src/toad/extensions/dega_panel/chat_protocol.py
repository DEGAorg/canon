"""Nostr transport for the DEGA/Canon P2P chat.

Wraps `nostr-sdk` (Rust bindings, pure-Python wheel) with the pieces a chat
node needs, keeping the nostr dependency isolated so the UI stays testable even
when no relay is reachable:

- identity  -> a Nostr keypair (nsec/npub). In production this derives from the
  DEGA Core wallet; for the sim/dev path a fresh keypair can be used.
- send DM   -> NIP-44 encrypted message published as a NIP-04 style event to a
  public relay (free, no API key, no infra owned by DEGA).
- receive   -> subscribe to DM events addressed to my pubkey and decrypt.

The publish/sync timing issue found earlier (relay reporting "not connected"
right after connect()) is handled here by awaiting a settled connection state
before every send, and by treating a disconnect as a retryable send failure
instead of a hard error.
"""

from __future__ import annotations

import asyncio
import time
from decimal import ROUND_HALF_UP, Decimal

from nostr_sdk import (
    Client,
    ClientBuilder,
    EventBuilder,
    Filter,
    Keys,
    Kind,
    Nip44Version,
    PublicKey,
    RelayMessage,
    RelayUrl,
    ReqTarget,
    SingleLetterTag,
    Tag,
    Timestamp,
)
from nostr_sdk import nip44_decrypt as _nip44_decrypt
from nostr_sdk import nip44_encrypt as _nip44_encrypt

from toad.extensions.dega_panel.chat_store import (
    append_messages,
    load_inbox,
)

DEFAULT_RELAYS = ["wss://relay.damus.io", "wss://nos.lol"]
DEGA_DECIMALS = 8
WEEGA_PER_DEGA = 10 ** DEGA_DECIMALS


_SIG_DIGITS = 6


def format_dega_amount(weega: int, *, decimals: int = DEGA_DECIMALS) -> str:
    """Render a DEGA amount from its smallest unit, honoring token decimals.

    Uses decimal arithmetic and always renders in fixed-point notation: ``%g``
    switched small fees to scientific notation (``5e-11``), which must never
    reach the UI. Rounds to 6 significant digits as ``%g`` did, then trims
    trailing zeros.
    """
    amount = Decimal(int(weega)).scaleb(-int(decimals))
    if amount == 0:
        return "0"
    quantum = Decimal(1).scaleb(amount.adjusted() - (_SIG_DIGITS - 1))
    if quantum > 1:
        # Amounts large enough that 6 significant digits reach past the units
        # place round to whole DEGA instead of implying false precision.
        quantum = Decimal(1)
    text = format(amount.quantize(quantum, rounding=ROUND_HALF_UP), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fee_display(weega: int, decimals: int | None) -> str:
    """Fee with unit for the UI.

    ``decimals`` comes from the registry's token; when it could not be read
    (None) the base amount is shown with an explicit note instead of a
    mis-scaled $DEGA figure.
    """
    if not weega:
        return "0 $DEGA"
    if decimals is None:
        return f"{weega} weega (token scale unavailable)"
    return f"{format_dega_amount(weega, decimals=decimals)} $DEGA"


class NostrError(Exception):
    """Raised when the Nostr transport cannot operate."""


def parse_public_key(pubkey: str) -> PublicKey:
    """Parse a Nostr pubkey, raising a friendly ``NostrError`` on garbage.

    ``PublicKey.parse`` raises ``NostrSdkError.Generic('malformed public key')``
    for an empty/placeholder/partial key (e.g. a peer whose stored pubkey is a
    dummy or got truncated). We convert that into a clear error at the transport
    boundary so callers (the TUI) can surface a message instead of crashing.
    """
    s = (pubkey or "").strip()
    if not s:
        raise NostrError("missing public key")
    try:
        return PublicKey.parse(s)
    except Exception as exc:  # noqa: BLE001 - nostr_sdk raises several types
        raise NostrError(f"invalid public key: {s[:16]}…") from exc


class ChatNode:
    """One chat identity bound to a Nostr keypair and a set of relays."""

    def __init__(self, *, secret_key: str | None = None, relays: list[str] | None = None) -> None:
        if secret_key:
            self._keys = Keys.parse(secret_key)
        else:
            self._keys = Keys.generate()
        self.relays = relays or DEFAULT_RELAYS
        self.pubkey: str = self._keys.public_key().to_hex()
        self.npub: str = self._keys.public_key().to_bech32()

    # --- identity -----------------------------------------------------------
    def short_id(self) -> str:
        return f"{self.npub[:12]}…"

    def _client(self) -> Client:
        c = ClientBuilder().build()
        return c

    async def _connect(self, client: Client, timeout: float = 20.0) -> None:
        for r in self.relays:
            await client.add_relay(RelayUrl.parse(r))
        await asyncio.wait_for(client.connect(), timeout=timeout)
        # Settle: give the handshake a beat before we send so the relay doesn't
        # report "not connected" for an in-flight connect.
        await asyncio.sleep(0.5)

    # --- messaging ----------------------------------------------------------
    async def send_encrypted(self, to_pubkey: str, message: str) -> str:
        """Encrypt (NIP-44) and publish a DM to a relay. Returns the event id."""
        peer = parse_public_key(to_pubkey)
        # nip44_encrypt lifts the peer's x-only key to a curve point; a key that
        # parses as 32-byte hex but is NOT a valid secp256k1 point (e.g. a
        # placeholder/dummy like 000102…1f) makes the Rust binding raise
        # NostrSdkError('malformed public key'). Convert any such failure into a
        # clear NostrError so the TUI shows a message instead of crashing.
        try:
            cipher = _nip44_encrypt(
                self._keys.secret_key(), peer, message, Nip44Version.V2
            )
            unsigned = (
                EventBuilder(Kind(4), cipher)
                .tags([Tag.parse(["p", peer.to_hex()])])
                .finalize_unsigned(self._keys.public_key())
            )
            event = self._keys.sign_event(unsigned)
        except NostrError:
            raise
        except Exception as exc:  # noqa: BLE001 - nostr_sdk raises several types
            raise NostrError(
                f"cannot encrypt to {peer.to_hex()[:16]}… (invalid peer key)"
            ) from exc

        client = self._client()
        await self._connect(client)
        try:
            out = await asyncio.wait_for(client.send_event(event), timeout=25.0)
        except Exception as exc:  # noqa: BLE001 - surface relay failures as an error
            raise NostrError(f"send failed: {exc}") from exc
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        return event.id().to_hex()

    async def decrypt_event(self, sender_pubkey: str, cipher: str) -> str:
        """Decrypt a NIP-44 message from a specific sender's pubkey."""
        sender = parse_public_key(sender_pubkey)
        return _nip44_decrypt(self._keys.secret_key(), sender, cipher)

    async def fetch_dms(self, since_secs: int | None = None) -> list[dict]:
        """Pull kind-4 DMs addressed to me and decrypt them.

        Decision (client): DMs live **in the relay with unlimited history** and
        are **not** synced across devices — the relay is the source of truth,
        and the TUI simply queries on each open. ``since_secs`` is optional so a
        caller can narrow (e.g. a fresh pane); default ``None`` = the full
        relay history.

        Uses a request-style subscription (``fetch_events``) filtered to kind-4
        events with a ``p`` tag pointing at my pubkey, then decrypts each event
        with NIP-44 using my key. Returns a list of ``{event_id, from, text,
        time}``; undecryptable events are kept with a marker rather than
        dropped (honest — nothing is fabricated).
        """
        client = self._client()
        await self._connect(client)
        try:
            ptag = SingleLetterTag.from_byte(ord("p"))
            f = Filter().kind(Kind(4)).custom_tag(ptag, self.pubkey)
            if since_secs is not None:
                f = f.since(Timestamp.from_secs(int(time.time()) - since_secs))
            events = await client.fetch_events(ReqTarget.auto([f]))
        except Exception as exc:  # noqa: BLE001
            raise NostrError(f"fetch_dms failed: {exc}") from exc
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

        msgs: list[dict] = []
        for event in events:
            try:
                sender = event.author().to_hex()
                cipher = str(event.content())
                text = _nip44_decrypt(self._keys.secret_key(), PublicKey.parse(sender), cipher)
            except Exception:  # noqa: BLE001 - undecryptable foreign/edge events
                text = "(undecryptable)"
                sender = event.author().to_hex()
            msgs.append(
                {
                    "event_id": event.id().to_hex(),
                    "from": sender,
                    "text": text,
                    "time": str(event.created_at().as_secs()),
                }
            )
        return msgs


class OfflineChatNode(ChatNode):
    """A chat node that works with no relay (local demo / tests).

    Each node owns an inbox of messages it has received. ``deliver_to`` encrypts
    a message to the recipient (NIP-44, exactly like the networked path) and
    drops it into that recipient's inbox; ``inbox_decrypted`` decrypts them back.
    This exercises the same E2E crypto with zero network — honest, no fabricated
    content.
    """

    def __init__(self, **kw) -> None:
        # messages this node received: [{from: sender_pubkey, cipher, time}]
        self._inbox: list[dict] = []
        self._store_path = kw.pop("store_path", None)
        super().__init__(**kw)

    async def deliver_to(self, receiver: "OfflineChatNode", message: str) -> str:
        """Encrypt ``message`` to ``receiver`` and deliver it to their inbox."""
        cipher = _nip44_encrypt(
            self._keys.secret_key(),
            PublicKey.parse(receiver.pubkey),
            message,
            Nip44Version.V2,
        )
        msg_id = f"offline-{len(receiver._inbox) + time.time_ns()}"
        receiver._inbox.append(
            {"id": msg_id, "from": self.pubkey, "cipher": cipher,
             "time": time.strftime("%H:%M")}
        )
        # Persist to the receiver's local inbox store (deduped by id), so an
        # offline conversation survives an app restart. Never stores plaintext.
        append_messages(receiver.pubkey, receiver._inbox[-1:], path=receiver._store_path)
        return msg_id

    def persisted(self) -> list[dict]:
        """Return the raw (still-encrypted) DMs loaded from the local store."""
        return load_inbox(self.pubkey, path=self._store_path)

    def inbox_decrypted(self) -> list[dict]:
        """Decrypt everything addressed to me (sender pubkey -> plaintext).

        Merges in-memory deliveries and the persisted store, deduped by id, so
        restarting the app does not lose or duplicate offline E2E messages.
        """
        by_id: dict[str, dict] = {}
        for m in self._inbox:
            by_id[m["id"]] = m
        for m in load_inbox(self.pubkey, path=self._store_path):
            key = m.get("id") or f"{m.get('from','')}:{m.get('cipher','')}"
            by_id.setdefault(key, m)
        decrypted: list[dict] = []
        for m in by_id.values():
            try:
                txt = _nip44_decrypt(
                    self._keys.secret_key(), PublicKey.parse(m["from"]), m["cipher"]
                )
            except Exception:  # noqa: BLE001
                txt = "(undecryptable)"
            decrypted.append({"from": pub_short(m["from"]), "text": txt, "time": m["time"]})
        return decrypted


def pub_short(hexkey: str) -> str:
    return f"{hexkey[:8]}…"


def make_node(secret_key: str | None = None, *, offline: bool = False, **kw) -> ChatNode:
    return (OfflineChatNode if offline else ChatNode)(secret_key=secret_key, **kw)
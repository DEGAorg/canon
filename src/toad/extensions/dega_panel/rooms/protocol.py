"""Signed room envelopes transported inside encrypted direct messages."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from nostr_sdk import Event, EventBuilder, Keys, Kind

PREFIX = "canon-room/1\n"
MAX_WIRE_BYTES = 65536


class RoomError(ValueError):
    """An actionable room operation or protocol failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def require(condition: bool, message: str, code: str = "invalid_payload") -> None:
    if not condition:
        raise RoomError(code, message)


def fields(value: Any, names: set[str]) -> dict:
    require(isinstance(value, dict), "Expected an object")
    require(set(value) == names, "Unexpected or missing fields")
    return value


def key(value: Any) -> str:
    require(isinstance(value, str) and len(value) == 64, "Expected a public key")
    require(all(char in "0123456789abcdef" for char in value), "Invalid public key")
    return value


def identifier(value: Any) -> str:
    require(isinstance(value, str), "Expected a UUID")
    try:
        require(str(UUID(value)) == value, "UUID must use canonical form")
    except ValueError as exc:
        raise RoomError("invalid_payload", "Invalid UUID") from exc
    return value


def number(value: Any) -> int:
    require(type(value) is int and value >= 0, "Expected a nonnegative integer")
    return value


def text(value: Any, limit: int) -> str:
    require(isinstance(value, str), "Expected text")
    require(0 < len(value.strip()) <= limit, f"Text must contain 1–{limit} characters")
    return value


@dataclass(frozen=True)
class Envelope:
    """A verified author and strictly parsed application envelope."""

    id: str
    room_id: str
    kind: str
    created_at: int
    payload: dict
    author: str
    signed: str
    event_id: str

    @property
    def key(self) -> str:
        return f"{self.room_id}/{self.author}/{self.id}"

    @property
    def owner(self) -> str:
        return self.room_id.split(":", 1)[0]

    @property
    def wire(self) -> str:
        return PREFIX + self.signed


def validate_state(payload: dict) -> None:
    fields(
        payload,
        {
            "revision",
            "previous_state_id",
            "name",
            "closed",
            "members",
            "pending_invites",
        },
    )
    revision = number(payload["revision"])
    previous = payload["previous_state_id"]
    require(
        previous is None if revision == 0 else isinstance(previous, str),
        "Invalid predecessor",
    )
    if previous is not None:
        key(previous)
    text(payload["name"], 80)
    require(type(payload["closed"]) is bool, "Invalid closed flag")
    members = payload["members"]
    require(isinstance(members, list) and 1 <= len(members) <= 50, "Invalid member list")
    require(len(set(key(member) for member in members)) == len(members), "Duplicate member")
    invites = payload["pending_invites"]
    require(isinstance(invites, list) and len(invites) <= 50, "Too many invitations")
    seen: set[str] = set()
    for invite in invites:
        fields(invite, {"invite_id", "recipient"})
        identifier(invite["invite_id"])
        recipient = key(invite["recipient"])
        require(recipient not in members and recipient not in seen, "Duplicate invite")
        seen.add(recipient)


def validate_payload(kind: str, payload: dict) -> None:
    if kind == "state":
        validate_state(payload)
    elif kind == "invite":
        fields(payload, {"invite_id", "recipient", "state"})
        identifier(payload["invite_id"])
        key(payload["recipient"])
        text(payload["state"], MAX_WIRE_BYTES)
    elif kind in {"accept", "decline"}:
        fields(payload, {"invite_id"})
        identifier(payload["invite_id"])
    elif kind == "leave":
        fields(payload, {"state_revision"})
        number(payload["state_revision"])
    elif kind == "message":
        fields(payload, {"text", "state"})
        text(payload["text"], 8000)
        text(payload["state"], MAX_WIRE_BYTES)
    else:
        raise RoomError("invalid_payload", "Unsupported room operation")


def decode(signed: str) -> Envelope:
    """Verify a signed envelope before trusting any room state or content.

    Args:
        signed: Serialized Nostr event, without the room transport prefix.
    """
    require(isinstance(signed, str), "Expected signed event text")
    require(len(signed.encode()) <= MAX_WIRE_BYTES, "Room payload is too large")
    try:
        event = Event.from_json(signed)
        require(event.verify(), "Invalid room signature")
        data = fields(
            json.loads(event.content()),
            {"version", "id", "room_id", "type", "created_at", "payload"},
        )
        require(
            type(data["version"]) is int and data["version"] == 1,
            "Unsupported room protocol version",
        )
        identifier(data["id"])
        owner, room_uuid = data["room_id"].split(":", 1)
        key(owner)
        identifier(room_uuid)
        number(data["created_at"])
        validate_payload(data["type"], data["payload"])
        result = Envelope(
            data["id"],
            data["room_id"],
            data["type"],
            data["created_at"],
            data["payload"],
            event.author().to_hex(),
            signed,
            event.id().to_hex(),
        )
        if result.kind == "state":
            require(
                result.author == owner,
                "Only the room owner can sign state",
                "not_owner",
            )
            require(owner in result.payload["members"], "Owner missing from room")
        return result
    except RoomError:
        raise
    except Exception as exc:
        raise RoomError("invalid_payload", "Malformed signed room event") from exc


def create(
    keys: Keys,
    room_id: str,
    kind: str,
    payload: dict,
    *,
    operation_id: str | None = None,
) -> Envelope:
    """Create a signed room operation; retries reuse the resulting event."""
    data = {
        "version": 1,
        "id": operation_id or str(uuid4()),
        "room_id": room_id,
        "type": kind,
        "created_at": int(time.time()),
        "payload": payload,
    }
    unsigned = EventBuilder(Kind(4), json.dumps(data, separators=(",", ":"))).finalize_unsigned(
        keys.public_key(),
    )
    return decode(keys.sign_event(unsigned).as_json())

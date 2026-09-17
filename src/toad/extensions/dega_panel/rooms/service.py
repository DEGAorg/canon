"""Room lifecycle, authenticated membership, and durable per-recipient delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

from nostr_sdk import Keys

from toad.extensions.dega_panel.rooms.journal import Journal
from toad.extensions.dega_panel.rooms.protocol import (
    PREFIX,
    Envelope,
    RoomError,
    create,
    decode,
    key,
    require,
    text,
)

Send = Callable[[str, str], Awaitable[str]]


class RoomService:
    """The shared application service for TUI and local agent commands."""

    def __init__(self, keys: Keys, send: Send, directory: Path) -> None:
        self.keys = keys
        self.me = keys.public_key().to_hex()
        self.send_wire = send
        self.journal = Journal(directory / f"{self.me}.sqlite3", keys)
        self.lock = asyncio.Lock()
        self.delivery_lock = asyncio.Lock()

    async def open(self) -> None:
        await self.journal.open()

    async def close(self) -> None:
        await self.journal.close()

    async def rooms(self) -> list[dict]:
        rows = await self.journal.rows("SELECT id,proof,status,conflict FROM rooms ORDER BY rowid")
        return [
            {
                "id": rid,
                "status": status,
                "conflict": bool(conflict),
                "owner": decode(proof).owner,
                **decode(proof).payload,
            }
            for rid, proof, status, conflict in rows
        ]

    async def _room(self, room_id: str) -> tuple[Envelope, str]:
        rows = await self.journal.rows(
            "SELECT proof,status,conflict FROM rooms WHERE id=?", (room_id,)
        )
        require(bool(rows), "Room not found", "not_member")
        require(not rows[0][2], "Room has conflicting owner states", "state_conflict")
        return decode(rows[0][0]), rows[0][1]

    async def _owned(self, room_id: str) -> Envelope:
        proof, _ = await self._room(room_id)
        require(proof.owner == self.me, "Only the creator can manage this room", "not_owner")
        require(not proof.payload["closed"], "Room is closed", "not_member")
        return proof

    async def _proof(self, proof: Envelope, *, persist: bool = True) -> None:
        require(proof.kind == "state", "Expected an owner state")
        rows = await self.journal.rows(
            "SELECT id,proof FROM proofs WHERE room=? AND revision=?",
            (proof.room_id, proof.payload["revision"]),
        )
        if rows and rows[0][0] != proof.event_id:
            await self._conflict(proof.room_id)
        revision = proof.payload["revision"]
        neighbors = await self.journal.rows(
            "SELECT revision,id,proof FROM proofs WHERE room=? AND revision IN (?,?)",
            (proof.room_id, revision - 1, revision + 1),
        )
        for rev, event_id, signed in neighbors:
            matches = (
                proof.payload["previous_state_id"] == event_id
                if rev < revision
                else decode(signed).payload["previous_state_id"] == proof.event_id
            )
            if not matches:
                await self._conflict(proof.room_id)
        if not persist:
            return
        await self.journal.db.execute(
            "INSERT OR IGNORE INTO proofs VALUES (?,?,?,?)",
            (
                proof.room_id,
                revision,
                proof.event_id,
                proof.signed,
            ),
        )
        await self.journal.db.commit()

    async def _conflict(self, room_id: str) -> None:
        await self.journal.db.execute("UPDATE rooms SET conflict=1 WHERE id=?", (room_id,))
        await self.journal.db.commit()
        raise RoomError("state_conflict", "Owner published conflicting room states")

    async def unresolved(self, room_id: str) -> int:
        """Count unresolved publications, including invitations and membership changes."""
        rows = await self.journal.rows(
            "SELECT COUNT(*) FROM outbox o JOIN events e ON e.id=o.event "
            "WHERE e.room=? AND o.status IN ('pending','failed')",
            (room_id,),
        )
        return rows[0][0]

    async def create_room(self, name: str) -> str:
        async with self.lock:
            room_id = f"{self.me}:{uuid4()}"
            proof = create(
                self.keys,
                room_id,
                "state",
                {
                    "revision": 0,
                    "previous_state_id": None,
                    "name": text(name, 80).strip(),
                    "closed": False,
                    "members": [self.me],
                    "pending_invites": [],
                },
            )
            await self._proof(proof, persist=False)
            await self.journal.write(proof, room=(room_id, proof.signed, "active"), proof=proof)
            return room_id

    async def _update(self, proof: Envelope, **changes) -> Envelope:
        payload = {
            **proof.payload,
            **changes,
            "revision": proof.payload["revision"] + 1,
            "previous_state_id": proof.event_id,
        }
        updated = create(self.keys, proof.room_id, "state", payload)
        recipients = set(proof.payload["members"] + payload["members"])
        recipients.update(invite["recipient"] for invite in proof.payload["pending_invites"])
        recipients.update(invite["recipient"] for invite in payload["pending_invites"])
        recipients.discard(self.me)
        await self._proof(updated, persist=False)
        status = "closed" if payload["closed"] else "active"
        await self.journal.write(
            updated,
            recipients=list(recipients),
            room=(proof.room_id, updated.signed, status),
            proof=updated,
        )
        return updated

    async def invite(self, room_id: str, recipient: str) -> str:
        key(recipient)
        async with self.lock:
            proof = await self._owned(room_id)
            require(recipient not in proof.payload["members"], "Contact is already a member")
            pending = list(proof.payload["pending_invites"])
            entry = next((item for item in pending if item["recipient"] == recipient), None)
            if entry is None:
                entry = {"invite_id": str(uuid4()), "recipient": recipient}
                pending.append(entry)
                proof = await self._update(proof, pending_invites=pending)
            operation = f"{room_id}/{self.me}/{entry['invite_id']}"
            existing = await self.journal.rows("SELECT id FROM events WHERE id=?", (operation,))
            if not existing:
                event = create(
                    self.keys,
                    room_id,
                    "invite",
                    {**entry, "state": proof.signed},
                    operation_id=entry["invite_id"],
                )
                await self.journal.write(event, recipients=[recipient])
        await self.flush()
        return operation

    async def respond(self, room_id: str, accept: bool) -> str:
        async with self.lock:
            proof, status = await self._room(room_id)
            require(
                status == "invited",
                "Invitation is no longer available",
                "invite_unavailable",
            )
            pending = next(
                (item for item in proof.payload["pending_invites"] if item["recipient"] == self.me),
                None,
            )
            require(pending is not None, "Invitation was revoked", "invite_unavailable")
            assert pending is not None
            event = create(
                self.keys,
                room_id,
                "accept" if accept else "decline",
                {"invite_id": pending["invite_id"]},
            )
            await self.journal.write(
                event,
                recipients=[proof.owner],
                room=(
                    room_id,
                    proof.signed,
                    "joining" if accept else "declined",
                ),
            )
        await self.flush()
        return event.key

    async def manage(self, room_id: str, action: str, value: str = "") -> None:
        async with self.lock:
            proof = await self._owned(room_id)
            if action == "rename":
                await self._update(proof, name=text(value, 80).strip())
            elif action == "close":
                await self._update(proof, closed=True, pending_invites=[])
            elif action == "remove":
                key(value)
                require(value != self.me, "The owner must close the room instead")
                members = [member for member in proof.payload["members"] if member != value]
                invites = [
                    item for item in proof.payload["pending_invites"] if item["recipient"] != value
                ]
                await self._update(proof, members=members, pending_invites=invites)
            else:
                raise RoomError("invalid_payload", "Unknown room management action")
        await self.flush()

    async def leave(self, room_id: str) -> None:
        async with self.lock:
            proof, status = await self._room(room_id)
            require(proof.owner != self.me, "The creator must close the room instead")
            require(status == "active", "You are not an active member", "not_member")
            event = create(
                self.keys,
                room_id,
                "leave",
                {"state_revision": proof.payload["revision"]},
            )
            await self.journal.write(
                event, recipients=[proof.owner], room=(room_id, proof.signed, "left")
            )
        await self.flush()

    async def send(self, room_id: str, body: str) -> str:
        async with self.lock:
            proof, status = await self._room(room_id)
            require(
                status == "active" and not proof.payload["closed"],
                "You cannot send to this room",
                "not_member",
            )
            require(
                self.me in proof.payload["members"],
                "You are not a member",
                "not_member",
            )
            event = create(self.keys, room_id, "message", {"text": body, "state": proof.signed})
            recipients = [peer for peer in proof.payload["members"] if peer != self.me]
            await self.journal.write(event, recipients=recipients)
        await self.flush()
        return event.key

    async def _accept_state(self, proof: Envelope) -> None:
        await self._proof(proof)
        rows = await self.journal.rows(
            "SELECT proof,status FROM rooms WHERE id=?", (proof.room_id,)
        )
        if not rows:
            # A state broadcast alone cannot enroll an identity or create an invitation.
            return
        old, status = decode(rows[0][0]), rows[0][1]
        if proof.payload["revision"] <= old.payload["revision"]:
            return
        if proof.payload["closed"]:
            status = "closed"
        elif self.me in proof.payload["members"] and status in {"joining", "active"}:
            status = "active"
        elif self.me not in proof.payload["members"] and status == "active":
            status = "removed"
        elif status in {"invited", "joining"} and not any(
            item["recipient"] == self.me for item in proof.payload["pending_invites"]
        ):
            status = "removed"
        await self.journal.db.execute(
            "UPDATE rooms SET proof=?,status=? WHERE id=?",
            (proof.signed, status, proof.room_id),
        )
        await self.journal.db.commit()

    async def _receive_invite(self, event: Envelope) -> None:
        proof = decode(event.payload["state"])
        require(proof.kind == "state", "Expected an owner state")
        require(
            event.author == proof.owner and event.room_id == proof.room_id,
            "Invitation owner mismatch",
            "not_owner",
        )
        require(event.payload["recipient"] == self.me, "Invitation is for another person")
        pending = {"invite_id": event.payload["invite_id"], "recipient": self.me}
        require(
            pending in proof.payload["pending_invites"] and not proof.payload["closed"],
            "Invitation is no longer valid",
            "invite_unavailable",
        )
        await self._proof(proof)
        latest = await self.journal.rows(
            "SELECT proof FROM proofs WHERE room=? ORDER BY revision DESC LIMIT 1",
            (event.room_id,),
        )
        effective = decode(latest[0][0])
        require(
            pending in effective.payload["pending_invites"] and not effective.payload["closed"],
            "Invitation was revoked",
            "invite_unavailable",
        )
        proof = effective
        known = await self.journal.rows(
            "SELECT proof,status FROM rooms WHERE id=?", (event.room_id,)
        )
        if known:
            old = decode(known[0][0])
            require(proof.payload["revision"] >= old.payload["revision"], "Stale invitation")
            require(known[0][1] != "active", "Already a member")
        await self.journal.write(event, room=(event.room_id, proof.signed, "invited"))

    async def _receive_response(self, event: Envelope) -> None:
        proof = await self._owned(event.room_id)
        pending = proof.payload["pending_invites"]
        match = next(
            (
                item
                for item in pending
                if item["invite_id"] == event.payload["invite_id"]
                and item["recipient"] == event.author
            ),
            None,
        )
        require(match is not None, "Invitation is unavailable", "invite_unavailable")
        members = list(proof.payload["members"])
        if event.kind == "accept":
            require(len(members) < 50, "Room is full")
            members.append(event.author)
        await self._update(
            proof,
            members=members,
            pending_invites=[item for item in pending if item != match],
        )
        await self.journal.write(event)

    async def _receive_message(self, event: Envelope) -> None:
        proof = decode(event.payload["state"])
        require(proof.kind == "state" and proof.room_id == event.room_id, "Wrong room proof")
        require(
            event.author in proof.payload["members"] and self.me in proof.payload["members"],
            "Sender or recipient is not a member",
            "invalid_payload",
        )
        await self._accept_state(proof)
        current, status = await self._room(event.room_id)
        require(
            status in {"active", "removed", "left", "closed"},
            "Room is not active",
            "not_member",
        )
        stale = (
            status != "active"
            or current.payload["closed"]
            or event.author not in current.payload["members"]
        )
        await self.journal.write(event, status="stale" if stale else "accepted")

    async def ingest(self, sender: str, wire: str) -> bool:
        """Route and validate a room event; return False for ordinary DM text."""
        if not wire.startswith(PREFIX):
            return False
        event = decode(wire[len(PREFIX) :])
        require(event.author == sender, "Transport and room authors differ")
        async with self.lock:
            seen = await self.journal.rows("SELECT cipher FROM events WHERE id=?", (event.key,))
            if seen:
                require(
                    decode(self.journal.decrypt(seen[0][0])).event_id == event.event_id,
                    "Operation ID reused with different content",
                    "state_conflict",
                )
                return True
            try:
                await self._ingest_event(event)
            except RoomError as exc:
                if event.kind != "message" or exc.code != "not_member":
                    raise
                count = await self.journal.rows("SELECT COUNT(*) FROM deferred")
                require(count[0][0] < 1000, "Too many pending room messages")
                await self.journal.db.execute(
                    "INSERT OR IGNORE INTO deferred VALUES (?,?,?)",
                    (
                        event.key,
                        event.room_id,
                        self.journal.encrypt(event.signed),
                    ),
                )
                await self.journal.db.commit()
            await self._drain_deferred(event.room_id)
        await self.flush()
        return True

    async def _drain_deferred(self, room_id: str) -> None:
        rows = await self.journal.rows("SELECT id,cipher FROM deferred WHERE room=?", (room_id,))
        for operation, cipher in rows:
            try:
                await self._receive_message(decode(self.journal.decrypt(cipher)))
            except RoomError as exc:
                if exc.code == "not_member":
                    continue
                raise
            await self.journal.db.execute("DELETE FROM deferred WHERE id=?", (operation,))
        await self.journal.db.commit()

    async def _ingest_event(self, event: Envelope) -> None:
        if event.kind == "invite":
            await self._receive_invite(event)
        elif event.kind in {"accept", "decline"}:
            await self._receive_response(event)
        elif event.kind == "message":
            await self._receive_message(event)
        elif event.kind == "state":
            await self._accept_state(event)
            await self.journal.write(event)
        elif event.kind == "leave":
            proof = await self._owned(event.room_id)
            require(
                event.author in proof.payload["members"] and event.author != self.me,
                "Not an active member",
                "not_member",
            )
            await self._update(
                proof,
                members=[peer for peer in proof.payload["members"] if peer != event.author],
            )
            await self.journal.write(event)

    async def flush(self) -> None:
        """Publish unresolved deliveries; an acknowledgement is not a read receipt."""
        async with self.delivery_lock:
            rows = await self.journal.rows(
                "SELECT o.event,o.peer,e.cipher FROM outbox o JOIN events e ON o.event=e.id "
                "WHERE o.status IN ('pending','failed')",
            )
            for operation, peer, cipher in rows:
                event = decode(self.journal.decrypt(cipher))
                status, error = "published", ""
                try:
                    if event.kind == "message":
                        proof, membership = await self._room(event.room_id)
                        if membership != "active" or peer not in proof.payload["members"]:
                            status = "cancelled"
                        else:
                            await self.send_wire(peer, event.wire)
                    elif event.kind == "invite":
                        proof, _ = await self._room(event.room_id)
                        valid = any(
                            item["invite_id"] == event.payload["invite_id"]
                            for item in proof.payload["pending_invites"]
                        )
                        if valid and not proof.payload["closed"]:
                            await self.send_wire(peer, event.wire)
                        else:
                            status = "cancelled"
                    else:
                        await self.send_wire(peer, event.wire)
                except Exception as exc:
                    status, error = "failed", str(exc)
                async with self.lock:
                    await self.journal.db.execute(
                        "UPDATE outbox SET status=?,error=? WHERE event=? AND peer=?",
                        (status, error, operation, peer),
                    )
                    await self.journal.db.commit()

    async def history(self, room_id: str) -> list[dict]:
        rows = await self.journal.rows(
            "SELECT id,cipher,status FROM events WHERE room=? AND kind='message' "
            "ORDER BY timestamp,id",
            (room_id,),
        )
        messages = []
        for operation, cipher, status in rows:
            event = decode(self.journal.decrypt(cipher))
            deliveries = await self.journal.rows(
                "SELECT peer,status,error FROM outbox WHERE event=?",
                (operation,),
            )
            messages.append(
                {
                    "id": operation,
                    "author": event.author,
                    "text": event.payload["text"],
                    "timestamp": event.created_at,
                    "status": status,
                    "deliveries": [
                        {"peer": peer, "status": state, "error": error}
                        for peer, state, error in deliveries
                    ],
                }
            )
        return messages

    async def remember_dm(
        self, event_id: str, *, peer: str, mine: bool, timestamp: int, body: str
    ) -> None:
        """Save a private message locally without changing its existing wire format."""
        async with self.lock:
            await self.journal.db.execute(
                "INSERT OR IGNORE INTO dm_history VALUES (?,?,?,?,?)",
                (
                    event_id,
                    peer,
                    int(mine),
                    timestamp,
                    self.journal.encrypt(body),
                ),
            )
            await self.journal.db.commit()

    async def direct_history(self) -> list[dict]:
        rows = await self.journal.rows("SELECT * FROM dm_history ORDER BY timestamp,id")
        return [
            {
                "event_id": eid,
                "peer": peer,
                "mine": bool(mine),
                "timestamp": timestamp,
                "text": self.journal.decrypt(cipher),
            }
            for eid, peer, mine, timestamp, cipher in rows
        ]

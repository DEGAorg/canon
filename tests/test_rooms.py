"""Multi-identity room tests with real signing/encryption and a controlled relay."""

import json

import pytest
from nostr_sdk import Keys, Nip44Version, nip44_decrypt, nip44_encrypt

from toad.extensions.dega_panel.rooms.protocol import PREFIX, RoomError, create, decode
from toad.extensions.dega_panel.rooms.service import RoomService


class Relay:
    def __init__(self):
        self.services = {}
        self.queue = []
        self.fail = set()

    def sender(self, keys):
        async def send(peer, wire):
            if peer in self.fail:
                raise OSError("relay unavailable")
            receiver = self.services[peer]
            cipher = nip44_encrypt(
                keys.secret_key(), receiver.keys.public_key(), wire, Nip44Version.V2
            )
            self.queue.append((keys.public_key().to_hex(), peer, cipher))
            return str(len(self.queue))

        return send

    async def drain(self):
        while self.queue:
            sender, peer, cipher = self.queue.pop(0)
            service = self.services[peer]
            plaintext = nip44_decrypt(
                service.keys.secret_key(),
                self.services[sender].keys.public_key(),
                cipher,
            )
            await service.ingest(sender, plaintext)


@pytest.fixture
async def network(tmp_path):
    relay = Relay()
    services = []
    for _ in range(3):
        keys = Keys.generate()
        service = RoomService(keys, relay.sender(keys), tmp_path)
        await service.open()
        relay.services[service.me] = service
        services.append(service)
    yield relay, services
    for service in relay.services.values():
        await service.close()


async def joined(network):
    relay, (owner, bob, carol) = network
    room = await owner.create_room("Release team")
    for member in [bob, carol]:
        await owner.invite(room, member.me)
        await relay.drain()
        assert (await member.rooms())[0]["status"] == "invited"
        await member.respond(room, True)
        await relay.drain()
        assert (await member.rooms())[0]["status"] == "active"
    return room


async def test_three_people_exchange_and_restore_encrypted_history(network):
    room = await joined(network)
    relay, (owner, bob, carol) = network
    await owner.send(room, "private launch notes")
    await bob.send(room, "I reviewed them")
    await relay.drain()
    for service in [owner, bob, carol]:
        assert {message["text"] for message in await service.history(room)} == {
            "private launch notes",
            "I reviewed them",
        }
        path, keys = service.journal.path, service.keys
        await service.close()
        assert b"private launch notes" not in path.read_bytes()
        replacement = RoomService(keys, relay.sender(keys), path.parent)
        await replacement.open()
        relay.services[replacement.me] = replacement
        assert len(await replacement.history(room)) == 2
        assert (await replacement.rooms())[0]["status"] == "active"
        assert path.stat().st_mode & 0o777 == 0o600


async def test_decline_revoke_and_owner_permissions(network):
    relay, (owner, bob, carol) = network
    room = await owner.create_room("Private")
    await owner.invite(room, bob.me)
    await relay.drain()
    with pytest.raises(RoomError, match="creator"):
        await bob.invite(room, carol.me)
    await bob.respond(room, False)
    await relay.drain()
    assert (await bob.rooms())[0]["status"] == "declined"
    with pytest.raises(RoomError):
        await bob.send(room, "not allowed")
    await owner.invite(room, bob.me)
    await relay.drain()
    await owner.manage(room, "remove", bob.me)
    await relay.drain()
    with pytest.raises(RoomError):
        await bob.respond(room, True)


async def test_partial_delivery_retry_and_removal(network):
    room = await joined(network)
    relay, (owner, bob, carol) = network
    relay.fail.add(carol.me)
    await owner.send(room, "partial")
    await relay.drain()
    delivery = (await owner.history(room))[0]["deliveries"]
    assert {item["status"] for item in delivery} == {"published", "failed"}
    await owner.manage(room, "remove", carol.me)
    relay.fail.clear()
    await owner.flush()
    await relay.drain()
    assert not await carol.history(room)
    assert (await carol.rooms())[0]["status"] == "removed"
    assert len(await bob.history(room)) == 1


async def test_duplicate_signed_message_is_idempotent(network):
    room = await joined(network)
    relay, (owner, bob, _) = network
    await owner.send(room, "one")
    duplicate = next(item for item in relay.queue if item[1] == bob.me)
    relay.queue.append(duplicate)
    await relay.drain()
    assert len(await bob.history(room)) == 1


async def test_close_and_leave(network):
    room = await joined(network)
    relay, (owner, bob, carol) = network
    await bob.leave(room)
    await relay.drain()
    assert (await bob.rooms())[0]["status"] == "left"
    await owner.manage(room, "close")
    await relay.drain()
    assert (await carol.rooms())[0]["status"] == "closed"
    with pytest.raises(RoomError):
        await carol.send(room, "late")


async def test_protocol_rejects_forgery_and_bad_payload(network):
    relay, (owner, bob, _) = network
    room = await owner.create_room("Private")
    proof, _ = await owner._room(room)
    raw = json.loads(proof.signed)
    raw["content"] = raw["content"].replace("Private", "Changed")
    with pytest.raises(RoomError):
        decode(json.dumps(raw))
    with pytest.raises(RoomError):
        await bob.ingest(owner.me, PREFIX + "not JSON")
    assert not await bob.ingest(owner.me, "ordinary direct message")
    with pytest.raises(RoomError):
        create(bob.keys, room, "state", proof.payload)


async def test_message_arriving_before_confirmation_is_buffered(network):
    relay, (owner, bob, _) = network
    room = await owner.create_room("Out of order")
    await owner.invite(room, bob.me)
    await relay.drain()
    await bob.respond(room, True)
    # Deliver acceptance only; hold the membership broadcast.
    sender, peer, cipher = relay.queue.pop(0)
    await owner.ingest(
        sender, nip44_decrypt(owner.keys.secret_key(), bob.keys.public_key(), cipher)
    )
    await owner.send(room, "welcome")
    relay.queue.reverse()
    await relay.drain()
    assert (await bob.rooms())[0]["status"] == "active"
    assert [m["text"] for m in await bob.history(room)] == ["welcome"]


async def test_conflicting_owner_state_disables_sending(network):
    room = await joined(network)
    relay, (owner, bob, _) = network
    proof, _ = await owner._room(room)
    conflict = create(owner.keys, room, "state", {**proof.payload, "name": "Conflict"})
    with pytest.raises(RoomError, match="conflicting"):
        await bob.ingest(owner.me, conflict.wire)
    assert (await bob.rooms())[0]["conflict"]
    with pytest.raises(RoomError, match="conflicting"):
        await bob.send(room, "must not send")


async def test_dm_history_is_encrypted_and_separate_from_rooms(network):
    _, (owner, _, _) = network
    room = await owner.create_room("Separate")
    await owner.remember_dm("dm-1", peer="ab" * 32, mine=True, timestamp=100, body="a private DM")
    assert not await owner.history(room)
    assert (await owner.direct_history())[0]["text"] == "a private DM"
    path = owner.journal.path
    await owner.close()
    assert b"a private DM" not in path.read_bytes()
    await owner.open()
    assert len(await owner.direct_history()) == 1


async def test_unknown_future_room_message_waits_for_invitation_and_acceptance(network):
    relay, (owner, bob, _) = network
    room = await owner.create_room("Delayed invite")
    await owner.invite(room, bob.me)
    relay.queue.clear()
    proof, _ = await owner._room(room)
    membership = create(
        owner.keys,
        room,
        "state",
        {
            **proof.payload,
            "revision": proof.payload["revision"] + 1,
            "previous_state_id": proof.event_id,
            "members": [owner.me, bob.me],
            "pending_invites": [],
        },
    )
    message = create(owner.keys, room, "message", {"text": "delayed", "state": membership.signed})
    await bob.ingest(owner.me, message.wire)
    assert not await bob.rooms()
    assert not await bob.history(room)
    # Never auto-enroll or display a room merely because its owner added our key.
    assert await bob.journal.rows("SELECT id FROM deferred")


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("message", {"text": "", "state": "bad"}),
        ("accept", {"invite_id": "not-a-uuid"}),
        ("leave", {"state_revision": True}),
        ("unexpected", {}),
    ],
)
async def test_invalid_envelopes_are_rejected(network, kind, payload):
    _, (owner, _, _) = network
    room = await owner.create_room("Validation")
    with pytest.raises(RoomError):
        create(owner.keys, room, kind, payload)


async def test_pending_delivery_recovers_after_restart(network):
    room = await joined(network)
    relay, (owner, bob, carol) = network
    relay.fail.update([bob.me, carol.me])
    await owner.send(room, "recover me")
    await owner.close()
    replacement = RoomService(owner.keys, relay.sender(owner.keys), owner.journal.path.parent)
    await replacement.open()
    relay.services[owner.me] = replacement
    relay.fail.clear()
    await replacement.flush()
    await relay.drain()
    assert [m["text"] for m in await bob.history(room)] == ["recover me"]
    assert [m["text"] for m in await carol.history(room)] == ["recover me"]


async def test_membership_does_not_reveal_previous_history(network):
    relay, (owner, bob, _) = network
    room = await owner.create_room("No backfill")
    await owner.send(room, "before joining")
    await owner.invite(room, bob.me)
    await relay.drain()
    await bob.respond(room, True)
    await relay.drain()
    assert not await bob.history(room)
    await owner.send(room, "after joining")
    await relay.drain()
    assert [m["text"] for m in await bob.history(room)] == ["after joining"]


async def test_response_replay_does_not_add_duplicate_members(network):
    relay, (owner, bob, _) = network
    room = await owner.create_room("Replay")
    await owner.invite(room, bob.me)
    await relay.drain()
    await bob.respond(room, True)
    duplicate = relay.queue[0]
    relay.queue.append(duplicate)
    await relay.drain()
    assert (await owner.rooms())[0]["members"].count(bob.me) == 1


async def test_database_failure_does_not_publish(network, monkeypatch):
    _, (owner, _, _) = network
    room = await owner.create_room("Durability")

    async def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(owner.journal, "write", fail)
    with pytest.raises(OSError, match="disk full"):
        await owner.send(room, "must not be published")
    assert not await owner.history(room)


async def test_broken_owner_chain_disables_sending(network):
    room = await joined(network)
    _, (owner, bob, _) = network
    proof, _ = await owner._room(room)
    conflict = create(
        owner.keys,
        room,
        "state",
        {
            **proof.payload,
            "revision": proof.payload["revision"] + 1,
            "previous_state_id": "ab" * 32,
        },
    )
    with pytest.raises(RoomError, match="conflicting"):
        await bob.ingest(owner.me, conflict.wire)
    assert (await bob.rooms())[0]["conflict"]


async def test_nonmember_message_is_rejected_without_buffering(network):
    _, (owner, bob, _) = network
    room = await owner.create_room("Owner only")
    proof, _ = await owner._room(room)
    event = create(bob.keys, room, "message", {"text": "outsider", "state": proof.signed})
    with pytest.raises(RoomError, match="not a member"):
        await owner.ingest(bob.me, event.wire)
    assert not await owner.history(room)
    assert not await owner.journal.rows("SELECT id FROM deferred")


async def test_two_rooms_keep_messages_separate(network):
    first = await joined(network)
    relay, (owner, bob, _) = network
    second = await owner.create_room("Other room")
    await owner.invite(second, bob.me)
    await relay.drain()
    await bob.respond(second, True)
    await relay.drain()
    await owner.send(first, "first room")
    await bob.send(second, "second room")
    await relay.drain()
    for service in [owner, bob]:
        assert [m["text"] for m in await service.history(first)] == ["first room"]
        assert [m["text"] for m in await service.history(second)] == ["second room"]


async def test_corrupt_store_is_preserved_and_connection_closed(tmp_path):
    from toad.extensions.dega_panel.rooms.journal import Journal
    import sqlite3

    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a database")
    journal = Journal(path, Keys.generate())
    with pytest.raises(sqlite3.DatabaseError):
        await journal.open()
    assert journal._db is None
    assert path.read_bytes() == b"not a database"


def test_random_text_never_escapes_protocol_error():
    from hypothesis import given, strategies as st

    @given(st.text())
    def check(value):
        with pytest.raises(RoomError):
            decode(value)

    check()


@pytest.mark.parametrize("change", [{"version": 2}, {"unexpected": True}, {"payload": None}])
async def test_signed_unsupported_or_malformed_envelope_is_rejected(network, change):
    from nostr_sdk import EventBuilder, Kind

    _, (owner, _, _) = network
    room = await owner.create_room("Strict protocol")
    proof, _ = await owner._room(room)
    data = json.loads(json.loads(proof.signed)["content"])
    data.update(change)
    unsigned = EventBuilder(Kind(4), json.dumps(data)).finalize_unsigned(owner.keys.public_key())
    with pytest.raises(RoomError):
        decode(owner.keys.sign_event(unsigned).as_json())

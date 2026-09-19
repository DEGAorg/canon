# Rooms

Open **Ctrl+G → DEGA → Chat**. Expand **Rooms** and use **New room** to create a conversation.
Profile, Contacts, and Rooms can each be collapsed. Long lists scroll independently;
selecting a contact or room opens it in the shared conversation area.
In **Members and settings**, choose an existing contact and select **Invite**.
Invitees see the room in their list and can accept or decline.

Adding a contact is still a local address-book operation. Room invitations do not
write to a blockchain or require a token transaction.

The creator owns the room and can rename it, invite people, revoke invitations,
remove members, or close it. Other members can leave. Destructive actions ask for
confirmation. Closed, left, or removed rooms retain their local history.

Acceptance waits for the owner to come online and confirm membership. Once active,
members exchange individually encrypted messages without routing through the owner.
New members receive future messages, not previous history. All participants need
a Canon version supporting rooms.

Membership updates are asynchronous. Someone offline may send using older
membership until receiving the update. Removal does not erase already received
messages. There are no moderators, ownership transfer, or read receipts in v1.

## History and delivery

Room state, encrypted message bodies, and outgoing delivery intent are persisted
under `~/.canon/rooms/<chat-public-key>.sqlite3`. Files are identity scoped; private
keys are not copied into them. Room names and member lists are local metadata.

Room messages are saved before publication. Failed recipients can be retried from
the room screen; retries also run in the background. Published recipients are not
retried. Pending sends to people removed in the latest known state are cancelled.
A successful publication means the relay accepted it, not that a person read it.

New DMs are also saved locally, without changing their existing wire format.
This does not recover older outgoing messages that were never persisted.
History is shown oldest first, with a stable tie-breaker for equal timestamps.

## Local agent commands

The existing `canon-ctl raw` interface uses the same room service as the UI:

```sh
canon-ctl raw '{"cmd":"room","action":"list"}'
canon-ctl raw '{"cmd":"room","action":"create","name":"Launch team"}'
canon-ctl raw '{"cmd":"room","action":"invite","room_id":"ROOM_ID","pubkey":"HEX_KEY"}'
canon-ctl raw '{"cmd":"room","action":"respond","room_id":"ROOM_ID","accept":true}'
canon-ctl raw '{"cmd":"room","action":"send","room_id":"ROOM_ID","text":"Hello team"}'
canon-ctl raw '{"cmd":"room","action":"history","room_id":"ROOM_ID"}'
canon-ctl raw '{"cmd":"room","action":"members","room_id":"ROOM_ID"}'
canon-ctl raw '{"cmd":"room","action":"rename","room_id":"ROOM_ID","name":"New name"}'
canon-ctl raw '{"cmd":"room","action":"remove","room_id":"ROOM_ID","pubkey":"HEX_KEY"}'
canon-ctl raw '{"cmd":"room","action":"leave","room_id":"ROOM_ID"}'
canon-ctl raw '{"cmd":"room","action":"close","room_id":"ROOM_ID"}'
canon-ctl raw '{"cmd":"room","action":"retry"}'
```

Replace placeholder IDs/keys with returned values. Socket mutations are explicit
commands and do not display UI confirmation dialogs. Retry covers unresolved
deliveries across all rooms. Run only one Canon process per chat identity.

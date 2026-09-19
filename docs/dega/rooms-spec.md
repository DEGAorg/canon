# Rooms — technical specification v0.1

Status: Approved by the user in this task (2026-09-16).
Worktree: canon-app-rooms. Branch: feat/chat-rooms.
Base: 53f8ba8 (PR #7, including its merge-conflict resolution).

Purpose: define rooms as separate conversations alongside direct messages, using
existing identities and encrypted relay transport. The user approved this model;
the service, TUI, and socket commands now implement the first version.

## 0. Legend

- 🟩 Decided: established by the user or verified in the current implementation.
- 🟩 Approved: accepted scope for this implementation.

## 1. Principles

- 🟩 Adding a contact is local. Inviting someone to a room is a separate action.
- 🟩 No blockchain membership transactions, token gating, or new registration fees.
- 🟩 A public key identifies a participant; a display name does not prove identity.
- 🟩 Private conversations remain isolated from rooms and from each other.
- 🟩 Room creation, membership changes, and messages survive process restarts.
- 🟩 Persist encrypted message bodies; never persist private keys in room records.
- 🟩 UI and agent operations use the same application service and state transitions.

## 2. Existing system and boundary

Baseline before this implementation:

- `chat_protocol.py`: NIP-44 encryption, signed kind-4 relay events, inbound DM fetch.
  Each send currently creates a fresh relay event and returns its event ID.
- `chat.py`: recipient-specific UI, drafts, local sent messages, inbound polling.
  Sent messages currently disappear on restart. The polling path returns decrypted
  dictionaries and loses the signed event needed for independent verification.
- `chat_contact.py`: a wallet-keyed local contact directory with optional public keys.
- `chat_store.py`: ciphertext-only inbox cache, currently used by offline transport.
  It has no outbound delivery state and is not a sufficient room database.

🟩 Inside scope: room protocol/model, local durable journal and outbox, membership
service, transport adapter, room UI, and room commands through the existing socket
controller. Extend DM persistence through the same journal without changing DM wire
content. No relay hosting, smart-contract changes, shared group secret, ownership
transfer, moderator roles, attachments, read receipts, or historical backfill for
new members in this first version.

## 3. Product behavior

🟩 A creator chooses a room name and becomes its owner and first member. The owner
invites existing contacts with valid chat keys. Invitees explicitly accept or
decline. Accepting becomes active only after an owner-issued membership update;
show “Waiting for room owner” if the owner is offline. Pending invites cannot send.

🟩 Every active participant can send messages. Each message is encrypted separately
for the current recipients; delivery cost grows with room size. No new group-key
exchange is needed. Successful relay publication is not a read receipt.

🟩 The owner can rename the room, invite, revoke invitations, and remove members.
Members can leave. The owner can close a room but cannot leave it without closing
it; ownership transfer is deferred. Removed/left/closed conversations remain
readable locally and disable sending.

🟩 Joining does not fetch earlier message bodies. Removing someone does not erase
copies they already received. Membership converges asynchronously: an offline
sender with stale membership can still encrypt to a removed member until it learns
the update. This first version does not promise immediate global revocation.

## 4. Wire contract

🟩 Room payloads travel inside the existing encrypted relay transport, using the
reserved prefix `canon-room/1\n` followed by a signed Nostr event serialized as JSON. Its content is the strict
JSON envelope below; this inner signature survives encrypted transport and retries. Ordinary
DM text remains unchanged. Parse prefixed messages before routing to DM history.
Malformed/unsupported room payloads produce a protocol error, not a DM bubble.

Common envelope (unknown fields rejected):

```text
RoomEnvelope = {
  version: 1,
  id: UUID,                        # logical operation/message ID; stable on retry
  room_id: "<owner hex pubkey>:<UUID>",
  type: "invite" | "accept" | "decline" | "leave" | "state" | "message",
  created_at: nonnegative integer, # Unix seconds
  payload: variant below
}
```

The authenticated author comes from the verified inner signature and must match
the transport sender. The recipient is the local decrypting identity, never a
claimed JSON sender field. Validate UUIDs and 32-byte hex public keys.
Bounds: room name 1–80 characters after trimming; text 1–8,000 characters;
maximum 50 active members including the owner; reject oversized payloads before
parsing. These are local usability/resource limits, not token enforcement.

```text
invite  = {invite_id: UUID, recipient: Pubkey, state: SignedOwnerState}
accept  = {invite_id: UUID}
decline = {invite_id: UUID}
leave   = {state_revision: integer}
state   = {revision: integer, previous_state_id: EventID | null,
           name: string, closed: bool, members: list[Pubkey],
           pending_invites: list[{invite_id: UUID, recipient: Pubkey}]}
message = {text: string, state: SignedOwnerState}
```

🟩 `SignedOwnerState` is the complete signed Nostr event containing an owner-authored
state envelope, verifiable with the installed SDK. It is embedded *inside*
recipient encryption, never published as a public member list. Include the same
signed state proof with every room message so out-of-order delivery does not
require the owner online to verify its membership snapshot. Unknown room messages
do not create an accepted room or enroll the local identity automatically.

🟩 State revision starts at 0 and increases by one for each owner mutation. Preserve
verified state history; use previous-state IDs to detect conflicting branches.
Do not silently choose between two different owner states with the same revision:
mark a conflict and disable mutations until resolved. One writer per identity
is the supported initial model; multi-device concurrent ownership is deferred.

## 5. Interfaces and state transitions

🟩 Async service methods are independent of Textual widgets. Envelopes are frozen
dataclasses; service query results are JSON-compatible dictionaries. Protocol and
authorization failures use `RoomError(code, message, retryable)`; local storage
errors remain explicit exceptions and are shown by the TUI/socket handler.

| Interface | Behavior |
|---|---|
| `create_room(name) -> str` | Persist owner state revision 0 and return room ID. |
| `invite(room_id, recipient) -> str` | Owner only; persist pending membership and invitation; reuse a pending invitation. Already-active members produce an error. |
| `respond(room_id, accept) -> str` | Persist answer and send it to owner. Unavailable invitations produce an error; relay replays are deduplicated. |
| `manage(room_id, action, value)` | Rename, remove/revoke, or close; owner only. |
| `leave(room_id)` | Disable local sending and ask owner to update membership. |
| `send(room_id, text) -> str` | Persist message and recipient outbox before publishing. |
| `ingest(sender, wire) -> bool` | Verify signatures, membership, and deduplication; False for ordinary DMs. |
| `flush()` | Retry all unresolved eligible recipients across rooms, preserving logical IDs. |
| `history(room_id) -> list[dict]` | Local messages ordered by timestamp and stable ID; no pagination in v1. |
| `rooms()`, `unresolved(room_id)` | Room projections and outstanding publication count. |

🟩 Owner processes acceptance/leave messages serially and issues the corresponding
state. Membership changes distribute to affected participants and pending invitees
where needed. A declined or revoked invite cannot be accepted by replaying an old
response. Re-invitation creates a new invite ID.

🟩 Deduplicate by `(room_id, authenticated_author, logical_id)`, not only relay event
ID: republishing after an uncertain send can yield a different relay event. Same
logical ID with different content is a conflict, not an update.

🟩 For incoming messages, verify sender and local recipient membership in the
attached owner state and that the local user accepted this room. If a newer known
state removes the sender or closes the room, hold older-state arrivals as stale
instead of treating them as new current-room messages. Previously accepted history
remains visible. This conservative policy may hold delayed legitimate messages;
the UI must explain the stale-state status rather than silently discard them.

## 6. Persistence, errors, and UI

🟩 Add an identity-scoped SQLite journal under the existing Canon config directory;
use the installed `aiosqlite`, not a new dependency. Store signed event proofs,
local encrypted copies of outgoing bodies, encrypted incoming events, membership
projections, invitation responses, and per-recipient publication outcomes.
Encrypt the local outbound copy for the current identity using the existing key.
Projection metadata (IDs, names, membership, timestamps) is local plaintext in a
0600 file under a 0700 directory; message bodies remain ciphertext. Ensure database
sidecar files inherit equivalent protection. No private-key columns.

🟩 For room operations, persist outbound content and delivery intent before network I/O;
mark each acknowledgement after publication. Persist inbound events and dedup state
before advancing the UI. Resume pending work after restart; storage failure must
not pretend a message or membership operation succeeded. Do not truncate a corrupt
store or fall back to an empty history.

🟩 Per-recipient delivery states: `pending`, `published`, `failed`, `cancelled`.
Partial publication is represented by mixed per-recipient outcomes.
Membership: `invited`, `joining`, `active`, `declined`, `left`, `removed`, `closed`.
Errors: `invalid_payload`, `not_owner`, `not_member`, `invite_unavailable`,
`state_conflict`, `transport_unavailable`, `storage_unavailable`.
Use structured logs with operation/room IDs; omit plaintext and secrets.

🟩 UI: collapsible Profile, Contacts, and Rooms sections inside Chat; New room; room header with name,
member count, and member details; invitation Accept/Decline actions; owner member
controls; Leave/Close actions with confirmation. Preserve selected conversation and
drafts across background refreshes. Never show protocol JSON in private history.
Use per-recipient failure information with a Retry action for partial publication.

🟩 Expose list/create/invite/respond/send/members/leave/remove/rename/close/retry
through the existing local socket command mechanism, using the same service methods.
No independent mutation logic in the UI or socket handlers.

## 7. Approved decisions and review

🟩 User direction is settled: local DM contacts, separate room invitations, no
blockchain membership or token enforcement.

🟩 Approved by the user on 2026-09-16, including these tradeoffs:

1. Membership changes need the owner online to finalize; ordinary room messages
   do not. This avoids introducing a hosted coordinator.
2. Invitation acceptance, creator-only membership administration, and no previous
   history for newly joined members.
3. Durable local encrypted history/outbox, with asynchronous membership convergence
   rather than an immediate-revocation guarantee.

QA review: room envelopes, persistence, invitation acceptance, and a durable room
outbox live in a separate service rather than in ChatView. Controlled relay tests
exercise actual signatures and encryption; Textual pilots exercise room actions.
No credentials or external deployments are needed to test the first version.

## 8. Verification targets

- [x] Three independent test identities create, invite, accept, and exchange messages.
- [x] A DM and two rooms involving the same people never mix history or drafts.
- [x] Unknown fields, malformed payloads, unsupported versions, forged ownership,
      replayed acceptance, duplicate delivery, and state conflicts have tested outcomes.
- [x] Restart each participant with the same identity: both directions of history,
      membership and incomplete deliveries recover without duplicates.
- [x] Partial publication retries only unresolved eligible recipients.
- [x] Membership changes, leave, close, and delayed events follow documented semantics.
- [x] Room service has no registry dependency or blockchain write path.
- [x] UI and socket dispatch create/send/history use the same service.
- [x] Existing DM tests continue passing; wide/narrow TUI and keyboard flows verified.
- [x] Tests use temporary identity/state directories, real local encryption, and a
      controlled transport boundary; no unsolicited live messages or transactions.

## 9. Version history

- v0.1 (2026-09-16): inspected the current implementation and drafted the proposed
  room model, protocol, persistence, behavior, and completion criteria. Reviewed
  for DM isolation, restart safety, owner-offline behavior, and delivery ordering.
  Status: Approved by the user (2026-09-16).

## 10. Implementation notes

New sent/received DMs are encrypted in the same identity-scoped store and restored
on startup. Their existing transport remains unchanged: DM publication precedes the
local history write, so a storage failure after publication is reported explicitly.
Room messages use the durable outbox. Earlier locally lost outgoing DMs cannot be
reconstructed by this change.

Tests cover three identities, restart, encryption at rest, out-of-order state,
duplicate delivery, replayed acceptance, broken/conflicting owner states,
partial delivery, removal, leave/close, no pre-join history, malformed envelopes,
unknown-room buffering, separate conversations, storage failure, socket commands,
and narrow/wide TUI creation/send/cancel/confirm. Live relay delivery is not part of
automated verification. First version supports one running writer per identity.

Validation: 96 focused tests passed; Ruff and scoped mypy passed. A temporary
mutation removing retry membership filtering was caught by its regression test.
The isolated DEGA panel smoke test also passed, including two-tab keyboard
cycling and the existing private-message flow.

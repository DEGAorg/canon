# Chat presence

Status: implemented and locally validated. The user authorized the proposed opt-in public
presence version and a PR on 2026-09-15. Technical defaults below are local design
choices; no backend API or contract changes are required.

## Contract

- NIP-38 kind 30315, `d=canon-presence`, content `online`, signed with the chat key.
- NIP-40 `expiration` equals creation time plus 90 seconds. Publish at most every
  30 seconds while the registered user's Chat view is visible and sharing enabled.
- Sharing defaults off and persists per public key in local `chat-presence.json`
  with mode 0600. UI says that sharing is public on Nostr before opt-in.
- Poll known contact keys every 15 seconds through the configured chat relays.
  Connection, publish and fetch operations are bounded by timeouts and cleaned up.
- Accept only verified events for requested authors, the exact kind/status/type,
  creation time no more than 15 seconds ahead, and an expiration no more than
  90 seconds after creation. Expired or malformed events never imply online.
- On read failure, clear online indications and retry next interval. Reading
  presence does not require publishing the user's own presence.
- Closing/hiding Chat or disabling sharing stops new heartbeats. Existing events
  expire within 90 seconds. No offline event is sent: closing one client must not
  override another still-active client using the same identity.
- Presence is an approximate active-client signal, not proof that a person is
  reading. Users can publish their own status; signatures prevent impersonation,
  not dishonest claims of activity. Expiration is not guaranteed relay deletion.

## UI

Contacts with a fresh event have a green dot and an Online tooltip. The selected
recipient's status is also displayed as text. Absence of a fresh event is unknown,
not Offline. A right-aligned neutral `!` help button separately indicates a missing
chat key, with mouse and keyboard explanations. Missing keys block sending; absence
of presence never blocks sending.

## Acceptance

- Default off, opt-in persistence and no publish when off/hidden/unregistered.
- Valid signed events show online; malformed, expired, wrong-author, future-dated,
  excessive-lifetime and invalid-signature events do not.
- Relay failures clear online status, retry recovers, and cancellation disconnects.
- Real SDK signatures and two clients exchanging presence through an isolated
  local relay; no user keys or public activity published during automated tests.
- UI controls work with mouse and keyboard, before/after registration, and in
  narrow/wide terminal layouts. Existing chat and login behavior remains covered.

References: [NIP-38](https://github.com/nostr-protocol/nips/blob/master/38.md),
[NIP-40](https://github.com/nostr-protocol/nips/blob/master/40.md).

Validation: 45 targeted tests pass, including two real Nostr SDK clients using a
local relay. UI and authentication harnesses pass. Ruff and scoped mypy checks
pass. Mutation checks confirm expiry and opt-out regressions are detected.
Public-relay interoperability and a macOS-to-WSL session remain release checks.

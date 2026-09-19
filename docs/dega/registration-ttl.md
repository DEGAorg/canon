# Registration expiration and renewal

Registration is time-limited. Its duration and DEGA fee are contract constructor parameters;
the registry owner can change them with `setRegistrationTTL` and `setFee`. A zero fee is
allowed; duration must be positive. Changes apply to future registration/renewal operations.

`openNode` records `expiresAt = block.timestamp + registrationTTL`. At that exact timestamp,
name-to-key, key-to-name, wallet-to-active-name and active membership queries stop returning
the registration. No cleanup transaction or background service is needed.

The wallet retains its name, Nostr key and members. `usernameTaken` remains true (reservation);
`registrationOfOwner` returns administrative status even after expiry. Renewal charges the
current fee and sets expiry to `max(currentExpiry, block.timestamp) + registrationTTL`.
A stale expiry or changed duration/fee limit rejects the renewal before any charge.

In Canon, **Registration** shows Active/Expired and the expiry date in UTC. **Renew** shows
fee and duration before confirmation. Existing conversations and message history remain
available; expiry removes active discovery, not Nostr keys. Online presence is separate.
RPC errors show **Unable to check** with **Retry**, not a new registration form.

## Transaction recovery

Canon saves a signed renewal before broadcasting, under
`~/.canon/registration-renewals/<chain>-<registry>-<wallet>.json`, mode 0600. It contains no
private key, but can rebroadcast the authorized transaction. On timeout/restart, retrying
checks or rebroadcasts that same transaction rather than buying another period. A pending
transaction retains its original terms; the confirmation panel offers **Check transaction**
instead of another purchase.
A mined revert or externally replaced transaction is surfaced for a fresh confirmation.
Do not delete a pending record while its transaction is unresolved.

## Deploy and configure

1. Build/test the contract; deploy to a testnet with an explicit fee and duration (or use the TTL
   deploy already on Sepolia, `0x50600d8D8BA6F36F51A81d70B891e7cC81E8C8fe`).
2. Verify `registrationTTL()`, `fee()`, `degaToken()` and `registrationOfOwner(wallet)`.
3. Update `DEGA_CHAT_REGISTRY` and `DEGA_CHAT_RPC` in `~/.canon/dega-chat.env`.
   Existing files are preserved by the generator, so this is a manual edit on an existing install.
   The shipped code defaults (`registry_client.py`, the `auth_store.py` template and
   `tests/test_dega_env_scaffold.py`) still identify the non-TTL v3 registry; move them together
   when the TTL deploy becomes the shipped default.
4. Test registration, expiry and renewal with the same wallet; repeat after restarting Canon.
5. Deploy the production contract with the chosen token, owner, fee, duration and member cap.
   Update shipped defaults/docs/config together before releasing the client.

This is a new contract deployment, not an upgrade to v3. Existing registrations are not
copied; arrange re-registration before switching production. On Sepolia a TTL registry is already
deployed (`0x50600d8D8BA6F36F51A81d70B891e7cC81E8C8fe`) and is configured in `~/.canon/dega-chat.env`;
the shipped code default has not moved to it yet. Instructions:
[testnet](contract-deploy-testnet.md), [mainnet](contract-deploy-mainnet.md).

## Implementation decisions

Implementation authorized by Alberto on 2026-09-16, based on
`feature/dega-canon-app` at `4269231`. Work is isolated in `feat/chat-registration-ttl`.
The implementation uses the current registration fee for renewal, reserves expired names,
and preserves existing conversations. Initial fee/duration and deployment addresses remain
operator inputs. No legacy-registry fallback or migration is included.

## Local validation

```bash
forge build --root src/toad/extensions/dega_panel/contracts
forge test --root src/toad/extensions/dega_panel/contracts
PYTHONPATH=src python -m pytest tests/test_registration_ttl.py tests/test_registration_chain.py
```

The Python chain tests start isolated Anvil nodes and use newly generated, locally funded
wallets. They exercise real token approvals, registration, chain-time expiry, renewal,
fee/duration changes, and lost-confirmation recovery without touching a public chain.

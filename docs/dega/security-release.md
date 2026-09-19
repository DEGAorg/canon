# Release security changes

The controller socket now lives at `~/.canon/sockets/toad-PID.sock`. The directory is
restricted to its owner (0700) and the socket to that user (0600). Update external
scripts using the former `/tmp` path. `canon-ctl` discovers the new location. This
isolates other OS users; processes running as the same user still control Canon.

Registration and renewal call the token's `burnFrom(payer, fee)` using the payer's
approval. This reduces total supply in the same transaction.
A failed burn reverts the entire operation. `FeeBurned` records payer and
amount. Zero fees skip the token call. No withdrawal function remains. Unsolicited
token deposits are not part of the fee and cannot be withdrawn; do not send them here.
This requires a new registry deployment and a token implementing ERC20Burnable.
Existing deployed registries cannot be upgraded by changing this source.

## Nostr key ownership

Registration now requires an EIP-712 proof signed by the active Nostr secret,
verified directly by the registry. A wallet signature alone is not accepted as
proof of a different Nostr identity. The proof binds the registering wallet,
username, chain ID, and registry address. Keys and wallets remain reserved after
expiry, preventing reuse of an already accepted proof. Renewal preserves identity.
See [the proof specification](nostr-registration-proof.md) for encoding and tests.

This closes the unproven-key registration path in source. It requires deploying
the new registry and releasing the matching client ABI; existing registries remain
unchanged and must not be presented as providing this protection.

# DEGA/Canon — chat P2P, contrato y trading LIVE

> **Superseded:** this file has been consolidated into
> [docs/dega/](dega/README.md) — see [sandbox-live.md](dega/sandbox-live.md) and
> [contracts.md](dega/contracts.md). Kept here as a historical redirect; the addresses below may
> be stale (the active testnet deploy is documented in `docs/dega/contracts.md`).

## (Historical) chat P2P
The token-gated P2P chat lives in the TUI (`dega_panel/chat.py` → `ChatView`), chain backend by
default, Nostr over public relays.

## (Historical) contract
`contracts/DegaChatRegistry.sol`: `openNode(string,bytes)`, `resolveNostrPubkey`,
`usernameTaken`, `invite`, fee in $DEGA via `transferFrom` (plus the registration-TTL and rooms work
added later). The "7/7 forge tests PASS" figure in this note is long outdated — current counts and
commands are in [docs/dega/testing.md](dega/testing.md).

See current deploy addresses in [docs/dega/contracts.md](dega/contracts.md).

## (Historical) trading LIVE
`L` in the catalogue → `run_live` → `LIVE` confirm → `npm run <script> -- --live`. Real orders
only with `--confirm-real` + funded wallet (blocked by default).

---

See the consolidated index: [docs/dega/README.md](dega/README.md).
Registration requires a local Nostr ownership proof; see [proof specification](dega/nostr-registration-proof.md).

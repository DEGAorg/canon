# DEGA / Canon — Documentation Index

Central index of the DEGA integration in the Canon TUI (Toad fork, AGPL-3.0).
These documents consolidate and supersede the loose files `docs/dega-chat-and-live-status.md`
and `docs/dega-runbook-operations.md`, which are kept as historical redirections.

## Index

| Doc | Content |
|-----|---------|
| [setup.md](setup.md) | Requirements, install (dev vs installed), repo layout |
| [configuration.md](configuration.md) | Environment variables and on-disk state (`~/.canon/*`) |
| [rooms.md](rooms.md) | Encrypted rooms — user guide + `canon-ctl raw` room commands |
| [rooms-spec.md](rooms-spec.md) | Rooms technical specification (approved 2026-09-16) |
| [chat-presence.md](chat-presence.md) | Opt-in public presence (NIP-38 / NIP-40) |
| [registration-ttl.md](registration-ttl.md) | Registration expiry, renewal and transaction recovery |
| [contracts.md](contracts.md) | Contract architecture, active addresses, tests, deploy |
| [contract-deploy-testnet.md](contract-deploy-testnet.md) | Step-by-step Sepolia redeploy incl. the registry-only `forge create` path |
| [contract-deploy-mainnet.md](contract-deploy-mainnet.md) | Production (mainnet) deploy with the real $DEGA token |
| [testing.md](testing.md) | What tests have been run and how to run them |
| [backend-runbook.md](backend-runbook.md) | Running the Encore backend, device-flow auth model, cookie policy, DB networking |
| [sandbox-live.md](sandbox-live.md) | Validated E2Es: real Nostr chat, resident bot, trading |
| [strategy-access.md](strategy-access.md) | Protected strategy delivery via the Encore backend (canon-app#2) |
| [review-macos-2026-09-11-triage.md](review-macos-2026-09-11-triage.md) | macOS review triage + follow-up status (F1–F7, A1–A3) |

## Current defaults (2026-09-18)

- **Chat backend:** `chain` by default; `simulated` is for isolated tests.
- **First-run configuration:** a fresh install writes `~/.canon/dega-chat.env` with mode 0600,
  pointing at the production backend and Ethereum mainnet registry. Existing files are preserved.
- **Production registry:** `0x4c698AC2f25dD82386658080223583e0EEbB523f` on chain ID 1,
  using DEGA `0x97aeE01ed2aabAd9F54692f94461AE761D225f17` (18 decimals).
  Verified contract values: fee **6,719,270 DEGA**, registration duration **365 days**, and
  node capacity **10**. These are on-chain settings, not environment overrides.
  See [configuration.md](configuration.md) and [contracts.md](contracts.md).
- **Rooms:** encrypted, invite-based, **off-chain** group conversations (no registry or token
  writes, no expiry model). See [rooms.md](rooms.md) and [rooms-spec.md](rooms-spec.md).
- **Presence:** opt-in public online signal, **off by default**; absence of a signal is "unknown",
  never "offline". See [chat-presence.md](chat-presence.md).
- **Earlier addresses:** `0x89fe...`/`0x0c18...` (08-31), `0x5FF8...`/`0xC577...` (09-04,
  allowed multi-node — do not use), `0x4b5f...`/`0x4f72...` (09-06). Full history in
  [contracts.md](contracts.md).
- **Strategies:** delivery is backend-authorized only (`GET /strategies/*` on the agents API).
  The 11 catalogue archives live in the backend repo (`backend/strategies/`) and reach prod by a push to
  `master`; there is **no public GitHub/codeload fallback** — a signed-in user with a current
  element grant downloads via the backend, and without a session install fails with an actionable
  message. See [strategy-access.md](strategy-access.md).
- **macOS review follow-up (2026-09-12):** all six review findings are resolved and verified with
  real execution (contract reads, a real Postgres, the real market-forecast package). The typeORM
  schema fix for `users.id` is load-bearing (reverting it fails the DB suite), the fee scale comes
  from the contract, and both test stacks are green. See
  [review-macos-2026-09-11-triage.md](review-macos-2026-09-11-triage.md) and
  [testing.md](testing.md).

## Elements / gating

The panel's element inventory is not user-editable. It is fetched from the DEGA API
(`GET /elements-aggregation/v2/by-email`) during login, persisted in auth state,
and used as a read-only snapshot while the panel is open.

Strategy purchase rules and durations are configured in the backend database.
Activation permanently consumes elements and grants timed access. Canon checks a
local grant before launching and synchronizes remotely after expiry; existing runs
continue. Local gating.json does not control strategy permissions.
See [timed strategy access](strategy-access.md) for activation and rollout details.

## Quick commands

```bash
# TUI with the DEGA panel (dev, always local source)
cd ~/projects/DEGA/canon-app && uv run canon .

# Headless verification after UI changes
uv run python tools/verify-tui.py --widget dega

# Read-only production contract health checks (no signer required)
RPC=https://ethereum-rpc.publicnode.com
R=0x4c698AC2f25dD82386658080223583e0EEbB523f
cast chain-id --rpc-url $RPC                              # 1
cast call $R "fee()(uint256)" --rpc-url $RPC              # 6719270000000000000000000
cast call $R "maxUsersPerNode()(uint256)" --rpc-url $RPC   # 10
cast call $R "registrationTTL()(uint256)" --rpc-url $RPC   # 31536000
cast call $R "degaToken()(address)" --rpc-url $RPC
```

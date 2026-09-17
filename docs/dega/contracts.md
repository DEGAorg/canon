# DEGA / Canon — Contract (DegaChatRegistry)

Documentation of the Solidity contract behind the token-gated P2P chat and node registry.

## Location

```
src/toad/extensions/dega_panel/contracts/
├── DegaChatRegistry.sol     # Main registry
├── MockDEGA.sol             # Mintable testnet token (fees)
├── IERC20.sol               # ERC-20 interface
├── script/Deploy.s.sol      # One-shot production deploy (real token)
├── script/DeployTestnet.s.sol  # Testnet deploy (MockDEGA + registry)
├── test/Registry.t.sol      # Forge tests: registration, fee, cap, pubkey
├── test/Expiry.t.sol        # Forge tests: registration TTL, renewal, rollback
├── test/Fuzz.t.sol          # Fuzz + invariant suites (stateful handlers)
├── foundry.toml             # src=".", solc 0.8.20
├── broadcast/...            # Deployment records (testnet)
├── cache/... out/...        # Build artifacts (gitignored)
└── lib/forge-std/           # Foundry submodule
```

## Key `DegaChatRegistry` interfaces

| Function | Behavior |
|----------|----------|
| `openNode(string username, bytes nostrPubkey, bytes proof)` | Verifies Nostr key ownership bound to wallet/name/chain/registry, registers the unique identity, and atomically transfers and burns the DEGA fee (0 = free tier) |
| `resolveNostrPubkey(string name)` | Returns the active node's Nostr key; empty at expiry |
| `usernameTaken(string name)` | Availability check (normalizes bare or `.dega`) |
| `invite(string username, address wallet)` | Adds an EVM member to the node |
| `degaToken() → address` | Fee token used |
| `fee() → uint256` | Current fee in weega |
| `maxUsersPerNode() → uint256` | Users per-node cap |
| `usernameOfOwner(address) → string` | Username bound to a wallet |
| `usernameForPubkey(bytes) → string` | Reverse lookup: bare username registered for a Nostr pubkey (labels inbound DMs from people you never invited) |
| `setFee(uint256)` | Changes registration and renewal fee (owner only) |
| `registrationTTL()` / `setRegistrationTTL(uint256)` | Positive duration in seconds; owner can update for future periods |
| `isActive(string)` | True only before expiration |
| `registrationOfOwner(address)` | Administrative status including expired username, owner, openedAt, expiresAt, memberCount, active, checkedAt |
| `renewNode(string,uint256,uint256,uint256)` | Owner renews with expected expiry, maximum fee and expected TTL |

Design rules:
- An address owns **exactly one** username (`openNode` reverts with "owner already has node").
- The Nostr keypair is derived from the on-chain signer (`wallet <-> nostr pubkey <-> nombre.dega`
  are one key).
- Both directions are stored privately. Discovery returns empty results once expired.
- Names remain reserved to their wallet; renewal preserves keys and members.
- Registration expires at `openedAt + registrationTTL`; renewal extends from the later of now or current expiry.
- See [registration-ttl.md](registration-ttl.md) for behavior and rollout requirements.

## Deployed addresses

Verified on-chain 2026-09-16. Several Sepolia registry deploys coexist:

- the **shipped default** (used by `registry_client.py`, the `auth_store.py` autogen template and
  `tests/test_dega_env_scaffold.py`) is the **09-15 v3** deploy, which has **no** `registrationTTL`;
- the **TTL deploy** (09-16) is what `~/.canon/dega-chat.env` on this machine points at and what the
  expiry/renewal flow requires. It is **not** a repo default (there is no `broadcast/` record for it,
  so it was created with `forge create` rather than `DeployTestnet.s.sol`).

| Deploy date | Registry | MockDEGA | fee (weega) | Notes |
|-------------|----------|----------|-------------|-------|
| 08-31 | `0x89fe6e11e64d92bb24787adf663246bc38fcf907` | `0x0c188444b0ad3d018ba4764c724a833657d0642e` | 0 (free) | old, no owner lookup, allows multi-node |
| 09-04 | `0x5FF86634Af51a5016065e2572dF67eB5270e4Fbc` | `0xC577E51f10F4A47d7afC56871830CbF0722305a7` | 5e7 | old, no owner lookup, allows multi-node (double-registration observed) |
| 09-06 | `0x4b5fbe0fe8f50e68f1c12faa8964108ae9f6494e` | `0x4F72FBB5356e433a6DCB10ed0Bc1F2647B10Fa57` | 5e7 | has owner lookup, no reverse pubkey |
| 09-15 | `0x2a536aF74177Cad23BA0F122c1Fc638c236b6fa5` | `0x5f431e1a97b18C2a81c625E01B643BC836592455` | 5e7 | v3 as produced by `DeployTestnet.s.sol` (`run-latest.json`); superseded the same day by the clean redeploy below after a test node with a non-curve pubkey was stored |
| **09-15 v3 (SHIPPED DEFAULT)** | **`0xf3D30Cf5FEBCa40Ff1E6A7254BEE34f170fAb088`** | **`0x5f431e1a97b18C2a81c625E01B643BC836592455`** | 5e7 = 0.00000000005 $DEGA (18 decimals) | one-node-per-address + `usernameOfOwner` + `usernameForPubkey`; **no `registrationTTL`** |
| **09-16 TTL (DEPLOYED, not a repo default)** | **`0x50600d8D8BA6F36F51A81d70B891e7cC81E8C8fe`** | same MockDEGA `0x5f431e1a97b18C2a81c625E01B643BC836592455` | 5e7 | adds `registrationTTL` (**86400 s**) + `renewNode`/`registrationOfOwner`; per-member expiry (`membershipPeriod`/`memberExpiry`) is **absent** — this is the shipped TTL design, not the reverted per-member experiment |

> **Redeploying on the same token loses nothing.** Pointing a new registry at the EXISTING MockDEGA
> keeps every balance, so a registry-only redeploy needs no re-funding (that is how the 09-15 v3 and
> the 09-16 TTL deploys were done). Command in
> [contract-deploy-testnet.md](contract-deploy-testnet.md).

> **Discriminating probe:** the old deploys (08-31 / 09-04) let the same wallet open multiple nodes
> AND revert `usernameOfOwner` (so the TUI reads "not registered" after relaunch). `usernameOfOwner`
> must return (possibly empty) in a `cast call` — if it reverts, the bytecode predates the source.
> Point the panel at another deploy by editing `~/.canon/dega-chat.env`
> (`DEGA_CHAT_REGISTRY` / `DEGA_CHAT_TOKEN`) — see [configuration.md](configuration.md).

> The fee format: fee() = 50000000 base units, token decimals 18 → **0.00000000005 $DEGA** (an
> 8-decimal read would print `0.5`). Gas for `openNode`/`invite` must be estimated (a fixed 300k
> cap under-estimates once the fee `burnFrom` + the reverse mapping storage is included; a fresh
> deploy needs ~480k).

## Contract tests

`forge test` in `contracts/` covers registration, TTL/renewal, reentrancy, fuzz and
stateful invariants — **24 tests in 5 suites, all passing (verified 2026-09-16)**:
`Registry.t.sol` 7 (`DegaChatRegistryTest`), `Expiry.t.sol` 10 (`RegistrationExpiryTest` 9 +
`RenewalReentrancyTest` 1), `Fuzz.t.sol` 7 (`DegaChatRegistryFuzzTest` 3 +
`DegaChatRegistryInvariantTest` 4). The invariant suites are the slow part (~3 min wall clock).

```bash
cd src/toad/extensions/dega_panel/contracts
forge test
```

> The `testUniqueUsername` case verifies that a **different** owner cannot take an already
> registered username (`vm.prank` to a second address). The one-owner-one-username rule means a
> same-owner re-register reverts with `owner already has node`, checked before `username taken`.

### Read-only health checks (no signer needed)

```bash
RPC=https://ethereum-sepolia-rpc.publicnode.com
R=0xf3D30Cf5FEBCa40Ff1E6A7254BEE34f170fAb088     # shipped default (v3, non-TTL)
cast call $R "fee()(uint256)" --rpc-url $RPC                # 50000000
cast call $R "maxUsersPerNode()(uint256)" --rpc-url $RPC    # 10
cast call $R "degaToken()(address)" --rpc-url $RPC
cast call $R "usernameOfOwner(address)(string)" 0x0000000000000000000000000000000000000000 --rpc-url $RPC  # must NOT revert (may be empty)
cast code $R --rpc-url $RPC                                   # contains bytecode
```

## Deploy

See [contract-deploy-testnet.md](contract-deploy-testnet.md) (testnet) and
[contract-deploy-mainnet.md](contract-deploy-mainnet.md) (production).
Registration requires a local Nostr ownership proof; see [proof specification](nostr-registration-proof.md).

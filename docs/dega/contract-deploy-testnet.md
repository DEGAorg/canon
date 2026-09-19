# DEGA / Canon — Contract deploy on testnet (Sepolia)

Step-by-step to deploy (or redeploy) `DegaChatRegistry` + `MockDEGA` on Sepolia and point the
panel at the new deployment.

## What `DeployTestnet.s.sol` deploys

1. `MockDEGA` (mintable token, same 18-decimal scale as the real $DEGA).
2. `DegaChatRegistry` pointing at that mock, with an initial fee (weega), positive registration TTL (seconds), and `maxUsersPerNode`.

Pass `INITIAL_FEE_WEEGA` explicitly (0 for free) and `REGISTRATION_TTL_SECONDS`. The 09-04 deploy used
`INITIAL_FEE_WEEGA=50000000` → **0.00000000005 $DEGA** at the token's 18 decimals (the panel reads
`decimals()` from the contract, so no scale is assumed).

> **Never run this on mainnet** — use `Deploy.s.sol` (see
> [deploy-mainnet](contract-deploy-mainnet.md)).

## Requirements

- `forge` + `cast` installed.
- A wallet private key (var `PRIVATE_KEY`).
- A Sepolia RPC: `https://ethereum-sepolia-rpc.publicnode.com`.

## Manual command

```bash
cd ~/projects/DEGA/canon-app/src/toad/extensions/dega_panel/contracts

PRIVATE_KEY=<hex> INITIAL_FEE_WEEGA=50000000 MAX_USERS_PER_NODE=10 REGISTRATION_TTL_SECONDS=2592000 \
forge script script/DeployTestnet.s.sol:DeployTestnet \
  --rpc-url https://ethereum-sepolia-rpc.publicnode.com \
  --broadcast --sig 'run()'
```

You should see at the end:

```
MockDEGA deployed at     : 0x...
DegaChatRegistry deployed: 0x...
  fee (weega)        : 50000000
  maxUsersPerNode    : 10
```

## Post-deploy (mint + approve + first node)

```bash
RPC=https://ethereum-sepolia-rpc.publicnode.com
PK=<hex>                      # same signer
OWNER=$(cast wallet address --private-key "$PK")

# Mint test $DEGA and approve the registry (only if fee > 0)
cast send <MOCKDEGA> "mint(address,uint256)" "$OWNER" 1000000000000000000000 --rpc-url $RPC --private-key "$PK"
cast send <MOCKDEGA> "approve(address,uint256)" <REGISTRY> 1000000000000000000000 --rpc-url $RPC --private-key "$PK"

# First test node
PUBKEY=$(uv run python -c "from toad.extensions.dega_panel.chat_identity import load_or_create_identity; k,_=load_or_create_identity(); print(k.public_key().to_hex())")
# Register through Canon Chat so the active Nostr key signs the ownership proof.
canon .

# Verify
cast call <REGISTRY> 'usernameOfOwner(address)(string)' "$OWNER" --rpc-url $RPC
```

## TTL verification

The example duration above is 30 days. Set a short duration for an expiry/renewal smoke test.
Use [registration-ttl.md](registration-ttl.md) to verify disappearing discovery and renewal.
The v3 registries in the table above do not implement these functions; the TTL flow needs the
09-16 TTL deploy (`0x50600d8D8BA6F36F51A81d70B891e7cC81E8C8fe`, `registrationTTL()` = 86400) or a
new deploy of your own — see [contracts.md](contracts.md).

## Registry-only redeploy (keeps the existing token and balances)

Preferred when you only need a clean/updated registry: deploy **only** the registry against the
**existing** MockDEGA, so no balance is lost and no wallet needs re-funding.

```bash
export PATH="$HOME/.foundry/bin:$PATH"
RPC=https://ethereum-sepolia-rpc.publicnode.com
# arg order must match the constructor: token, fee weega, max users, TTL seconds
forge create src/toad/extensions/dega_panel/contracts/DegaChatRegistry.sol:DegaChatRegistry \
  --rpc-url $RPC --private-key $PRIVATE_KEY --broadcast --optimize \
  --constructor-args 0x5f431e1a97b18C2a81c625E01B643BC836592455 50000000 10 86400
```

- `--optimize` is what makes the grown contract fit the deployer's remaining gas.
- `--gas-price` must be at or above the block base fee (~1 gwei on Sepolia) or the tx is rejected as
  underpriced; check the signer's ETH balance first — "insufficient funds" is a balance problem, not
  a bytecode problem.
- A full `DeployTestnet.s.sol` run instead creates a NEW MockDEGA, so old token balances do **not**
  carry over and every wallet must be re-funded.
- Finish by updating the address carriers together (see the note at the end of this page). A
  registry-only deploy has **no** `broadcast/` record — write the new address into the docs and
  `~/.canon/dega-chat.env` yourself.

## Where the records land

- `broadcast/DeployTestnet.s.sol/11155111/run-*.json` — each broadcast.
- `run-latest.json` — the most recent scripted deploy: 09-15, Registry `0x2a536a...` (later
  superseded by the registry-only `0xf3D30Cf5...` redeploy, which has no record here).
- `cache/.../dry-run/` — executions without broadcast.

> **An address change touches five carriers — update them together, then grep the old value across
> the repo:** `~/.canon/dega-chat.env`, `_DEFAULT_SEPOLIA_REGISTRY` in `registry_client.py`, the
> autogen template in `auth_store.py`, `docs/dega/*.md`, and `tests/test_dega_env_scaffold.py`.
> A leftover carrier silently points users at a dead registry.

> Contracts are NOT upgradeable: a storage-mapping change (e.g. the reverse `usernameByPubkey`)
> only exists in a NEW deploy. Editing `DegaChatRegistry.sol` without redeploying leaves old
> addresses running the old bytecode (which still allows multi-node and reverts `usernameOfOwner`).
> After any source change, redeploy and update `~/.canon/dega-chat.env` + the code defaults.

See [contracts.md](contracts.md) for the full address table and which one is active.
# DEGA / Canon — Production deploy (mainnet)

Guide to deploying `DegaChatRegistry` on **Ethereum mainnet** with the real $DEGA token.

> ⚠️ **You need access to the deploying wallet.** This is a sensitive on-chain change; confirm the
> fee, registration duration and `maxUsersPerNode` with the owner before `--broadcast`.

## Production contract: `Deploy.s.sol`

Unlike testnet, the production flow does **not** deploy a mock token — it uses the existing $DEGA
address on mainnet.

Real $DEGA token (mainnet, 18 decimals): `0x97aeE01ed2aabAd9F54692f94461AE761D225f17`
(noted in the `DeployTestnet.s.sol` docstring).

Script signature:

```solidity
function run(address degaToken, uint256 initialFeeWeega, uint256 maxUsersPerNode, uint256 registrationTTL) external
```

A zero fee deploys the free tier (staging/demos); `setFee` on-chain later changes it without a
redeploy — the fee is parametrizable at runtime.

## Command

```bash
cd ~/projects/DEGA/canon-app/src/toad/extensions/dega_panel/contracts

# Fee: decide the value in weega (1 $DEGA = 1e18 weega).
#   - 0            → free tier (staging/demos)
#   - otherwise, the per-node amount in weega agreed with the owner.
PRIVATE_KEY=<hex_mainnet> \
forge script script/Deploy.s.sol:DeployChatRegistry \
  --rpc-url "$MAINNET_RPC" \
  --broadcast --private-key "$PK" \
  --sig "run(address,uint256,uint256,uint256)" \
  0x97aeE01ed2aabAd9F54692f94461AE761D225f17 <FEE_WEEGA> 10 <TTL_SECONDS>
```

Example with fee 0 (free tier for staging):

```bash
PRIVATE_KEY=<hex_mainnet> forge script script/Deploy.s.sol:DeployChatRegistry \
  --rpc-url "$MAINNET_RPC" --broadcast --private-key "$PK" \
  --sig "run(address,uint256,uint256,uint256)" \
  0x97aeE01ed2aabAd9F54692f94461AE761D225f17 0 10 2592000
```

Registration and renewal both charge and burn the current fee. The registry calls
DEGA `burnFrom(payer, fee)` atomically with registration or renewal.
The payer still approves the registry first. No treasury withdrawal is available. The duration is in seconds
(2592000 = 30 days is an example, not a fixed requirement). Owners can change it with
`setRegistrationTTL(uint256)`; existing expiration dates do not change.

This TTL contract requires a **new address**. Existing v3 registrations are not migrated.
On Sepolia a TTL registry is already deployed and configured locally
(`0x50600d8D8BA6F36F51A81d70B891e7cC81E8C8fe`, `registrationTTL()` = 86400); mainnet still needs its
own deploy, and the shipped code default points at the non-TTL v3 registry until it exists.
Do not publish the updated client as ready until the mainnet address has been deployed,
verified and configured. See [registration-ttl.md](registration-ttl.md).

## After the deploy

1. Note the deployed `DegaChatRegistry` address.
2. Read-only verification:
   ```bash
   RPC=<mainnet rpc>
   cast call <REGISTRY> "degaToken()(address)" --rpc-url $RPC   # → 0x97aeE... (real token)
   cast call <REGISTRY> "fee()(uint256)" --rpc-url $RPC
   cast call <REGISTRY> "registrationTTL()(uint256)" --rpc-url $RPC
   cast code <REGISTRY> --rpc-url $RPC                            # bytecode present
   ```
3. Set an initial fee if desired: `cast send <REGISTRY> "setFee(uint256)" N` (owner only).
4. Update the app default:
   - `src/toad/extensions/dega_panel/registry_client.py` → `_DEFAULT_SEPOLIA_REGISTRY` /
     `_DEFAULT_SEPOLIA_TOKEN` (if pointing at mainnet, or add a mainnet default).
   - or `~/.canon/dega-chat.env` on each client deployment.

## Production checklist

- [ ] `PRIVATE_KEY` of a controlled, funded (gas) mainnet wallet.
- [ ] `$MAINNET_RPC` points at mainnet (never Sepolia).
- [ ] Correct token: `0x97aeE01ed2aabAd9F54692f94461AE761D225f17`.
- [ ] Fee, positive TTL in seconds and `maxUsersPerNode` agreed with the owner.
- [ ] Dry-run first: drop `--broadcast` to review.

## Deploying / promoting the client

"Production deployment" of the client (the TUI) is not a contract: it is installing the package
from `install.sh` with variables pointing at mainnet. See [configuration.md](configuration.md).

```bash
# Build/install the production app
cd ~/projects/DEGA/canon-app && bash install.sh
# on the target node point the chat at mainnet
#   ~/.canon/dega-chat.env … DEGA_CHAT_RPC=<mainnet> DEGA_CHAT_REGISTRY=<MAINNET_REGISTRY>
```
### Verify fee burning before broadcast

Run the real-token integration test on an isolated mainnet fork:

```bash
DEGA_MAINNET_RPC="$RPC" forge test --match-contract MainnetFeeBurnTest -vv
```

The test funds a simulated wallet on the fork, registers and renews, and asserts
that DEGA total supply falls by both fees while the registry retains no fee balance.
It broadcasts nothing. Without `DEGA_MAINNET_RPC` the fork test is skipped; it must
pass before deploying with the mainnet DEGA address. Testnet MockDEGA must also
be redeployed from the burnable version when testing nonzero fees.

# Cardano registration and discovery

Canon supports Cardano registration with native DEGA payments and contact discovery
across Cardano and Ethereum. Wallets are generated locally; public Koios endpoints
provide chain access without a Blockfrost account. Signing secrets stay on your computer.

## Mainnet registration

The public distribution selects the production mainnet registry by default. Its initial
registration price is **6,719,270 DEGA**, matching the Ethereum registry at deployment,
with a **365-day** registration period. ADA transaction fees and output reserves are
additional. Tokens are sent to the confirmed collector; no automatic bridge or Ethereum
burn is performed.

From the repository root, with Node.js 26 or newer available:

```sh
uv sync
uv run python -m toad.cardano_install
uv run canon
```

Select Cardano in Chat, fund the wallet address displayed in your profile and review the
current price before registering. Keep a separate ADA-only UTxO available for collateral;
collateral is normally unspent on a valid transaction. Retrying reconciles the saved
transaction rather than purchasing another registration.

The production manifest is `deployments/mainnet.json` and is also included in the Python
package. Explicit `CANON_CARDANO_DEPLOYMENT` or saved deployment settings take precedence;
remove a demo override or point it at the production manifest to use production. Existing
wallets and explicit recording configurations are preserved.

A second computer can resolve usernames and public chat keys using the same production
registry without paying a registration fee or copying wallet secrets. Ethereum and Cardano
identities share the chat transport. Registration is only needed to create an identity.

## Registry design

Each registration has a contract-held unique marker token and inline identity data.
A shared Merkle Patricia Forestry root reserves usernames, owners and chat keys.
There is no hardcoded total-registration limit; the per-room membership cap is 10.
Expiry hides an inactive registration from normal discovery but does not release its
reserved identities. Owners can renew and invite room members.

The client reconstructs and verifies the index from public records. An incomplete or
inconsistent provider response fails closed. Large-scale indexing and throughput still
need public-release validation. Simultaneous registrations can conflict on the shared
root and require a fresh transaction.

The deployable validator is `contracts/validators/registry_mpf.ak`. It always starts
with an empty uniqueness root. The separate `registry_benchmark` validator permits
synthetic roots only for local measurements and must not be deployed. Older demo
manifests are historical test artifacts and are never selected by the production default.

The production admin key hash and collector address are recorded in `deployments/mainnet.json`.
The companion verifies the current on-chain terms when quoting registration or renewal.

## Verification and costs

```sh
cd cardano/contracts
aiken check
aiken build
cd ../client
npm ci --ignore-scripts
npm run check
```

Use Aiken 1.1.24. The tests cover actual Plutus execution, more than eight registrations,
uniqueness, ownership, payment, renewal, invitations, configuration and pending recovery.
The user confirmed registration on a separate MPF mainnet test deployment using the same validator implementation.

See [benchmark instructions](client/benchmark/README.md) and
[measured results](client/benchmark/mpf-results.json). Those measurements are for the
benchmark contract and sampled synthetic registry sizes, not a fixed mainnet quote or
a production audit. ADA reserves, collector-output ADA, network fees and collateral
are reported separately.

## Production deployment

- Bootstrap transaction: [`02eb4d2748275c06fa6a6d0922bced5a946a30075e8eaabe9239cab15b8922c6`](https://cardanoscan.io/transaction/02eb4d2748275c06fa6a6d0922bced5a946a30075e8eaabe9239cab15b8922c6).
- Registry policy: `301eb0fc86601695370cee04ee40bc28eaf2819d3bd78d7483759791`.
- Deployer: `addr1vyvmz3ujjcwvvaxch2036uzsxu67rsh0mecjj6up59a6hxsgn0pay`.
- Collector: `addr1v872cc5863ku2gh2uwjudq3ca0d0jrgxzxh9yz9q7zdcmcsk0xrkf`.
- Initial fee: `671927000000000` Cardano DEGA base units (8 decimals).

The amount was read from Ethereum registry
`0x4c698AC2f25dD82386658080223583e0EEbB523f` at block `26149585`:
`6719270000000000000000000` DEGA base units (18 decimals), with TTL `31536000` seconds.

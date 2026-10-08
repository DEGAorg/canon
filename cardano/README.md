# Cardano registration and discovery

Canon supports Cardano registration with native DEGA payments and contact discovery
across Cardano and Ethereum. Wallets are generated locally; public Koios endpoints
provide chain access without a Blockfrost account. Signing secrets stay on your computer.

## Try the mainnet test registry

This deployment uses real ADA and DEGA. Registration costs **15.1234 DEGA**, plus ADA
transaction fees and output reserves. The final production price and wallets are not
configured by this release. No automatic bridge or Ethereum burn is performed.

From the repository root, install the companion with Node.js 26 or newer available:

```sh
uv sync
uv run python -m toad.cardano_install
CANON_CARDANO_DEPLOYMENT="$PWD/cardano/deployments/mainnet-mpf-test.json" uv run canon
```

Select Cardano in Chat and use the wallet address displayed in your profile. Fund that
wallet with ADA and DEGA. Keep a separate ADA-only UTxO available for collateral;
collateral is normally unspent on a valid transaction. Review the registration price
in Canon, then submit. Restarting or retrying reconciles the saved transaction.

To test discovery on another computer, use the same public deployment manifest.
Do not copy wallet secrets. The second computer can resolve registered usernames and
public chat keys without paying a registration fee. Register there only if you want
to create another identity. Ethereum and Cardano identities use the same chat transport.

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

Confirmed test deployment:

- Manifest: `deployments/mainnet-mpf-test.json`
- Policy: `d6db7a1b214dc679812b7cca790c561df94c20964d4bf156cac74195`
- Bootstrap: `d43964e5a763675382141be65ba3d321ba7319a62278c2a0ba88f11465c03707`
- Registration period: 365 days
- Fee destination: the collector encoded in the manifest and validator parameters

The deployable validator is `contracts/validators/registry_mpf.ak`. It always starts
with an empty uniqueness root. The separate `registry_benchmark` validator permits
synthetic roots for local measurements and must not be deployed. The older bounded
registry and `mainnet-demo.json` manifest are retained for existing demo deployments;
new testing uses the MPF manifest above.

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
The user also confirmed registration on the MPF mainnet test deployment.

See [benchmark instructions](client/benchmark/README.md) and
[measured results](client/benchmark/mpf-results.json). Those measurements are for the
benchmark contract and sampled synthetic registry sizes, not a fixed mainnet quote or
a production audit. ADA reserves, collector-output ADA, network fees and collateral
are reported separately.

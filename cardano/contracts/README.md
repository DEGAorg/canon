# Bounded Cardano registration contracts

Aiken 1.1.24, stdlib 4.0.0, Plutus V3. This bounded Preview/mainnet demo permanently reserves at
most eight names and permits at most ten members per registration. It is not a
production registry.

`registry.registry.mint` and `registry.registry.spend` share one compiled script
parameterized by `Deployment`. Apply that single record before deriving the policy
ID and state address. The NFT name is UTF-8 `DEGA_CHAT_REGISTRY`. Bootstrap requires
the designated seed and admin; subsequent state must contain ADA and this NFT only.

Run `aiken fmt --check lib/*.ak validators/*.ak`, `aiken check`, and `aiken build`.
`plutus.json` is the generated unparameterized blueprint; both handlers have the same
script. `fixtures/proof-vector.json` is shared with the TypeScript client and checked
against Aiken CBOR, SHA256 and BIP340 verification. Its scalar-3 synthetic public key
is test material, not a wallet identity.

Native DEGA fees use a dedicated inline receipt binding the consumed state output,
registry, action, and name. Register and renew prohibit minting or burning the fee
asset. Time-dependent mutations require finite semi-open validity bounds to enforce registration
expiry. There is no contract-imposed maximum transaction duration; configuration needs no
time bounds.

Mainnet deployment parameters use domain `mainnet` and must select the exact DEGA native
asset policy/name; Preview parameters use `preview` and a separate mock asset. Proofs are
bound to the deployment domain. `fixtures/proof-mainnet-vector.json` verifies the mainnet
CBOR/digest/signature against the same synthetic scalar-3 identity. Neither domain string
alone proves the ledger network: the client also enforces provider and address networks.
The demo starts with the existing bootstrap terms and configures the 15.1234 DEGA fee before
any user registration; the deployment runbook requires checking confirmed configuration.

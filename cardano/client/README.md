# Cardano registry companion

This is a bounded local/Preview prototype with an explicitly selected Mainnet demo path. It uses an Aiken registry with eight permanently reserved
records and ten members per record. TypeScript owns separate Cardano and Nostr signing keys.
The existing Core EVM wallet is unchanged. No browser wallet is used.

Use Node 26. Install locked dependencies from this directory with `npm ci`. The checked-in
`../contracts/plutus.json` is required. Then run:

```sh
npm run demo
```

The demo builds the client, starts a local Lucid emulator, deploys the actual compiled Aiken
validator, registers `alice`, pays mock native DEGA, and resolves its Nostr identity. All
accounts are synthetic. It prints only public results. It never connects to Preview.

```sh
npm run check
```

The tests execute the compiled validator using Lucid's default local UPLC evaluator, then
submit those evaluated transactions to the emulator. Emulator submission by itself does not
execute Plutus. The capacity test creates eight records, fills every member list to ten, and
renews at full capacity. `test/budget-report.json` records measured signed size and execution
units from the evaluated transactions, the blueprint hash, and protocol limits. It is a local
measurement, not a mainnet audit or throughput claim. Override `CARDANO_BLUEPRINT` only when
checking another compiled blueprint. Rebuild contracts with the pinned compiler before
intentionally refreshing the fixture and capacity report.

## Network and wallet setup

The contract does not cap transaction validity duration; the client chooses ten minutes.
The updated mainnet demo is deployed and confirmed at policy
`ec579bb000654bef2346aeae9915a99bb2a04bd66d601b521d501ea5`, with a 15.1234 DEGA fee.
Its public manifest is locally stored at `~/.canon/cardano-mainnet-demo-v2/deployment.json`.
The previous demo remains on chain but Canon now targets the updated deployment.
Production awaits user testing, capacity changes, and confirmed admin/collector addresses.

Submission requires explicit commands and a funded wallet. Koios provides public access without
an API key or account. Mainnet accepts only `https://api.koios.rest/api/v1`; Preview accepts
only `https://preview.koios.rest/api/v1`. Arbitrary and cross-network endpoints are rejected.
There is no alternate provider mode. The client checks Koios `/tip` block_time and rejects
stale tips or local clock differences over 120 seconds. Live local time then supplies
`checkedAtMs`. Transactions start at the earlier of the latest block time and ten seconds before local time,
with a client-selected 600-second interval capped by record expiry. After evaluation, live transactions
require at least 30 seconds remaining before signing. Submission errors identify timing, input,
or script rejection without exposing signed transaction data.

Public access is shared and rate limited. Keep passive UI snapshots cached rather than polling
continuously; writes must obtain fresh state. Koios documents a public tier of 5,000 requests
per day; limits may change and HTTP429 remains authoritative. Every SDK read has a 10-second
request deadline and at most one delayed retry (750ms). Tip/status HTTP429 responses receive
one retry with Retry-After bounded to two seconds. Repeated failures remain visible, never
name absence. Submission has a 10-second deadline with no automatic retry: the durable journal
keeps the same signed bytes for explicit retry. The provider requires strictly positive block
confirmations; zero observations remain submitted, even when the SDK labels them confirmed.
A normal status call performs tip, protocol-parameter and state-UTxO reads; optional owner
lookup uses that same state response.

Run `npm run build`, then invoke `node /absolute/path/cardano/client/dist/cli.js`. Each input
line is one JSON request; each output line is one result. Any failed request sets a nonzero
process exit status. Errors are sanitized and do not echo request/provider contents.

```json
{"operation":"wallet.ensure","network":"Preview","deployment":"/private/cardano/deployment.json","walletPath":"/private/cardano/wallet"}
```

Store runtime files outside the repository. `wallet.ensure` requires top-level `network:"Mainnet"` or `network:"Preview"` and creates
`cardano.json` and
`nostr.json` once, atomically, at mode 0600 in a mode-0700 directory. It returns only public
network, address, owner payment-key hash and Nostr public key. The network is stored with
the seed and must match the deployment for signing. Old seed-only files are rejected, never
guessed or silently migrated. `wallet.status` reads an existing wallet
without creating one. Read-only registry commands never open these files and need no wallet.
Fund the returned address with Preview ADA for collateral, fees and minimum output values,
and separately issued **mock native DEGA** under a Preview policy. Do not use the production
DEGA policy or substitute ADA for the native-token registry fee. The initial fee is
671927000000000 base units, TTL31536000000 milliseconds, and cap10 including the owner.

Choose an existing unspent output at that admin wallet as the one-time bootstrap seed. Obtain
its transaction hash and integer output index from your Preview provider/wallet explorer.
Choose a Preview payment-key collector address. Bootstrap writes a public deployment manifest
before submission; preserve it and the wallet's pending journal across retries.

```json
{"operation":"bootstrap","network":"Preview","deployment":"/private/cardano/deployment.json","walletPath":"/private/cardano/wallet","payload":{"blueprint":"/absolute/path/cardano/contracts/plutus.json","seed":{"txHash":"REPLACE_WITH_64_HEX","outputIndex":0},"feePolicy":"REPLACE_WITH_56_HEX_MOCK_POLICY","feeName":"44454741","collector":"REPLACE_WITH_PREVIEW_ADDRESS"}}
```

The manifest contains version, explicit network, provider URL, parameterized script, policy ID,
script address, state token, bootstrap seed, admin, fee asset, collector and blueprint hash.
It contains no seed phrase or Nostr secret. No provider credential is used.

## JSON operations

Common request shape:

```json
{"operation":"resolve","deployment":"/private/cardano/deployment.json","payload":{"name":"alice.dega"}}
```

Success is `{"ok":true,"result":{...}}`; failure is
`{"ok":false,"error":{"code":"...","message":"..."}}`. Integers on the wire use decimal
strings, including timestamps in milliseconds. Seed output indexes are integers.

| Operation | Payload | Result |
|---|---|---|
| `wallet.ensure` | requires walletPath and top-level network | network, address, owner, nostrKey |
| `wallet.status` | requires walletPath; optional top-level network must match | network, address, owner |
| `wallet.inspect` | requires walletPath; optional top-level network must match | public wallet fields, balances, UTxOs, checkedAtMs |
| `pending.status` | none; requires walletPath | pending:null or operation/name/network/policyId/stateRef/nostrKey |
| `status` | optional owner:28-byte hex | feeAmount, ttlMs, maxUsers, stateRef, policyId, address, checkedAtMs; owner adds record including expired |
| `resolve` | name, optional includeExpired:boolean | record or null, checkedAtMs |
| `reverse` | nostrKey:32-byte hex | active record or null, checkedAtMs |
| `owner` | owner:28-byte hex | record including expired or null, checkedAtMs |
| `quote` | name | status fields and record including expired or null |
| `register` | name, stateRef, maxFee, expectedTtlMs | txHash, status, optional record |
| `renew` | name, stateRef, maxFee, expectedTtlMs, expectedExpiryMs | txHash, status, optional record |
| `invite` | name, member:28-byte hex, stateRef | txHash, status, optional record |
| `config` | feeAmount, ttlMs, maxUsers, stateRef | txHash, status |
| `retry` | none | txHash, submitted or confirmed status |

Records contain name, owner, nostrKey, openedMs, expiresMs, members. Names preserve case and
internal dots; whitespace is trimmed and one exact `.dega` suffix removed. Read errors never
mean name absence. Expired names remain reserved and recoverable. Mutations require walletPath.
Use a fresh `quote`/`status` stateRef, decimal-string fees and TTL. The signer rejects stale
state and terms before signing. Registration can optionally receive `nostrPath` pointing to a
private `{"secretKey":"..."}` file, or `nostrSecret` through local stdin only; optional nostrKey
must match the secret. Never put a secret on a command line. Otherwise the separate generated
Nostr identity is used. Neither identity secret is sent to the provider or retained in intent
journals.

```json
{"operation":"quote","deployment":"/private/cardano/deployment.json","payload":{"name":"alice"}}
{"operation":"register","deployment":"/private/cardano/deployment.json","walletPath":"/private/cardano/wallet","payload":{"name":"alice","stateRef":"REPLACE_TX_HASH#0","maxFee":"671927000000000","expectedTtlMs":"31536000000"}}
{"operation":"retry","deployment":"/private/cardano/deployment.json","walletPath":"/private/cardano/wallet"}
```

Canon waits for confirmation with up to eight retries spaced 15 seconds apart; a longer wait
remains pending in the UI, not a failed registration. At the companion CLI level,
`submitted` means broadcast, not confirmation. Keep calling `retry` until `confirmed` before
claiming the registration succeeded. Signed CBOR/hash and a nonsecret intent digest are
synchronized to a private journal before broadcast. Retry resubmits the same bytes; it does
not rebuild or pay a second term. When the chain has passed the signed expiry, the transaction
is absent and its registry input remains unspent, retry archives the journal and returns
`PENDING_EXPIRED`. Canon rebuilds registration once with the same identity and original fee/TTL
bounds. Changed terms require a fresh action. Exact confirmed intent replays return the previous hash.
An unrelated pending intent blocks a new operation. If another transaction consumed the state
and the provider cannot confirm this transaction, the client fails closed with
`PENDING_CONFLICT`; preserve the journal and reconcile it manually. A stale operation.lock
also fails closed: remove it only after verifying no signer process is running. Fee payments
are native-token collector outputs with bound receipts; no DEGA burn or approval transaction
is performed.

The prototype does not provide scalable indexing, rollback/reorg automation, custody,
independent production auditing or bridge settlement. Mainnet support is for an isolated demo,
not production readiness. The mainnet fee asset is pinned to the DEGA policy/name below.

Dependency exception: Lucid Evolution0.6.5 transitively requires deprecated `@effect/schema`
0.66.16/0.68.27. npm reports those upstream deprecations; replacing them independently would
change Lucid's supported dependency graph, so the pinned prototype retains them. The package
explicitly denies optional `cbor-extract` and `fsevents` native installation scripts; the tested
JavaScript fallbacks work without them. Type-check, lint and test warnings are not suppressed.


## Isolated Mainnet demonstration: 15.1234 DEGA

These are instructions for an explicitly authorized operator; the local demo and tests never
broadcast transactions. Do not run the registration step while preparing the environment:
the user registers their own selected name. Eight names remain permanently reserved even
when expired. Use a dedicated demo wallet and preserve all local state outside this repo.

1. Generate the dedicated wallet with explicit Mainnet and inspect its public funding state:

```json
{"operation":"wallet.ensure","network":"Mainnet","deployment":"/private/cardano-mainnet/deployment.json","walletPath":"/private/cardano-mainnet/wallet"}
{"operation":"wallet.inspect","network":"Mainnet","deployment":"/private/cardano-mainnet/deployment.json","walletPath":"/private/cardano-mainnet/wallet"}
```

`wallet.inspect` reads public on-chain balances and UTxOs without signing or creating anything.
It needs public Koios access and an existing wallet, but no deployment manifest.
Its decimal-string `balances` map uses `lovelace` and native asset units. Each UTxO contains
`txHash`, numeric `outputIndex`, `assets`, and `collateralCandidate`. A candidate is a datum-free
ADA-only output of at least 5 ADA; this is an inspection hint, not a computed transaction
collateral guarantee. The actual builder still computes collateral and minimum ADA. Keep an
ADA-only collateral output available instead of putting all ADA in a token-bearing output.

2. Fund that public address with enough ADA for bootstrap/configuration, collateral and the
registration transaction, plus exactly the desired DEGA funding. The registry fee will be
15.1234 DEGA after configuration. Bootstrap and configuration pay ADA transaction costs but
no DEGA registration fee. The eight-decimal native asset is pinned to:

```text
policy: 25c5de5f5b286073c593edfd77b48abc7a48e5a4f3d4cd9d428ff935
name:   44454741
unit:   25c5de5f5b286073c593edfd77b48abc7a48e5a4f3d4cd9d428ff93544454741
```

3. Select a current unspent admin-wallet output from `wallet.inspect` as the seed. Preserve a
separate collateral candidate. The user supplied this collector, verified locally as a valid
Mainnet address with a payment-key credential:

```text
addr1qyz74sz6v5ufwvmvaw2ry8k289c97ltg235mqvdqjxgcdk3af7q4hn357pyrvk638e2mejq45jk3cxsnwctj77nudktqe9tz88
```

The collector receives the registration/renewal DEGA fee; no Cardano fee burn occurs.
Bootstrap uses the original ABI and initial high fee until the next explicit configuration.

```json
{"operation":"bootstrap","network":"Mainnet","deployment":"/private/cardano-mainnet/deployment.json","walletPath":"/private/cardano-mainnet/wallet","payload":{"blueprint":"/absolute/path/cardano/contracts/plutus.json","seed":{"txHash":"REPLACE_WITH_INSPECTED_TX_HASH","outputIndex":0},"feePolicy":"25c5de5f5b286073c593edfd77b48abc7a48e5a4f3d4cd9d428ff935","feeName":"44454741","collector":"addr1qyz74sz6v5ufwvmvaw2ry8k289c97ltg235mqvdqjxgcdk3af7q4hn357pyrvk638e2mejq45jk3cxsnwctj77nudktqe9tz88"}}
{"operation":"retry","deployment":"/private/cardano-mainnet/deployment.json","walletPath":"/private/cardano-mainnet/wallet"}
{"operation":"status","deployment":"/private/cardano-mainnet/deployment.json"}
```

4. Wait for bootstrap `confirmed`, then use the returned stateRef to configure the lower fee:

```json
{"operation":"config","deployment":"/private/cardano-mainnet/deployment.json","walletPath":"/private/cardano-mainnet/wallet","payload":{"stateRef":"REPLACE_WITH_CURRENT_TX_HASH#0","feeAmount":"1512340000","ttlMs":"31536000000","maxUsers":"10"}}
{"operation":"retry","deployment":"/private/cardano-mainnet/deployment.json","walletPath":"/private/cardano-mainnet/wallet"}
{"operation":"status","deployment":"/private/cardano-mainnet/deployment.json"}
```

Do not expose the user registration flow until configuration is confirmed and status reports
`feeAmount:"1512340000"`, `ttlMs:"31536000000"`, `maxUsers:"10"`. The registration command then
uses a fresh quote, `maxFee:"1512340000"`, and the user's chosen name/current Nostr identity.
The demonstration or video take is a later user action, not an automatic setup step.

Mainnet emulator coverage uses synthetic ADA and native DEGA UTxOs with actual Mainnet address
encoding, the Mainnet proof domain, and the compiled Aiken script. It bootstraps, configures,
registers and verifies the exact 1512340000-unit collector delta. This local ledger exercise
is not evidence of a live deployment or real funds movement.


Wallet startup is offline and concurrency-safe. `wallet.ensure`, `wallet.status`,
`wallet.inspect`, and `pending.status` accept omission of `deployment`. Only `wallet.inspect`
contacts Koios. Concurrent ensure processes return the same persisted public identity; corrupt
or network-mismatched files fail without replacing the wallet. Canon's existing Nostr chat
identity remains separate from these local Cardano wallet files.

Live mainnet deployment exposed a Koios SDK incompatibility in historical `tx_info` collateral
outputs. The adapter now resolves `/utxo_info`, requires unspent references, and reads current
address UTxOs for full data. It also handles multiple requested transaction hashes. This avoids
both that historical schema incompatibility and reporting already-spent outputs as available.

# MPF registry benchmark

This is an **emulator experiment**, not a production deployment or the Canon runtime.
It tests one authenticated record output per registration and three uniqueness
reservations in a shared Merkle Patricia Forestry root. It uses the upstream Aiken
MPF 2.1.0 and Node MPF 1.3.1 libraries instead of implementing a trie.

From the repository root, with Aiken 1.1.24 on PATH:

```bash
cd cardano/contracts
aiken check
aiken build
cd ../client
npm ci --ignore-scripts
npm run benchmark:mpf
```

`benchmark/mpf-results.json` is overwritten with the latest local measurements.
Existing demo tests run with `npm run check`. No real wallet, provider credential,
network submission, or payment is involved. `--ignore-scripts` is intentional.

## What is exercised

- Actual compiled Plutus mint/spend validators through Lucid local evaluation.
- Owner and Nostr signatures, DEGA collection, sequential uniqueness proofs.
- Registration, owner renewal before/after expiry and unauthorized renewal rejection.
- Independent reading from provider UTxOs; unrelated outputs are ignored.
- Rebuilding the uniqueness trie from public records and checking its root.
- Concurrent root-spend conflict followed by rebuilding and a successful retry.
- Malformed proof, incorrect root, missing payment and signature rejection.
- Scale fixtures: 0, 100, 1,000 and 10,000 pre-existing records (three keys each).

The large fixtures initialize a **synthetic root**. They do not represent thousands
of submitted or independently discovered registrations. Small integration scenarios
exercise real record creation and reconstruction within the emulator. The test ledger
and generated keys are disposable fixtures. Never deploy the benchmark validator:
its configurable initial root is a measurement shortcut, not production bootstrap.

## Reading the report

- `networkFeeLovelace`: transaction fee, including attached validator witnesses.
- `recordReserveLovelace`: ADA held with the new registration record.
- `collectorOutputLovelace`: ADA sent with the DEGA payment to the collector. This
  leaves the registering wallet and is not automatically returned.
- `rootReserveLovelace`: existing shared root reserve; one-time bootstrap funding,
  not a new per-user output in these runs.
- `collateralLovelace`: the builder's collateral allocation; normally unspent on a
  valid transaction. It is separate from registration expenditure.
- `allocatedCpu` / `allocatedMemory`: redeemer budgets allocated after local UPLC
  evaluation, read from the completed transaction, not independent node telemetry.
- `proofBytes`: sum of the three proofs; actual transaction bytes also include
  redeemers, witnesses and outputs. Both mint and spend carry the register redeemer.
- `protocol`: the emulator's pinned protocol parameters, not a live mainnet query.

One ADA = 1,000,000 lovelace. DEGA is additional and the benchmark uses the current
code's Ethereum-equivalent token amount. Reported sizes are specific deterministic
identity samples, not adversarial worst-case bounds. Account keys are randomly
created, so some transaction encodings and fees can vary slightly across runs.

## Production gates still open

This does not replace the live demo. Production needs reviewed initialization,
configuration and invitation semantics, fee/TTL quote protection, wallet/runtime
integration, paginated public discovery, durable proof synchronization and rollback
handling, concurrency UX, worst-case size testing, and independent security review.
Reference scripts may reduce witness fees but are not measured here. Production
wallets, final parameters and deployment still need the previously requested confirmation.

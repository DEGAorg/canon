//// Never deploy: initial_root intentionally supports synthetic fixtures.

use aiken/collection/dict
use aiken/collection/list
use aiken/interval.{Finite, Interval, IntervalBound}
use aiken/primitive/bytearray
use cardano/address.{Address, Script, VerificationKey}
use cardano/assets
use cardano/transaction.{
  InlineDatum, Input, Output, OutputReference, Spend, Transaction,
}
use registry_benchmark_types as benchmark
use registry_benchmark_types.{
  Action, BenchmarkDatum, Bootstrap, Entry, Register, Renew, Root,
}
use registry_types.{Deployment}

validator registry_benchmark(deployment: Deployment, initial_root: ByteArray) {
  mint(action: Action, policy: ByteArray, tx: Transaction) {
    expect registry_types.valid_deployment(deployment, policy)
    when action is {
      Bootstrap -> {
        expect bytearray.length(initial_root) == 32
        expect
          list.any(tx.inputs, fn(i) { i.output_reference == deployment.seed })
        expect list.has(tx.extra_signatories, deployment.admin)
        expect
          dict.to_pairs(assets.tokens(tx.mint, policy)) == [
            Pair(benchmark.root_token, 1),
          ]
        let output = benchmark.unique_output(tx, policy, benchmark.root_token)
        and {
          output.address.payment_credential == Script(policy),
          output.address.stake_credential == None,
          benchmark.datum_of(output) == Root {
            root: initial_root,
            fee: registry_types.initial.fee_amount,
            ttl: registry_types.initial.ttl_ms,
          },
        }
      }
      Register { record, .. } -> {
        expect
          dict.to_pairs(assets.tokens(tx.mint, policy)) == [
            Pair(benchmark.record_token(record.name), 1),
          ]
        expect [input] = list.filter(
          tx.inputs,
          fn(i) {
            assets.quantity_of(i.output.value, policy, benchmark.root_token) != 0
          },
        )
        let data: Data = action
        and {
          benchmark.authentic(input.output, policy, benchmark.root_token),
          input.output.address.payment_credential == Script(policy),
          list.has(tx.redeemers, Pair(Spend(input.output_reference), data)),
        }
      }
      Renew -> False
    }
  }

  spend(
    datum: Option<BenchmarkDatum>,
    action: Action,
    own_ref: OutputReference,
    tx: Transaction,
  ) {
    expect Some(old) = datum
    expect Some(input) = list.find(
      tx.inputs,
      fn(i) { i.output_reference == own_ref },
    )
    expect Script(policy) = input.output.address.payment_credential
    expect registry_types.valid_deployment(deployment, policy)
    let old_data: Data = old
    expect input.output.datum == InlineDatum(old_data)
    when old is {
      Root { .. } -> register(deployment, old, action, (policy, own_ref, tx))
      Entry { record } -> {
        expect Renew = action
        expect dict.is_empty(assets.tokens(tx.mint, policy))
        let token = benchmark.record_token(record.name)
        expect benchmark.authentic(input.output, policy, token)
        expect [reference] = list.filter(
          tx.reference_inputs,
          fn(i) {
            assets.quantity_of(i.output.value, policy, benchmark.root_token) != 0
          },
        )
        expect
          benchmark.authentic(reference.output, policy, benchmark.root_token)
        expect reference.output.address == input.output.address
        let state = benchmark.datum_of(reference.output)
        expect Root { ttl, .. } = state
        let (lower, upper) = registry_types.bounds(tx)
        let expires = if record.expires_ms > lower {
          record.expires_ms
        } else {
          lower
        } + ttl
        let output = benchmark.unique_output(tx, policy, token)
        and {
          list.has(tx.extra_signatories, record.owner),
          upper <= expires,
          benchmark.paid(
            deployment,
            state,
            (policy, own_ref, tx),
            1,
            record.name,
          ),
          output.address == input.output.address,
          assets.lovelace_of(output.value) >= assets.lovelace_of(
            input.output.value,
          ),
          benchmark.datum_of(output) == Entry {
            record: registry_types.Record { ..record, expires_ms: expires },
          },
        }
      }
    }
  }

  else(_) {
    fail
  }
}

fn register(
  deployment: Deployment,
  old: BenchmarkDatum,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> Bool {
  let (policy, own_ref, tx) = context
  expect Root { root, fee, ttl } = old
  expect Register { record, signature, proofs } = action
  expect Some(input) = list.find(
    tx.inputs,
    fn(i) { i.output_reference == own_ref },
  )
  expect benchmark.authentic(input.output, policy, benchmark.root_token)
  expect
    dict.to_pairs(assets.tokens(tx.mint, policy)) == [
      Pair(benchmark.record_token(record.name), 1),
    ]
  let (lower, upper) = registry_types.bounds(tx)
  let output = benchmark.unique_output(tx, policy, benchmark.root_token)
  let entry = benchmark.unique_output(
    tx,
    policy,
    benchmark.record_token(record.name),
  )
  and {
    registry_types.name_valid(record.name),
    bytearray.length(record.owner) == 28,
    list.has(tx.extra_signatories, record.owner),
    record.opened_ms == lower,
    record.expires_ms == lower + ttl,
    upper <= record.expires_ms,
    record.members == [record.owner],
    registry_types.proof_valid(
      deployment,
      policy,
      registry_types.Register {
        name: record.name,
        owner: record.owner,
        nostr_key: record.nostr_key,
        nostr_signature: signature,
        max_fee: fee,
        expected_ttl_ms: ttl,
      },
    ),
    benchmark.paid(deployment, old, context, 0, record.name),
    output.address == input.output.address,
    assets.lovelace_of(output.value) >= assets.lovelace_of(input.output.value),
    benchmark.datum_of(output) == Root {
      root: benchmark.inserted_root(root, record, proofs),
      fee,
      ttl,
    },
    entry.address == input.output.address,
    benchmark.datum_of(entry) == Entry { record },
  }
}

const test_root =
  #"0000000000000000000000000000000000000000000000000000000000000000"

const test_policy = #"22222222222222222222222222222222222222222222222222222222"

const test_owner = #"11111111111111111111111111111111111111111111111111111111"

const test_ref =
  OutputReference {
    transaction_id: #"0000000000000000000000000000000000000000000000000000000000000000",
    output_index: 0,
  }

fn test_deployment() -> Deployment {
  Deployment {
    seed: test_ref,
    admin: test_owner,
    network_domain: "preview",
    fee_policy: #"33333333333333333333333333333333333333333333333333333333",
    fee_name: "DEGA",
    collector: Address {
      payment_credential: VerificationKey(test_owner),
      stake_credential: None,
    },
  }
}

fn test_output() -> Output {
  let data: Data = Root {
    root: test_root,
    fee: registry_types.initial.fee_amount,
    ttl: registry_types.initial.ttl_ms,
  }
  Output {
    address: Address {
      payment_credential: Script(test_policy),
      stake_credential: None,
    },
    value: assets.from_lovelace(2000000)
      |> assets.add(test_policy, benchmark.root_token, 1),
    datum: InlineDatum(data),
    reference_script: None,
  }
}

fn test_tx() -> Transaction {
  Transaction {
    ..transaction.placeholder,
    inputs: [Input { output_reference: test_ref, output: test_output() }],
    outputs: [test_output()],
    extra_signatories: [test_owner],
    validity_range: Interval {
      lower_bound: IntervalBound {
        bound_type: Finite(1000),
        is_inclusive: True,
      },
      upper_bound: IntervalBound {
        bound_type: Finite(2000),
        is_inclusive: False,
      },
    },
  }
}

fn bootstrap_tx() -> Transaction {
  Transaction {
    ..test_tx(),
    inputs: [
      Input {
        output_reference: test_ref,
        output: Output { ..test_output(), value: assets.from_lovelace(2000000) },
      },
    ],
    mint: assets.from_asset(test_policy, benchmark.root_token, 1),
  }
}

test bootstrap_valid() {
  registry_benchmark.mint(
    test_deployment(),
    test_root,
    Bootstrap,
    test_policy,
    bootstrap_tx(),
  )
}

test bootstrap_requires_admin() fail {
  registry_benchmark.mint(
    test_deployment(),
    test_root,
    Bootstrap,
    test_policy,
    Transaction { ..bootstrap_tx(), extra_signatories: [] },
  )
}

test bootstrap_rejects_extra_mint() fail {
  registry_benchmark.mint(
    test_deployment(),
    test_root,
    Bootstrap,
    test_policy,
    Transaction {
      ..bootstrap_tx(),
      mint: assets.from_asset(test_policy, benchmark.root_token, 2),
    },
  )
}

test bootstrap_rejects_wrong_root() {
  !registry_benchmark.mint(
    test_deployment(),
    #"1111111111111111111111111111111111111111111111111111111111111111",
    Bootstrap,
    test_policy,
    bootstrap_tx(),
  )
}

fn renewal_tx() -> Transaction {
  let old: Data = Entry { record: test_record() }
  let next: Data = Entry {
    record: registry_types.Record { ..test_record(), expires_ms: 2000 },
  }
  let root: Data = Root { root: test_root, fee: 0, ttl: 1000 }
  let output = Output {
    ..test_output(),
    datum: InlineDatum(old),
    value: assets.from_lovelace(2000000)
      |> assets.add(test_policy, benchmark.record_token("alice"), 1),
  }
  Transaction {
    ..test_tx(),
    inputs: [Input { output_reference: test_ref, output }],
    outputs: [Output { ..output, datum: InlineDatum(next) }],
    reference_inputs: [
      Input {
        output_reference: OutputReference { ..test_ref, output_index: 1 },
        output: Output { ..test_output(), datum: InlineDatum(root) },
      },
    ],
  }
}

fn test_record() -> registry_types.Record {
  registry_types.Record {
    name: "alice",
    owner: test_owner,
    nostr_key: test_root,
    opened_ms: 0,
    expires_ms: 1000,
    members: [test_owner],
  }
}

test renew_valid() {
  registry_benchmark.spend(
    test_deployment(),
    test_root,
    Some(Entry { record: test_record() }),
    Renew,
    test_ref,
    renewal_tx(),
  )
}

test renew_requires_owner() {
  !registry_benchmark.spend(
    test_deployment(),
    test_root,
    Some(Entry { record: test_record() }),
    Renew,
    test_ref,
    Transaction { ..renewal_tx(), extra_signatories: [] },
  )
}

test renew_requires_root_reference() fail {
  registry_benchmark.spend(
    test_deployment(),
    test_root,
    Some(Entry { record: test_record() }),
    Renew,
    test_ref,
    Transaction { ..renewal_tx(), reference_inputs: [] },
  )
}

test renew_preserves_reserve() {
  expect [output] = renewal_tx().outputs
  !registry_benchmark.spend(
    test_deployment(),
    test_root,
    Some(Entry { record: test_record() }),
    Renew,
    test_ref,
    Transaction {
      ..renewal_tx(),
      outputs: [
        Output {
          ..output,
          value: assets.from_asset(
            test_policy,
            benchmark.record_token("alice"),
            1,
          ),
        },
      ],
    },
  )
}

fn register_mint_tx() -> Transaction {
  let action: Data = Register {
    record: test_record(),
    signature: #"",
    proofs: [],
  }
  Transaction {
    ..test_tx(),
    mint: assets.from_asset(test_policy, benchmark.record_token("alice"), 1),
    redeemers: [Pair(Spend(test_ref), action)],
  }
}

test registration_mint_requires_matching_root_spend() {
  !registry_benchmark.mint(
    test_deployment(),
    test_root,
    Register { record: test_record(), signature: #"", proofs: [] },
    test_policy,
    Transaction { ..register_mint_tx(), redeemers: [] },
  )
}

test registration_mint_rejects_root_without_nft() fail {
  registry_benchmark.mint(
    test_deployment(),
    test_root,
    Register { record: test_record(), signature: #"", proofs: [] },
    test_policy,
    Transaction {
      ..register_mint_tx(),
      inputs: [
        Input {
          output_reference: test_ref,
          output: Output {
            ..test_output(),
            value: assets.from_lovelace(2000000),
          },
        },
      ],
    },
  )
}

test registration_mint_requires_script_root() {
  !registry_benchmark.mint(
    test_deployment(),
    test_root,
    Register { record: test_record(), signature: #"", proofs: [] },
    test_policy,
    Transaction {
      ..register_mint_tx(),
      inputs: [
        Input {
          output_reference: test_ref,
          output: Output {
            ..test_output(),
            address: test_deployment().collector,
          },
        },
      ],
    },
  )
}

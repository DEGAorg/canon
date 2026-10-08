use aiken/collection/dict
use aiken/collection/list
use aiken/interval.{Finite, Interval, IntervalBound}
use cardano/address.{Address, Script, VerificationKey}
use cardano/assets
use cardano/transaction.{
  InlineDatum, Input, Output, OutputReference, Transaction,
}
use registry_types.{Action, Deployment, MintAction, RegistryDatum}

validator registry(deployment: Deployment) {
  mint(_action: MintAction, policy: ByteArray, tx: Transaction) {
    expect registry_types.valid_deployment(deployment, policy)
    expect list.any(tx.inputs, fn(i) { i.output_reference == deployment.seed })
    expect list.has(tx.extra_signatories, deployment.admin)
    expect
      dict.to_pairs(assets.tokens(tx.mint, policy)) == [
        Pair(registry_types.nft, 1),
      ]
    expect [output] = list.filter(
      tx.outputs,
      fn(o) { assets.quantity_of(o.value, policy, registry_types.nft) != 0 },
    )
    let initial: Data = registry_types.initial
    and {
      output.address.payment_credential == Script(policy),
      output.address.stake_credential == None,
      registry_types.state_value(output, policy),
      output.datum == InlineDatum(initial),
    }
  }

  spend(
    datum: Option<RegistryDatum>,
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
    expect registry_types.state_value(input.output, policy)
    let old_data: Data = old
    expect input.output.datum == InlineDatum(old_data)
    expect dict.is_empty(assets.tokens(tx.mint, policy))
    expect [output] = list.filter(
      tx.outputs,
      fn(o) { assets.quantity_of(o.value, policy, registry_types.nft) != 0 },
    )
    let next: Data = registry_types.successor(
      deployment,
      old,
      action,
      (policy, own_ref, tx),
    )
    and {
      output.address == input.output.address,
      registry_types.state_value(output, policy),
      assets.lovelace_of(output.value) >= assets.lovelace_of(input.output.value),
      output.datum == InlineDatum(next),
    }
  }

  else(_) {
    fail
  }
}

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
  let data: Data = registry_types.initial
  Output {
    address: Address {
      payment_credential: Script(test_policy),
      stake_credential: None,
    },
    value: assets.from_lovelace(2000000)
      |> assets.add(test_policy, registry_types.nft, 1),
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

fn configure() -> Action {
  registry_types.Configure {
    fee_amount: 671927000000000,
    ttl_ms: 31536000000,
    max_users: 10,
  }
}

test bootstrap_valid() {
  registry.mint(
    test_deployment(),
    registry_types.Bootstrap,
    test_policy,
    Transaction {
      ..bootstrap_tx(),
      mint: assets.from_asset(test_policy, registry_types.nft, 1),
    },
  )
}

test bootstrap_extra_asset() {
  !registry.mint(
    test_deployment(),
    registry_types.Bootstrap,
    test_policy,
    Transaction {
      ..bootstrap_tx(),
      mint: assets.from_asset(test_policy, registry_types.nft, 1),
      outputs: [
        Output {
          ..test_output(),
          value: test_output().value |> assets.add(#"ff", "X", 1),
        },
      ],
    },
  )
}

test bootstrap_unauthorized() fail {
  registry.mint(
    test_deployment(),
    registry_types.Bootstrap,
    test_policy,
    Transaction {
      ..bootstrap_tx(),
      extra_signatories: [],
      mint: assets.from_asset(test_policy, registry_types.nft, 1),
    },
  )
}

test bootstrap_burn() fail {
  registry.mint(
    test_deployment(),
    registry_types.Bootstrap,
    test_policy,
    Transaction {
      ..bootstrap_tx(),
      mint: assets.from_asset(test_policy, registry_types.nft, -1),
    },
  )
}

test configure_valid() {
  registry.spend(
    test_deployment(),
    Some(registry_types.initial),
    configure(),
    test_ref,
    test_tx(),
  )
}

test spoofed_input() fail {
  registry.spend(
    test_deployment(),
    Some(registry_types.initial),
    configure(),
    test_ref,
    Transaction {
      ..test_tx(),
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

test nft_loss() fail {
  registry.spend(
    test_deployment(),
    Some(registry_types.initial),
    configure(),
    test_ref,
    Transaction {
      ..test_tx(),
      outputs: [
        Output { ..test_output(), value: assets.from_lovelace(2000000) },
      ],
    },
  )
}

test reserve_theft() {
  !registry.spend(
    test_deployment(),
    Some(registry_types.initial),
    configure(),
    test_ref,
    Transaction {
      ..test_tx(),
      outputs: [
        Output {
          ..test_output(),
          value: assets.from_asset(test_policy, registry_types.nft, 1),
        },
      ],
    },
  )
}

test successor_tampering() {
  let data: Data = RegistryDatum { ..registry_types.initial, fee_amount: 0 }
  !registry.spend(
    test_deployment(),
    Some(registry_types.initial),
    configure(),
    test_ref,
    Transaction {
      ..test_tx(),
      outputs: [Output { ..test_output(), datum: InlineDatum(data) }],
    },
  )
}

test wrong_own_reference() fail {
  registry.spend(
    test_deployment(),
    Some(registry_types.initial),
    configure(),
    OutputReference { ..test_ref, output_index: 1 },
    test_tx(),
  )
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
  }
}

test configure_without_validity_bounds() {
  registry.spend(
    test_deployment(),
    Some(registry_types.initial),
    configure(),
    test_ref,
    Transaction {
      ..test_tx(),
      validity_range: transaction.placeholder.validity_range,
    },
  )
}

use aiken/collection/dict
use aiken/collection/list
use aiken/interval.{Finite, Interval, IntervalBound}
use aiken/primitive/bytearray
use cardano/address.{Address, Script, VerificationKey}
use cardano/assets
use cardano/transaction.{
  InlineDatum, Input, Output, OutputReference, Spend, Transaction,
}
use registry_mpf_types as mpf_types
use registry_mpf_types.{
  Action, Bootstrap, Configure, Entry, Invite, Register, RegistryDatumMPF, Renew,
  Root, Terms,
}
use registry_types.{Deployment, Record}

validator registry_mpf(deployment: Deployment, terms: Terms) {
  mint(action: Action, policy: ByteArray, tx: Transaction) {
    expect registry_types.valid_deployment(deployment, policy)
    expect mpf_types.valid_terms(terms)
    when action is {
      Bootstrap -> {
        expect
          list.any(tx.inputs, fn(i) { i.output_reference == deployment.seed })
        expect list.has(tx.extra_signatories, deployment.admin)
        expect
          dict.to_pairs(assets.tokens(tx.mint, policy)) == [
            Pair(mpf_types.root_token, 1),
          ]
        let output = mpf_types.unique_output(tx, policy, mpf_types.root_token)
        and {
          output.address.payment_credential == Script(policy),
          output.address.stake_credential == None,
          mpf_types.datum_of(output) == Root {
            root: mpf_types.empty_root,
            fee: terms.fee_amount,
            ttl: terms.ttl_ms,
            max_users: terms.max_users,
          },
        }
      }
      Register { record, .. } -> {
        expect
          dict.to_pairs(assets.tokens(tx.mint, policy)) == [
            Pair(mpf_types.record_token(record.name), 1),
          ]
        expect [input] = list.filter(
          tx.inputs,
          fn(i) {
            assets.quantity_of(i.output.value, policy, mpf_types.root_token) != 0
          },
        )
        let data: Data = action
        and {
          mpf_types.authentic(input.output, policy, mpf_types.root_token),
          input.output.address.payment_credential == Script(policy),
          list.has(tx.redeemers, Pair(Spend(input.output_reference), data)),
        }
      }
      _ -> False
    }
  }

  spend(
    datum: Option<RegistryDatumMPF>,
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
    expect mpf_types.valid_terms(terms)
    let old_data: Data = old
    expect input.output.datum == InlineDatum(old_data)
    when old is {
      Root { .. } ->
        when action is {
          Register { .. } ->
            register(deployment, old, action, (policy, own_ref, tx))
          Configure { .. } ->
            configure(deployment, old, action, (policy, own_ref, tx))
          _ -> False
        }
      Entry { record } -> {
        expect dict.is_empty(assets.tokens(tx.mint, policy))
        let token = mpf_types.record_token(record.name)
        expect mpf_types.authentic(input.output, policy, token)
        expect [reference] = list.filter(
          tx.reference_inputs,
          fn(i) {
            assets.quantity_of(i.output.value, policy, mpf_types.root_token) != 0
          },
        )
        expect
          mpf_types.authentic(reference.output, policy, mpf_types.root_token)
        expect reference.output.address == input.output.address
        let state = mpf_types.datum_of(reference.output)
        expect list.has(tx.extra_signatories, record.owner)
        let next = entry_successor(
          deployment,
          state,
          record,
          action,
          (policy, own_ref, tx),
        )
        let output = mpf_types.unique_output(tx, policy, token)
        and {
          output.address == input.output.address,
          assets.lovelace_of(output.value) >= assets.lovelace_of(
            input.output.value,
          ),
          mpf_types.datum_of(output) == Entry { record: next },
        }
      }
    }
  }

  else(_) {
    fail
  }
}

fn entry_successor(
  deployment: Deployment,
  state: RegistryDatumMPF,
  record: Record,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> Record {
  let (_, _, tx) = context
  expect Root { fee, ttl, max_users, .. } = state
  let (lower, upper) = registry_types.bounds(tx)
  when action is {
    Renew { expected_expiry_ms, max_fee, expected_ttl_ms } -> {
      let expires = if record.expires_ms > lower {
        record.expires_ms
      } else {
        lower
      } + ttl
      expect and {
          record.expires_ms == expected_expiry_ms,
          fee <= max_fee,
          ttl == expected_ttl_ms,
          upper <= expires,
          mpf_types.paid(deployment, state, context, 1, record.name),
        }
      Record { ..record, expires_ms: expires }
    }
    Invite { member } -> {
      expect and {
          upper <= record.expires_ms,
          bytearray.length(member) == 28,
          !list.has(record.members, member),
          list.length(record.members) < max_users,
        }
      Record { ..record, members: list.concat(record.members, [member]) }
    }
    _ -> fail
  }
}

fn configure(
  deployment: Deployment,
  old: RegistryDatumMPF,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> Bool {
  let (policy, own_ref, tx) = context
  expect Root { root, .. } = old
  expect Configure { fee_amount, ttl_ms, max_users } = action
  expect list.has(tx.extra_signatories, deployment.admin)
  expect mpf_types.valid_terms(Terms { fee_amount, ttl_ms, max_users })
  expect dict.is_empty(assets.tokens(tx.mint, policy))
  expect Some(input) = list.find(
    tx.inputs,
    fn(i) { i.output_reference == own_ref },
  )
  expect mpf_types.authentic(input.output, policy, mpf_types.root_token)
  let output = mpf_types.unique_output(tx, policy, mpf_types.root_token)
  and {
    output.address == input.output.address,
    assets.lovelace_of(output.value) >= assets.lovelace_of(input.output.value),
    mpf_types.datum_of(output) == Root {
      root,
      fee: fee_amount,
      ttl: ttl_ms,
      max_users,
    },
  }
}

fn register(
  deployment: Deployment,
  old: RegistryDatumMPF,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> Bool {
  let (policy, own_ref, tx) = context
  expect Root { root, fee, ttl, max_users } = old
  expect Register { record, signature, proofs, max_fee, expected_ttl_ms } = action
  expect Some(input) = list.find(
    tx.inputs,
    fn(i) { i.output_reference == own_ref },
  )
  expect mpf_types.authentic(input.output, policy, mpf_types.root_token)
  expect
    dict.to_pairs(assets.tokens(tx.mint, policy)) == [
      Pair(mpf_types.record_token(record.name), 1),
    ]
  let (lower, upper) = registry_types.bounds(tx)
  let output = mpf_types.unique_output(tx, policy, mpf_types.root_token)
  let entry = mpf_types.unique_output(
    tx,
    policy,
    mpf_types.record_token(record.name),
  )
  and {
    fee <= max_fee,
    ttl == expected_ttl_ms,
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
    mpf_types.paid(deployment, old, context, 0, record.name),
    output.address == input.output.address,
    assets.lovelace_of(output.value) >= assets.lovelace_of(input.output.value),
    mpf_types.datum_of(output) == Root {
      root: mpf_types.inserted_root(root, record, proofs),
      fee,
      ttl,
      max_users,
    },
    entry.address == input.output.address,
    mpf_types.datum_of(entry) == Entry { record },
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
    max_users: 10,
  }
  Output {
    address: Address {
      payment_credential: Script(test_policy),
      stake_credential: None,
    },
    value: assets.from_lovelace(2000000)
      |> assets.add(test_policy, mpf_types.root_token, 1),
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
    mint: assets.from_asset(test_policy, mpf_types.root_token, 1),
  }
}

fn renewal_tx() -> Transaction {
  let old: Data = Entry { record: test_record() }
  let next: Data = Entry {
    record: registry_types.Record { ..test_record(), expires_ms: 2000 },
  }
  let root: Data = Root { root: test_root, fee: 0, ttl: 1000, max_users: 10 }
  let output = Output {
    ..test_output(),
    datum: InlineDatum(old),
    value: assets.from_lovelace(2000000)
      |> assets.add(test_policy, mpf_types.record_token("alice"), 1),
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

fn test_terms() -> Terms {
  Terms {
    fee_amount: registry_types.initial.fee_amount,
    ttl_ms: registry_types.initial.ttl_ms,
    max_users: 10,
  }
}

fn renewal_action() -> Action {
  Renew { expected_expiry_ms: 1000, max_fee: 0, expected_ttl_ms: 1000 }
}

test bootstrap_valid() {
  registry_mpf.mint(
    test_deployment(),
    test_terms(),
    Bootstrap,
    test_policy,
    bootstrap_tx(),
  )
}

test bootstrap_rejects_nonempty_root() {
  let data: Data = Root {
    root: #"1111111111111111111111111111111111111111111111111111111111111111",
    fee: test_terms().fee_amount,
    ttl: test_terms().ttl_ms,
    max_users: 10,
  }
  !registry_mpf.mint(
    test_deployment(),
    test_terms(),
    Bootstrap,
    test_policy,
    Transaction {
      ..bootstrap_tx(),
      outputs: [Output { ..test_output(), datum: InlineDatum(data) }],
    },
  )
}

test bootstrap_requires_admin() fail {
  registry_mpf.mint(
    test_deployment(),
    test_terms(),
    Bootstrap,
    test_policy,
    Transaction { ..bootstrap_tx(), extra_signatories: [] },
  )
}

test invalid_initial_terms() fail {
  registry_mpf.mint(
    test_deployment(),
    Terms { ..test_terms(), max_users: 11 },
    Bootstrap,
    test_policy,
    bootstrap_tx(),
  )
}

test renew_valid() {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(Entry { record: test_record() }),
    renewal_action(),
    test_ref,
    renewal_tx(),
  )
}

test renew_rejects_changed_ttl_quote() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(Entry { record: test_record() }),
    Renew { expected_expiry_ms: 1000, max_fee: 0, expected_ttl_ms: 2000 },
    test_ref,
    renewal_tx(),
  )
}

test renew_rejects_fee_quote() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(Entry { record: test_record() }),
    Renew { expected_expiry_ms: 1000, max_fee: -1, expected_ttl_ms: 1000 },
    test_ref,
    renewal_tx(),
  )
}

test renew_rejects_changed_expiry() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(Entry { record: test_record() }),
    Renew { expected_expiry_ms: 999, max_fee: 0, expected_ttl_ms: 1000 },
    test_ref,
    renewal_tx(),
  )
}

fn configure_action() -> Action {
  Configure {
    fee_amount: test_terms().fee_amount,
    ttl_ms: test_terms().ttl_ms,
    max_users: 10,
  }
}

test configure_valid_without_time_bounds() {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(mpf_types.datum_of(test_output())),
    configure_action(),
    test_ref,
    Transaction {
      ..test_tx(),
      validity_range: transaction.placeholder.validity_range,
    },
  )
}

test configure_unauthorized() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(mpf_types.datum_of(test_output())),
    configure_action(),
    test_ref,
    Transaction { ..test_tx(), extra_signatories: [] },
  )
}

fn invitation_tx() -> Transaction {
  let old: Data = Entry { record: Record { ..test_record(), expires_ms: 3000 } }
  let next: Data = Entry {
    record: Record {
      ..test_record(),
      expires_ms: 3000,
      members: [test_owner, test_policy],
    },
  }
  expect [input] = renewal_tx().inputs
  expect [output] = renewal_tx().outputs
  Transaction {
    ..renewal_tx(),
    inputs: [
      Input {
        ..input,
        output: Output { ..input.output, datum: InlineDatum(old) },
      },
    ],
    outputs: [Output { ..output, datum: InlineDatum(next) }],
  }
}

fn invite_old() -> RegistryDatumMPF {
  Entry { record: Record { ..test_record(), expires_ms: 3000 } }
}

test invite_valid() {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(invite_old()),
    Invite { member: test_policy },
    test_ref,
    invitation_tx(),
  )
}

test invite_requires_owner() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(invite_old()),
    Invite { member: test_policy },
    test_ref,
    Transaction { ..invitation_tx(), extra_signatories: [] },
  )
}

test invite_rejects_duplicate_member() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(invite_old()),
    Invite { member: test_owner },
    test_ref,
    invitation_tx(),
  )
}

test invite_rejects_expired_record() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(Entry { record: test_record() }),
    Invite { member: test_policy },
    test_ref,
    renewal_tx(),
  )
}

test invite_rejects_invalid_member() fail {
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(invite_old()),
    Invite { member: #"ff" },
    test_ref,
    invitation_tx(),
  )
}

test invite_rejects_capacity() fail {
  expect [reference] = invitation_tx().reference_inputs
  let root: Data = Root { root: test_root, fee: 0, ttl: 1000, max_users: 1 }
  registry_mpf.spend(
    test_deployment(),
    test_terms(),
    Some(invite_old()),
    Invite { member: test_policy },
    test_ref,
    Transaction {
      ..invitation_tx(),
      reference_inputs: [
        Input {
          ..reference,
          output: Output { ..reference.output, datum: InlineDatum(root) },
        },
      ],
    },
  )
}

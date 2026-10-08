use aiken/builtin
use aiken/crypto
use aiken/interval.{Finite, Interval, IntervalBound}
use cardano/address.{Address, VerificationKey}
use cardano/assets
use cardano/transaction.{InlineDatum, Output, OutputReference, Transaction}
use registry_types.{
  Configure, Deployment, FeeReceipt, Invite, Record, RegistryDatum, Renew,
}
use registry_types as r

const owner = #"11111111111111111111111111111111111111111111111111111111"

const policy = #"22222222222222222222222222222222222222222222222222222222"

const fee_policy = #"33333333333333333333333333333333333333333333333333333333"

const member = #"44444444444444444444444444444444444444444444444444444444"

const reference =
  OutputReference {
    transaction_id: #"0000000000000000000000000000000000000000000000000000000000000000",
    output_index: 0,
  }

const deployment =
  Deployment {
    seed: reference,
    admin: owner,
    network_domain: "preview",
    fee_policy,
    fee_name: "DEGA",
    collector: Address {
      payment_credential: VerificationKey(owner),
      stake_credential: None,
    },
  }

const record =
  Record {
    name: "Alice",
    owner,
    nostr_key: #"0000000000000000000000000000000000000000000000000000000000000000",
    opened_ms: 1000,
    expires_ms: 200000,
    members: [owner],
  }

const datum =
  RegistryDatum {
    fee_amount: 0,
    ttl_ms: 31536000000,
    max_users: 10,
    records: [record],
  }

fn tx(lower: Int, upper: Int) -> Transaction {
  Transaction {
    ..transaction.placeholder,
    extra_signatories: [owner],
    validity_range: Interval {
      lower_bound: IntervalBound {
        bound_type: Finite(lower),
        is_inclusive: True,
      },
      upper_bound: IntervalBound {
        bound_type: Finite(upper),
        is_inclusive: False,
      },
    },
  }
}

fn receipt() -> FeeReceipt {
  FeeReceipt {
    registry_policy: policy,
    consumed_tx_id: reference.transaction_id,
    consumed_output_index: 0,
    action: 1,
    name: "Alice",
  }
}

fn payment() -> Output {
  let data: Data = receipt()
  Output {
    address: deployment.collector,
    value: assets.from_asset(fee_policy, "DEGA", 42),
    datum: InlineDatum(data),
    reference_script: None,
  }
}

test names() {
  and {
    r.name_valid("aZ09._-"),
    !r.name_valid(""),
    !r.name_valid("abcdefghijklmnop"),
    !r.name_valid("a b"),
    !r.name_valid(#"ff"),
  }
}

test renewal_before_expiry() {
  let next = r.successor(
    deployment,
    datum,
    Renew {
      name: "Alice",
      expected_expiry_ms: 200000,
      max_fee: 0,
      expected_ttl_ms: datum.ttl_ms,
    },
    (policy, reference, tx(1000, 2000)),
  )
  next.records == [Record { ..record, expires_ms: 200000 + datum.ttl_ms }]
}

test renewal_after_expiry() {
  let next = r.successor(
    deployment,
    datum,
    Renew {
      name: "Alice",
      expected_expiry_ms: 200000,
      max_fee: 0,
      expected_ttl_ms: datum.ttl_ms,
    },
    (policy, reference, tx(300000, 301000)),
  )
  next.records == [Record { ..record, expires_ms: 300000 + datum.ttl_ms }]
}

test stale_renewal() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Renew {
      name: "Alice",
      expected_expiry_ms: 199999,
      max_fee: 0,
      expected_ttl_ms: datum.ttl_ms,
    },
    (policy, reference, tx(1000, 2000)),
  )

  True
}

test invitation_expiry_boundary() {
  r.successor(
    deployment,
    datum,
    Invite { name: "Alice", member },
    (policy, reference, tx(199000, 200000)),
  ).records == [Record { ..record, members: [owner, member] }]
}

test invitation_expired() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Invite { name: "Alice", member },
    (policy, reference, tx(199000, 200001)),
  )

  True
}

test duplicate_member() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Invite { name: "Alice", member: owner },
    (policy, reference, tx(1000, 2000)),
  )

  True
}

test unauthorized_invitation() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Invite { name: "Alice", member },
    (
      policy,
      reference,
      Transaction { ..tx(1000, 2000), extra_signatories: [member] },
    ),
  )

  True
}

test cap_reduction_preserves_members() {
  r.successor(
    deployment,
    datum,
    Configure { fee_amount: 3, ttl_ms: 1, max_users: 1 },
    (policy, reference, tx(1000, 2000)),
  ).records == datum.records
}

test cap_limit() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Configure { fee_amount: 0, ttl_ms: 1, max_users: 11 },
    (policy, reference, tx(1000, 2000)),
  )

  True
}

test ten_minute_interval() {
  r.bounds(tx(1000, 601000)) == (1000, 601000)
}

test interval_has_no_arbitrary_duration_cap() {
  r.bounds(tx(1000, 3601000)) == (1000, 3601000)
}

test interval_empty() fail {
  expect _ = r.bounds(tx(1000, 1000))
  True
}

test correct_fee() {
  r.fee_paid(
    deployment,
    RegistryDatum { ..datum, fee_amount: 42 },
    receipt(),
    Transaction { ..tx(1000, 2000), outputs: [payment()] },
  )
}

test missing_fee() fail {
  expect _ = r.fee_paid(
    deployment,
    RegistryDatum { ..datum, fee_amount: 42 },
    receipt(),
    tx(1000, 2000),
  )

  True
}

test duplicated_receipt() fail {
  expect _ = r.fee_paid(
    deployment,
    RegistryDatum { ..datum, fee_amount: 42 },
    receipt(),
    Transaction { ..tx(1000, 2000), outputs: [payment(), payment()] },
  )

  True
}

test underpayment() {
  !r.fee_paid(
    deployment,
    RegistryDatum { ..datum, fee_amount: 43 },
    receipt(),
    Transaction { ..tx(1000, 2000), outputs: [payment()] },
  )
}

test receipt_different_input() fail {
  expect _ = r.fee_paid(
    deployment,
    RegistryDatum { ..datum, fee_amount: 42 },
    FeeReceipt { ..receipt(), consumed_output_index: 1 },
    Transaction { ..tx(1000, 2000), outputs: [payment()] },
  )

  True
}

test minted_fee_rejected() fail {
  expect _ = r.fee_paid(
    deployment,
    datum,
    receipt(),
    Transaction {
      ..tx(1000, 2000),
      mint: assets.from_asset(fee_policy, "DEGA", 42),
    },
  )

  True
}

test golden_proof() {
  let proof: Data = r.RegistrationProof {
    domain: "dega/cardano/registration/v1",
    network_domain: "preview",
    registry_policy: #"11111111111111111111111111111111111111111111111111111111",
    owner: #"22222222222222222222222222222222222222222222222222222222",
    name: "Alice.test",
    nostr_key: #"f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
  }
  and {
    builtin.serialise_data(proof) == #"d8799f581c646567612f63617264616e6f2f726567697374726174696f6e2f76314770726576696577581c11111111111111111111111111111111111111111111111111111111581c222222222222222222222222222222222222222222222222222222224a416c6963652e746573745820f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9ff",
    crypto.sha2_256(builtin.serialise_data(proof)) == #"7da0323db1698f57b544366051c95671c202c1b1d05a022df12ec24982899fa2",
    r.proof_valid(
      deployment,
      #"11111111111111111111111111111111111111111111111111111111",
      r.Register {
        name: "Alice.test",
        owner: #"22222222222222222222222222222222222222222222222222222222",
        nostr_key: #"f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
        nostr_signature: #"a30afb9423b16ab0aa7631f02fede2ab27799f533edd04f875e6a28756e4f9b03d64587d9f824fbc7762f78ce3572c4e27437b9e661b55c03937c9fb49e6fd1f",
        max_fee: 0,
        expected_ttl_ms: 1,
      },
    ),
  }
}

fn registration() -> r.Action {
  r.Register {
    name: "Alice.test",
    owner: #"22222222222222222222222222222222222222222222222222222222",
    nostr_key: #"f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
    nostr_signature: #"a30afb9423b16ab0aa7631f02fede2ab27799f533edd04f875e6a28756e4f9b03d64587d9f824fbc7762f78ce3572c4e27437b9e661b55c03937c9fb49e6fd1f",
    max_fee: 0,
    expected_ttl_ms: datum.ttl_ms,
  }
}

fn registration_tx() -> Transaction {
  Transaction {
    ..tx(1000, 2000),
    extra_signatories: [
      #"22222222222222222222222222222222222222222222222222222222",
    ],
  }
}

test register_valid() {
  let next = r.successor(
    deployment,
    RegistryDatum { ..datum, records: [] },
    registration(),
    (
      #"11111111111111111111111111111111111111111111111111111111",
      reference,
      registration_tx(),
    ),
  )
  next.records == [
    Record {
      name: "Alice.test",
      owner: #"22222222222222222222222222222222222222222222222222222222",
      nostr_key: #"f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
      opened_ms: 1000,
      expires_ms: 1000 + datum.ttl_ms,
      members: [#"22222222222222222222222222222222222222222222222222222222"],
    },
  ]
}

test register_replay_expired_identity() fail {
  let next = r.successor(
    deployment,
    RegistryDatum { ..datum, records: [] },
    registration(),
    (
      #"11111111111111111111111111111111111111111111111111111111",
      reference,
      registration_tx(),
    ),
  )
  expect _ = r.successor(
    deployment,
    next,
    registration(),
    (
      #"11111111111111111111111111111111111111111111111111111111",
      reference,
      Transaction {
        ..registration_tx(),
        validity_range: tx(40000000000, 40000001000).validity_range,
      },
    ),
  )
  True
}

test proof_wrong_registry() {
  !r.proof_valid(deployment, policy, registration())
}

test proof_wrong_network() {
  !r.proof_valid(
    Deployment { ..deployment, network_domain: "other" },
    #"11111111111111111111111111111111111111111111111111111111",
    registration(),
  )
}

test registration_capacity() fail {
  expect _ = r.successor(
    deployment,
    RegistryDatum {
      ..datum,
      records: [record, record, record, record, record, record, record, record],
    },
    registration(),
    (
      #"11111111111111111111111111111111111111111111111111111111",
      reference,
      registration_tx(),
    ),
  )
  True
}

test configuration_unauthorized() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Configure { fee_amount: 0, ttl_ms: 1, max_users: 1 },
    (
      policy,
      reference,
      Transaction { ..tx(1000, 2000), extra_signatories: [member] },
    ),
  )
  True
}

test configuration_negative_fee() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Configure { fee_amount: -1, ttl_ms: 1, max_users: 1 },
    (policy, reference, tx(1000, 2000)),
  )
  True
}

test configuration_zero_ttl() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Configure { fee_amount: 0, ttl_ms: 0, max_users: 1 },
    (policy, reference, tx(1000, 2000)),
  )
  True
}

test lowered_cap_blocks_invites() fail {
  expect _ = r.successor(
    deployment,
    RegistryDatum { ..datum, max_users: 1 },
    Invite { name: "Alice", member },
    (policy, reference, tx(1000, 2000)),
  )
  True
}

test renewal_stale_terms() fail {
  expect _ = r.successor(
    deployment,
    datum,
    Renew {
      name: "Alice",
      expected_expiry_ms: 200000,
      max_fee: 0,
      expected_ttl_ms: 1,
    },
    (policy, reference, tx(1000, 2000)),
  )
  True
}

test renewal_fee_limit() fail {
  expect _ = r.successor(
    deployment,
    RegistryDatum { ..datum, fee_amount: 42 },
    Renew {
      name: "Alice",
      expected_expiry_ms: 200000,
      max_fee: 41,
      expected_ttl_ms: datum.ttl_ms,
    },
    (policy, reference, tx(1000, 2000)),
  )
  True
}

test burned_fee_rejected() fail {
  expect _ = r.fee_paid(
    deployment,
    datum,
    receipt(),
    Transaction {
      ..tx(1000, 2000),
      mint: assets.from_asset(fee_policy, "DEGA", -42),
    },
  )
  True
}

test malformed_signature_rejected() {
  expect
      r.Register {
        name,
        owner: proof_owner,
        nostr_key,
        max_fee,
        expected_ttl_ms,
        ..
      }
    = registration()
  !r.proof_valid(
    deployment,
    owner,
    r.Register {
      name,
      owner: proof_owner,
      nostr_key,
      nostr_signature: #"00",
      max_fee,
      expected_ttl_ms,
    },
  )
}

fn mainnet_deployment() -> Deployment {
  Deployment {
    ..deployment,
    network_domain: "mainnet",
    fee_policy: #"25c5de5f5b286073c593edfd77b48abc7a48e5a4f3d4cd9d428ff935",
  }
}

test mainnet_deployment_requires_dega() {
  and {
    r.valid_deployment(mainnet_deployment(), policy),
    !r.valid_deployment(
      Deployment { ..deployment, network_domain: "mainnet" },
      policy,
    ),
    !r.valid_deployment(
      Deployment { ..deployment, network_domain: "unknown" },
      policy,
    ),
  }
}

test mainnet_golden_proof_is_network_bound() {
  let action = r.Register {
    name: "Alice.test",
    owner: #"22222222222222222222222222222222222222222222222222222222",
    nostr_key: #"f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
    nostr_signature: #"4c132c6293d45dfb0fb30e299a8e8489ccd0d20552ed3e518862bd5d979654cdd89fff2e4e075514801d87eda00fabfd6fe4527392abf7626b03a0b2d37faa08",
    max_fee: 1512340000,
    expected_ttl_ms: 31536000000,
  }
  let proof: Data = r.RegistrationProof {
    domain: "dega/cardano/registration/v1",
    network_domain: "mainnet",
    registry_policy: #"11111111111111111111111111111111111111111111111111111111",
    owner: #"22222222222222222222222222222222222222222222222222222222",
    name: "Alice.test",
    nostr_key: #"f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
  }
  and {
    builtin.serialise_data(proof) == #"d8799f581c646567612f63617264616e6f2f726567697374726174696f6e2f7631476d61696e6e6574581c11111111111111111111111111111111111111111111111111111111581c222222222222222222222222222222222222222222222222222222224a416c6963652e746573745820f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9ff",
    crypto.sha2_256(builtin.serialise_data(proof)) == #"39575413d1bb9ee006b748c66fb99f50fae40a8f9ef29d8e8d467b302457fe0c",
    r.proof_valid(
      mainnet_deployment(),
      #"11111111111111111111111111111111111111111111111111111111",
      action,
    ),
    !r.proof_valid(
      deployment,
      #"11111111111111111111111111111111111111111111111111111111",
      action,
    ),
    !r.proof_valid(
      mainnet_deployment(),
      #"11111111111111111111111111111111111111111111111111111111",
      registration(),
    ),
  }
}

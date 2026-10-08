use aiken/builtin
use aiken/collection/list
use aiken/crypto
use aiken/interval.{Finite}
use aiken/primitive/bytearray
use cardano/address.{Address, VerificationKey}
use cardano/assets
use cardano/transaction.{InlineDatum, Output, OutputReference, Transaction}

pub type Deployment {
  seed: OutputReference,
  admin: ByteArray,
  network_domain: ByteArray,
  fee_policy: ByteArray,
  fee_name: ByteArray,
  collector: Address,
}

pub type RegistryDatum {
  fee_amount: Int,
  ttl_ms: Int,
  max_users: Int,
  records: List<Record>,
}

pub type Record {
  name: ByteArray,
  owner: ByteArray,
  nostr_key: ByteArray,
  opened_ms: Int,
  expires_ms: Int,
  members: List<ByteArray>,
}

pub type MintAction {
  Bootstrap
}

pub type Action {
  Register {
    name: ByteArray,
    owner: ByteArray,
    nostr_key: ByteArray,
    nostr_signature: ByteArray,
    max_fee: Int,
    expected_ttl_ms: Int,
  }
  Renew {
    name: ByteArray,
    expected_expiry_ms: Int,
    max_fee: Int,
    expected_ttl_ms: Int,
  }
  Invite { name: ByteArray, member: ByteArray }
  Configure { fee_amount: Int, ttl_ms: Int, max_users: Int }
}

pub type RegistrationProof {
  domain: ByteArray,
  network_domain: ByteArray,
  registry_policy: ByteArray,
  owner: ByteArray,
  name: ByteArray,
  nostr_key: ByteArray,
}

pub type FeeReceipt {
  registry_policy: ByteArray,
  consumed_tx_id: ByteArray,
  consumed_output_index: Int,
  action: Int,
  name: ByteArray,
}

pub const nft = "DEGA_CHAT_REGISTRY"

pub const initial =
  RegistryDatum {
    fee_amount: 671927000000000,
    ttl_ms: 31536000000,
    max_users: 10,
    records: [],
  }

pub fn valid_deployment(d: Deployment, policy: ByteArray) -> Bool {
  expect VerificationKey(collector) = d.collector.payment_credential
  and {
    bytearray.length(d.admin) == 28,
    bytearray.length(collector) == 28,
    bytearray.length(d.fee_policy) == 28,
    d.fee_policy != policy,
    bytearray.length(d.fee_name) <= 32,
    or {
      d.network_domain == "preview",
      d.network_domain == "mainnet",
    },
    if d.network_domain == "mainnet" {
      and {
        d.fee_policy == #"25c5de5f5b286073c593edfd77b48abc7a48e5a4f3d4cd9d428ff935",
        d.fee_name == "DEGA",
      }
    } else {
      True
    },
  }
}

pub fn state_value(output: Output, policy: ByteArray) -> Bool {
  assets.flatten(assets.without_lovelace(output.value)) == [(policy, nft, 1)]
}

pub fn name_valid(name: ByteArray) -> Bool {
  and {
    bytearray.length(name) > 0,
    bytearray.length(name) <= 15,
    bytearray.foldl(name, True, fn(c, valid) { valid && or {
          c >= 65 && c <= 90,
          c >= 97 && c <= 122,
          c >= 48 && c <= 57,
          c == 46,
          c == 95,
          c == 45,
        } }),
  }
}

pub fn bounds(tx: Transaction) -> (Int, Int) {
  expect Finite(lower) = tx.validity_range.lower_bound.bound_type
  expect Finite(upper) = tx.validity_range.upper_bound.bound_type
  expect tx.validity_range.lower_bound.is_inclusive
  expect !tx.validity_range.upper_bound.is_inclusive
  expect upper > lower
  (lower, upper)
}

pub fn fee_paid(
  d: Deployment,
  datum: RegistryDatum,
  receipt: FeeReceipt,
  tx: Transaction,
) -> Bool {
  expect assets.quantity_of(tx.mint, d.fee_policy, d.fee_name) == 0
  if datum.fee_amount == 0 {
    True
  } else {
    let data: Data = receipt
    let outputs = list.filter(
      tx.outputs,
      fn(o) { o.address == d.collector && o.datum == InlineDatum(data) },
    )
    expect [output] = outputs
    assets.flatten(assets.without_lovelace(output.value)) == [
      (d.fee_policy, d.fee_name, datum.fee_amount),
    ]
  }
}

pub fn proof_valid(d: Deployment, policy: ByteArray, action: Action) -> Bool {
  expect Register { name, owner, nostr_key, nostr_signature, .. } = action
  let proof: Data = RegistrationProof {
    domain: "dega/cardano/registration/v1",
    network_domain: d.network_domain,
    registry_policy: policy,
    owner,
    name,
    nostr_key,
  }
  and {
    bytearray.length(nostr_key) == 32,
    bytearray.length(nostr_signature) == 64,
    crypto.verify_schnorr_signature(
      nostr_key,
      crypto.sha2_256(builtin.serialise_data(proof)),
      nostr_signature,
    ),
  }
}

pub fn successor(
  d: Deployment,
  old: RegistryDatum,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> RegistryDatum {
  when action is {
    Register { .. } -> register(d, old, action, context)
    Renew { .. } -> renew(d, old, action, context)
    Invite { .. } -> invite(d, old, action, context)
    Configure { .. } -> configure(d, old, action, context)
  }
}

fn register(
  d: Deployment,
  old: RegistryDatum,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> RegistryDatum {
  let (policy, own_ref, tx) = context
  let (lower, upper) = bounds(tx)
  expect Register { name, owner, nostr_key, max_fee, expected_ttl_ms, .. } = action

  expect and {
      list.length(old.records) < 8,
      name_valid(name),
      bytearray.length(owner) == 28,
      list.has(tx.extra_signatories, owner),
      old.fee_amount <= max_fee,
      old.ttl_ms == expected_ttl_ms,
      upper <= lower + old.ttl_ms,
      proof_valid(d, policy, action),
      list.all(
        old.records,
        fn(r) { r.name != name && r.owner != owner && r.nostr_key != nostr_key },
      ),
      fee_paid(
        d,
        old,
        FeeReceipt {
          registry_policy: policy,
          consumed_tx_id: own_ref.transaction_id,
          consumed_output_index: own_ref.output_index,
          action: 0,
          name,
        },
        tx,
      ),
    }
  RegistryDatum {
    ..old,
    records: list.concat(
      old.records,
      [
        Record {
          name,
          owner,
          nostr_key,
          opened_ms: lower,
          expires_ms: lower + old.ttl_ms,
          members: [owner],
        },
      ],
    ),
  }
}

fn renew(
  d: Deployment,
  old: RegistryDatum,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> RegistryDatum {
  let (policy, own_ref, tx) = context
  let (lower, upper) = bounds(tx)
  expect Renew { name, expected_expiry_ms, max_fee, expected_ttl_ms } = action

  expect Some(record) = list.find(old.records, fn(r) { r.name == name })
  let expires = if record.expires_ms > lower {
    record.expires_ms
  } else {
    lower
  } + old.ttl_ms
  expect and {
      list.has(tx.extra_signatories, record.owner),
      record.expires_ms == expected_expiry_ms,
      old.fee_amount <= max_fee,
      old.ttl_ms == expected_ttl_ms,
      upper <= expires,
      fee_paid(
        d,
        old,
        FeeReceipt {
          registry_policy: policy,
          consumed_tx_id: own_ref.transaction_id,
          consumed_output_index: own_ref.output_index,
          action: 1,
          name,
        },
        tx,
      ),
    }
  RegistryDatum {
    ..old,
    records: list.map(
      old.records,
      fn(r) {
        if r.name == name {
          Record { ..r, expires_ms: expires }
        } else {
          r
        }
      },
    ),
  }
}

fn invite(
  _d: Deployment,
  old: RegistryDatum,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> RegistryDatum {
  let (_, _, tx) = context
  let (_, upper) = bounds(tx)
  expect Invite { name, member } = action

  expect Some(record) = list.find(old.records, fn(r) { r.name == name })
  expect and {
      list.has(tx.extra_signatories, record.owner),
      upper <= record.expires_ms,
      bytearray.length(member) == 28,
      !list.has(record.members, member),
      list.length(record.members) < old.max_users,
    }
  RegistryDatum {
    ..old,
    records: list.map(
      old.records,
      fn(r) {
        if r.name == name {
          Record { ..r, members: list.concat(r.members, [member]) }
        } else {
          r
        }
      },
    ),
  }
}

fn configure(
  d: Deployment,
  old: RegistryDatum,
  action: Action,
  context: (ByteArray, OutputReference, Transaction),
) -> RegistryDatum {
  let (_, _, tx) = context
  expect Configure { fee_amount, ttl_ms, max_users } = action

  expect and {
      list.has(tx.extra_signatories, d.admin),
      fee_amount >= 0,
      ttl_ms > 0,
      max_users >= 1,
      max_users <= 10,
    }
  RegistryDatum { ..old, fee_amount, ttl_ms, max_users }
}

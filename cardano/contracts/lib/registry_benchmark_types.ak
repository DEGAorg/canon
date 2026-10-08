//// Benchmark only: configurable initial roots support synthetic fixtures.

use aiken/collection/list
use aiken/crypto
use aiken/merkle_patricia_forestry as mpf
use aiken/primitive/bytearray
use cardano/assets
use cardano/transaction.{InlineDatum, Output, OutputReference, Transaction}
use registry_types.{Deployment, FeeReceipt, Record, RegistryDatum}

pub type BenchmarkDatum {
  Root { root: ByteArray, fee: Int, ttl: Int }
  Entry { record: Record }
}

pub type Action {
  Bootstrap
  Register { record: Record, signature: ByteArray, proofs: List<mpf.Proof> }
  Renew
}

pub const root_token = "ROOT"

pub fn record_token(name: ByteArray) -> ByteArray {
  bytearray.concat(#"01", bytearray.take(crypto.blake2b_256(name), 31))
}

pub fn authentic(output: Output, policy: ByteArray, token: ByteArray) -> Bool {
  assets.flatten(assets.without_lovelace(output.value)) == [(policy, token, 1)]
}

pub fn datum_of(output: Output) -> BenchmarkDatum {
  expect InlineDatum(data) = output.datum
  expect datum: BenchmarkDatum = data
  datum
}

pub fn unique_output(
  tx: Transaction,
  policy: ByteArray,
  token: ByteArray,
) -> Output {
  expect [output] = list.filter(
    tx.outputs,
    fn(o) { assets.quantity_of(o.value, policy, token) != 0 },
  )
  expect authentic(output, policy, token)
  output
}

pub fn inserted_root(
  root: ByteArray,
  record: Record,
  proofs: List<mpf.Proof>,
) -> ByteArray {
  expect [name_proof, owner_proof, nostr_proof] = proofs
  let token = record_token(record.name)
  mpf.from_root(root)
    |> mpf.insert(bytearray.concat(#"00", record.name), token, name_proof)
    |> mpf.insert(bytearray.concat(#"01", record.owner), token, owner_proof)
    |> mpf.insert(bytearray.concat(#"02", record.nostr_key), token, nostr_proof)
    |> mpf.root
}

pub fn paid(
  deployment: Deployment,
  state: BenchmarkDatum,
  context: (ByteArray, OutputReference, Transaction),
  action: Int,
  name: ByteArray,
) -> Bool {
  expect Root { fee, ttl, .. } = state
  let (policy, own_ref, tx) = context
  expect fee >= 0 && ttl > 0
  registry_types.fee_paid(
    deployment,
    RegistryDatum { fee_amount: fee, ttl_ms: ttl, max_users: 1, records: [] },
    FeeReceipt {
      registry_policy: policy,
      consumed_tx_id: own_ref.transaction_id,
      consumed_output_index: own_ref.output_index,
      action,
      name,
    },
    tx,
  )
}

test token_namespace() {
  bytearray.length(record_token("alice")) == 32 && record_token("alice") != root_token
}

test invalid_proof_count() fail {
  inserted_root(
    #"",
    Record {
      name: "alice",
      owner: #"",
      nostr_key: #"",
      opened_ms: 0,
      expires_ms: 1,
      members: [],
    },
    [],
  ) != #""
}

fn proof_record() -> Record {
  Record {
    name: "alice",
    owner: #"11111111111111111111111111111111111111111111111111111111",
    nostr_key: #"2222222222222222222222222222222222222222222222222222222222222222",
    opened_ms: 0,
    expires_ms: 1000,
    members: [],
  }
}

test occupied_name_rejects_insertion() fail {
  let record = proof_record()
  let root = mpf.empty
    |> mpf.insert(
        bytearray.concat(#"00", record.name),
        record_token(record.name),
        [],
      )
    |> mpf.root
  inserted_root(root, record, [[], [], []]) != #""
}

test stale_empty_proof_rejected() fail {
  let root = mpf.empty
    |> mpf.insert(#"00626f62", record_token("bob"), [])
    |> mpf.root
  inserted_root(root, proof_record(), [[], [], []]) != #""
}

test malformed_root_rejected() fail {
  inserted_root(#"00", proof_record(), [[], [], []]) == #"00"
}

fn occupied_owner_proofs() -> List<mpf.Proof> {
  [
    [
      mpf.Leaf {
        skip: 0,
        key: #"cb4d5315d3e740b131dcc08196c993ec14a080960a439186f040bfa752f230f3",
        value: #"35b9b138d34637253b1423786c29de812752ed8899d18c2473da9dc91d51ced1",
      },
    ],
    [
      mpf.Leaf {
        skip: 0,
        key: #"5306681507b37dbb94504c94728e721da8cd017e35da6e3381e4e8ec6c766a21",
        value: #"35b9b138d34637253b1423786c29de812752ed8899d18c2473da9dc91d51ced1",
      },
    ],
    [],
  ]
}

test occupied_owner_preceding_insertions_valid() {
  expect [name_proof, owner_proof, nostr_proof] = occupied_owner_proofs()
  let root = mpf.from_root(
    #"1a81ad1945551a06a84dc0b15b52f758244bc50c99bb48228ff137f07234a4a2",
  )
    |> mpf.insert(
        bytearray.concat(#"00", proof_record().name),
        record_token("alice"),
        name_proof,
      )
  mpf.has(
    root,
    #"0111111111111111111111111111111111111111111111111111111111",
    record_token("alice"),
    owner_proof,
  ) && nostr_proof == []
}

test occupied_owner_rejects_insertion() fail {
  inserted_root(
    #"1a81ad1945551a06a84dc0b15b52f758244bc50c99bb48228ff137f07234a4a2",
    proof_record(),
    occupied_owner_proofs(),
  ) != #""
}

test expired_owner_reservation_rejects_reuse() fail {
  let expired = Record { ..proof_record(), opened_ms: 0, expires_ms: 1 }
  let replacement = Record { ..expired, opened_ms: 2000, expires_ms: 3000 }
  inserted_root(
    #"1a81ad1945551a06a84dc0b15b52f758244bc50c99bb48228ff137f07234a4a2",
    replacement,
    occupied_owner_proofs(),
  ) != #""
}

fn occupied_nostr_proofs() -> List<mpf.Proof> {
  [
    [
      mpf.Leaf {
        skip: 0,
        key: #"0f0b1ea1891b827742baf34f381ac9e7da679cf971a87126d8c691ef89e2afe1",
        value: #"35b9b138d34637253b1423786c29de812752ed8899d18c2473da9dc91d51ced1",
      },
    ],
    [
      mpf.Branch {
        skip: 0,
        neighbors: #"9853bcf35cd1e0a1662df4c3765dac5133bc03f02c7a0fec546b5cae7df0741b85c09af929492a871e4fae32d9d5c36e352471cd659bcdb61de08f1722acc3b10eb923b0cbd24df54401d998531feead35a47a99f4deed205de4af81120f97610000000000000000000000000000000000000000000000000000000000000000",
      },
    ],
    [
      mpf.Branch {
        skip: 0,
        neighbors: #"0644ef979733214e1ca8d5e799fd3fd8a758b37744d83e03cae00aafdbc493827dc8d42239a99394ca7eea6adf8b87f61442d50322c94abe8889b17a6273c8b40eb923b0cbd24df54401d998531feead35a47a99f4deed205de4af81120f97610000000000000000000000000000000000000000000000000000000000000000",
      },
    ],
  ]
}

test occupied_nostr_preceding_insertions_valid() {
  expect [name_proof, owner_proof, nostr_proof] = occupied_nostr_proofs()
  let root = mpf.from_root(
    #"bc60b968348ba7eaedcea6fa61a5fc77e9ec99cf84cb6b04ea3ecec30094af1c",
  )
    |> mpf.insert(
        bytearray.concat(#"00", proof_record().name),
        record_token("alice"),
        name_proof,
      )
    |> mpf.insert(
        bytearray.concat(#"01", proof_record().owner),
        record_token("alice"),
        owner_proof,
      )
  mpf.has(
    root,
    #"022222222222222222222222222222222222222222222222222222222222222222",
    record_token("alice"),
    nostr_proof,
  )
}

test occupied_nostr_rejects_insertion() fail {
  inserted_root(
    #"bc60b968348ba7eaedcea6fa61a5fc77e9ec99cf84cb6b04ea3ecec30094af1c",
    proof_record(),
    occupied_nostr_proofs(),
  ) != #""
}

test expired_nostr_reservation_rejects_reuse() fail {
  let expired = Record { ..proof_record(), opened_ms: 0, expires_ms: 1 }
  let replacement = Record { ..expired, opened_ms: 2000, expires_ms: 3000 }
  inserted_root(
    #"bc60b968348ba7eaedcea6fa61a5fc77e9ec99cf84cb6b04ea3ecec30094af1c",
    replacement,
    occupied_nostr_proofs(),
  ) != #""
}

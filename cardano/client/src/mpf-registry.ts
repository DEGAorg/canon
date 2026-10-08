import { RegistryKoios } from '#koios';
import { Constr, Data, fromText, paymentCredentialOf } from '@lucid-evolution/lucid';
import type { LucidEvolution, TxBuilder, TxSignBuilder, UTxO } from '@lucid-evolution/lucid';
import { schnorr } from '@noble/curves/secp256k1.js';
import { bytes, hex, recordData, signProof } from '#codec';
import { decodeEntry, decodeRoot, EMPTY_ROOT, entryData, rootData } from '#mpf-codec';
import type { MpfRoot } from '#mpf-codec';
import { insertionProofs, marker, rebuildIndex, trieRoot } from '#mpf-index';
import { canonicalName, RegistryError, requireHex, requireInteger, requireText } from '#types';
import type { Deployment, RecordEntry, RegistryState, StateSnapshot } from '#types';

export interface Mutation {
  operation: 'register' | 'renew' | 'invite' | 'config';
  payload: { [key: string]: unknown };
  nostrSecret?: string;
}
export interface PreparedMutation {
  transaction: TxSignBuilder;
  stateRef: string;
  record?: RecordEntry;
}
interface MpfSnapshot extends StateSnapshot {
  root: MpfRoot;
  entries: Map<string, UTxO>;
}
function reference(utxo: UTxO): string {
  return `${utxo.txHash}#${utxo.outputIndex}`;
}
function requireAssets(utxo: UTxO, unit: string): void {
  if (
    utxo.assets[unit] !== 1n ||
    !utxo.datum ||
    utxo.datumHash ||
    Object.keys(utxo.assets).some((asset) => asset !== 'lovelace' && asset !== unit)
  ) {
    throw new RegistryError('MALFORMED_STATE', 'Invalid MPF assets or inline datum');
  }
}
async function rootUtxo(lucid: LucidEvolution, deployment: Deployment): Promise<UTxO> {
  const roots = await lucid.utxosAtWithUnit(deployment.address, deployment.stateUnit);
  if (roots.length !== 1) {
    throw new RegistryError('STATE_UNAVAILABLE', 'Expected exactly one MPF root');
  }
  const root = roots[0]!;
  requireAssets(root, deployment.stateUnit);
  return root;
}
function decodeRecords(
  candidates: UTxO[],
  deployment: Deployment,
): {
  entries: Map<string, UTxO>;
  records: RecordEntry[];
} {
  const entries = new Map<string, UTxO>();
  const records: RecordEntry[] = [];
  const seen = new Set<string>();
  for (const candidate of candidates) {
    const tokens = Object.keys(candidate.assets).filter(
      (unit) => unit.startsWith(deployment.policyId + '01') && unit.length === 120,
    );
    if (tokens.length === 0) continue;
    if (tokens.length !== 1) {
      throw new RegistryError('MALFORMED_STATE', 'Multiple registration tokens on an output');
    }
    const unit = tokens[0]!;
    requireAssets(candidate, unit);
    const record = decodeEntry(candidate.datum!);
    if (unit !== deployment.policyId + marker(record.name)) {
      throw new RegistryError('MALFORMED_STATE', 'Registration token does not match its name');
    }
    for (const identity of [record.name, record.owner, record.nostrKey].map(
      (value, index) => `${index}:${value}`,
    )) {
      if (seen.has(identity)) {
        throw new RegistryError('MALFORMED_STATE', 'Duplicate reserved registration identity');
      }
      seen.add(identity);
    }
    entries.set(record.name, candidate);
    records.push(record);
  }
  return { entries, records };
}
/** Authenticate all public registrations against the current MPF root. */
export async function snapshot(
  lucid: LucidEvolution,
  deployment: Deployment,
  now: () => number = Date.now,
): Promise<MpfSnapshot> {
  const utxo = await rootUtxo(lucid, deployment);
  const root = decodeRoot(utxo.datum!);
  const { entries, records } = decodeRecords(await lucid.utxosAt(deployment.address), deployment);
  if (trieRoot(await rebuildIndex(records)) !== root.root) {
    throw new RegistryError('STATE_UNAVAILABLE', 'Registration snapshot does not match MPF root');
  }
  const after = await rootUtxo(lucid, deployment);
  if (reference(after) !== reference(utxo) || after.datum !== utxo.datum) {
    throw new RegistryError('STALE_QUOTE', 'Registry changed during lookup; retry');
  }
  return {
    utxo,
    root,
    entries,
    state: { ...root, records },
    stateRef: reference(utxo),
    checkedAtMs: BigInt(now()),
  };
}
export function lookup(
  state: StateSnapshot,
  field: 'name' | 'owner' | 'nostrKey',
  value: string,
  includeExpired = false,
): { record: RecordEntry | null; checkedAtMs: bigint } {
  const record = state.state.records.find((item) => item[field] === value);
  return {
    record: record && (includeExpired || state.checkedAtMs < record.expiresMs) ? record : null,
    checkedAtMs: state.checkedAtMs,
  };
}
export async function bootstrap(
  lucid: LucidEvolution,
  deployment: Deployment,
): Promise<TxSignBuilder> {
  const owner = paymentCredentialOf(await lucid.wallet().address()).hash;
  if (owner !== deployment.admin) throw new RegistryError('UNAUTHORIZED', 'Admin wallet required');
  const seed = await lucid.utxosByOutRef([deployment.seed]);
  if (seed.length !== 1) throw new RegistryError('SEED_SPENT', 'Bootstrap seed is absent or spent');
  return lucid
    .newTx()
    .collectFrom(seed)
    .mintAssets({ [deployment.stateUnit]: 1n }, Data.to(new Constr(0, [])))
    .attach.MintingPolicy(deployment.script)
    .addSignerKey(owner)
    .pay.ToContract(
      deployment.address,
      { kind: 'inline', value: rootData(initialRoot(deployment)) },
      { [deployment.stateUnit]: 1n },
    )
    .complete();
}
function initialRoot(deployment: Deployment): MpfRoot {
  const terms = deployment.initialTerms;
  if (!terms) throw new RegistryError('INVALID_DEPLOYMENT', 'MPF initial terms are missing');
  return decodeRoot(
    rootData({
      root: EMPTY_ROOT,
      feeAmount: requireInteger(terms.feeAmount, 'feeAmount'),
      ttlMs: requireInteger(terms.ttlMs, 'ttlMs'),
      maxUsers: requireInteger(terms.maxUsers, 'maxUsers'),
    }),
  );
}
function requireQuote(state: StateSnapshot, payload: Mutation['payload']): void {
  if (requireText(payload.stateRef, 'stateRef') !== state.stateRef) {
    throw new RegistryError('STALE_QUOTE', 'Registry changed; request a fresh quote');
  }
}
function requireTerms(state: RegistryState, payload: Mutation['payload']): void {
  if (
    state.feeAmount > requireInteger(payload.maxFee, 'maxFee') ||
    state.ttlMs !== requireInteger(payload.expectedTtlMs, 'expectedTtlMs')
  ) {
    throw new RegistryError('STALE_TERMS', 'Fee or TTL changed; request a fresh quote');
  }
}
function existingRecord(state: RegistryState, name: string, owner: string): RecordEntry {
  const record = state.records.find((value) => value.name === name);
  if (!record) throw new RegistryError('NOT_FOUND', 'Registration does not exist');
  if (record.owner !== owner)
    throw new RegistryError('UNAUTHORIZED', 'Registration owner required');
  return record;
}
function registerTransition(
  state: RegistryState,
  input: Mutation,
  owner: string,
  lower: bigint,
  deployment: Deployment,
): { next: RegistryState; redeemer: string; record: RecordEntry } {
  const name = canonicalName(input.payload.name);
  requireTerms(state, input.payload);
  if (!input.nostrSecret) throw new RegistryError('NO_NOSTR_KEY', 'Nostr signing key is required');
  const key = hex(schnorr.getPublicKey(bytes(input.nostrSecret)));
  if (input.payload.nostrKey !== undefined && input.payload.nostrKey !== key) {
    throw new RegistryError(
      'IDENTITY_MISMATCH',
      'Supplied Nostr key does not match signing identity',
    );
  }
  if (
    state.records.some(
      (record) => record.name === name || record.owner === owner || record.nostrKey === key,
    )
  ) {
    throw new RegistryError(
      'IDENTITY_RESERVED',
      'Name, owner or Nostr identity is permanently reserved',
    );
  }
  const record: RecordEntry = {
    name,
    owner,
    nostrKey: key,
    openedMs: lower,
    expiresMs: lower + state.ttlMs,
    members: [owner],
  };
  const redeemer = Data.to(
    new Constr(1, [
      recordData(record),
      signProof(deployment.network, deployment.policyId, owner, name, input.nostrSecret),
      [],
      requireInteger(input.payload.maxFee, 'maxFee'),
      state.ttlMs,
    ]),
  );
  return { next: { ...state, records: [...state.records, record] }, redeemer, record };
}
function renewTransition(
  state: RegistryState,
  input: Mutation,
  owner: string,
  lower: bigint,
): { next: RegistryState; redeemer: string; record: RecordEntry } {
  const record = existingRecord(state, canonicalName(input.payload.name), owner);
  requireTerms(state, input.payload);
  if (requireInteger(input.payload.expectedExpiryMs, 'expectedExpiryMs') !== record.expiresMs) {
    throw new RegistryError('STALE_QUOTE', 'Registration expiry changed; request a fresh quote');
  }
  const renewed = {
    ...record,
    expiresMs: (record.expiresMs > lower ? record.expiresMs : lower) + state.ttlMs,
  };
  return {
    next: { ...state, records: state.records.map((value) => (value === record ? renewed : value)) },
    record: renewed,
    redeemer: Data.to(
      new Constr(2, [
        record.expiresMs,
        requireInteger(input.payload.maxFee, 'maxFee'),
        state.ttlMs,
      ]),
    ),
  };
}
function inviteTransition(
  state: RegistryState,
  input: Mutation,
  owner: string,
): {
  next: RegistryState;
  redeemer: string;
  record: RecordEntry;
} {
  const record = existingRecord(state, canonicalName(input.payload.name), owner);
  const member = requireHex(input.payload.member, 28, 'member');
  if (record.members.includes(member) || BigInt(record.members.length) >= state.maxUsers) {
    throw new RegistryError('MEMBER_CAPACITY', 'Member already joined or node is full');
  }
  const invited = { ...record, members: [...record.members, member] };
  return {
    next: { ...state, records: state.records.map((value) => (value === record ? invited : value)) },
    record: invited,
    redeemer: Data.to(new Constr(3, [member])),
  };
}
function configureTransition(
  state: RegistryState,
  input: Mutation,
): {
  next: RegistryState;
  redeemer: string;
  record?: RecordEntry;
} {
  const feeAmount = requireInteger(input.payload.feeAmount, 'feeAmount');
  const ttlMs = requireInteger(input.payload.ttlMs, 'ttlMs');
  const maxUsers = requireInteger(input.payload.maxUsers, 'maxUsers');
  if (ttlMs <= 0n || maxUsers < 1n || maxUsers > 10n) {
    throw new RegistryError('INVALID_TERMS', 'TTL must be positive; cap must be 1–10');
  }
  return {
    next: { ...state, feeAmount, ttlMs, maxUsers },
    redeemer: Data.to(new Constr(4, [feeAmount, ttlMs, maxUsers])),
  };
}
function feeOutput(
  tx: TxBuilder,
  deployment: Deployment,
  state: StateSnapshot,
  operation: 'register' | 'renew',
  name: string,
): TxBuilder {
  if (state.state.feeAmount === 0n) return tx;
  const receipt = Data.to(
    new Constr(0, [
      deployment.policyId,
      state.utxo.txHash,
      BigInt(state.utxo.outputIndex),
      operation === 'register' ? 0n : 1n,
      fromText(name),
    ]),
  );
  return tx.pay.ToAddressWithData(
    deployment.collector,
    { kind: 'inline', value: receipt },
    { [deployment.feePolicy + deployment.feeName]: state.state.feeAmount },
  );
}
/** Build against an authenticated snapshot and let Lucid evaluate the actual Plutus script. */
export async function prepareMutation(
  lucid: LucidEvolution,
  deployment: Deployment,
  input: Mutation,
  now: () => number = Date.now,
): Promise<PreparedMutation> {
  const current = await snapshot(lucid, deployment, now);
  requireQuote(current, input.payload);
  const owner = paymentCredentialOf(await lucid.wallet().address()).hash;
  const lower = await validityLower(lucid, now);
  const transitions = {
    register: () => registerTransition(current.state, input, owner, lower, deployment),
    renew: () => renewTransition(current.state, input, owner, lower),
    invite: () => inviteTransition(current.state, input, owner),
    config: () => configureTransition(current.state, input),
  };
  if (input.operation === 'config' && owner !== deployment.admin) {
    throw new RegistryError('UNAUTHORIZED', 'Admin wallet required');
  }
  const { next, redeemer: initialRedeemer, record } = transitions[input.operation]();
  const { root, redeemer } = await mutationRoot(current, input, {
    next,
    initialRedeemer,
    record,
  });
  const spendsRoot = input.operation === 'register' || input.operation === 'config';
  const spent = spendsRoot ? current.utxo : current.entries.get(record!.name)!;
  const upper = validityUpper(lower, record);
  if (upper <= BigInt(now())) {
    throw new RegistryError('EXPIRED', 'Transaction validity has expired; refresh the terms');
  }
  let tx = lucid
    .newTx()
    .collectFrom([spent], redeemer)
    .attach.SpendingValidator(deployment.script)
    .addSignerKey(owner)
    .validFrom(Number(lower))
    .validTo(Number(upper));
  if (spendsRoot) {
    tx = tx.pay.ToContract(
      deployment.address,
      { kind: 'inline', value: rootData(root) },
      current.utxo.assets,
    );
  } else {
    tx = tx.readFrom([current.utxo]);
  }
  tx = recordOutputs(tx, deployment, input, { current, spent, record, redeemer });
  const transaction = await tx.complete();
  requireHeadroom(lucid, transaction, now);
  return { transaction, stateRef: reference(spent), record };
}

async function mutationRoot(
  current: MpfSnapshot,
  input: Mutation,
  transition: { next: RegistryState; initialRedeemer: string; record?: RecordEntry },
): Promise<{ root: MpfRoot; redeemer: string }> {
  const { next, initialRedeemer, record } = transition;
  let redeemer = initialRedeemer;
  let root = {
    ...current.root,
    feeAmount: next.feeAmount,
    ttlMs: next.ttlMs,
    maxUsers: next.maxUsers,
  };
  if (input.operation === 'register') {
    const proof = await insertionProofs(await rebuildIndex(current.state.records), record!);
    root = { ...root, root: proof.root };
    const action = Data.from(redeemer) as Constr<Data>;
    action.fields[2] = proof.proofs;
    redeemer = Data.to(action);
  }
  return { root, redeemer };
}

function recordOutputs(
  tx: TxBuilder,
  deployment: Deployment,
  input: Mutation,
  context: { current: MpfSnapshot; spent: UTxO; record?: RecordEntry; redeemer: string },
): TxBuilder {
  const { current, spent, record, redeemer } = context;
  if (record) {
    const unit = deployment.policyId + marker(record.name);
    const assets = input.operation === 'register' ? { [unit]: 1n } : spent.assets;
    tx = tx.pay.ToContract(
      deployment.address,
      { kind: 'inline', value: entryData(record) },
      assets,
    );
    if (input.operation === 'register') {
      tx = tx.mintAssets({ [unit]: 1n }, redeemer).attach.MintingPolicy(deployment.script);
    }
  }
  if (input.operation === 'register' || input.operation === 'renew') {
    tx = feeOutput(tx, deployment, { ...current, utxo: spent }, input.operation, record!.name);
  }
  return tx;
}

function validityUpper(lower: bigint, record?: RecordEntry): bigint {
  const expiry = record?.expiresMs ?? lower + 600000n;
  const upper = expiry < lower + 600000n ? expiry : lower + 600000n;
  if (upper <= lower) throw new RegistryError('EXPIRED', 'Registration is expired');
  return upper;
}

async function validityLower(lucid: LucidEvolution, now: () => number): Promise<bigint> {
  const provider = lucid.config().provider;
  const anchor =
    provider instanceof RegistryKoios
      ? Math.min(now() - 10000, (await provider.getTip()).timeMs)
      : now() - 10000;
  return BigInt(lucid.slotToUnixTime(lucid.unixTimeToSlot(anchor)));
}

function requireHeadroom(
  lucid: LucidEvolution,
  transaction: TxSignBuilder,
  now: () => number,
): void {
  const upperSlot = transaction.toTransaction().body().ttl();
  if (upperSlot === undefined) throw new RegistryError('INVALID_TRANSACTION', 'Missing expiry');
  const upper = BigInt(lucid.slotToUnixTime(Number(upperSlot)));
  if (lucid.config().provider instanceof RegistryKoios && upper - BigInt(now()) < 30000n) {
    throw new RegistryError(
      'TRANSACTION_TIMING',
      'Too little validity time remains after evaluation; retry when Koios catches up',
    );
  }
}

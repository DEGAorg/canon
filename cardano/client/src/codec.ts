import { Constr, Data, fromText, getAddressDetails } from '@lucid-evolution/lucid';
import { createHash } from 'node:crypto';
import { schnorr } from '@noble/curves/secp256k1.js';
import { RegistryError, canonicalName, requireHex } from '#types';
import type { CardanoNetwork, Deployment, RecordEntry, RegistryState } from '#types';

export const INITIAL_STATE: RegistryState = {
  feeAmount: 671927000000000n,
  ttlMs: 31536000000n,
  maxUsers: 10n,
  records: [],
};
export const NFT_NAME = fromText('DEGA_CHAT_REGISTRY');
export const hex = (bytes: Uint8Array): string => Buffer.from(bytes).toString('hex');
export const bytes = (value: string): Uint8Array => Buffer.from(value, 'hex');

export function recordData(record: RecordEntry): Constr<Data> {
  return new Constr(0, [
    fromText(record.name),
    record.owner,
    record.nostrKey,
    record.openedMs,
    record.expiresMs,
    record.members,
  ]);
}
export function stateData(state: RegistryState): string {
  return Data.to(
    new Constr(0, [state.feeAmount, state.ttlMs, state.maxUsers, state.records.map(recordData)]),
  );
}
function fields(data: Data, size: number): Data[] {
  if (!(data instanceof Constr) || data.index !== 0 || data.fields.length !== size) {
    throw new RegistryError('MALFORMED_STATE', 'Unexpected datum constructor');
  }
  return data.fields;
}
function integer(value: Data | undefined): bigint {
  if (typeof value !== 'bigint') throw new RegistryError('MALFORMED_STATE', 'Expected integer');
  return value;
}
function dataHex(value: Data | undefined, length: number): string {
  return requireHex(value, length, 'datum bytes');
}
function decodeRecord(data: Data): RecordEntry {
  const f = fields(data, 6);
  if (typeof f[0] !== 'string' || !Array.isArray(f[5])) {
    throw new RegistryError('MALFORMED_STATE', 'Invalid registration fields');
  }
  const name = Buffer.from(f[0], 'hex').toString('utf8');
  if (canonicalName(name) !== name || Buffer.from(name).toString('hex') !== f[0]) {
    throw new RegistryError('MALFORMED_STATE', 'Invalid stored name');
  }
  const result = {
    name,
    owner: dataHex(f[1], 28),
    nostrKey: dataHex(f[2], 32),
    openedMs: integer(f[3]),
    expiresMs: integer(f[4]),
    members: f[5].map((member) => dataHex(member, 28)),
  };
  validateRecord(result);
  return result;
}
export function decodeState(cbor: string): RegistryState {
  const f = fields(Data.from(cbor), 4);
  if (!Array.isArray(f[3])) throw new RegistryError('MALFORMED_STATE', 'Expected records list');
  const state = {
    feeAmount: integer(f[0]),
    ttlMs: integer(f[1]),
    maxUsers: integer(f[2]),
    records: f[3].map(decodeRecord),
  };
  validateState(state);
  return state;
}
export function proofData(
  network: CardanoNetwork,
  policy: string,
  owner: string,
  name: string,
  key: string,
): string {
  return Data.to(
    new Constr(0, [
      fromText('dega/cardano/registration/v1'),
      fromText(network.toLowerCase()),
      policy,
      owner,
      fromText(name),
      key,
    ]),
  );
}
export function proofDigest(
  network: CardanoNetwork,
  policy: string,
  owner: string,
  name: string,
  key: string,
): Uint8Array {
  return createHash('sha256')
    .update(bytes(proofData(network, policy, owner, name, key)))
    .digest();
}
export function signProof(
  network: CardanoNetwork,
  policy: string,
  owner: string,
  name: string,
  secret: string,
): string {
  const key = hex(schnorr.getPublicKey(bytes(secret)));
  return hex(schnorr.sign(proofDigest(network, policy, owner, name, key), bytes(secret)));
}
export function addressData(address: string, network: CardanoNetwork): Constr<Data> {
  const details = getAddressDetails(address);
  const payment = details.paymentCredential;
  if (!payment || payment.type !== 'Key' || details.networkId !== (network === 'Mainnet' ? 1 : 0)) {
    throw new RegistryError(
      'INVALID_DEPLOYMENT',
      'Collector must be a payment-key address on the selected network',
    );
  }
  const credential = (kind: 'Key' | 'Script', hash: string) =>
    new Constr<Data>(kind === 'Key' ? 0 : 1, [hash]);
  const stake = details.stakeCredential;
  return new Constr(0, [
    credential(payment.type, payment.hash),
    stake
      ? new Constr(0, [new Constr(0, [credential(stake.type, stake.hash)])])
      : new Constr(1, []),
  ]);
}
export function deploymentData(
  value: Omit<
    Deployment,
    'script' | 'policyId' | 'address' | 'stateUnit' | 'blueprintHash' | 'version'
  >,
): Constr<Data> {
  return new Constr(0, [
    new Constr(0, [value.seed.txHash, BigInt(value.seed.outputIndex)]),
    value.admin,
    fromText(value.network.toLowerCase()),
    value.feePolicy,
    value.feeName,
    addressData(value.collector, value.network),
  ]);
}

function validateRecord(result: RecordEntry): void {
  if (
    result.openedMs < 0n ||
    result.expiresMs <= result.openedMs ||
    result.members[0] !== result.owner ||
    result.members.length > 10 ||
    new Set(result.members).size !== result.members.length
  ) {
    throw new RegistryError('MALFORMED_STATE', 'Invalid registration invariants');
  }
}

function validateState(state: RegistryState): void {
  const unique = (key: 'name' | 'owner' | 'nostrKey') =>
    new Set(state.records.map((record) => record[key])).size === state.records.length;
  if (
    state.feeAmount < 0n ||
    state.ttlMs <= 0n ||
    state.maxUsers < 1n ||
    state.maxUsers > 10n ||
    state.records.length > 8 ||
    !(['name', 'owner', 'nostrKey'] as const).every(unique)
  ) {
    throw new RegistryError('MALFORMED_STATE', 'Invalid registry invariants');
  }
}

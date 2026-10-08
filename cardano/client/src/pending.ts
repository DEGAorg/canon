import { CML, Constr, Data, coreToTxOutput, isEmulatorProvider } from '@lucid-evolution/lucid';
import { decodeState } from '#codec';
import { RegistryKoios } from '#koios';
import { parseNetwork } from '#network';
import { open, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import type { LucidEvolution, TransactionStatus, TxSignBuilder } from '@lucid-evolution/lucid';
import { atomicJson, json, object, readJson } from '#storage';
import type { PendingTransaction } from '#storage';
import { RegistryError, requireHex, requireText } from '#types';
import type { Deployment, Request } from '#types';

export async function withWalletLock<T>(directory: string, action: () => Promise<T>): Promise<T> {
  const path = join(directory, 'operation.lock');
  let handle;
  try {
    handle = await open(path, 'wx', 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
    throw new RegistryError(
      'WALLET_BUSY',
      'Wallet lock exists; verify no process runs before removing it',
    );
  }
  try {
    return await action();
  } finally {
    await handle.close();
    await unlink(path);
  }
}
export async function readPending(directory: string): Promise<PendingTransaction | null> {
  let raw: unknown;
  try {
    raw = await readJson(join(directory, 'pending.json'));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
  const value = object(raw, 'pending transaction');
  if (value.stateRef !== null && typeof value.stateRef !== 'string') {
    throw new RegistryError('INVALID_PENDING', 'Invalid pending state reference');
  }
  return {
    network: parseNetwork(value.network),
    txHash: requireHex(value.txHash, 32, 'pending hash'),
    cbor: requireText(value.cbor, 'pending CBOR'),
    policyId: requireHex(value.policyId, 28, 'pending policy'),
    stateRef: value.stateRef,
    operation: requireText(value.operation, 'pending operation'),
    intentHash: requireHex(value.intentHash, 32, 'pending intent'),
    ...(typeof value.nostrKey === 'string'
      ? { nostrKey: requireHex(value.nostrKey, 32, 'nostrKey') }
      : {}),
    ...(typeof value.name === 'string' ? { name: value.name } : {}),
  };
}
export async function submitPending(
  lucid: LucidEvolution,
  deployment: Deployment,
  directory: string,
): Promise<{ txHash: string; status: 'submitted' | 'confirmed' }> {
  const pending = await readPending(directory);
  if (!pending) throw new RegistryError('NO_PENDING', 'No pending transaction exists');
  if (
    pending.network !== deployment.network ||
    pending.policyId !== deployment.policyId ||
    lucid.fromTx(pending.cbor).toHash() !== pending.txHash
  ) {
    throw new RegistryError(
      'INVALID_PENDING',
      'Pending transaction belongs to another registry or hash',
    );
  }
  const status = await lucid.transactionStatus(pending.txHash);
  if (positivelyConfirmed(status)) {
    await atomicJson(join(directory, 'last-confirmed.json'), pending);
    await unlink(join(directory, 'pending.json'));
    return { txHash: pending.txHash, status: 'confirmed' };
  }
  if (status.status === 'pending' || status.status === 'confirmed') {
    return { txHash: pending.txHash, status: 'submitted' };
  }
  await prepareResubmission(lucid, deployment, directory, pending, status);
  await lucid.config().provider!.submitTx(pending.cbor);
  return { txHash: pending.txHash, status: 'submitted' };
}
export async function persistAndSubmit(
  lucid: LucidEvolution,
  deployment: Deployment,
  directory: string,
  transaction: TxSignBuilder,
  intent: {
    operation: string;
    stateRef: string | null;
    intentHash: string;
    nostrKey?: string;
    name?: string;
  },
): Promise<object> {
  if (await readPending(directory)) {
    throw new RegistryError('PENDING_EXISTS', 'Retry and confirm the existing transaction first');
  }
  const signed = await transaction.sign.withWallet().complete();
  await atomicJson(
    join(directory, 'pending.json'),
    {
      ...intent,
      txHash: signed.toHash(),
      cbor: signed.toCBOR(),
      policyId: deployment.policyId,
      network: deployment.network,
    },
    true,
  );
  return submitPending(lucid, deployment, directory);
}

export function intentHash(request: Request): string {
  const payload = request.payload ?? {};
  const fields = [
    'name',
    'nostrKey',
    'member',
    'stateRef',
    'maxFee',
    'expectedTtlMs',
    'expectedExpiryMs',
    'feeAmount',
    'ttlMs',
    'maxUsers',
  ];
  const intent = Object.fromEntries(
    fields.filter((key) => payload[key] !== undefined).map((key) => [key, payload[key]]),
  );
  return createHash('sha256')
    .update(json({ operation: request.operation, payload: intent }))
    .digest('hex');
}
export async function confirmedReplay(
  directory: string,
  deployment: Deployment,
  hash: string,
): Promise<{ txHash: string; status: 'confirmed' } | null> {
  let raw: unknown;
  try {
    raw = await readJson(join(directory, 'last-confirmed.json'));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
  const value = object(raw, 'last confirmed transaction');
  if (
    value.intentHash !== hash ||
    value.policyId !== deployment.policyId ||
    value.network !== deployment.network
  )
    return null;
  return {
    txHash: requireHex(value.txHash, 32, 'confirmed transaction hash'),
    status: 'confirmed',
  };
}

async function requireUnspentState(
  lucid: LucidEvolution,
  pending: PendingTransaction,
): Promise<void> {
  if (pending.stateRef) {
    const [txHash, index] = pending.stateRef.split('#');
    const input = await lucid.utxosByOutRef([{ txHash: txHash!, outputIndex: Number(index) }]);
    if (!input.length) {
      throw new RegistryError(
        'PENDING_CONFLICT',
        'Pending state consumed; retain journal and reconcile before another purchase',
      );
    }
  }
}

function positivelyConfirmed(status: TransactionStatus): boolean {
  return status.status === 'confirmed' && (status.confirmation.confirmations ?? 0) > 0;
}

async function archiveIfExpired(
  lucid: LucidEvolution,
  deployment: Deployment,
  directory: string,
  pending: PendingTransaction,
): Promise<void> {
  using transaction = CML.Transaction.from_cbor_hex(pending.cbor);
  using body = transaction.body();
  const upperSlot = body.ttl();
  if (upperSlot === undefined || upperSlot > (await validatedSlot(lucid))) return;
  const details =
    deployment.version === 2
      ? signedMpfTerms(transaction, pending.operation)
      : signedTerms(body, deployment);
  await atomicJson(join(directory, `expired-${pending.txHash}.json`), pending);
  await unlink(join(directory, 'pending.json'));
  throw new RegistryError(
    'PENDING_EXPIRED',
    'Pending transaction expired without confirmation; request a fresh quote before retrying',
    details,
  );
}

async function validatedSlot(lucid: LucidEvolution): Promise<bigint> {
  const provider = lucid.config().provider;
  if (isEmulatorProvider(provider)) return BigInt(provider.slot);
  if (provider instanceof RegistryKoios) return BigInt((await provider.getTip()).slot);
  throw new RegistryError('PROVIDER_UNAVAILABLE', 'Cannot verify pending transaction expiry');
}

function signedTerms(
  body: CML.TransactionBody,
  deployment: Deployment,
): {
  maxFee: string;
  expectedTtlMs: string;
} {
  using outputs = body.outputs();
  const matching = [];
  for (let index = 0; index < outputs.len(); index++) {
    using output = outputs.get(index);
    const decoded = coreToTxOutput(output);
    if (decoded.address === deployment.address && decoded.assets[deployment.stateUnit] === 1n) {
      matching.push(decoded);
    }
  }
  if (matching.length !== 1 || !matching[0]?.datum) {
    throw new RegistryError(
      'INVALID_PENDING',
      'Pending transaction lacks an unambiguous state datum',
    );
  }
  const state = decodeState(matching[0].datum);
  return { maxFee: state.feeAmount.toString(), expectedTtlMs: state.ttlMs.toString() };
}

async function prepareResubmission(
  lucid: LucidEvolution,
  deployment: Deployment,
  directory: string,
  pending: PendingTransaction,
  status: TransactionStatus,
): Promise<void> {
  await requireUnspentState(lucid, pending);
  if (status.status === 'not_found') await archiveIfExpired(lucid, deployment, directory, pending);
}

/** Recover the original signed quote from the actual MPF redeemer, never current pricing. */
function signedMpfTerms(
  transaction: CML.Transaction,
  operation: string,
): { maxFee: string; expectedTtlMs: string } | undefined {
  if (operation !== 'register' && operation !== 'renew') return undefined;
  using witnesses = transaction.witness_set();
  using redeemers = witnesses.redeemers();
  if (!redeemers) throw new RegistryError('INVALID_PENDING', 'Missing signed registry redeemer');
  using flat = redeemers.to_flat_format();
  const terms: { maxFee: string; expectedTtlMs: string }[] = [];
  for (let index = 0; index < flat.len(); index++) {
    using redeemer = flat.get(index);
    if (redeemer.tag() !== CML.RedeemerTag.Spend) continue;
    using raw = redeemer.data();
    const decoded = decodeSignedMpfTerms(Data.from(raw.to_cbor_hex()), operation);
    if (decoded) terms.push(decoded);
  }
  if (terms.length !== 1) throw new RegistryError('INVALID_PENDING', 'Ambiguous signed MPF terms');
  return terms[0]!;
}

function decodeSignedMpfTerms(
  data: Data,
  operation: string,
): { maxFee: string; expectedTtlMs: string } | undefined {
  if (!(data instanceof Constr)) return undefined;
  const [constructor, offset] = operation === 'register' ? ([1, 3] as const) : ([2, 1] as const);
  if (data.index !== constructor) return undefined;
  const fee = data.fields[offset];
  const ttl = data.fields[offset + 1];
  if (typeof fee !== 'bigint' || typeof ttl !== 'bigint' || fee < 0n || ttl <= 0n) {
    throw new RegistryError('INVALID_PENDING', 'Malformed signed MPF terms');
  }
  return { maxFee: fee.toString(), expectedTtlMs: ttl.toString() };
}

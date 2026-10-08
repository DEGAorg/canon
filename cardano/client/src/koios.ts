import { Koios } from '@lucid-evolution/lucid';
import type {
  Credential,
  OutRef,
  TransactionStatus,
  TransactionStatusOptions,
  UTxO,
} from '@lucid-evolution/lucid';
import { RegistryError, requireHex } from '#types';
import { object } from '#storage';

const delay = (milliseconds: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

/** Fetch a public read with a 10-second deadline and one bounded rate-limit retry. */
export async function koiosJson(url: string, options: RequestInit = {}): Promise<unknown> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const signal = requestSignal(options.signal);
    const response = await fetch(url, { ...options, signal });
    if (response.status === 429 && attempt === 0) {
      await rateLimitPause(response);
      continue;
    }
    if (!response.ok) {
      throw new RegistryError(
        response.status === 429 ? 'PROVIDER_RATE_LIMIT' : 'PROVIDER_UNAVAILABLE',
        'Public Koios request failed; wait before trying again',
      );
    }
    return response.json();
  }
  throw new RegistryError('PROVIDER_RATE_LIMIT', 'Public Koios rate limit; try again later');
}

/** Parse confirmations without treating mempool/zero-confirmation observations as inclusion. */
export function transactionStatus(value: unknown, txHash: string): TransactionStatus {
  if (!Array.isArray(value) || value.length > 1) {
    throw new RegistryError('MALFORMED_PROVIDER', 'Invalid Koios transaction status response');
  }
  if (value.length === 0) return { status: 'not_found', txHash };
  const row = object(value[0], 'transaction status');
  if (row.tx_hash !== txHash) {
    throw new RegistryError('MALFORMED_PROVIDER', 'Koios returned a different transaction');
  }
  if (row.num_confirmations === null) return { status: 'not_found', txHash };
  const confirmations = parseConfirmations(row.num_confirmations);
  if (confirmations === 0) return { status: 'pending', txHash };
  return { status: 'confirmed', txHash, confirmation: { txHash, confirmations } };
}

/** Read retries never submit a transaction; each SDK request already has a 10-second deadline. */
async function read<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch {
    await delay(750);
  }
  try {
    return await operation();
  } catch {
    throw new RegistryError(
      'PROVIDER_UNAVAILABLE',
      'Public Koios read failed twice; wait before trying again',
    );
  }
}

export class RegistryKoios extends Koios {
  constructor(private readonly endpoint: string) {
    super(endpoint);
  }
  async getTip(): Promise<{ slot: number; timeMs: number }> {
    const rows = await koiosJson(`${this.endpoint}/tip`);
    if (!Array.isArray(rows) || rows.length !== 1) {
      throw new RegistryError('MALFORMED_PROVIDER', 'Koios returned an invalid chain tip');
    }
    const row = object(rows[0], 'chain tip');
    if (
      !Number.isSafeInteger(row.abs_slot) ||
      Number(row.abs_slot) < 0 ||
      !Number.isSafeInteger(row.block_time)
    ) {
      throw new RegistryError('MALFORMED_PROVIDER', 'Koios returned an invalid tip slot or time');
    }
    const timeMs = Number(row.block_time) * 1000;
    if (Math.abs(Date.now() - timeMs) > 120000) {
      throw new RegistryError('STALE_CHAIN_TIP', 'Koios tip is stale; retry when it catches up');
    }
    return { slot: Number(row.abs_slot), timeMs };
  }
  override async submitTx(tx: string): Promise<string> {
    try {
      const response = await fetch(`${this.endpoint}/submittx`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/cbor' },
        body: Buffer.from(tx, 'hex'),
        signal: AbortSignal.timeout(10000),
      });
      const body = await response.text();
      if (!response.ok) throw new Error(body);
      return requireHex(JSON.parse(body) as unknown, 32, 'submitted transaction hash');
    } catch (error) {
      const message = String(error);
      if (message.includes('OutsideValidityInterval')) {
        throw new RegistryError(
          'TRANSACTION_TIMING',
          'Node rejected the transaction validity window; retry registration',
        );
      }
      if (message.includes('BadInputsUTxO')) {
        throw new RegistryError(
          'TRANSACTION_INPUTS',
          'Transaction inputs are no longer available; refresh and retry',
        );
      }
      if (/ValidationTagMismatch|ScriptWitnessNotValidating|CollectErrors/.test(message)) {
        throw new RegistryError(
          'SCRIPT_REJECTED',
          'Node rejected registry script validation; check the deployment',
        );
      }
      throw new RegistryError(
        'SUBMISSION_FAILED',
        'Koios could not submit the transaction; retry to check confirmation and resubmit',
      );
    }
  }
  override getProtocolParameters() {
    return read(() => super.getProtocolParameters());
  }
  override getUtxos(address: string | Credential) {
    return read(() => super.getUtxos(address));
  }
  override getUtxosWithUnit(address: string | Credential, unit: string) {
    return read(() => super.getUtxosWithUnit(address, unit));
  }
  override async getUtxosByOutRef(refs: OutRef[]): Promise<UTxO[]> {
    if (!refs.length) return [];
    const requested = new Set(refs.map(outRefKey));
    const rows = await koiosJson(`${this.endpoint}/utxo_info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ _utxo_refs: [...requested], _extended: false }),
    });
    const unspent = unspentAddresses(rows, requested);
    const addresses = [...new Set(unspent.values())];
    const groups = await Promise.all(addresses.map((address) => this.getUtxos(address)));
    return groups.flat().filter((utxo) => unspent.has(outRefKey(utxo)));
  }
  override evaluateTx(tx: string, utxos?: UTxO[]) {
    return read(() => super.evaluateTx(tx, utxos));
  }
  override async getTransactionStatus(
    txHash: string,
    options: TransactionStatusOptions = {},
  ): Promise<TransactionStatus> {
    requireHex(txHash, 32, 'transaction hash');
    return transactionStatus(
      await koiosJson(`${this.endpoint}/tx_status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ _tx_hashes: [txHash] }),
        signal: options.signal,
      }),
      txHash,
    );
  }
  override async awaitTx(txHash: string): Promise<boolean> {
    return (await this.getTransactionStatus(txHash)).status === 'confirmed';
  }
}

function outRefKey(ref: OutRef): string {
  requireHex(ref.txHash, 32, 'transaction hash');
  if (!Number.isSafeInteger(ref.outputIndex) || ref.outputIndex < 0) {
    throw new RegistryError('INVALID_REQUEST', 'Output index must be a nonnegative integer');
  }
  return `${ref.txHash}#${ref.outputIndex}`;
}

/** Query live outputs, avoiding unrelated historical transaction/collateral schemas. */
function unspentAddresses(value: unknown, requested: Set<string>): Map<string, string> {
  if (!Array.isArray(value)) {
    throw new RegistryError('MALFORMED_PROVIDER', 'Invalid Koios output response');
  }
  const result = new Map<string, string>();
  const seen = new Set<string>();
  for (const item of value) {
    const row = object(item, 'Koios output');
    const key = `${String(row.tx_hash)}#${String(row.tx_index)}`;
    if (!requested.has(key) || seen.has(key)) {
      throw new RegistryError('MALFORMED_PROVIDER', 'Unexpected Koios output reference');
    }
    seen.add(key);
    const address = unspentAddress(row);
    if (address !== null) result.set(key, address);
  }
  return result;
}

function unspentAddress(row: { [key: string]: unknown }): string | null {
  if (typeof row.is_spent !== 'boolean') {
    throw new RegistryError('MALFORMED_PROVIDER', 'Invalid Koios output spent status');
  }
  if (typeof row.address !== 'string' || !row.address.startsWith('addr')) {
    throw new RegistryError('MALFORMED_PROVIDER', 'Invalid Koios output address');
  }
  return row.is_spent ? null : row.address;
}

function requestSignal(signal?: AbortSignal | null): AbortSignal {
  return signal
    ? AbortSignal.any([signal, AbortSignal.timeout(10000)])
    : AbortSignal.timeout(10000);
}
async function rateLimitPause(response: Response): Promise<void> {
  const seconds = Number(response.headers.get('retry-after') ?? '1');
  await response.body?.cancel();
  await delay(Number.isFinite(seconds) ? Math.min(2000, Math.max(250, seconds * 1000)) : 1000);
}

function parseConfirmations(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new RegistryError('MALFORMED_PROVIDER', 'Invalid Koios confirmation count');
  }
  return Number(value);
}

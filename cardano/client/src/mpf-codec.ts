import { Constr, Data, fromText } from '@lucid-evolution/lucid';
import { decodeState, recordData } from '#codec';
import { RegistryError } from '#types';
import type { RecordEntry } from '#types';

export interface MpfRoot {
  root: string;
  feeAmount: bigint;
  ttlMs: bigint;
  maxUsers: bigint;
}
export const ROOT_NAME = fromText('ROOT');
export const EMPTY_ROOT = '00'.repeat(32);
export function rootData(root: MpfRoot): string {
  return Data.to(new Constr(0, [root.root, root.feeAmount, root.ttlMs, root.maxUsers]));
}
export function entryData(record: RecordEntry): string {
  return Data.to(new Constr(1, [recordData(record)]));
}
export function decodeRoot(cbor: string): MpfRoot {
  try {
    const data = Data.from(cbor);
    if (!(data instanceof Constr) || data.index !== 0 || data.fields.length !== 4) {
      throw new Error('Expected root constructor');
    }
    const [root, feeAmount, ttlMs, maxUsers] = data.fields;
    if (typeof root !== 'string' || !/^[0-9a-f]{64}$/.test(root)) {
      throw new Error('Invalid root hash');
    }
    const terms = decodeState(Data.to(new Constr(0, [feeAmount!, ttlMs!, maxUsers!, []])));
    return { root, feeAmount: terms.feeAmount, ttlMs: terms.ttlMs, maxUsers: terms.maxUsers };
  } catch {
    throw new RegistryError('MALFORMED_STATE', 'Invalid MPF root datum');
  }
}
export function decodeEntry(cbor: string): RecordEntry {
  try {
    const data = Data.from(cbor);
    if (!(data instanceof Constr) || data.index !== 1 || data.fields.length !== 1) {
      throw new Error('Expected entry constructor');
    }
    return decodeState(Data.to(new Constr(0, [0n, 1n, 10n, [data.fields[0]!]]))).records[0]!;
  } catch {
    throw new RegistryError('MALFORMED_STATE', 'Invalid MPF registration datum');
  }
}

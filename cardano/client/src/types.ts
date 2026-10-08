import type { Script, UTxO } from '@lucid-evolution/lucid';

export type CardanoNetwork = 'Mainnet' | 'Preview';

export interface RecordEntry {
  name: string;
  owner: string;
  nostrKey: string;
  openedMs: bigint;
  expiresMs: bigint;
  members: string[];
}
export interface RegistryState {
  feeAmount: bigint;
  ttlMs: bigint;
  maxUsers: bigint;
  records: RecordEntry[];
}
export interface Deployment {
  version: 1 | 2;
  initialTerms?: { feeAmount: string; ttlMs: string; maxUsers: string };
  network: CardanoNetwork;
  providerUrl: string;
  policyId: string;
  address: string;
  stateUnit: string;
  script: Script;
  seed: { txHash: string; outputIndex: number };
  admin: string;
  feePolicy: string;
  feeName: string;
  collector: string;
  blueprintHash: string;
}
export interface StateSnapshot {
  utxo: UTxO;
  state: RegistryState;
  stateRef: string;
  checkedAtMs: bigint;
}
export interface Request {
  operation: string;
  deployment: string;
  walletPath?: string;
  network?: CardanoNetwork;
  payload?: { [key: string]: unknown };
}
export class RegistryError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly details?: { maxFee: string; expectedTtlMs: string },
  ) {
    super(message);
    this.name = 'RegistryError';
  }
}
export function requireText(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value) {
    throw new RegistryError('INVALID_REQUEST', `${label} must be a nonempty string`);
  }
  return value;
}
export function requireInteger(value: unknown, label: string): bigint {
  const text = requireText(value, label);
  if (!/^(0|[1-9][0-9]*)$/.test(text)) {
    throw new RegistryError('INVALID_REQUEST', `${label} must be a nonnegative decimal string`);
  }
  return BigInt(text);
}
export function requireHex(value: unknown, bytes: number, label: string): string {
  const text = requireText(value, label);
  if (!new RegExp(`^[0-9a-f]{${bytes * 2}}$`).test(text)) {
    throw new RegistryError('INVALID_REQUEST', `${label} must be ${bytes} bytes of lowercase hex`);
  }
  return text;
}
export function canonicalName(value: unknown): string {
  const name = requireText(value, 'name')
    .trim()
    .replace(/\.dega$/, '')
    .trim();
  if (!/^[A-Za-z0-9._-]{1,15}$/.test(name)) {
    throw new RegistryError('INVALID_NAME', 'Name must contain 1–15 ASCII letters, digits, . _ -');
  }
  return name;
}

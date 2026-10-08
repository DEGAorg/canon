import { chmod, link, lstat, mkdir, open, readFile, rename, unlink } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { generateSeedPhrase, walletFromSeed, paymentCredentialOf } from '@lucid-evolution/lucid';
import { schnorr } from '@noble/curves/secp256k1.js';
import { bytes, hex } from '#codec';
import { parseNetwork } from '#network';
import type { CardanoNetwork } from '#types';
import { RegistryError, requireHex } from '#types';

interface CardanoSecret {
  network: CardanoNetwork;
  seed: string;
}
interface NostrSecret {
  secretKey: string;
}
export interface LocalIdentity {
  seed: string;
  nostrSecret: string;
}
export interface PendingTransaction {
  network: CardanoNetwork;
  txHash: string;
  cbor: string;
  policyId: string;
  stateRef: string | null;
  operation: string;
  intentHash: string;
  nostrKey?: string;
  name?: string;
}
export const json = (value: unknown): string =>
  JSON.stringify(value, (_key, item: unknown) =>
    typeof item === 'bigint' ? item.toString() : item,
  );

/** Write and synchronize a complete JSON file before exposing it at its destination. */
export async function atomicJson(path: string, value: unknown, exclusive = false): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${randomUUID()}.tmp`;
  const handle = await open(temporary, 'wx', 0o600);
  try {
    await handle.writeFile(`${json(value)}\n`);
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    if (exclusive) await link(temporary, path);
    else await rename(temporary, path);
    const directory = await open(dirname(path), 'r');
    try {
      await directory.sync();
    } finally {
      await directory.close();
    }
  } finally {
    await unlink(temporary).catch((error) => {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    });
  }
}
export async function readJson(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, 'utf8')) as unknown;
}
export function object(value: unknown, label: string): { [key: string]: unknown } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new RegistryError('INVALID_REQUEST', `${label} must be an object`);
  }
  return value as { [key: string]: unknown };
}
async function secretJson(path: string): Promise<{ [key: string]: unknown }> {
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink() || (stat.mode & 0o077) !== 0) {
    throw new RegistryError('UNSAFE_WALLET', 'Wallet must be a regular private mode-0600 file');
  }
  try {
    return object(await readJson(path), 'wallet');
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new RegistryError(
        'INVALID_WALLET',
        'Wallet data is corrupt; restore it before continuing',
      );
    }
    throw error;
  }
}
async function ensureSecret(
  path: string,
  create: () => CardanoSecret | NostrSecret,
): Promise<void> {
  try {
    await atomicJson(path, create(), true);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
  }
}
export async function readWallet(
  directory: string,
  expected?: CardanoNetwork,
): Promise<CardanoSecret> {
  const value = await secretJson(join(directory, 'cardano.json'));
  const network = parseNetwork(value.network);
  if (expected !== undefined && expected !== network) {
    throw new RegistryError(
      'WALLET_NETWORK_MISMATCH',
      'Wallet network differs from requested network',
    );
  }
  if (typeof value.seed !== 'string' || value.seed.split(' ').length !== 24) {
    throw new RegistryError('INVALID_WALLET', 'Invalid local Cardano seed');
  }
  return { network, seed: value.seed };
}
export async function readSeed(directory: string, network: CardanoNetwork): Promise<string> {
  return (await readWallet(directory, network)).seed;
}
export async function readNostr(directory: string, path?: string): Promise<string> {
  const value = await secretJson(path ?? join(directory, 'nostr.json'));
  return requireHex(value.secretKey, 32, 'local Nostr key');
}
export async function walletStatus(directory: string, expected?: CardanoNetwork): Promise<object> {
  const { seed, network } = await readWallet(directory, expected);
  const wallet = walletFromSeed(seed, { network, addressType: 'Enterprise' });
  return { network, address: wallet.address, owner: paymentCredentialOf(wallet.address).hash };
}
export async function ensureWallet(directory: string, network: CardanoNetwork): Promise<object> {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await chmod(directory, 0o700);
  await ensureSecret(join(directory, 'cardano.json'), () => ({
    network,
    seed: generateSeedPhrase(),
  }));
  await walletStatus(directory, network);
  await ensureSecret(join(directory, 'nostr.json'), () => ({
    secretKey: hex(schnorr.utils.randomSecretKey()),
  }));
  const secret = await readNostr(directory);
  return {
    ...(await walletStatus(directory, network)),
    nostrKey: hex(schnorr.getPublicKey(bytes(secret))),
  };
}

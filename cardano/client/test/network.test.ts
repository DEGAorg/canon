import { afterEach, expect, test, vi } from 'vitest';
import { mkdtemp, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { schnorr } from '@noble/curves/secp256k1.js';
import type { LucidEvolution } from '@lucid-evolution/lucid';
import * as deployment from '#deployment';
import { generateSeedPhrase } from '@lucid-evolution/lucid';
import { addressData, bytes, hex, proofData, proofDigest } from '#codec';
import {
  DEGA_NAME,
  DEGA_POLICY,
  parseNetwork,
  validateProvider,
  providerUrl,
  validateFeeAsset,
} from '#network';
import { atomicJson, ensureWallet, readSeed, walletStatus } from '#storage';
import { execute } from '#commands';

const collector =
  'addr1qyz74sz6v5ufwvmvaw2ry8k289c97ltg235mqvdqjxgcdk3af7q4hn357pyrvk638' +
  'e2mejq45jk3cxsnwctj77nudktqe9tz88';
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

test('explicit network, collector and exact native DEGA boundaries reject cross-network data', () => {
  expect(() => parseNetwork(undefined)).toThrow('Explicit');
  expect(() => parseNetwork('mainnet')).toThrow('Explicit');
  expect(() => addressData(collector, 'Mainnet')).not.toThrow();
  expect(() => addressData(collector, 'Preview')).toThrow('network');
  expect(() => addressData(collector.slice(0, -1) + 'q', 'Mainnet')).toThrow();
  expect(() => validateFeeAsset('Mainnet', DEGA_POLICY, DEGA_NAME)).not.toThrow();
  expect(() => validateFeeAsset('Mainnet', 'ab'.repeat(28), DEGA_NAME)).toThrow('verified');
  expect(() => validateFeeAsset('Mainnet', DEGA_POLICY, '44')).toThrow('verified');
  expect(() => validateFeeAsset('Preview', DEGA_POLICY, DEGA_NAME)).toThrow('mock');
});

test('wallet initialization stores network, status derives it and signing refuses mismatch', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'mainnet-network-wallet-'));
  const created = await ensureWallet(directory, 'Mainnet');
  expect(created).toMatchObject({ network: 'Mainnet' });
  expect(await walletStatus(directory)).toMatchObject({ network: 'Mainnet' });
  expect(await ensureWallet(directory, 'Mainnet')).toEqual(created);
  await expect(ensureWallet(directory, 'Preview')).rejects.toThrow('differs');
  await expect(readSeed(directory, 'Preview')).rejects.toThrow('differs');
  await expect(walletStatus(directory, 'Preview')).rejects.toThrow('differs');
  const oldDirectory = await mkdtemp(join(tmpdir(), 'seed-only-wallet-'));
  await atomicJson(join(oldDirectory, 'cardano.json'), { seed: generateSeedPhrase() });
  await expect(walletStatus(oldDirectory)).rejects.toThrow('Explicit');
  await expect(ensureWallet(oldDirectory, 'Mainnet')).rejects.toThrow('Explicit');
  await expect(
    execute({ operation: 'wallet.ensure', deployment: 'unused', walletPath: directory }),
  ).rejects.toThrow('Explicit');
});

test('Koios endpoint must agree with the chosen network without credentials', () => {
  expect(() => validateProvider('Mainnet', providerUrl('Mainnet'))).not.toThrow();
  expect(() => validateProvider('Preview', providerUrl('Preview'))).not.toThrow();
  expect(() => validateProvider('Mainnet', providerUrl('Preview'))).toThrow('network');
  expect(() => validateProvider('Mainnet', 'https://example.invalid')).toThrow('network');
});

test('Mainnet golden proof matches Aiken and cannot authenticate the Preview domain', async () => {
  const vector = JSON.parse(await readFile('test/proof-mainnet-vector.json', 'utf8'));
  const digest = proofDigest('Mainnet', vector.policy, vector.owner, vector.name, vector.key);
  expect(proofData('Mainnet', vector.policy, vector.owner, vector.name, vector.key)).toBe(
    vector.cbor,
  );
  expect(hex(digest)).toBe(vector.digest);
  expect(schnorr.verify(bytes(vector.signature), digest, bytes(vector.key))).toBe(true);
  expect(
    schnorr.verify(
      bytes(vector.signature),
      proofDigest('Preview', vector.policy, vector.owner, vector.name, vector.key),
      bytes(vector.key),
    ),
  ).toBe(false);
});

test('wallet.inspect exposes public balances and UTxOs without selecting a signing wallet', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'mainnet-inspect-'));
  const publicWallet = await ensureWallet(directory, 'Mainnet');
  const unit = DEGA_POLICY + DEGA_NAME;
  const utxosAt = vi.fn().mockResolvedValue([
    { txHash: '11'.repeat(32), outputIndex: 0, assets: { lovelace: 6000000n } },
    {
      txHash: '22'.repeat(32),
      outputIndex: 1,
      assets: { lovelace: 2000000n, [unit]: 1512340000n },
    },
  ]);
  vi.spyOn(deployment, 'connect').mockResolvedValue({ utxosAt } as unknown as LucidEvolution);
  vi.spyOn(deployment, 'checkedClock').mockResolvedValue(() => 1800000000000);
  const result = await execute({
    operation: 'wallet.inspect',
    network: 'Mainnet',
    deployment: 'unused',
    walletPath: directory,
  });
  expect(result).toMatchObject({
    network: 'Mainnet',
    checkedAtMs: 1800000000000n,
    balances: { lovelace: 8000000n, [unit]: 1512340000n },
    utxos: [{ collateralCandidate: true }, { collateralCandidate: false }],
  });
  expect(utxosAt).toHaveBeenCalledWith((publicWallet as { address: string }).address);
  expect(result).not.toHaveProperty('seed');
  expect(result).not.toHaveProperty('nostrSecret');
  await expect(
    execute({
      operation: 'wallet.inspect',
      network: 'Preview',
      deployment: 'unused',
      walletPath: directory,
    }),
  ).rejects.toThrow('differs');
});

import { afterEach, describe, expect, test, vi } from 'vitest';
import { mkdtemp, readFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { schnorr } from '@noble/curves/secp256k1.js';
import { bytes, decodeState, hex, INITIAL_STATE, proofData, proofDigest, stateData } from '#codec';
import { canonicalName } from '#types';
import { ensureWallet, readSeed, walletStatus } from '#storage';
import { checkedClock } from '#deployment';
import type { Deployment } from '#types';
import { parseRequest } from '#commands';
import { lookup } from '#registry';
import type { StateSnapshot } from '#types';

describe('boundary and identity behavior', () => {
  test('canonical names preserve case and dotted names', () => {
    expect(canonicalName(' Alice.test.dega ')).toBe('Alice.test');
    for (const value of ['', 'é', 'with space', 'a'.repeat(16)]) {
      expect(() => canonicalName(value)).toThrow();
    }
  });
  test('ABI proof matches shared Aiken golden vector', async () => {
    const vector = JSON.parse(await readFile('test/proof-vector.json', 'utf8'));
    expect(proofData('Preview', vector.policy, vector.owner, vector.name, vector.key)).toBe(
      vector.cbor,
    );
    const digest = proofDigest('Preview', vector.policy, vector.owner, vector.name, vector.key);
    expect(hex(digest)).toBe(vector.digest);
    expect(schnorr.verify(bytes(vector.signature), digest, bytes(vector.key))).toBe(true);
    expect(
      schnorr.verify(
        bytes(vector.signature),
        proofDigest('Preview', '33'.repeat(28), vector.owner, vector.name, vector.key),
        bytes(vector.key),
      ),
    ).toBe(false);
  });
  test('state decoding rejects malformed and duplicate permanent identities', () => {
    expect(decodeState(stateData(INITIAL_STATE))).toEqual(INITIAL_STATE);
    const record = {
      name: 'A',
      owner: '11'.repeat(28),
      nostrKey: '22'.repeat(32),
      openedMs: 1n,
      expiresMs: 100n,
      members: ['11'.repeat(28)],
    };
    expect(() => decodeState(stateData({ ...INITIAL_STATE, records: [record, record] }))).toThrow();
    expect(() => decodeState('d87980')).toThrow();
  });
  test('exact expiry is hidden in discovery but preserved in recovery', () => {
    const record = {
      name: 'A',
      owner: '11'.repeat(28),
      nostrKey: '22'.repeat(32),
      openedMs: 1n,
      expiresMs: 100n,
      members: ['11'.repeat(28)],
    };
    const snapshot = {
      checkedAtMs: 100n,
      state: { ...INITIAL_STATE, records: [record] },
    } as StateSnapshot;
    expect(lookup(snapshot, 'name', 'A').record).toBeNull();
    expect(lookup(snapshot, 'name', 'A', true).record).toEqual(record);
  });
  test('wallet ensure is private, idempotent and secrets never appear in public status', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'cardano-wallet-test-'));
    const initial = await ensureWallet(directory, 'Preview');
    const seed = await readSeed(directory, 'Preview');
    expect(await ensureWallet(directory, 'Preview')).toEqual(initial);
    expect(await readSeed(directory, 'Preview')).toBe(seed);
    for (const file of ['cardano.json', 'nostr.json']) {
      expect((await stat(join(directory, file))).mode & 0o777).toBe(0o600);
    }
    expect(JSON.stringify(await walletStatus(directory))).not.toContain(seed);
  });
  test('readonly wallet status does not create missing secrets', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'cardano-wallet-missing-'));
    await expect(walletStatus(directory)).rejects.toThrow();
    await expect(stat(join(directory, 'cardano.json'))).rejects.toThrow();
  });
  test('CLI malformed input produces structured sanitized errors and nonzero exit', () => {
    const child = spawnSync(process.execPath, ['dist/cli.js'], {
      input: 'secret invalid input\n',
      encoding: 'utf8',
    });
    expect(child.status).toBe(1);
    const output = JSON.parse(child.stdout);
    expect(output.ok).toBe(false);
    expect(child.stdout).not.toContain('secret invalid input');
    expect(child.stderr).toBe('');
    expect(() => parseRequest({ operation: 'resolve' })).toThrow();
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

test('validated tip clock stays live even when the latest block is 90 seconds old', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(1800000000000);

  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => [{ block_time: 1799999910 }] }),
  );
  const clock = await checkedClock({
    network: 'Preview',
    providerUrl: 'https://preview.koios.rest/api/v1',
  } as Deployment);
  expect(clock()).toBe(1800000000000);
  vi.advanceTimersByTime(5000);
  expect(clock()).toBe(1800000005000);
});
test('clock rejects stale provider state and mainnet endpoint', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(1800000000000);

  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => [{ block_time: 1799999800 }] }),
  );
  await expect(
    checkedClock({
      network: 'Preview',
      providerUrl: 'https://preview.koios.rest/api/v1',
    } as Deployment),
  ).rejects.toThrow('stale');
  await expect(
    checkedClock({
      network: 'Preview',
      providerUrl: 'https://api.koios.rest/api/v1',
    } as Deployment),
  ).rejects.toThrow('network');
});

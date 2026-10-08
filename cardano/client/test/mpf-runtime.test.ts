import { expect, test } from 'vitest';
import { resolve, join } from 'node:path';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import {
  Emulator,
  Lucid,
  generateEmulatorAccount,
  paymentCredentialOf,
  walletFromSeed,
} from '@lucid-evolution/lucid';
import { createDeployment, validateDeployment } from '#deployment';
import { bootstrap, snapshot, prepareMutation, lookup } from '#mpf-registry';
import { readOperation } from '#commands';
import { atomicJson } from '#storage';
import { readPending, submitPending } from '#pending';
import type { Mutation } from '#registry';
const blueprint = resolve('../contracts/plutus.json');
const initialTerms = { feeAmount: '1512340000', ttlMs: '31536000000', maxUsers: '10' };

async function context() {
  const accounts = Array.from({ length: 14 }, () =>
    generateEmulatorAccount({
      lovelace: 1000000000n,
      ['ab'.repeat(28) + '44454741']: 100000000000n,
    }),
  );
  for (const account of accounts)
    account.address = walletFromSeed(account.seedPhrase, {
      network: 'Preview',
      addressType: 'Enterprise',
    }).address;
  const emulator = new Emulator(accounts);
  const lucid = await Lucid(emulator, 'Preview');
  lucid.selectWallet.fromSeed(accounts[0]!.seedPhrase, { addressType: 'Enterprise' });
  const [seed] = await lucid.wallet().getUtxos();
  const deployment = await createDeployment(blueprint, {
    network: 'Preview',
    providerUrl: 'emulator',
    seed: seed!,
    admin: paymentCredentialOf(accounts[0]!.address).hash,
    feePolicy: 'ab'.repeat(28),
    feeName: '44454741',
    collector: accounts[13]!.address,
    initialTerms,
  });
  expect(deployment.version).toBe(2);
  const tx = await bootstrap(lucid, deployment);
  await (await tx.sign.withWallet().complete()).submit();
  emulator.awaitBlock();
  return { accounts, lucid, emulator, deployment };
}
type Context = Awaited<ReturnType<typeof context>>;
function select(c: Context, index: number) {
  c.lucid.selectWallet.fromSeed(c.accounts[index]!.seedPhrase, { addressType: 'Enterprise' });
}
async function prepare(c: Context, input: Mutation) {
  const state = await snapshot(c.lucid, c.deployment, () => c.emulator.now());
  return prepareMutation(
    c.lucid,
    c.deployment,
    {
      ...input,
      payload: {
        stateRef: state.stateRef,
        maxFee: state.state.feeAmount.toString(),
        expectedTtlMs: state.state.ttlMs.toString(),
        ...input.payload,
      },
    },
    () => c.emulator.now(),
  );
}
async function change(c: Context, input: Mutation) {
  const prepared = await prepare(c, input);
  await (await prepared.transaction.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  return prepared;
}
function registration(index: number): Mutation {
  return {
    operation: 'register',
    payload: { name: `member${index}` },
    nostrSecret: index.toString(16).padStart(64, '0'),
  };
}

test('deployable MPF registers twelve users and resolves through Canon interface', async () => {
  const c = await context();
  for (let i = 1; i <= 12; i++) {
    select(c, i);
    await change(c, registration(i));
  }
  const state = await snapshot(c.lucid, c.deployment, () => c.emulator.now());
  expect(state.state.records).toHaveLength(12);
  expect(state.state.feeAmount).toBe(1512340000n);
  expect(lookup(state, 'name', 'member12').record!.nostrKey).toHaveLength(64);
  const status = await readOperation(
    c.lucid,
    c.deployment,
    {
      operation: 'status',
      deployment: 'unused',
      payload: { owner: state.state.records[0]!.owner },
    },
    () => c.emulator.now(),
  );
  expect(status).toMatchObject({
    feeAmount: 1512340000n,
    record: { name: state.state.records[0]!.name },
  });
  await expect(change(c, registration(13))).rejects.toThrow();
}, 120000);

test('deployable MPF renewal, invitation and configuration preserve identities', async () => {
  const c = await context();
  select(c, 1);
  const p = await change(c, registration(1));
  const record = p.record!;
  await change(c, {
    operation: 'renew',
    payload: { name: record.name, expectedExpiryMs: record.expiresMs.toString() },
  });
  await change(c, {
    operation: 'invite',
    payload: { name: record.name, member: paymentCredentialOf(c.accounts[2]!.address).hash },
  });
  let state = await snapshot(c.lucid, c.deployment, () => c.emulator.now());
  expect(state.state.records[0]!.members).toHaveLength(2);
  expect(state.state.records[0]!.expiresMs).toBe(record.expiresMs + 31536000000n);
  await expect(
    change(c, {
      operation: 'config',
      payload: { feeAmount: '1', ttlMs: '1000000', maxUsers: '2' },
    }),
  ).rejects.toThrow();
  select(c, 0);
  await change(c, {
    operation: 'config',
    payload: { feeAmount: '1', ttlMs: '1000000', maxUsers: '2' },
  });
  state = await snapshot(c.lucid, c.deployment, () => c.emulator.now());
  expect(state.state.feeAmount).toBe(1n);
  select(c, 1);
  await expect(
    change(c, {
      operation: 'renew',
      payload: {
        name: record.name,
        expectedExpiryMs: state.state.records[0]!.expiresMs.toString(),
        expectedTtlMs: '31536000000',
      },
    }),
  ).rejects.toThrow();
  await expect(
    change(c, {
      operation: 'invite',
      payload: { name: record.name, member: paymentCredentialOf(c.accounts[3]!.address).hash },
    }),
  ).rejects.toThrow();
}, 120000);

test('deployable MPF expires pending registration with original signed quote', async () => {
  const c = await context();
  select(c, 1);
  const p = await prepare(c, registration(1));
  const signed = await p.transaction.sign.withWallet().complete();
  const directory = await mkdtemp(join(tmpdir(), 'mpf-pending-'));
  await atomicJson(join(directory, 'pending.json'), {
    network: 'Preview',
    policyId: c.deployment.policyId,
    txHash: signed.toHash(),
    cbor: signed.toCBOR(),
    stateRef: p.stateRef,
    operation: 'register',
    intentHash: '33'.repeat(32),
    name: 'member1',
  });
  c.emulator.awaitSlot(Number(signed.toTransaction().body().ttl()) - c.emulator.slot);
  await expect(submitPending(c.lucid, c.deployment, directory)).rejects.toMatchObject({
    code: 'PENDING_EXPIRED',
    details: { maxFee: '1512340000', expectedTtlMs: '31536000000' },
  });
  expect(await readPending(directory)).toBeNull();
}, 120000);

test('version two manifest rejects missing terms and wrong root token', async () => {
  const c = await context();
  expect(() => validateDeployment({ ...c.deployment, initialTerms: undefined })).toThrow();
  expect(() =>
    validateDeployment({ ...c.deployment, stateUnit: c.deployment.policyId + '00' }),
  ).toThrow();
});

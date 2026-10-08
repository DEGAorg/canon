import { expect, test, vi } from 'vitest';
import { mkdir, mkdtemp, readFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { RegistryKoios } from '#koios';
import { CML } from '@lucid-evolution/lucid';
import { emulatorContext, demoRegister } from '#emulator';
import { prepareMutation, snapshot } from '#registry';
import { atomicJson } from '#storage';
import type { PendingTransaction } from '#storage';
import { readPending, submitPending, withWalletLock } from '#pending';

const blueprint = process.env.CARDANO_BLUEPRINT ?? resolve('../contracts/plutus.json');

async function fixture() {
  const context = await emulatorContext(blueprint);
  const { lucid, deployment, emulator, accounts } = context;
  lucid.selectWallet.fromSeed(accounts[1]!.seedPhrase, { addressType: 'Enterprise' });
  const current = await snapshot(lucid, deployment, () => emulator.now());
  const prepared = await prepareMutation(
    lucid,
    deployment,
    {
      operation: 'register',
      payload: {
        name: 'expiry',
        stateRef: current.stateRef,
        maxFee: (current.state.feeAmount + 100n).toString(),
        expectedTtlMs: current.state.ttlMs.toString(),
      },
      nostrSecret: '00'.repeat(31) + '02',
    },
    () => emulator.now(),
  );
  const signed = await prepared.transaction.sign.withWallet().complete();
  const directory = await mkdtemp(join(tmpdir(), 'pending-expiry-'));
  const pending: PendingTransaction = {
    cbor: signed.toCBOR(),
    txHash: signed.toHash(),
    network: deployment.network,
    policyId: deployment.policyId,
    operation: 'register',
    stateRef: current.stateRef,
    intentHash: '33'.repeat(32),
    name: 'expiry',
  };
  await atomicJson(join(directory, 'pending.json'), pending);
  using transaction = CML.Transaction.from_cbor_hex(pending.cbor);
  using body = transaction.body();
  const upper = Number(body.ttl());
  const submit = () => withWalletLock(directory, () => submitPending(lucid, deployment, directory));
  return { ...context, directory, pending, current, upper, submit };
}

test('exact expiry archives unknown transaction with signed terms', async () => {
  const context = await fixture();
  context.emulator.awaitSlot(context.upper - context.emulator.slot);
  const submit = vi.spyOn(context.emulator, 'submitTx');
  await expect(context.submit()).rejects.toMatchObject({
    code: 'PENDING_EXPIRED',
    details: {
      maxFee: context.current.state.feeAmount.toString(),
      expectedTtlMs: context.current.state.ttlMs.toString(),
    },
  });
  expect(await readPending(context.directory)).toBeNull();
  const path = join(context.directory, `expired-${context.pending.txHash}.json`);
  expect(JSON.parse(await readFile(path, 'utf8'))).toEqual(context.pending);
  expect((await stat(path)).mode & 0o777).toBe(0o600);
  expect(submit).not.toHaveBeenCalled();
  expect(
    (await snapshot(context.lucid, context.deployment, () => context.emulator.now())).state.records,
  ).toHaveLength(0);
}, 60000);

test('unexpired transaction resubmits identical bytes and retains journal', async () => {
  const context = await fixture();
  context.emulator.awaitSlot(context.upper - context.emulator.slot - 1);
  const submit = vi.spyOn(context.emulator, 'submitTx');
  await expect(context.submit()).resolves.toEqual({
    txHash: context.pending.txHash,
    status: 'submitted',
  });
  expect(submit).toHaveBeenCalledWith(context.pending.cbor);
  expect(await readPending(context.directory)).toEqual(context.pending);
}, 60000);

test('confirmed transaction wins over elapsed TTL and retains confirmed receipt', async () => {
  const context = await fixture();
  await context.submit();
  context.emulator.awaitBlock();
  context.emulator.awaitSlot(context.upper - context.emulator.slot + 1);
  await expect(context.submit()).resolves.toEqual({
    txHash: context.pending.txHash,
    status: 'confirmed',
  });
  expect(await readPending(context.directory)).toBeNull();
  expect(
    JSON.parse(await readFile(join(context.directory, 'last-confirmed.json'), 'utf8')),
  ).toEqual(context.pending);
}, 60000);

test('unconfirmed observed transaction retains journal even after expiry', async () => {
  const context = await fixture();
  context.emulator.awaitSlot(context.upper - context.emulator.slot);
  vi.spyOn(context.emulator, 'getTransactionStatus').mockResolvedValue({
    status: 'pending',
    txHash: context.pending.txHash,
  });
  const submit = vi.spyOn(context.emulator, 'submitTx');
  await expect(context.submit()).resolves.toMatchObject({ status: 'submitted' });
  expect(await readPending(context.directory)).toEqual(context.pending);
  expect(submit).not.toHaveBeenCalled();
}, 60000);

test('competing consumption prevents expiry cleanup', async () => {
  const context = await fixture();
  await demoRegister(context, 2, 'competitor');
  context.emulator.awaitSlot(Math.max(0, context.upper - context.emulator.slot));
  await expect(context.submit()).rejects.toMatchObject({ code: 'PENDING_CONFLICT' });
  expect(await readPending(context.directory)).toEqual(context.pending);
}, 60000);

test('provider status failure never archives or submits', async () => {
  const context = await fixture();
  context.emulator.awaitSlot(context.upper - context.emulator.slot);
  vi.spyOn(context.emulator, 'getTransactionStatus').mockRejectedValue(new Error('unavailable'));
  const submit = vi.spyOn(context.emulator, 'submitTx');
  await expect(context.submit()).rejects.toThrow('unavailable');
  expect(await readPending(context.directory)).toEqual(context.pending);
  expect(submit).not.toHaveBeenCalled();
}, 60000);

test('reported failed transaction is not archived as an unobserved expiry', async () => {
  const context = await fixture();
  context.emulator.awaitSlot(context.upper - context.emulator.slot);
  vi.spyOn(context.emulator, 'getTransactionStatus').mockResolvedValue({
    status: 'failed',
    txHash: context.pending.txHash,
  });
  const submit = vi.spyOn(context.emulator, 'submitTx').mockRejectedValue(new Error('rejected'));
  await expect(context.submit()).rejects.toThrow('rejected');
  expect(await readPending(context.directory)).toEqual(context.pending);
  expect(submit).toHaveBeenCalledWith(context.pending.cbor);
}, 60000);

test('unavailable validated chain tip retains pending transaction without submission', async () => {
  const context = await fixture();
  const provider = new RegistryKoios('https://preview.koios.rest/api/v1');
  vi.spyOn(provider, 'getTip').mockRejectedValue(new Error('stale tip'));
  const submit = vi.spyOn(provider, 'submitTx');
  vi.spyOn(context.lucid, 'config').mockReturnValue({ ...context.lucid.config(), provider });
  await expect(context.submit()).rejects.toThrow('stale tip');
  expect(await readPending(context.directory)).toEqual(context.pending);
  expect(submit).not.toHaveBeenCalled();
}, 60000);

test('archive persistence failure never clears the pending journal', async () => {
  const context = await fixture();
  context.emulator.awaitSlot(context.upper - context.emulator.slot);
  await mkdir(join(context.directory, `expired-${context.pending.txHash}.json`));
  await expect(context.submit()).rejects.toThrow();
  expect(await readPending(context.directory)).toEqual(context.pending);
}, 60000);

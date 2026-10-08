import { expect, test, vi } from 'vitest';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { Constr, Data, fromText, paymentCredentialOf } from '@lucid-evolution/lucid';
import { emulatorContext, demoRegister } from '#emulator';
import type { TestContext } from '#emulator';
import { lookup, prepareMutation, snapshot } from '#registry';
import type { Mutation } from '#registry';
import { stateData } from '#codec';
import { atomicJson, readJson } from '#storage';
import { execute, mutate, readOperation } from '#commands';
import type { Request } from '#types';

const blueprint = process.env.CARDANO_BLUEPRINT ?? resolve('../contracts/plutus.json');
function select(context: TestContext, index: number): void {
  context.lucid.selectWallet.fromSeed(context.accounts[index]!.seedPhrase, {
    addressType: 'Enterprise',
  });
}
async function change(
  context: TestContext,
  operation: Mutation['operation'],
  payload: { [key: string]: unknown },
): Promise<object> {
  const state = await snapshot(context.lucid, context.deployment, () => context.emulator.now());
  const transaction = await prepareMutation(
    context.lucid,
    context.deployment,
    { operation, payload: { stateRef: state.stateRef, ...payload } },
    () => context.emulator.now(),
  );
  const signed = await transaction.transaction.sign.withWallet().complete();
  await signed.submit();
  context.emulator.awaitBlock();
  return {
    size: signed.toCBOR().length / 2,
    budgets: await context.emulator.evaluateTx(signed.toCBOR()),
  };
}

test('bootstrap, native fee registration, discovery, renewal, invite, expiry and owner recovery', async () => {
  const context = await emulatorContext(blueprint);
  const { lucid, deployment, emulator, accounts } = context;
  const before = await lucid.utxosAt(deployment.collector);
  await demoRegister(context, 1, 'Alice.test');
  let current = await snapshot(lucid, deployment, () => emulator.now());
  const record = lookup(current, 'name', 'Alice.test').record!;
  expect(record.members).toEqual([record.owner]);
  expect(lookup(current, 'nostrKey', record.nostrKey).record).toEqual(record);
  const total = (utxos: typeof before) =>
    utxos.reduce(
      (sum, utxo) => sum + (utxo.assets[deployment.feePolicy + deployment.feeName] ?? 0n),
      0n,
    );
  expect(total(await lucid.utxosAt(deployment.collector)) - total(before)).toBe(
    current.state.feeAmount,
  );
  await change(context, 'renew', {
    name: record.name,
    maxFee: current.state.feeAmount.toString(),
    expectedTtlMs: current.state.ttlMs.toString(),
    expectedExpiryMs: record.expiresMs.toString(),
  });
  current = await snapshot(lucid, deployment, () => emulator.now());
  expect(current.state.records[0]!.expiresMs).toBe(record.expiresMs + current.state.ttlMs);
  await change(context, 'invite', {
    name: record.name,
    member: paymentCredentialOf(accounts[2]!.address).hash,
  });
  current = await snapshot(lucid, deployment, () => emulator.now());
  expect(current.state.records[0]!.members).toHaveLength(2);
  const oldExpiry = current.state.records[0]!.expiresMs;
  emulator.awaitSlot(Math.ceil(Number(oldExpiry - BigInt(emulator.now())) / 1000));
  current = await snapshot(lucid, deployment, () => emulator.now());
  expect(lookup(current, 'name', record.name).record).toBeNull();
  expect(lookup(current, 'owner', record.owner, true).record).not.toBeNull();
  expect(
    await readOperation(
      lucid,
      deployment,
      { operation: 'status', deployment: 'unused', payload: { owner: record.owner } },
      () => emulator.now(),
    ),
  ).toMatchObject({
    stateRef: current.stateRef,
    feeAmount: current.state.feeAmount,
    record: { owner: record.owner, expiresMs: oldExpiry },
    checkedAtMs: current.checkedAtMs,
  });
  await change(context, 'renew', {
    name: record.name,
    maxFee: current.state.feeAmount.toString(),
    expectedTtlMs: current.state.ttlMs.toString(),
    expectedExpiryMs: oldExpiry.toString(),
  });
  expect(
    lookup(await snapshot(lucid, deployment, () => emulator.now()), 'name', record.name).record,
  ).not.toBeNull();
}, 60000);

test('owner, stale quote and duplicate identities fail without changing state', async () => {
  const context = await emulatorContext(blueprint);
  await demoRegister(context, 1, 'alice');
  const current = await snapshot(context.lucid, context.deployment, () => context.emulator.now());
  select(context, 2);
  await expect(
    change(context, 'invite', { name: 'alice', member: '33'.repeat(28) }),
  ).rejects.toThrow('owner required');
  select(context, 1);
  await expect(demoRegister(context, 1, 'another')).rejects.toThrow('permanently reserved');
  await expect(
    prepareMutation(
      context.lucid,
      context.deployment,
      { operation: 'renew', payload: { name: 'alice', stateRef: 'stale' } },
      () => context.emulator.now(),
    ),
  ).rejects.toThrow('fresh quote');
  expect(
    (await snapshot(context.lucid, context.deployment, () => context.emulator.now())).stateRef,
  ).toBe(current.stateRef);
}, 60000);

test('actual script rejects unauthorized successor and omitted positive fee', async () => {
  const context = await emulatorContext(blueprint);
  await demoRegister(context, 1, 'alice');
  const { lucid, deployment, emulator } = context;
  const current = await snapshot(lucid, deployment, () => emulator.now());
  const record = current.state.records[0]!;
  const lower = emulator.now();
  const next = {
    ...current.state,
    records: [{ ...record, expiresMs: record.expiresMs + current.state.ttlMs }],
  };
  const redeemer = Data.to(
    new Constr(1, [
      fromText(record.name),
      record.expiresMs,
      current.state.feeAmount,
      current.state.ttlMs,
    ]),
  );
  const build = () =>
    lucid
      .newTx()
      .collectFrom([current.utxo], redeemer)
      .attach.SpendingValidator(deployment.script)
      .addSignerKey(record.owner)
      .validFrom(lower)
      .validTo(lower + 60000)
      .pay.ToContract(
        deployment.address,
        { kind: 'inline', value: stateData(next) },
        current.utxo.assets,
      )
      .complete();
  await expect(build()).rejects.toThrow();
  select(context, 2);
  await expect(
    lucid
      .newTx()
      .collectFrom([current.utxo], Data.to(new Constr(3, [0n, current.state.ttlMs, 10n])))
      .attach.SpendingValidator(deployment.script)
      .addSignerKey(paymentCredentialOf(context.accounts[2]!.address).hash)
      .validFrom(lower)
      .validTo(lower + 60000)
      .pay.ToContract(
        deployment.address,
        { kind: 'inline', value: stateData({ ...current.state, feeAmount: 0n }) },
        current.utxo.assets,
      )
      .complete(),
  ).rejects.toThrow();
}, 60000);

test('durable submitted retry confirms same tx, replay never buys another term', async () => {
  const context = await emulatorContext(blueprint);
  const directory = await mkdtemp(join(tmpdir(), 'cardano-pending-test-'));
  await atomicJson(join(directory, 'cardano.json'), {
    network: 'Preview',
    seed: context.accounts[1]!.seedPhrase,
  });
  const current = await snapshot(context.lucid, context.deployment, () => context.emulator.now());
  const request: Request = {
    operation: 'register',
    deployment: 'unused',
    walletPath: directory,
    payload: {
      name: 'alice',
      nostrSecret: '00'.repeat(31) + '02',
      stateRef: current.stateRef,
      maxFee: current.state.feeAmount.toString(),
      expectedTtlMs: current.state.ttlMs.toString(),
    },
  };
  const result = await mutate(context.lucid, context.deployment, request, () =>
    context.emulator.now(),
  );
  expect(result).toMatchObject({ status: 'submitted' });
  const pendingHash = (result as { txHash: string }).txHash;
  const observed = vi.spyOn(context.emulator, 'getTransactionStatus').mockResolvedValueOnce({
    status: 'confirmed',
    txHash: pendingHash,
    confirmation: { txHash: pendingHash, confirmations: 0 },
  });
  const submitObserved = vi.spyOn(context.emulator, 'submitTx');
  expect(
    await mutate(context.lucid, context.deployment, request, () => context.emulator.now()),
  ).toMatchObject({ status: 'submitted', txHash: pendingHash });
  expect(submitObserved).not.toHaveBeenCalled();
  observed.mockRestore();
  submitObserved.mockRestore();
  const journal = await readFile(join(directory, 'pending.json'), 'utf8');
  expect(journal).not.toContain(request.payload!.nostrSecret);
  expect(journal).not.toContain(context.accounts[1]!.seedPhrase);
  await expect(
    mutate(context.lucid, context.deployment, { ...request, operation: 'renew' }, () =>
      context.emulator.now(),
    ),
  ).rejects.toThrow('existing');
  await expect(
    mutate(
      context.lucid,
      context.deployment,
      { ...request, payload: { ...request.payload, nostrSecret: '00'.repeat(31) + '03' } },
      () => context.emulator.now(),
    ),
  ).rejects.toThrow('existing');
  const pendingStatus = await execute({
    operation: 'pending.status',
    deployment: 'unused',
    walletPath: directory,
  });
  expect(pendingStatus).toMatchObject({
    pending: {
      operation: 'register',
      name: 'alice',
      nostrKey: 'c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5',
    },
  });
  expect(JSON.stringify(pendingStatus)).not.toContain('cbor');
  context.emulator.awaitBlock();
  const confirmed = await mutate(context.lucid, context.deployment, request, () =>
    context.emulator.now(),
  );
  expect(confirmed).toMatchObject({
    status: 'confirmed',
    txHash: (result as { txHash: string }).txHash,
  });
  expect(
    await mutate(context.lucid, context.deployment, request, () => context.emulator.now()),
  ).toEqual(confirmed);
  expect(
    (await snapshot(context.lucid, context.deployment, () => context.emulator.now())).state.records,
  ).toHaveLength(1);
}, 60000);

test('eight permanent records with ten members fit protocol size and execution limits', async () => {
  const context = await emulatorContext(blueprint);
  const measurements: { operation: string; size: number; cpu: number; mem: number }[] = [];
  for (let index = 0; index < 8; index++) {
    const register = await demoRegister(context, index, `member-${index}`);
    measurements.push({ operation: 'register', ...register });
    for (let member = 1; member < 10; member++) {
      const metrics = (await change(context, 'invite', {
        name: `member-${index}`,
        member: (1000 + index * 10 + member).toString(16).padStart(56, '0'),
      })) as {
        size: number;
        budgets: { ex_units: { steps: number; mem: number } }[];
      };
      measurements.push({
        operation: 'invite',
        size: metrics.size,
        cpu: metrics.budgets.reduce((sum, value) => sum + value.ex_units.steps, 0),
        mem: metrics.budgets.reduce((sum, value) => sum + value.ex_units.mem, 0),
      });
    }
  }
  const state = await snapshot(context.lucid, context.deployment, () => context.emulator.now());
  expect(state.state.records).toHaveLength(8);
  expect(state.state.records.every((record) => record.members.length === 10)).toBe(true);
  select(context, 7);
  const record = state.state.records[7]!;
  const renewed = (await change(context, 'renew', {
    name: record.name,
    maxFee: state.state.feeAmount.toString(),
    expectedTtlMs: state.state.ttlMs.toString(),
    expectedExpiryMs: record.expiresMs.toString(),
  })) as {
    size: number;
    budgets: { ex_units: { steps: number; mem: number } }[];
  };
  measurements.push({
    operation: 'renew',
    size: renewed.size,
    cpu: renewed.budgets.reduce((sum, value) => sum + value.ex_units.steps, 0),
    mem: renewed.budgets.reduce((sum, value) => sum + value.ex_units.mem, 0),
  });
  const parameters = context.emulator.protocolParameters;
  for (const value of measurements) {
    expect(value.size).toBeLessThanOrEqual(parameters.maxTxSize);
    expect(BigInt(value.cpu)).toBeLessThanOrEqual(parameters.maxTxExSteps);
    expect(BigInt(value.mem)).toBeLessThanOrEqual(parameters.maxTxExMem);
  }
  await expect(demoRegister(context, 8, 'ninth')).rejects.toThrow('eight records');
  const report = {
    blueprintHash: context.deployment.blueprintHash,
    maxSize: Math.max(...measurements.map((value) => value.size)),
    maxCpu: Math.max(...measurements.map((value) => value.cpu)),
    maxMem: Math.max(...measurements.map((value) => value.mem)),
    transactions: measurements.length,
    limits: {
      maxTxSize: parameters.maxTxSize,
      maxTxExSteps: parameters.maxTxExSteps.toString(),
      maxTxExMem: parameters.maxTxExMem.toString(),
    },
  };
  await atomicJson('test/budget-report.json', report);
}, 120000);

test('submit transport failure preserves journal and confirmed retry never resubmits', async () => {
  const context = await emulatorContext(blueprint);
  const directory = await mkdtemp(join(tmpdir(), 'cardano-submit-crash-'));
  await atomicJson(join(directory, 'cardano.json'), {
    network: 'Preview',
    seed: context.accounts[1]!.seedPhrase,
  });
  const state = await snapshot(context.lucid, context.deployment, () => context.emulator.now());
  const request: Request = {
    operation: 'register',
    deployment: 'unused',
    walletPath: directory,
    payload: {
      name: 'crash',
      nostrSecret: '00'.repeat(31) + '02',
      stateRef: state.stateRef,
      maxFee: state.state.feeAmount.toString(),
      expectedTtlMs: state.state.ttlMs.toString(),
    },
  };
  const original = context.emulator.submitTx.bind(context.emulator);
  const submit = vi.spyOn(context.emulator, 'submitTx').mockImplementationOnce(async (cbor) => {
    await original(cbor);
    throw new Error('Transport lost after acceptance');
  });
  await expect(
    mutate(context.lucid, context.deployment, request, () => context.emulator.now()),
  ).rejects.toThrow('Transport');
  const journal = (await readJson(join(directory, 'pending.json'))) as { txHash: string };
  context.emulator.awaitBlock();
  expect(
    await mutate(context.lucid, context.deployment, request, () => context.emulator.now()),
  ).toEqual({ txHash: journal.txHash, status: 'confirmed' });
  expect(submit).toHaveBeenCalledTimes(1);
  submit.mockRestore();
}, 60000);

test('competing state consumption preserves unresolved journal and blocks another charge', async () => {
  const context = await emulatorContext(blueprint);
  const directory = await mkdtemp(join(tmpdir(), 'cardano-conflict-'));
  await atomicJson(join(directory, 'cardano.json'), {
    network: 'Preview',
    seed: context.accounts[1]!.seedPhrase,
  });
  const state = await snapshot(context.lucid, context.deployment, () => context.emulator.now());
  const request: Request = {
    operation: 'register',
    deployment: 'unused',
    walletPath: directory,
    payload: {
      name: 'lost',
      nostrSecret: '00'.repeat(31) + '02',
      stateRef: state.stateRef,
      maxFee: state.state.feeAmount.toString(),
      expectedTtlMs: state.state.ttlMs.toString(),
    },
  };
  const submit = vi.spyOn(context.emulator, 'submitTx').mockRejectedValueOnce(new Error('Offline'));
  await expect(
    mutate(context.lucid, context.deployment, request, () => context.emulator.now()),
  ).rejects.toThrow('Offline');
  submit.mockRestore();
  await demoRegister(context, 2, 'winner');
  await expect(
    mutate(context.lucid, context.deployment, request, () => context.emulator.now()),
  ).rejects.toThrow('consumed');
  expect(await readJson(join(directory, 'pending.json'))).toHaveProperty('cbor');
}, 60000);

test('Mainnet addresses and domain: bootstrap, configure 15.1234 DEGA and register', async () => {
  const context = await emulatorContext(blueprint, 'Mainnet');
  const { lucid, deployment, emulator } = context;
  expect(deployment.address.startsWith('addr1')).toBe(true);
  expect(deployment.collector.startsWith('addr1')).toBe(true);
  await change(context, 'config', {
    feeAmount: '1512340000',
    ttlMs: '31536000000',
    maxUsers: '10',
  });
  let state = await snapshot(lucid, deployment, () => emulator.now());
  expect(state.state.feeAmount).toBe(1512340000n);
  const feeUnit = deployment.feePolicy + deployment.feeName;
  const balance = async () =>
    (await lucid.utxosAt(deployment.collector)).reduce(
      (sum, utxo) => sum + (utxo.assets[feeUnit] ?? 0n),
      0n,
    );
  const before = await balance();
  await demoRegister(context, 1, 'mainnet-demo');
  state = await snapshot(lucid, deployment, () => emulator.now());
  expect((await balance()) - before).toBe(1512340000n);
  expect(lookup(state, 'name', 'mainnet-demo').record?.nostrKey).toBe(
    'c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5',
  );
  expect(lookup(state, 'nostrKey', state.state.records[0]!.nostrKey).record?.name).toBe(
    'mainnet-demo',
  );
}, 60000);

test('mainnet configuration tolerates a local clock one second ahead of the node', async () => {
  const { lucid, deployment, emulator } = await emulatorContext(blueprint, 'Mainnet');
  const state = await snapshot(lucid, deployment, () => emulator.now());
  const prepared = await prepareMutation(
    lucid,
    deployment,
    {
      operation: 'config',
      payload: {
        stateRef: state.stateRef,
        feeAmount: '1512340000',
        ttlMs: '31536000000',
        maxUsers: '10',
      },
    },
    () => emulator.now() + 1000,
  );
  const signed = await prepared.transaction.sign.withWallet().complete();
  await signed.submit();
  emulator.awaitBlock();
  expect((await snapshot(lucid, deployment, () => emulator.now())).state.feeAmount).toBe(
    1512340000n,
  );
}, 60000);

test('recently expired invitation fails before preparing an expired transaction', async () => {
  const context = await emulatorContext(blueprint);
  await demoRegister(context, 1, 'expiry-guard');
  const { lucid, deployment, emulator, accounts } = context;
  let state = await snapshot(lucid, deployment, () => emulator.now());
  const record = state.state.records[0]!;
  emulator.awaitSlot(Math.ceil(Number(record.expiresMs - BigInt(emulator.now())) / 1000) + 1);
  state = await snapshot(lucid, deployment, () => emulator.now());
  await expect(
    prepareMutation(
      lucid,
      deployment,
      {
        operation: 'invite',
        payload: {
          stateRef: state.stateRef,
          name: record.name,
          member: paymentCredentialOf(accounts[2]!.address).hash,
        },
      },
      () => emulator.now(),
    ),
  ).rejects.toMatchObject({ code: 'EXPIRED' });
}, 60000);

test('live timing anchors to the provider tip and rejects slow evaluation before signing', async () => {
  const { RegistryKoios } = await import('#koios');
  const { lucid, deployment, emulator } = await emulatorContext(blueprint, 'Mainnet');
  const provider = new RegistryKoios('https://api.koios.rest/api/v1');
  const originalConfig = lucid.config();
  vi.spyOn(lucid, 'config').mockReturnValue({ ...originalConfig, provider });
  vi.spyOn(provider, 'getTip').mockResolvedValue({
    slot: emulator.slot,
    timeMs: emulator.now() - 20000,
  });
  const state = await snapshot(lucid, deployment, () => emulator.now());
  const input: Mutation = {
    operation: 'config',
    payload: {
      stateRef: state.stateRef,
      feeAmount: '1512340000',
      ttlMs: '31536000000',
      maxUsers: '10',
    },
  };
  const prepared = await prepareMutation(lucid, deployment, input, () => emulator.now());
  const signed = await prepared.transaction.sign.withWallet().complete();
  await signed.submit();
  emulator.awaitBlock();
  const refreshed = await snapshot(lucid, deployment, () => emulator.now());
  input.payload.stateRef = refreshed.stateRef;
  vi.spyOn(provider, 'getTip').mockResolvedValue({
    slot: emulator.slot,
    timeMs: emulator.now() - 580000,
  });
  await expect(
    prepareMutation(lucid, deployment, input, () => emulator.now()),
  ).rejects.toMatchObject({ code: 'TRANSACTION_TIMING' });
  vi.restoreAllMocks();
}, 60000);

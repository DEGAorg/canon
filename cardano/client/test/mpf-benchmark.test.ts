import { expect, test } from 'vitest';
import { resolve } from 'node:path';
import { writeFile } from 'node:fs/promises';
import { Constr, Data } from '@lucid-evolution/lucid';
import {
  benchmarkContext,
  prepareRegistration,
  prepareRenewal,
  readRecords,
  rootUtxo,
  selectAccount,
  syncIndex,
} from '#mpf-benchmark';
import { insertionProofs, rebuildIndex, marker, trieRoot } from '#mpf-index';

import { syntheticRecords } from '#mpf-fixture';

const blueprint = resolve('../contracts/plutus.json');
const secret = (i: number) => i.toString(16).padStart(64, '0');

test('MPF real registration, independent discovery, replay, fee and renewal', async () => {
  const c = await benchmarkContext(blueprint);
  selectAccount(c, 1);
  const beforeRoot = trieRoot(c.index);
  const prepared = await prepareRegistration(c, { name: 'alice', secret: secret(1) });
  expect(trieRoot(c.index)).toBe(beforeRoot);
  await (await prepared.transaction.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  const records = await readRecords(c.emulator, { address: c.address, policy: c.policy });
  expect(records).toEqual([prepared.record]);
  await syncIndex(c);
  expect(trieRoot(c.index)).not.toBe(beforeRoot);
  const rootBeforeRenew = (await rootUtxo(c)).datum;
  const tx = await prepareRenewal(c, records[0]!);
  await (await tx.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  expect((await readRecords(c.emulator, c))[0]!.expiresMs).toBe(
    prepared.record.expiresMs + 31536000000n,
  );
  expect((await rootUtxo(c)).datum).toBe(rootBeforeRenew);
  const payments = await c.emulator.getUtxos(c.collector);
  expect(
    payments
      .filter((u) => u.datum !== undefined)
      .flatMap((u) => Object.entries(u.assets))
      .filter(([unit]) => unit !== 'lovelace')
      .reduce((sum, [, amount]) => sum + amount, 0n),
  ).toBe(1343854000000000n);
  selectAccount(c, 2);
  await expect(prepareRenewal(c, (await readRecords(c.emulator, c))[0]!)).rejects.toThrow();
}, 120000);

test('MPF rejects duplicate names, wallets and chat keys independently', async () => {
  const c = await benchmarkContext(blueprint);
  selectAccount(c, 1);
  const p = await prepareRegistration(c, { name: 'alice', secret: secret(1) });
  await (await p.transaction.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  await syncIndex(c);
  await expect(prepareRegistration(c, { name: 'bob', secret: secret(2) })).rejects.toThrow(
    'reserved',
  );
  selectAccount(c, 2);
  await expect(prepareRegistration(c, { name: 'alice', secret: secret(2) })).rejects.toThrow(
    'reserved',
  );
  await expect(prepareRegistration(c, { name: 'bob', secret: secret(1) })).rejects.toThrow(
    'reserved',
  );
}, 120000);

test('MPF validator rejects missing fee, bad signature and false proofs', async () => {
  const c = await benchmarkContext(blueprint, syntheticRecords(100));
  selectAccount(c, 1);
  const input = { name: 'alice', secret: secret(1) };
  await expect(prepareRegistration(c, { ...input, omitFee: true })).rejects.toThrow();
  await expect(prepareRegistration(c, { ...input, signature: '00'.repeat(64) })).rejects.toThrow();
  await expect(prepareRegistration(c, { ...input, proofs: [[], [], []] })).rejects.toThrow();
  await expect(prepareRegistration(c, { ...input, nextRoot: '00'.repeat(32) })).rejects.toThrow();
  expect(await readRecords(c.emulator, c)).toEqual([]);
}, 120000);

test('MPF concurrent root spends conflict and losing client rebuilds successfully', async () => {
  const c = await benchmarkContext(blueprint);
  selectAccount(c, 1);
  const a = await prepareRegistration(c, { name: 'alice', secret: secret(1) });
  const signedA = await a.transaction.sign.withWallet().complete();
  selectAccount(c, 2);
  const b = await prepareRegistration(c, { name: 'bob', secret: secret(2) });
  const signedB = await b.transaction.sign.withWallet().complete();
  await signedA.submit();
  c.emulator.awaitBlock();
  await expect(signedB.submit()).rejects.toThrow();
  await syncIndex(c);
  const retry = await prepareRegistration(c, { name: 'bob', secret: secret(2) });
  await (await retry.transaction.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  expect((await readRecords(c.emulator, c)).map((r) => r.name).sort()).toEqual(['alice', 'bob']);
  await syncIndex(c);
}, 120000);

test('MPF complete transaction cost at increasing synthetic registry sizes', async () => {
  const results: object[] = [];
  let protocol: object = {};
  for (const size of [0, 100, 1000, 10000]) {
    const start = performance.now();
    const c = await benchmarkContext(blueprint, syntheticRecords(size));
    const fixtureMs = performance.now() - start;
    const parameters = c.emulator.protocolParameters;
    protocol = {
      coinsPerUtxoByte: parameters.coinsPerUtxoByte.toString(),
      maxTxSize: parameters.maxTxSize,
      maxTxExMem: parameters.maxTxExMem.toString(),
      maxTxExSteps: parameters.maxTxExSteps.toString(),
      minFeeA: parameters.minFeeA,
      minFeeB: parameters.minFeeB,
      priceMem: parameters.priceMem,
      priceStep: parameters.priceStep,
      collateralPercentage: parameters.collateralPercentage,
    };
    selectAccount(c, 1);
    const prepared = await prepareRegistration(c, { name: 'benchmark', secret: secret(1) });
    const signed = await prepared.transaction.sign.withWallet().complete();
    const budgets = await c.emulator.evaluateTx(signed.toCBOR());
    const transactionBytes = signed.toCBOR().length / 2;
    const tx = signed.toTransaction();
    const fee = tx.body().fee();
    const cpu = budgets.reduce((s, b) => s + b.ex_units.steps, 0);
    const memory = budgets.reduce((s, b) => s + b.ex_units.mem, 0);
    expect(transactionBytes).toBeLessThanOrEqual(c.emulator.protocolParameters.maxTxSize);
    expect(BigInt(cpu)).toBeLessThanOrEqual(c.emulator.protocolParameters.maxTxExSteps);
    expect(BigInt(memory)).toBeLessThanOrEqual(c.emulator.protocolParameters.maxTxExMem);
    await signed.submit();
    c.emulator.awaitBlock();
    const utxos = await c.emulator.getUtxos(c.address);
    const record = utxos.find((u) => u.assets[c.policy + marker('benchmark')] === 1n)!;
    const collector = (await c.emulator.getUtxos(c.collector)).find(
      (u) => u.txHash === signed.toHash(),
    )!;
    const root = await rootUtxo(c);
    const datum = Data.from(root.datum!);
    expect(datum).toBeInstanceOf(Constr);
    results.push({
      syntheticExistingRecords: size,
      reservedKeys: size * 3,
      proofBytes: prepared.proofBytes,
      transactionBytes,
      allocatedCpu: cpu,
      allocatedMemory: memory,
      networkFeeLovelace: fee.toString(),
      recordReserveLovelace: record.assets.lovelace!.toString(),
      collectorOutputLovelace: collector.assets.lovelace!.toString(),
      rootReserveLovelace: root.assets.lovelace!.toString(),
      collateralLovelace: tx.body().total_collateral()?.toString(),
      fixtureMs: Math.round(fixtureMs),
    });
  }
  await writeFile(
    resolve('benchmark/mpf-results.json'),
    JSON.stringify(
      {
        scope: 'local emulator; synthetic pre-existing roots; not mainnet deployment',
        evaluation:
          'Lucid complete performs local UPLC evaluation; reported budgets are allocated redeemer units',
        protocol,
        measuredAt: new Date().toISOString(),
        results,
      },
      null,
      2,
    ) + '\n',
  );
}, 240000);

test('MPF script rejects externally supplied proofs for already reserved identities', async () => {
  const c = await benchmarkContext(blueprint);
  selectAccount(c, 1);
  const p = await prepareRegistration(c, { name: 'alice', secret: secret(1) });
  await (await p.transaction.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  await syncIndex(c);
  const record = {
    ...p.record,
    openedMs: BigInt(c.emulator.now()),
    expiresMs: BigInt(c.emulator.now()) + 31536000000n,
  };
  const insertion = await insertionProofs(await rebuildIndex([]), record);
  await expect(
    prepareRegistration(c, {
      name: record.name,
      secret: secret(1),
      record,
      insertion,
    }),
  ).rejects.toThrow();
});

test('MPF reader ignores unauthenticated outputs and expired records can be renewed', async () => {
  const c = await benchmarkContext(blueprint);
  selectAccount(c, 1);
  const p = await prepareRegistration(c, { name: 'alice', secret: secret(1) });
  await (await p.transaction.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  const donation = await c.lucid
    .newTx()
    .pay.ToContract(c.address, { kind: 'inline', value: Data.to(123n) }, { lovelace: 2000000n })
    .complete();
  await (await donation.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  expect(await readRecords(c.emulator, c)).toEqual([p.record]);
  c.emulator.awaitSlot(Math.ceil(Number(p.record.expiresMs - BigInt(c.emulator.now())) / 1000));
  const all = await readRecords(c.emulator, c);
  expect(all.filter((record) => record.expiresMs > BigInt(c.emulator.now()))).toEqual([]);
  const tx = await prepareRenewal(c, all[0]!);
  await (await tx.sign.withWallet().complete()).submit();
  c.emulator.awaitBlock();
  expect((await readRecords(c.emulator, c))[0]!.expiresMs).toBeGreaterThan(
    BigInt(c.emulator.now()),
  );
  await syncIndex(c);
}, 120000);

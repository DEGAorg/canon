/** Emulator-only registry experiment. No provider URL or real wallet is accepted. */
import { readFile } from 'node:fs/promises';
import {
  Constr,
  Data,
  Emulator,
  Lucid,
  applyParamsToScript,
  fromText,
  generateEmulatorAccount,
  paymentCredentialOf,
  validatorToAddress,
  validatorToScriptHash,
  walletFromSeed,
} from '@lucid-evolution/lucid';
import type { EmulatorAccount, LucidEvolution, Script, UTxO } from '@lucid-evolution/lucid';
import { schnorr } from '@noble/curves/secp256k1.js';
import type { Trie } from '@aiken-lang/merkle-patricia-forestry';
import { deploymentData, INITIAL_STATE, recordData, signProof, decodeState } from '#codec';
import type { RecordEntry } from '#types';
import { insertionProofs, marker, rebuildIndex, trieRoot } from '#mpf-index';

const FEE_UNIT = 'ab'.repeat(28) + fromText('DEGA');
const ROOT_NAME = fromText('ROOT');
interface Blueprint {
  validators: { title: string; compiledCode: string }[];
}
export interface BenchmarkContext {
  emulator: Emulator;
  lucid: LucidEvolution;
  accounts: EmulatorAccount[];
  script: Script;
  policy: string;
  address: string;
  collector: string;
  index: Trie;
  seededRecords: RecordEntry[];
}
export function rootDatum(root: string): string {
  return Data.to(new Constr(0, [root, INITIAL_STATE.feeAmount, INITIAL_STATE.ttlMs]));
}
export function entryDatum(record: RecordEntry): string {
  return Data.to(new Constr(1, [recordData(record)]));
}
export function selectAccount(context: BenchmarkContext, account: number): void {
  context.lucid.selectWallet.fromSeed(context.accounts[account]!.seedPhrase, {
    addressType: 'Enterprise',
  });
}
/** Initialize a local ledger with an explicitly synthetic root for scale measurements. */
export async function benchmarkContext(
  blueprintPath: string,
  seededRecords: RecordEntry[] = [],
): Promise<BenchmarkContext> {
  const accounts = Array.from({ length: 5 }, () =>
    generateEmulatorAccount({
      lovelace: 900000000n,
      [FEE_UNIT]: INITIAL_STATE.feeAmount * 100n,
    }),
  );
  for (const account of accounts) {
    account.address = walletFromSeed(account.seedPhrase, {
      network: 'Preview',
      addressType: 'Enterprise',
    }).address;
  }
  const emulator = new Emulator(accounts);
  const lucid = await Lucid(emulator, 'Preview');
  lucid.selectWallet.fromSeed(accounts[0]!.seedPhrase, { addressType: 'Enterprise' });
  const [seed] = await lucid.wallet().getUtxos();
  if (!seed) throw new Error('Benchmark seed UTxO missing');
  const index = await rebuildIndex(seededRecords);
  const blueprint = JSON.parse(await readFile(blueprintPath, 'utf8')) as Blueprint;
  const validator = blueprint.validators.find(
    (v) => v.title === 'registry_benchmark.registry_benchmark.spend',
  );
  if (!validator) throw new Error('Build the benchmark Aiken validator first');
  const script: Script = {
    type: 'PlutusV3',
    script: applyParamsToScript(validator.compiledCode, [
      deploymentData({
        network: 'Preview',
        providerUrl: 'emulator',
        seed: { txHash: seed.txHash, outputIndex: seed.outputIndex },
        admin: paymentCredentialOf(accounts[0]!.address).hash,
        feePolicy: FEE_UNIT.slice(0, 56),
        feeName: FEE_UNIT.slice(56),
        collector: accounts[4]!.address,
      }),
      trieRoot(index),
    ]),
  };
  const policy = validatorToScriptHash(script);
  const address = validatorToAddress('Preview', script);
  const context = {
    emulator,
    lucid,
    accounts,
    script,
    policy,
    address,
    collector: accounts[4]!.address,
    index,
    seededRecords,
  };
  const tx = await lucid
    .newTx()
    .collectFrom([seed])
    .mintAssets({ [policy + ROOT_NAME]: 1n }, Data.to(new Constr(0, [])))
    .attach.MintingPolicy(script)
    .addSigner(accounts[0]!.address)
    .pay.ToContract(
      address,
      { kind: 'inline', value: rootDatum(trieRoot(index)) },
      { [policy + ROOT_NAME]: 1n },
    )
    .complete();
  await (await tx.sign.withWallet().complete()).submit();
  emulator.awaitBlock();
  return context;
}
export async function rootUtxo(context: BenchmarkContext): Promise<UTxO> {
  const roots = (await context.lucid.utxosAt(context.address)).filter(
    (u) => u.assets[context.policy + ROOT_NAME] === 1n,
  );
  if (roots.length !== 1) throw new Error('Expected exactly one authenticated root');
  return roots[0]!;
}
export function feeReceipt(
  context: BenchmarkContext,
  utxo: UTxO,
  name: string,
  action: bigint,
): string {
  return Data.to(
    new Constr(0, [context.policy, utxo.txHash, BigInt(utxo.outputIndex), action, fromText(name)]),
  );
}
export interface RegistrationOptions {
  name: string;
  secret: string;
  omitFee?: boolean;
  signature?: string;
  record?: RecordEntry;
  proofs?: Data[];
  nextRoot?: string;
  insertion?: Awaited<ReturnType<typeof insertionProofs>>;
}
/** Build a real script transaction; chain validation remains authoritative. */
export async function prepareRegistration(context: BenchmarkContext, options: RegistrationOptions) {
  const { lucid, script, address, policy, index } = context;
  const owner = paymentCredentialOf(await lucid.wallet().address()).hash;
  const lower = BigInt(context.emulator.now());
  const record = options.record ?? {
    name: options.name,
    owner,
    nostrKey: Buffer.from(schnorr.getPublicKey(Buffer.from(options.secret, 'hex'))).toString('hex'),
    openedMs: lower,
    expiresMs: lower + INITIAL_STATE.ttlMs,
    members: [owner],
  };
  const insertion = options.insertion ?? (await insertionProofs(index, record));
  const root = await rootUtxo(context);
  const signature =
    options.signature ?? signProof('Preview', policy, owner, record.name, options.secret);
  const redeemer = Data.to(
    new Constr(1, [recordData(record), signature, options.proofs ?? insertion.proofs]),
  );
  let builder = lucid
    .newTx()
    .collectFrom([root], redeemer)
    .mintAssets({ [policy + marker(record.name)]: 1n }, redeemer)
    .attach.SpendingValidator(script)
    .attach.MintingPolicy(script)
    .addSignerKey(owner)
    .validFrom(Number(lower))
    .validTo(Number(lower + 600000n))
    .pay.ToContract(
      address,
      { kind: 'inline', value: rootDatum(options.nextRoot ?? insertion.root) },
      root.assets,
    )
    .pay.ToContract(
      address,
      { kind: 'inline', value: entryDatum(record) },
      { [policy + marker(record.name)]: 1n },
    );
  if (!options.omitFee)
    builder = builder.pay.ToAddressWithData(
      context.collector,
      { kind: 'inline', value: feeReceipt(context, root, record.name, 0n) },
      { [FEE_UNIT]: INITIAL_STATE.feeAmount },
    );
  return { transaction: await builder.complete(), record, proofBytes: insertion.proofBytes };
}
function hasRecordToken(utxo: UTxO, policy: string): boolean {
  const tokens = Object.entries(utxo.assets).filter(([unit]) => unit !== 'lovelace');
  if (tokens.length !== 1) return false;
  const [unit, quantity] = tokens[0]!;
  return unit.startsWith(policy + '01') && unit.length === 120 && quantity === 1n;
}
/** Read from provider outputs only; no writer trie, identity secrets or wallet required. */
export async function readRecords(
  provider: Pick<Emulator, 'getUtxos'>,
  deployment: { address: string; policy: string },
): Promise<RecordEntry[]> {
  const records: RecordEntry[] = [];
  for (const utxo of await provider.getUtxos(deployment.address)) {
    if (!hasRecordToken(utxo, deployment.policy)) continue;
    if (!utxo.datum) throw new Error('Authenticated registration has no inline datum');
    const data = Data.from(utxo.datum);
    if (!(data instanceof Constr) || data.index !== 1 || data.fields.length !== 1) continue;
    const wrapped = Data.to(
      new Constr(0, [
        INITIAL_STATE.feeAmount,
        INITIAL_STATE.ttlMs,
        INITIAL_STATE.maxUsers,
        [data.fields[0]!],
      ]),
    );
    const record = decodeState(wrapped).records[0]!;
    if (utxo.assets[deployment.policy + marker(record.name)] === 1n) records.push(record);
  }
  return records;
}
export async function syncIndex(context: BenchmarkContext): Promise<void> {
  context.index = await rebuildIndex([
    ...context.seededRecords,
    ...(await readRecords(context.emulator, context)),
  ]);
  const root = await rootUtxo(context);
  if (root.datum !== rootDatum(trieRoot(context.index)))
    throw new Error('Public records do not match root');
}
export async function prepareRenewal(context: BenchmarkContext, record: RecordEntry) {
  const { lucid, script, policy, address } = context;
  const [input] = (await lucid.utxosAt(address)).filter(
    (u) => u.assets[policy + marker(record.name)] === 1n,
  );
  if (!input) throw new Error('Authenticated record missing');
  const lower = BigInt(context.emulator.now());
  const next = {
    ...record,
    expiresMs: (record.expiresMs > lower ? record.expiresMs : lower) + INITIAL_STATE.ttlMs,
  };
  return lucid
    .newTx()
    .collectFrom([input], Data.to(new Constr(2, [])))
    .readFrom([await rootUtxo(context)])
    .attach.SpendingValidator(script)
    .addSignerKey(paymentCredentialOf(await lucid.wallet().address()).hash)
    .validFrom(Number(lower))
    .validTo(Number(lower + 600000n))
    .pay.ToContract(address, { kind: 'inline', value: entryDatum(next) }, input.assets)
    .pay.ToAddressWithData(
      context.collector,
      { kind: 'inline', value: feeReceipt(context, input, record.name, 1n) },
      { [FEE_UNIT]: INITIAL_STATE.feeAmount },
    )
    .complete();
}

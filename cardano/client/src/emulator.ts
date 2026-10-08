import {
  Emulator,
  generateEmulatorAccount,
  Lucid,
  paymentCredentialOf,
  walletFromSeed,
} from '@lucid-evolution/lucid';
import type { EmulatorAccount, LucidEvolution } from '@lucid-evolution/lucid';
import { DEGA_POLICY } from '#network';
import { createDeployment } from '#deployment';
import { bootstrap, prepareMutation, snapshot } from '#registry';
import { INITIAL_STATE } from '#codec';
import type { CardanoNetwork, Deployment } from '#types';

export interface TestContext {
  emulator: Emulator;
  lucid: LucidEvolution;
  deployment: Deployment;
  accounts: EmulatorAccount[];
}
/** Create synthetic funded accounts and deploy the actual compiled validator locally. */
export async function emulatorContext(
  blueprint: string,
  network: CardanoNetwork = 'Preview',
): Promise<TestContext> {
  const mockPolicy = network === 'Mainnet' ? DEGA_POLICY : 'ab'.repeat(28);
  const accounts = Array.from({ length: 10 }, () =>
    generateEmulatorAccount({
      lovelace: 900000000n,
      [mockPolicy + '44454741']: INITIAL_STATE.feeAmount * 100n,
    }),
  );
  for (const account of accounts) {
    account.address = walletFromSeed(account.seedPhrase, {
      network,
      addressType: 'Enterprise',
    }).address;
  }
  const emulator = new Emulator(accounts);
  const lucid = await Lucid(emulator, network);
  lucid.selectWallet.fromSeed(accounts[0]!.seedPhrase, { addressType: 'Enterprise' });
  const utxos = await lucid.wallet().getUtxos();
  const deployment = await createDeployment(blueprint, {
    network,
    providerUrl: 'emulator',
    seed: { txHash: utxos[0]!.txHash, outputIndex: utxos[0]!.outputIndex },
    admin: paymentCredentialOf(accounts[0]!.address).hash,
    feePolicy: mockPolicy,
    feeName: '44454741',
    collector: accounts[9]!.address,
  });
  const tx = await bootstrap(lucid, deployment);
  await (await tx.sign.withWallet().complete()).submit();
  emulator.awaitBlock();
  return { emulator, lucid, deployment, accounts };
}
export async function demoRegister(
  context: TestContext,
  accountIndex: number,
  name: string,
): Promise<{ txHash: string; size: number; cpu: number; mem: number }> {
  const { lucid, deployment, emulator, accounts } = context;
  lucid.selectWallet.fromSeed(accounts[accountIndex]!.seedPhrase, { addressType: 'Enterprise' });
  const current = await snapshot(lucid, deployment, () => emulator.now());
  const prepared = await prepareMutation(
    lucid,
    deployment,
    {
      operation: 'register',
      payload: {
        name,
        stateRef: current.stateRef,
        maxFee: current.state.feeAmount.toString(),
        expectedTtlMs: current.state.ttlMs.toString(),
      },
      nostrSecret: (accountIndex + 1).toString(16).padStart(64, '0'),
    },
    () => emulator.now(),
  );
  const signed = await prepared.transaction.sign.withWallet().complete();
  const budgets = await emulator.evaluateTx(signed.toCBOR());
  const txHash = await signed.submit();
  emulator.awaitBlock();
  return {
    txHash,
    size: signed.toCBOR().length / 2,
    cpu: budgets.reduce((sum, value) => sum + value.ex_units.steps, 0),
    mem: budgets.reduce((sum, value) => sum + value.ex_units.mem, 0),
  };
}

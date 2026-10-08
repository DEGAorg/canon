import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { demoRegister, emulatorContext } from '#emulator';
import { lookup, snapshot } from '#registry';
import { json } from '#storage';

const blueprint =
  process.argv[2] ?? fileURLToPath(new URL('../../contracts/plutus.json', import.meta.url));
const context = await emulatorContext(resolve(blueprint));
const transaction = await demoRegister(context, 1, 'alice');
const state = await snapshot(context.lucid, context.deployment, () => context.emulator.now());
process.stdout.write(
  `${json({
    event: 'local_demo_complete',
    network: 'emulator',
    policyId: context.deployment.policyId,
    transaction,
    result: lookup(state, 'name', 'alice'),
  })}\n`,
);

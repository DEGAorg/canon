import { koiosJson, RegistryKoios } from '#koios';
import { parseNetwork, validateProvider, validateFeeAsset } from '#network';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import {
  applyParamsToScript,
  validatorToAddress,
  validatorToScriptHash,
  Lucid,
  Constr,
  fromText,
} from '@lucid-evolution/lucid';
import type { LucidEvolution, Script } from '@lucid-evolution/lucid';
import { addressData, deploymentData, NFT_NAME } from '#codec';
import { object, readJson } from '#storage';
import { RegistryError, requireHex, requireText, requireInteger } from '#types';
import type { Deployment } from '#types';

export function validateDeployment(value: unknown): Deployment {
  const data = object(value, 'deployment');
  const network = parseNetwork(data.network);
  const revision = deploymentRevision(data);
  const scriptValue = object(data.script, 'script');
  if (scriptValue.type !== 'PlutusV3') {
    throw new RegistryError('INVALID_DEPLOYMENT', 'Expected PlutusV3 script');
  }
  const script: Script = { type: 'PlutusV3', script: requireText(scriptValue.script, 'script') };
  const policyId = validatorToScriptHash(script);
  const address = validatorToAddress(network, script);
  if (
    data.policyId !== policyId ||
    data.address !== address ||
    data.stateUnit !== policyId + revision.token
  ) {
    throw new RegistryError('INVALID_DEPLOYMENT', 'Script, address and state token do not agree');
  }
  const seed = parseSeed(data.seed);
  const feeName = parseFeeName(data.feeName);
  const result: Deployment = {
    version: revision.version,
    initialTerms: revision.initialTerms,
    network,
    script,
    policyId,
    address,
    stateUnit: policyId + revision.token,
    seed: {
      txHash: requireHex(seed.txHash, 32, 'seed hash'),
      outputIndex: Number(seed.outputIndex),
    },
    admin: requireHex(data.admin, 28, 'admin'),
    feePolicy: requireHex(data.feePolicy, 28, 'feePolicy'),
    feeName,
    collector: requireText(data.collector, 'collector'),
    providerUrl: requireText(data.providerUrl, 'providerUrl'),
    blueprintHash: requireHex(data.blueprintHash, 32, 'blueprintHash'),
  };
  addressData(result.collector, network);
  validateFeeAsset(network, result.feePolicy, result.feeName);
  if (result.feePolicy === policyId) {
    throw new RegistryError('INVALID_DEPLOYMENT', 'Fee policy cannot be the state policy');
  }
  return result;
}
export async function loadDeployment(path: string): Promise<Deployment> {
  return validateDeployment(await readJson(path));
}
export async function connect(
  deployment: Pick<Deployment, 'network' | 'providerUrl'>,
): Promise<LucidEvolution> {
  validateProvider(deployment.network, deployment.providerUrl);
  return Lucid(new RegistryKoios(deployment.providerUrl), deployment.network);
}
export async function createDeployment(
  blueprintPath: string,
  parameters: Omit<
    Deployment,
    'script' | 'policyId' | 'address' | 'stateUnit' | 'blueprintHash' | 'version'
  >,
): Promise<Deployment> {
  const content = await readFile(blueprintPath, 'utf8');
  const blueprint = object(JSON.parse(content) as unknown, 'blueprint');
  if (!Array.isArray(blueprint.validators)) {
    throw new RegistryError('INVALID_BLUEPRINT', 'Blueprint has no validators');
  }
  const validators = blueprint.validators.map((value) => object(value, 'validator'));
  const validator = validators.find(
    (value) =>
      value.title ===
      (parameters.initialTerms ? 'registry_mpf.registry_mpf.spend' : 'registry.registry.spend'),
  );
  if (!validator) throw new RegistryError('INVALID_BLUEPRINT', 'Registry spend validator missing');
  const script: Script = {
    type: 'PlutusV3',
    script: applyParamsToScript(requireText(validator.compiledCode, 'compiledCode'), [
      deploymentData(parameters),
      ...(parameters.initialTerms ? [termsData(parameters.initialTerms)] : []),
    ]),
  };
  const policyId = validatorToScriptHash(script);
  return validateDeployment({
    ...parameters,
    version: parameters.initialTerms ? 2 : 1,
    script,
    policyId,
    address: validatorToAddress(parameters.network, script),
    stateUnit: policyId + (parameters.initialTerms ? fromText('ROOT') : NFT_NAME),
    blueprintHash: createHash('sha256').update(content).digest('hex'),
  });
}

/** Validate a recent network tip, then use live local time for validity and discovery. */
export async function checkedClock(
  deployment: Pick<Deployment, 'network' | 'providerUrl'>,
): Promise<() => number> {
  validateProvider(deployment.network, deployment.providerUrl);
  const response = await koiosJson(`${deployment.providerUrl}/tip`);
  if (!Array.isArray(response) || response.length !== 1) {
    throw new RegistryError('MALFORMED_PROVIDER', 'Koios returned an invalid chain tip');
  }
  const block = object(response[0], 'chain tip');
  if (!Number.isSafeInteger(block.block_time)) {
    throw new RegistryError('PROVIDER_UNAVAILABLE', 'Provider returned an invalid block timestamp');
  }
  const timestamp = Number(block.block_time) * 1000;
  if (Math.abs(Date.now() - timestamp) > 120000) {
    throw new RegistryError(
      'STALE_CHAIN_TIP',
      'Chain tip is stale or local clock differs by over 120 seconds',
    );
  }
  return Date.now;
}

function parseSeed(value: unknown): { txHash: string; outputIndex: number } {
  const seed = object(value, 'seed');
  if (!Number.isSafeInteger(seed.outputIndex) || Number(seed.outputIndex) < 0) {
    throw new RegistryError('INVALID_DEPLOYMENT', 'Invalid seed output index');
  }
  return {
    txHash: requireHex(seed.txHash, 32, 'seed hash'),
    outputIndex: Number(seed.outputIndex),
  };
}

function parseFeeName(value: unknown): string {
  const feeName = requireText(value, 'feeName');
  if (!/^(?:[0-9a-f]{2}){1,32}$/.test(feeName)) {
    throw new RegistryError('INVALID_DEPLOYMENT', 'Invalid fee asset name');
  }
  return feeName;
}

function parseInitialTerms(value: unknown): NonNullable<Deployment['initialTerms']> {
  const data = object(value, 'initial terms');
  const fee = requireInteger(data.feeAmount, 'initial fee');
  const ttl = requireInteger(data.ttlMs, 'initial TTL');
  const max = requireInteger(data.maxUsers, 'initial membership cap');
  if (ttl <= 0n || max < 1n || max > 10n) {
    throw new RegistryError('INVALID_DEPLOYMENT', 'Invalid initial registry terms');
  }
  return { feeAmount: fee.toString(), ttlMs: ttl.toString(), maxUsers: max.toString() };
}
function termsData(value: NonNullable<Deployment['initialTerms']>): Constr<bigint> {
  const terms = parseInitialTerms(value);
  return new Constr(0, [BigInt(terms.feeAmount), BigInt(terms.ttlMs), BigInt(terms.maxUsers)]);
}

function deploymentRevision(data: { [key: string]: unknown }): {
  version: 1 | 2;
  token: string;
  initialTerms?: NonNullable<Deployment['initialTerms']>;
} {
  if (data.version === 1) return { version: 1, token: NFT_NAME };
  if (data.version === 2)
    return {
      version: 2,
      token: fromText('ROOT'),
      initialTerms: parseInitialTerms(data.initialTerms),
    };
  throw new RegistryError('INVALID_DEPLOYMENT', 'Unsupported deployment version');
}

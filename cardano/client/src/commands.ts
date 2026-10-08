import { parseNetwork, providerUrl } from '#network';
import { schnorr } from '@noble/curves/secp256k1.js';
import { bytes, hex } from '#codec';
import type { LucidEvolution } from '@lucid-evolution/lucid';
import { checkedClock, connect, createDeployment, loadDeployment } from '#deployment';
import { atomicJson, ensureWallet, object, readNostr, readSeed, walletStatus } from '#storage';
import {
  confirmedReplay,
  intentHash,
  persistAndSubmit,
  readPending,
  submitPending,
  withWalletLock,
} from '#pending';
import { lookup } from '#registry';
import * as legacyRegistry from '#registry';
import * as mpfRegistry from '#mpf-registry';
import type { Mutation } from '#registry';
import { canonicalName, RegistryError, requireHex, requireText } from '#types';
import type { CardanoNetwork, Deployment, Request, StateSnapshot } from '#types';

export function parseRequest(value: unknown): Request {
  const data = object(value, 'request');
  const operation = requireText(data.operation, 'operation');
  const offline = ['wallet.ensure', 'wallet.status', 'wallet.inspect', 'pending.status'];
  const deployment =
    offline.includes(operation) && data.deployment === undefined
      ? ''
      : requireText(data.deployment, 'deployment');
  return {
    operation,
    ...(data.network === undefined ? {} : { network: parseNetwork(data.network) }),
    deployment,
    ...(data.walletPath === undefined
      ? {}
      : { walletPath: requireText(data.walletPath, 'walletPath') }),
    payload: data.payload === undefined ? {} : object(data.payload, 'payload'),
  };
}
export async function readOperation(
  lucid: LucidEvolution,
  deployment: Deployment,
  request: Request,
  now: () => number = Date.now,
): Promise<object> {
  const state = await registryFor(deployment).snapshot(lucid, deployment, now);
  const payload = request.payload ?? {};
  const status = {
    feeAmount: state.state.feeAmount,
    ttlMs: state.state.ttlMs,
    maxUsers: state.state.maxUsers,
    stateRef: state.stateRef,
    policyId: deployment.policyId,
    address: deployment.address,
    checkedAtMs: state.checkedAtMs,
  };
  switch (request.operation) {
    case 'status':
      return statusResult(status, state, payload);
    case 'quote':
      return { ...status, record: lookup(state, 'name', canonicalName(payload.name), true).record };
    case 'resolve':
      return lookup(state, 'name', canonicalName(payload.name), payload.includeExpired === true);
    case 'reverse':
      return lookup(state, 'nostrKey', requireHex(payload.nostrKey, 32, 'nostrKey'));
    case 'owner':
      return lookup(state, 'owner', requireHex(payload.owner, 28, 'owner'), true);
    default:
      throw new RegistryError('UNKNOWN_OPERATION', 'Unsupported read operation');
  }
}
async function signer(
  lucid: LucidEvolution,
  directory: string,
  network: CardanoNetwork,
): Promise<void> {
  lucid.selectWallet.fromSeed(await readSeed(directory, network), { addressType: 'Enterprise' });
}
export async function mutate(
  lucid: LucidEvolution,
  deployment: Deployment,
  request: Request,
  now: () => number = Date.now,
): Promise<object> {
  const directory = requireText(request.walletPath, 'walletPath');
  await walletStatus(directory, deployment.network);
  return withWalletLock(directory, async () => {
    const payload = { ...request.payload };
    const nostrSecret =
      request.operation === 'register' ? await registrationIdentity(directory, payload) : undefined;
    const hash = intentHash({ ...request, payload });
    const resumed = await resumeIntent(lucid, deployment, directory, request.operation, hash);
    if (resumed) return resumed;
    await signer(lucid, directory, deployment.network);
    if (request.operation === 'bootstrap') {
      return persistAndSubmit(
        lucid,
        deployment,
        directory,
        await registryFor(deployment).bootstrap(lucid, deployment),
        {
          operation: 'bootstrap',
          stateRef: null,
          intentHash: hash,
        },
      );
    }
    const allowed = ['register', 'renew', 'invite', 'config'];
    if (!allowed.includes(request.operation)) {
      throw new RegistryError('UNKNOWN_OPERATION', 'Unsupported mutation');
    }
    const operation = request.operation as Mutation['operation'];
    const prepared = await registryFor(deployment).prepareMutation(
      lucid,
      deployment,
      { operation, payload, nostrSecret },
      now,
    );
    return {
      ...(await persistAndSubmit(lucid, deployment, directory, prepared.transaction, {
        operation,
        stateRef: prepared.stateRef,
        intentHash: hash,
        nostrKey: prepared.record?.nostrKey,
        name: prepared.record?.name,
      })),
      ...(prepared.record ? { record: prepared.record } : {}),
    };
  });
}
async function createBootstrapDeployment(request: Request): Promise<Deployment> {
  const payload = request.payload ?? {};
  const directory = requireText(request.walletPath, 'walletPath');
  const network = parseNetwork(request.network);
  const publicWallet = object(await walletStatus(directory, network), 'wallet');
  const seed = object(payload.seed, 'seed');
  if (!Number.isSafeInteger(seed.outputIndex) || Number(seed.outputIndex) < 0) {
    throw new RegistryError('INVALID_REQUEST', 'seed.outputIndex must be a nonnegative integer');
  }
  const deployment = await createDeployment(requireText(payload.blueprint, 'blueprint'), {
    network,
    providerUrl: providerUrl(network),
    seed: {
      txHash: requireHex(seed.txHash, 32, 'seed hash'),
      outputIndex: Number(seed.outputIndex),
    },
    admin: requireHex(publicWallet.owner, 28, 'owner'),
    feePolicy: requireHex(payload.feePolicy, 28, 'feePolicy'),
    feeName: requireText(payload.feeName, 'feeName'),
    collector: requireText(payload.collector, 'collector'),
    ...(payload.initialTerms === undefined
      ? {}
      : {
          initialTerms: {
            feeAmount: requireText(
              object(payload.initialTerms, 'initial terms').feeAmount,
              'feeAmount',
            ),
            ttlMs: requireText(object(payload.initialTerms, 'initial terms').ttlMs, 'ttlMs'),
            maxUsers: requireText(
              object(payload.initialTerms, 'initial terms').maxUsers,
              'maxUsers',
            ),
          },
        }),
  });
  await atomicJson(request.deployment, deployment, true);
  return deployment;
}
export async function execute(request: Request): Promise<object> {
  if (request.operation === 'wallet.ensure') {
    return ensureWallet(
      requireText(request.walletPath, 'walletPath'),
      parseNetwork(request.network),
    );
  }
  if (request.operation === 'wallet.status') {
    return walletStatus(requireText(request.walletPath, 'walletPath'), request.network);
  }
  if (request.operation === 'wallet.inspect') return inspectWallet(request);
  if (request.operation === 'pending.status') {
    const pending = await readPending(requireText(request.walletPath, 'walletPath'));
    return {
      pending: pending
        ? {
            operation: pending.operation,
            name: pending.name,
            policyId: pending.policyId,
            network: pending.network,
            stateRef: pending.stateRef,
            nostrKey: pending.nostrKey,
          }
        : null,
    };
  }
  const deployment = await requestDeployment(request);
  const now = await checkedClock(deployment);
  const lucid = await connect(deployment);
  const reads = ['status', 'quote', 'resolve', 'reverse', 'owner'];
  if (reads.includes(request.operation)) return readOperation(lucid, deployment, request, now);
  return mutate(lucid, deployment, request, now);
}

async function registrationIdentity(
  directory: string,
  payload: { [key: string]: unknown },
): Promise<string> {
  const secret =
    payload.nostrSecret === undefined
      ? await readNostr(
          directory,
          typeof payload.nostrPath === 'string' ? payload.nostrPath : undefined,
        )
      : requireHex(payload.nostrSecret, 32, 'nostrSecret');
  const publicKey = hex(schnorr.getPublicKey(bytes(secret)));
  if (payload.nostrKey !== undefined && payload.nostrKey !== publicKey) {
    throw new RegistryError('IDENTITY_MISMATCH', 'Nostr key does not match signing identity');
  }
  payload.nostrKey = publicKey;
  return secret;
}

async function resumeIntent(
  lucid: LucidEvolution,
  deployment: Deployment,
  directory: string,
  operation: string,
  hash: string,
): Promise<object | null> {
  const pending = await readPending(directory);
  if (pending) {
    if (operation !== 'retry' && pending.intentHash !== hash) {
      throw new RegistryError(
        'PENDING_EXISTS',
        'Retry the existing operation before another intent',
      );
    }
    return submitPending(lucid, deployment, directory);
  }
  if (operation === 'retry') return submitPending(lucid, deployment, directory);
  return confirmedReplay(directory, deployment, hash);
}

async function requestDeployment(request: Request): Promise<Deployment> {
  requireText(request.deployment, 'deployment');
  let deployment: Deployment;
  try {
    deployment = await loadDeployment(request.deployment);
  } catch (error) {
    if (request.operation !== 'bootstrap' || (error as NodeJS.ErrnoException).code !== 'ENOENT') {
      throw error;
    }
    deployment = await createBootstrapDeployment(request);
  }
  if (request.operation === 'bootstrap') parseNetwork(request.network);
  if (request.network !== undefined && request.network !== deployment.network) {
    throw new RegistryError('INVALID_NETWORK', 'Request network differs from deployment');
  }
  return deployment;
}

async function inspectWallet(request: Request): Promise<object> {
  const status = object(
    await walletStatus(requireText(request.walletPath, 'walletPath'), request.network),
    'wallet status',
  );
  const network = parseNetwork(status.network);
  const connection = { network, providerUrl: providerUrl(network) };
  const now = await checkedClock(connection);
  const lucid = await connect(connection);
  const utxos = await lucid.utxosAt(requireText(status.address, 'wallet address'));
  const balances: { [unit: string]: bigint } = {};
  for (const utxo of utxos) {
    for (const [unit, quantity] of Object.entries(utxo.assets)) {
      balances[unit] = (balances[unit] ?? 0n) + quantity;
    }
  }
  return {
    ...status,
    checkedAtMs: BigInt(now()),
    balances,
    utxos: utxos.map((utxo) => ({
      txHash: utxo.txHash,
      outputIndex: utxo.outputIndex,
      assets: utxo.assets,
      collateralCandidate:
        Object.keys(utxo.assets).length === 1 &&
        (utxo.assets.lovelace ?? 0n) >= 5000000n &&
        !utxo.datum &&
        !utxo.datumHash,
    })),
  };
}

function statusResult(
  status: object,
  state: StateSnapshot,
  payload: { [key: string]: unknown },
): object {
  if (payload.owner === undefined) return status;
  return {
    ...status,
    record: lookup(state, 'owner', requireHex(payload.owner, 28, 'owner'), true).record,
  };
}

function registryFor(deployment: Deployment): typeof legacyRegistry {
  return deployment.version === 2 ? mpfRegistry : legacyRegistry;
}

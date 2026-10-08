import { afterEach, expect, test, vi } from 'vitest';
import { RegistryKoios, koiosJson, transactionStatus } from '#koios';
import { providerUrl } from '#network';

const hash = '11'.repeat(32);
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

test('strict confirmation parsing distinguishes absent, pending and included transactions', () => {
  expect(transactionStatus([], hash).status).toBe('not_found');
  expect(transactionStatus([{ tx_hash: hash, num_confirmations: null }], hash).status).toBe(
    'not_found',
  );
  expect(transactionStatus([{ tx_hash: hash, num_confirmations: 0 }], hash).status).toBe('pending');
  expect(transactionStatus([{ tx_hash: hash, num_confirmations: 1 }], hash)).toMatchObject({
    status: 'confirmed',
    confirmation: { confirmations: 1 },
  });
  for (const count of [-1, '1', 0.5, undefined]) {
    expect(() => transactionStatus([{ tx_hash: hash, num_confirmations: count }], hash)).toThrow();
  }
  expect(() =>
    transactionStatus([{ tx_hash: '22'.repeat(32), num_confirmations: 2 }], hash),
  ).toThrow('different');
});

test('public transaction status sends no credentials and keeps zero confirmations pending', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify([{ tx_hash: hash, num_confirmations: 0 }])));
  vi.stubGlobal('fetch', fetch);
  expect((await new RegistryKoios(providerUrl('Mainnet')).getTransactionStatus(hash)).status).toBe(
    'pending',
  );
  expect(fetch.mock.calls[0]![0]).toBe('https://api.koios.rest/api/v1/tx_status');
  const options = fetch.mock.calls[0]![1] as RequestInit;
  expect(options.headers).toEqual({ 'Content-Type': 'application/json' });
  expect(options.signal).toBeInstanceOf(AbortSignal);
  expect(options.body).toBe(JSON.stringify({ _tx_hashes: [hash] }));
});

test('429 gets one bounded retry and persistent rate limit remains visible', async () => {
  vi.useFakeTimers();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response('', { status: 429, headers: { 'Retry-After': '999' } }))
    .mockResolvedValueOnce(new Response('[]'));
  vi.stubGlobal('fetch', fetch);
  const response = koiosJson(providerUrl('Mainnet') + '/tip');
  await vi.advanceTimersByTimeAsync(1999);
  expect(fetch).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(await response).toEqual([]);
  expect(fetch).toHaveBeenCalledTimes(2);
  fetch.mockReset().mockImplementation(async () => new Response('', { status: 429 }));
  const failure = expect(koiosJson(providerUrl('Preview') + '/tip')).rejects.toMatchObject({
    code: 'PROVIDER_RATE_LIMIT',
  });
  await vi.advanceTimersByTimeAsync(1000);
  await failure;
  expect(fetch).toHaveBeenCalledTimes(2);
});

test('SDK reads have one delayed retry but failed submissions are never retried automatically', async () => {
  const fetch = vi
    .fn()
    .mockImplementation(async () => new Response('unavailable', { status: 503 }));
  vi.stubGlobal('fetch', fetch);
  const provider = new RegistryKoios(providerUrl('Mainnet'));
  await expect(provider.getProtocolParameters()).rejects.toMatchObject({
    code: 'PROVIDER_UNAVAILABLE',
  });
  expect(fetch).toHaveBeenCalledTimes(2);
  fetch.mockClear();
  await expect(provider.submitTx('84a0a0f5f6')).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test('HTTP abort and malformed response fail instead of reporting absence', async () => {
  const controller = new AbortController();
  controller.abort(new Error('cancelled'));
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options: RequestInit) => {
      if (options.signal?.aborted) throw options.signal.reason;
      return new Response('not JSON');
    }),
  );
  await expect(
    koiosJson(providerUrl('Mainnet') + '/tip', { signal: controller.signal }),
  ).rejects.toThrow('cancelled');
  await expect(koiosJson(providerUrl('Mainnet') + '/tip')).rejects.toThrow();
});

const address = 'addr1w85k4stuysm5nu9wzsxz9esg0jwa294l7gdfuam5l2sqrdsf3m6gn';
const secondHash = '22'.repeat(32);
const inlineDatum = 'd87980';
function outputRow(txHash: string, spent = false) {
  return { tx_hash: txHash, tx_index: 0, address, is_spent: spent };
}
function addressInfo(txHash: string) {
  return {
    address,
    balance: '2000000',
    stake_address: null,
    script_address: true,
    utxo_set: [
      {
        tx_hash: txHash,
        tx_index: 0,
        block_time: 1,
        block_height: 1,
        value: '2000000',
        datum_hash: null,
        inline_datum: { bytes: inlineDatum, value: {} },
        reference_script: null,
        asset_list: [],
      },
    ],
  };
}

test('output lookup reads all requested live references without historical collateral parsing', async () => {
  const fetch = vi.fn<typeof globalThis.fetch>(async (input) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.endsWith('/utxo_info')) {
      return new Response(JSON.stringify([outputRow(hash), outputRow(secondHash)]));
    }
    if (url.endsWith('/address_info')) {
      const first = addressInfo(hash);
      first.utxo_set.push(...addressInfo(secondHash).utxo_set);
      return new Response(JSON.stringify([first]));
    }
    throw new Error('Unexpected historical transaction request');
  });
  vi.stubGlobal('fetch', fetch);
  const utxos = await new RegistryKoios(providerUrl('Mainnet')).getUtxosByOutRef([
    { txHash: hash, outputIndex: 0 },
    { txHash: secondHash, outputIndex: 0 },
  ]);
  expect(utxos.map((utxo) => utxo.txHash)).toEqual([hash, secondHash]);
  expect(utxos[0]).toMatchObject({ datum: inlineDatum, assets: { lovelace: 2000000n } });
});

test('spent outputs are absent even if their original transaction still exists', async () => {
  const fetch = vi.fn<typeof globalThis.fetch>(async (input) => {
    const url = input instanceof Request ? input.url : String(input);
    const result = url.endsWith('/utxo_info') ? [outputRow(hash, true)] : [addressInfo(hash)];
    return new Response(JSON.stringify(result));
  });
  vi.stubGlobal('fetch', fetch);
  const provider = new RegistryKoios(providerUrl('Mainnet'));
  expect(await provider.getUtxosByOutRef([{ txHash: hash, outputIndex: 0 }])).toEqual([]);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(await provider.getUtxosByOutRef([])).toEqual([]);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test.each([
  {},
  [outputRow(secondHash)],
  [outputRow(hash), outputRow(hash)],
  [{ ...outputRow(hash), is_spent: null }],
  [{ ...outputRow(hash), address: null }],
])('malformed output lookup fails closed: %j', async (response) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response))));
  await expect(
    new RegistryKoios(providerUrl('Mainnet')).getUtxosByOutRef([{ txHash: hash, outputIndex: 0 }]),
  ).rejects.toMatchObject({ code: 'MALFORMED_PROVIDER' });
});

test('tip validates slot and freshness before transaction timing uses it', async () => {
  const time = Math.floor(Date.now() / 1000);
  const fetch = vi
    .fn()
    .mockImplementation(
      async () => new Response(JSON.stringify([{ abs_slot: 123, block_time: time }])),
    );
  vi.stubGlobal('fetch', fetch);
  const provider = new RegistryKoios(providerUrl('Mainnet'));
  await expect(provider.getTip()).resolves.toEqual({ slot: 123, timeMs: time * 1000 });
  fetch.mockResolvedValue(new Response(JSON.stringify([{ abs_slot: -1, block_time: time }])));
  await expect(provider.getTip()).rejects.toMatchObject({ code: 'MALFORMED_PROVIDER' });
  fetch.mockResolvedValue(
    new Response(JSON.stringify([{ abs_slot: 123, block_time: time - 121 }])),
  );
  await expect(provider.getTip()).rejects.toMatchObject({ code: 'STALE_CHAIN_TIP' });
});

test.each([
  ['OutsideValidityIntervalUTxO', 'TRANSACTION_TIMING'],
  ['BadInputsUTxO', 'TRANSACTION_INPUTS'],
  ['ValidationTagMismatch', 'SCRIPT_REJECTED'],
  ['arbitrary secret-containing provider response', 'SUBMISSION_FAILED'],
])('submission rejection %s becomes a useful sanitized error', async (message, code) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () => new Response(message, { status: 400 })),
  );
  const provider = new RegistryKoios(providerUrl('Mainnet'));
  await expect(provider.submitTx('cbor')).rejects.toMatchObject({ code });
  await expect(provider.submitTx('cbor')).rejects.not.toThrow(message);
});

test('submission sends CBOR and parses the returned hash', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(hash)));
  vi.stubGlobal('fetch', fetch);
  await expect(new RegistryKoios(providerUrl('Mainnet')).submitTx('abcd')).resolves.toBe(hash);
  expect(fetch.mock.calls[0]![1].body).toEqual(Buffer.from('abcd', 'hex'));
});

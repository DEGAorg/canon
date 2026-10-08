import { expect, test } from 'vitest';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, readdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

function ensure(directory: string): Promise<{ code: number | null; output: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['dist/cli.js']);
    let output = '';
    child.stdout.on('data', (data) => {
      output += data;
    });
    child.once('error', reject);
    child.once('close', (code) => resolve({ code, output }));
    child.stdin.end(
      JSON.stringify({ operation: 'wallet.ensure', network: 'Mainnet', walletPath: directory }) +
        '\n',
    );
  });
}
test('concurrent real CLI startup creates one persistent wallet and Nostr identity', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'canon-wallet-race-'));
  const results = await Promise.all([ensure(directory), ensure(directory), ensure(directory)]);
  expect(results.every((result) => result.code === 0)).toBe(true);
  const values = results.map((result) => JSON.parse(result.output).result);
  expect(values[1]).toEqual(values[0]);
  expect(values[2]).toEqual(values[0]);
  expect(values[0].address).toMatch(/^addr1/);
  expect((await readdir(directory)).sort()).toEqual(['cardano.json', 'nostr.json']);
  expect(JSON.parse((await ensure(directory)).output).result).toEqual(values[0]);
}, 15000);

test('corrupted persisted wallet fails visibly and is never replaced', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'canon-wallet-corrupt-'));
  await writeFile(join(directory, 'cardano.json'), '{broken', { mode: 0o600 });
  const result = await ensure(directory);
  expect(result.code).toBe(1);
  expect(JSON.parse(result.output)).toMatchObject({ ok: false, error: { code: 'INVALID_WALLET' } });
  expect(await readFile(join(directory, 'cardano.json'), 'utf8')).toBe('{broken');
  expect(await readdir(directory)).toEqual(['cardano.json']);
});

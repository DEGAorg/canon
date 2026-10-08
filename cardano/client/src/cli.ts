import { createInterface } from 'node:readline';
import { execute, parseRequest } from '#commands';
import { json } from '#storage';
import { RegistryError } from '#types';

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  try {
    if (Buffer.byteLength(line) > 65536) {
      throw new RegistryError('INVALID_REQUEST', 'Request exceeds 64 KiB');
    }
    const result = await execute(parseRequest(JSON.parse(line) as unknown));
    process.stdout.write(`${json({ ok: true, result })}\n`);
  } catch (error) {
    const failure =
      error instanceof RegistryError
        ? { code: error.code, message: error.message, details: error.details }
        : {
            code: 'OPERATION_FAILED',
            message: 'Operation failed; check deployment, provider and file permissions',
          };
    process.stdout.write(`${json({ ok: false, error: failure })}\n`);
    process.exitCode = 1;
  }
}

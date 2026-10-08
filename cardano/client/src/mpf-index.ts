/** Shared MPF token and proof encoding for registry clients. */
import { Trie } from '@aiken-lang/merkle-patricia-forestry';
import { blake2b } from '@noble/hashes/blake2.js';
import { Data } from '@lucid-evolution/lucid';
import type { RecordEntry } from '#types';

export function marker(name: string): string {
  return (
    '01' +
    Buffer.from(blake2b(Buffer.from(name), { dkLen: 32 }))
      .subarray(0, 31)
      .toString('hex')
  );
}
export function reservationKeys(record: RecordEntry): Buffer[] {
  return [
    Buffer.concat([Buffer.from([0]), Buffer.from(record.name)]),
    Buffer.from('01' + record.owner, 'hex'),
    Buffer.from('02' + record.nostrKey, 'hex'),
  ];
}
export function trieRoot(trie: Trie): string {
  return trie.hash?.toString('hex') ?? '00'.repeat(32);
}
/** Rebuild the index from public records without access to registration secrets. */
export async function rebuildIndex(records: RecordEntry[]): Promise<Trie> {
  const pairs = records.flatMap((record) =>
    reservationKeys(record).map((key) => ({
      key,
      value: Buffer.from(marker(record.name), 'hex'),
    })),
  );
  return Trie.fromList(pairs);
}
/** Make sequential insertion proofs, leaving the caller's index unchanged. */
export async function insertionProofs(
  trie: Trie,
  record: RecordEntry,
): Promise<{
  proofs: Data[];
  root: string;
  proofBytes: number;
}> {
  const keys = reservationKeys(record);
  for (const key of keys) {
    if (await trie.get(key)) throw new Error('Identity is permanently reserved');
  }
  const inserted: Buffer[] = [];
  const proofs: Data[] = [];
  let proofBytes = 0;
  try {
    for (const key of keys) {
      await trie.insert(key, Buffer.from(marker(record.name), 'hex'));
      inserted.push(key);
      const proof = (await trie.prove(key)).toCBOR();
      proofBytes += proof.length;
      proofs.push(Data.from(proof.toString('hex')));
    }
    return { proofs, root: trieRoot(trie), proofBytes };
  } finally {
    for (const key of inserted.reverse()) await trie.delete(key);
  }
}

import type { RecordEntry } from '#types';
/** Deterministic public records for scaling; not claimed to be chain registrations. */
export function syntheticRecords(count: number): RecordEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `seed${i}`,
    owner: (i + 1).toString(16).padStart(56, '0'),
    nostrKey: (i + 1).toString(16).padStart(64, '0'),
    openedMs: 0n,
    expiresMs: 31536000000n,
    members: [(i + 1).toString(16).padStart(56, '0')],
  }));
}

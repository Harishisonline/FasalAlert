/**
 * Last good public board in this server process, so R1 can show "Live data unavailable, showing last
 * update at 14:20 IST" when the API is down (PRD §7.1). The cached rows keep their real timestamps.
 */
import type { PublicRisksResponse } from '@fasalalert/shared/api';
import { getPublicRisks } from './api';

const g = globalThis as typeof globalThis & { __faBoard?: PublicRisksResponse };

export type BoardResult =
  | { kind: 'live'; data: PublicRisksResponse }
  | { kind: 'cached'; data: PublicRisksResponse }
  | { kind: 'down'; traceId: string | null }
  | { kind: 'empty'; data: PublicRisksResponse };

export async function getBoard(): Promise<BoardResult> {
  const r = await getPublicRisks();
  if (r.ok && Array.isArray(r.data?.districts)) {
    if (r.data.districts.length === 0) return { kind: 'empty', data: r.data };
    g.__faBoard = r.data;
    return { kind: 'live', data: r.data };
  }
  if (g.__faBoard) return { kind: 'cached', data: g.__faBoard };
  return { kind: 'down', traceId: !r.ok ? r.error?.trace_id ?? null : null };
}

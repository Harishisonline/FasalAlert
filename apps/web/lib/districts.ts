/** District list search, filter and sort for the Regional outlook (docs/UX_QA_AUDIT.md MAP-03). Pure, unit tested. */
import type { DisplayLevel } from './risk';

export type LevelFilter = 'all' | 'atRisk' | DisplayLevel;
export type DistrictSort = 'severity' | 'name';

export interface DistrictRow { code: string; level: DisplayLevel; probability: number | null; name: { en: string; mr: string; hi: string } }

const SEVERITY: Record<DisplayLevel, number> = { critical: 5, high: 4, medium: 3, low: 2, none: 1, nodata: 0 };

function norm(s: string): string {
  return s.normalize('NFC').toLocaleLowerCase().trim();
}

/** Search matches the district name in any of the three languages, so a Marathi reader can type in English. */
export function filterDistricts<T extends DistrictRow>(rows: T[], opts: { query: string; level: LevelFilter; sort: DistrictSort; locale: 'en' | 'mr' | 'hi' }): T[] {
  const q = norm(opts.query);
  const out = rows.filter((r) => {
    if (opts.level === 'atRisk' && SEVERITY[r.level] < SEVERITY.low) return false;
    if (opts.level !== 'all' && opts.level !== 'atRisk' && r.level !== opts.level) return false;
    if (!q) return true;
    return [r.name.en, r.name.mr, r.name.hi].some((n) => norm(n).includes(q));
  });
  const byName = (a: T, b: T) => a.name[opts.locale].localeCompare(b.name[opts.locale], opts.locale);
  return out.sort(opts.sort === 'name' ? byName : (a, b) => SEVERITY[b.level] - SEVERITY[a.level] || (b.probability ?? 0) - (a.probability ?? 0) || byName(a, b));
}

export function levelCounts(rows: DistrictRow[]): Record<DisplayLevel, number> {
  const c: Record<DisplayLevel, number> = { critical: 0, high: 0, medium: 0, low: 0, none: 0, nodata: 0 };
  for (const r of rows) c[r.level] += 1;
  return c;
}

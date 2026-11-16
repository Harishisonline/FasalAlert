/** My Fields search, filter and sort (docs/UX_QA_AUDIT.md FIELDS-01). Pure, unit tested. */
import type { Crop } from '@fasalalert/shared/api';
import { LEVEL_RANK, type DisplayLevel } from './risk';

export interface FieldCardData {
  id: number;
  name: string;
  crop: Crop;
  cropText: string;
  variety: string | null;
  location: string | null;
  stage: string | null;
  level: DisplayLevel;
  status: 'decision' | 'abstain' | 'stale' | 'pending' | 'loading';
  headline: string | null;
  decisionDate: string | null;
}

export type FieldRiskFilter = 'all' | 'atRisk' | 'noRisk' | 'attention';
export type FieldSort = 'risk' | 'name' | 'newest';

export function filterFields(items: FieldCardData[], opts: { query: string; crop: Crop | 'all'; risk: FieldRiskFilter; sort: FieldSort; locale: string }): FieldCardData[] {
  const q = opts.query.normalize('NFC').toLocaleLowerCase().trim();
  const out = items.filter((f) => {
    if (opts.crop !== 'all' && f.crop !== opts.crop) return false;
    if (opts.risk === 'atRisk' && LEVEL_RANK[f.level] < LEVEL_RANK.low) return false;
    if (opts.risk === 'noRisk' && !(f.status === 'decision' && f.level === 'none')) return false;
    if (opts.risk === 'attention' && f.status === 'decision') return false;
    if (!q) return true;
    return [f.name, f.cropText, f.variety ?? '', f.location ?? ''].some((s) => s.normalize('NFC').toLocaleLowerCase().includes(q));
  });
  const byName = (a: FieldCardData, b: FieldCardData) => a.name.localeCompare(b.name, opts.locale);
  if (opts.sort === 'name') return out.sort(byName);
  if (opts.sort === 'newest') return out.sort((a, b) => b.id - a.id);
  return out.sort((a, b) => LEVEL_RANK[b.level] - LEVEL_RANK[a.level] || byName(a, b));
}

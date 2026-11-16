/**
 * Pure risk logic (design.md 22.1): level ordering, the Home sort (10.4), the IMD probability term
 * (15.3), natural frequencies, transport bins (14.12), card state and staleness (20.2).
 */
import type { Abstention, Decision, Risk, RiskKind, RiskLevel } from '@fasalalert/shared/api';
import { istDateKey, toDate } from './format';

export type DisplayLevel = RiskLevel | 'nodata';

export const LEVEL_RANK: Record<DisplayLevel, number> = { nodata: -1, none: 0, low: 1, medium: 2, high: 3, critical: 4 };
export const LEVELS: RiskLevel[] = ['none', 'low', 'medium', 'high', 'critical'];

export function isAbstention(d: Decision | Abstention): d is Abstention {
  return d.abstain_reason !== null;
}

export function compareLevel(a: DisplayLevel, b: DisplayLevel): number {
  return LEVEL_RANK[a] - LEVEL_RANK[b];
}

/** The risk that drives a card: highest level, then highest probability. */
export function topRisk(risks: Risk[] | null | undefined): Risk | null {
  if (!risks || risks.length === 0) return null;
  return [...risks].sort((a, b) => compareLevel(b.level, a.level) || b.probability - a.probability)[0] ?? null;
}

export type ImdTerm = 'unlikely' | 'likely' | 'veryLikely' | 'mostLikely';

/** IMD probability vocabulary (design.md 15.3): <25, 25 to 49, 50 to 74, 75 and above. */
export function imdTerm(p: number): ImdTerm {
  if (p < 0.25) return 'unlikely';
  if (p < 0.5) return 'likely';
  if (p < 0.75) return 'veryLikely';
  return 'mostLikely';
}

/** "as likely as not" at 45 to 55 percent (WMO, design.md 15.3). */
export function asLikelyAsNot(p: number): boolean {
  return p >= 0.45 && p <= 0.55;
}

/** Design-default transport bins until the model publishes its own (Appendix B, Q10). */
export function transportLevel(p: number): RiskLevel {
  if (p < 0.15) return 'none';
  if (p < 0.35) return 'low';
  if (p < 0.6) return 'medium';
  if (p < 0.8) return 'high';
  return 'critical';
}

/** Stale after one missed 3-hourly refresh plus the 900 s TTL (design.md 20.2, Appendix B Q16). */
export const FORECAST_STALE_MS = (3 * 60 + 15) * 60_000;

export function isOlderThan(iso: string | null | undefined, ms: number, now: Date = new Date()): boolean {
  if (!iso) return false;
  const t = toDate(iso).getTime();
  return Number.isFinite(t) && now.getTime() - t > ms;
}

/** Latest forecast fetch time behind a decision (evidence first, then forecast sources). */
export function forecastFetchedAt(decision: Decision): string | null {
  const times: string[] = [];
  for (const r of decision.risks) {
    const at = r.evidence?.forecast_fetched_at;
    if (typeof at === 'string') times.push(at);
  }
  if (times.length === 0) {
    for (const s of decision.sources ?? []) if (s.kind === 'forecast' && s.fetched_at) times.push(s.fetched_at);
  }
  if (times.length === 0) return null;
  return times.sort((a, b) => toDate(b).getTime() - toDate(a).getTime())[0] ?? null;
}

export type CardState = 'actionable' | 'no-risk' | 'abstain' | 'stale' | 'raw' | 'loading';

export interface CardModel {
  state: CardState;
  level: DisplayLevel;
  risk: Risk | null;
  lastUpdatedAt: string | null;
}

/** Map a decision (or abstention, or nothing) to the DecisionCard state (design.md 14.1). */
export function cardModel(decision: Decision | Abstention | null | undefined, now: Date = new Date()): CardModel {
  if (!decision) return { state: 'stale', level: 'nodata', risk: null, lastUpdatedAt: null };
  if (isAbstention(decision)) {
    if (decision.abstain_reason === 'data_stale') {
      return { state: 'stale', level: 'nodata', risk: null, lastUpdatedAt: decision.last_update ?? null };
    }
    return { state: 'abstain', level: 'nodata', risk: topRisk(decision.risks), lastUpdatedAt: decision.last_update ?? null };
  }
  const fetched = forecastFetchedAt(decision);
  if (fetched && isOlderThan(fetched, FORECAST_STALE_MS, now)) {
    return { state: 'stale', level: 'nodata', risk: null, lastUpdatedAt: fetched };
  }
  const risk = topRisk(decision.risks);
  if (!risk || risk.level === 'none') return { state: 'no-risk', level: 'none', risk, lastUpdatedAt: fetched };
  return { state: 'actionable', level: risk.level, risk, lastUpdatedAt: fetched };
}

/** Pinned: a frost or heat decision whose action falls on today's IST date (design.md 10.4). */
export function isPinned(decision: Decision | Abstention | null | undefined, now: Date = new Date()): boolean {
  if (!decision || isAbstention(decision) || !decision.action_by) return false;
  const today = istDateKey(now);
  if (istDateKey(decision.action_by) !== today) return false;
  return decision.risks.some((r) => (r.kind === 'frost' || r.kind === 'heatwave') && r.level !== 'none');
}

export interface HomeItem {
  fieldId: number;
  fieldName: string;
  decision: Decision | Abstention | null;
}

function sortBucket(item: HomeItem, now: Date): number {
  const m = cardModel(item.decision, now);
  if (isPinned(item.decision, now)) return 0;
  if (m.state === 'actionable') {
    if (m.level === 'critical') return 1;
    if (m.level === 'high') return 2;
    if (m.level === 'medium') return 3;
  }
  if (m.state === 'abstain' || m.state === 'stale' || m.state === 'raw') return 4;
  if (m.state === 'actionable' && m.level === 'low') return 5;
  return 6;
}

function actionTime(d: Decision | Abstention | null): number {
  if (!d || isAbstention(d) || !d.action_by) return Number.POSITIVE_INFINITY;
  return toDate(d.action_by).getTime();
}

/** Home urgency order (design.md 10.4). */
export function sortHome<T extends HomeItem>(items: T[], now: Date = new Date()): T[] {
  return [...items].sort(
    (a, b) =>
      sortBucket(a, now) - sortBucket(b, now) ||
      actionTime(a.decision) - actionTime(b.decision) ||
      a.fieldName.localeCompare(b.fieldName),
  );
}

export type Trend = { direction: 'up' | 'down' | 'flat'; wide: boolean };

/** Plain trend read from numbers, never from an LLM (design.md 12.7; cut-offs are Q9 defaults). */
export function trendRead(modal: number, p10: number | null, p50: number | null, p90: number | null): Trend | null {
  if (p50 === null || !Number.isFinite(modal) || modal <= 0) return null;
  const change = (p50 - modal) / modal;
  // "Mostly above": more than half of the p10 to p90 band lies above today's modal price.
  const mostlyAbove = p10 === null || p90 === null || p90 <= p10 ? true : (p90 - modal) / (p90 - p10) > 0.5;
  let direction: Trend['direction'] = 'flat';
  if (change >= 0.03 && mostlyAbove) direction = 'up';
  else if (change <= -0.03) direction = 'down';
  const wide = p10 !== null && p90 !== null && p10 < modal * 0.95 && p90 > modal * 1.05;
  return { direction, wide };
}

export const KIND_ICON_KEYS: Record<RiskKind | 'price', string> = {
  frost: 'frost', heatwave: 'heatwave', heavy_rain: 'heavy_rain', dry_spell: 'dry_spell', transport: 'transport', price: 'price',
};

/** Alert filter chips (PRD §7.6). Alert.kind is a free string, so several spellings map to one chip. */
export type AlertFilter = 'all' | 'frost' | 'heat' | 'rain' | 'transport' | 'price';
export function alertFilterOf(kind: string): Exclude<AlertFilter, 'all'> | null {
  const k = kind.toLowerCase();
  if (k.includes('frost') || k.includes('cold')) return 'frost';
  if (k.includes('heat')) return 'heat';
  if (k.includes('rain') || k.includes('dry')) return 'rain';
  if (k.includes('transport') || k.includes('route') || k.includes('road')) return 'transport';
  if (k.includes('price') || k.includes('market')) return 'price';
  return null;
}

export function riskKindOf(kind: string): RiskKind | 'price' | null {
  const f = alertFilterOf(kind);
  if (f === 'frost') return 'frost';
  if (f === 'heat') return 'heatwave';
  if (f === 'rain') return kind.toLowerCase().includes('dry') ? 'dry_spell' : 'heavy_rain';
  if (f === 'transport') return 'transport';
  if (f === 'price') return 'price';
  return null;
}

/** Ranked districts for R1: top 3 by level then probability, excluding no-data and no-risk (PRD §7.1). */
export function rankDistricts<T extends { level: DisplayLevel; probability: number | null }>(rows: T[], n = 3): T[] {
  return rows
    .filter((r) => r.level !== 'nodata' && r.level !== 'none')
    .sort((a, b) => compareLevel(b.level, a.level) || (b.probability ?? 0) - (a.probability ?? 0))
    .slice(0, n);
}

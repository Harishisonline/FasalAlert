/**
 * View helpers shared by server and client display components. They turn API values into
 * localised phrases through the translator, so word order stays per locale (design.md 18.3).
 */
import type { Crop, Localized, RiskKind, SourceRef } from '@fasalalert/shared/api';
import type { Translator } from './i18n';
import type { Locale } from './locales';
import {
  countdown, daysBetween, formatDateShort, istDateKey, formatPercent, formatTime, formatWeekday, naturalFrequency, relativeDay, type TempUnit,
} from './format';
import { asLikelyAsNot, imdTerm, type DisplayLevel } from './risk';

export interface ViewCtx { t: Translator; locale: Locale; now: Date; unit: TempUnit }

export function loc(value: Localized | null | undefined, locale: Locale): string {
  if (!value) return '';
  return value[locale] || value.en || value.mr || value.hi || '';
}

export function levelLabel(t: Translator, level: DisplayLevel): string {
  return t(`risk.level.${level}`);
}

export function kindLabel(t: Translator, kind: RiskKind | 'price' | string): string {
  const known = ['frost', 'heatwave', 'heavy_rain', 'dry_spell', 'transport', 'price'];
  return known.includes(kind) ? t(`risk.kind.${kind}`) : kind;
}

export function cropLabel(t: Translator, crop: Crop | string, lower = false): string {
  const known = ['mango', 'pomegranate', 'grape', 'cotton', 'soybean', 'sugarcane'];
  if (!known.includes(crop)) return crop;
  return t(lower ? `crop.lower.${crop}` : `crop.${crop}`);
}

/** "tonight", "today", "tomorrow", "on Wed", or "on 18 Jan" (for chance phrases). */
export function whenWord(t: Translator, iso: string, now: Date, locale: Locale): string {
  const r = relativeDay(iso, now);
  if (r === 'tonight') return t('when.tonight');
  if (r === 'today') return t('when.today');
  if (r === 'tomorrow') return t('when.tomorrow');
  if (r === 'weekday') return t('when.onDay', { day: formatWeekday(iso, locale) });
  return t('when.onDay', { day: formatDateShort(iso, locale, now) });
}

/** Date words only, for "Act by 21:30 today" (the time already carries the day-part in mr and hi). */
export function dayWord(t: Translator, iso: string, now: Date, locale: Locale): string {
  const diff = daysBetween(istDateKey(now), istDateKey(iso));
  if (diff === 0) return t('day.today');
  if (diff === 1) return t('day.tomorrow');
  if (diff > 1 && diff <= 6) return t('day.on', { day: formatWeekday(iso, locale) });
  return t('day.on', { day: formatDateShort(iso, locale, now) });
}

export function actByText(t: Translator, iso: string, now: Date, locale: Locale): string {
  return t('decision.actBy', { time: formatTime(iso, locale), day: dayWord(t, iso, now, locale) });
}

/** "in 5 h 10 min", only when under 12 h (design.md 14.1 row 4). */
export function countdownText(t: Translator, iso: string, now: Date): string | null {
  const c = countdown(iso, now);
  if (c.totalMinutes <= 0 || c.totalMinutes >= 12 * 60) return null;
  return c.hours > 0 ? t('time.inHoursMinutes', { h: c.hours, m: c.minutes }) : t('time.inMinutes', { m: c.minutes });
}

export function pctText(t: Translator, p: number, locale: Locale): string {
  return formatPercent(p, locale) ?? t('prob.belowOne');
}

export function naturalText(t: Translator, p: number): string {
  const n = naturalFrequency(p);
  const base = n === 0 ? t('prob.naturalZero') : t('prob.natural', { n });
  return asLikelyAsNot(p) ? `${base}, ${t('prob.asLikely')}` : base;
}

export function termText(t: Translator, p: number): string {
  return t(`prob.${imdTerm(p)}`);
}

/** Home cards use words only: "Frost most likely tonight." (design.md 15.3). */
export function chancePhrase(t: Translator, kind: RiskKind, p: number, atIso: string | null | undefined, now: Date, locale: Locale): string {
  const when = atIso ? whenWord(t, atIso, now, locale) : '';
  return t(`chance.${kind}`, { term: imdTerm(p), when }).replace(/\s+\./, '.').trim();
}

export type SourceKind = 'forecast' | 'observed' | 'advisory' | 'market' | 'model' | 'synthetic' | 'generic';

export interface SourceItem {
  label: string;
  url?: string | null;
  at?: string | null;
  kind: SourceKind;
  verified?: boolean;
  stale?: boolean;
}

export function fromSourceRef(ref: SourceRef, extra: Partial<SourceItem> = {}): SourceItem {
  const kind: SourceKind = ref.synthetic ? 'synthetic' : (ref.kind ?? 'generic');
  return { label: ref.label, url: ref.url ?? null, at: ref.fetched_at, kind, ...extra };
}

export function isSafeHttpUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'http:';
  } catch {
    return false;
  }
}

/**
 * Every number, date and time on screen goes through this file (design.md 7.5, 18.3, 22.1).
 * Western digits in every locale via `-u-nu-latn`. Times are IST (Asia/Kolkata).
 */
import { intlLocale, type Locale } from './locales';

export const IST = 'Asia/Kolkata';
/** Narrow no-break space between a number and its unit (design.md 7.5). */
export const NNBSP = String.fromCharCode(0x202f);
export const MINUS = String.fromCharCode(0x2212);

const nfCache = new Map<string, Intl.NumberFormat>();
function nf(locale: Locale, opts: Intl.NumberFormatOptions = {}): Intl.NumberFormat {
  const key = `${locale}|${JSON.stringify(opts)}`;
  let f = nfCache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(intlLocale(locale), opts);
    nfCache.set(key, f);
  }
  return f;
}

/** A true minus sign for negative data values (design.md 7.5). */
function signed(text: string): string {
  const t = text.replace(/^-/, MINUS);
  return t.startsWith(MINUS) && /^0([.,]0+)?$/.test(t.slice(1)) ? t.slice(1) : t;
}

export function formatNumber(value: number, locale: Locale, maxFractionDigits = 0): string {
  return signed(nf(locale, { maximumFractionDigits: maxFractionDigits, minimumFractionDigits: 0 }).format(value));
}

export function formatFixed(value: number, locale: Locale, digits: number): string {
  return signed(nf(locale, { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value));
}

export type TempUnit = 'celsius' | 'fahrenheit';

export function toUnit(celsius: number, unit: TempUnit): number {
  return unit === 'fahrenheit' ? (celsius * 9) / 5 + 32 : celsius;
}

/** "3.2 °C": one decimal, unit after a narrow no-break space. */
export function formatTemp(celsius: number, locale: Locale, unit: TempUnit = 'celsius'): string {
  const v = toUnit(celsius, unit);
  return `${formatFixed(v, locale, 1)}${NNBSP}${unit === 'fahrenheit' ? '°F' : '°C'}`;
}

/** "₹4,520": whole rupees with Indian grouping, the symbol attached. */
export function formatRupees(value: number, locale: Locale): string {
  const text = formatNumber(Math.round(value), locale);
  return text.startsWith(MINUS) ? `${MINUS}₹${text.slice(1)}` : `₹${text}`;
}

export function formatWithUnit(value: number, unit: string, locale: Locale, digits = 0): string {
  return `${formatNumber(digits ? Number(value.toFixed(digits)) : Math.round(value), locale, digits)}${NNBSP}${unit}`;
}

/** Whole percent, never "0%" or "100%" (design.md 15.3). Returns null below 1 percent. */
export function formatPercent(p: number, locale: Locale): string | null {
  const pct = Math.round(p * 100);
  if (p < 0.005) return null;
  return `${formatNumber(Math.min(Math.max(pct, 1), 99), locale)}%`;
}

/** Natural frequency numerator: round(p x 10) in 10 (design.md 15.3). */
export function naturalFrequency(p: number): number {
  return Math.min(10, Math.max(0, Math.round(p * 10)));
}

/* ---------------- Dates and times (IST) ---------------- */

export interface IstParts { year: number; month: number; day: number; hour: number; minute: number; weekday: number }

const partsFmt = new Intl.DateTimeFormat('en-GB-u-nu-latn', {
  timeZone: IST,
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short',
});
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export function toDate(value: string | number | Date): Date {
  if (value instanceof Date) return value;
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    // A plain ISO date is a calendar day in IST.
    return new Date(`${value}T12:00:00+05:30`);
  }
  return new Date(value);
}

export function istParts(value: string | number | Date): IstParts {
  const parts = partsFmt.formatToParts(toDate(value));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '0';
  return {
    year: Number(get('year')),
    month: Number(get('month')),
    day: Number(get('day')),
    hour: Number(get('hour')) % 24,
    minute: Number(get('minute')),
    weekday: WEEKDAYS.indexOf(get('weekday')),
  };
}

/** "2026-01-18" for the IST calendar day. */
export function istDateKey(value: string | number | Date): string {
  const p = istParts(value);
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`;
}

export function daysBetween(fromKey: string, toKey: string): number {
  const a = Date.parse(`${fromKey}T00:00:00Z`);
  const b = Date.parse(`${toKey}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

export type DayPart = 'predawn' | 'morning' | 'afternoon' | 'evening' | 'night';

/** Day-part bands from design.md 18.3. */
export function dayPart(hour: number): DayPart {
  if (hour >= 4 && hour < 6) return 'predawn';
  if (hour >= 6 && hour < 12) return 'morning';
  if (hour >= 12 && hour < 16) return 'afternoon';
  if (hour >= 16 && hour < 20) return 'evening';
  return 'night';
}

export const DAY_PART_WORDS: Record<'mr' | 'hi', Record<DayPart, string>> = {
  mr: { predawn: 'पहाटे', morning: 'सकाळी', afternoon: 'दुपारी', evening: 'संध्याकाळी', night: 'रात्री' },
  hi: { predawn: 'तड़के', morning: 'सुबह', afternoon: 'दोपहर', evening: 'शाम', night: 'रात' },
};

/**
 * en keeps the PRD's 24-hour style ("21:30"). mr and hi use the 12-hour clock with a
 * day-part word ("रात्री 9:30", "रात 9:30"), design.md 18.3 and D-18.
 */
export function formatTime(value: string | number | Date, locale: Locale): string {
  const { hour, minute } = istParts(value);
  const mm = String(minute).padStart(2, '0');
  if (locale === 'en') return `${String(hour).padStart(2, '0')}:${mm}`;
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${DAY_PART_WORDS[locale][dayPart(hour)]} ${h12}:${mm}`;
}

/** "17 Jan" (mr "17 जाने.", hi "17 जन."). The year is added only when it is not the current year. */
export function formatDateShort(value: string | number | Date, locale: Locale, now: Date = new Date()): string {
  const d = toDate(value);
  const sameYear = istParts(d).year === istParts(now).year;
  return new Intl.DateTimeFormat(intlLocale(locale), {
    timeZone: IST, day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }),
  }).format(d);
}

export function formatWeekday(value: string | number | Date, locale: Locale, style: 'short' | 'long' = 'short'): string {
  return new Intl.DateTimeFormat(intlLocale(locale), { timeZone: IST, weekday: style }).format(toDate(value));
}

/** "Wed, 18 Jan" */
export function formatDayDate(value: string | number | Date, locale: Locale, now: Date = new Date()): string {
  return `${formatWeekday(value, locale)}, ${formatDateShort(value, locale, now)}`;
}

export function formatLongDate(value: string | number | Date, locale: Locale): string {
  return new Intl.DateTimeFormat(intlLocale(locale), { timeZone: IST, weekday: 'long', day: 'numeric', month: 'long' }).format(toDate(value));
}

/** Same IST day: the time only. Other days: "16 Jan 19:00". */
export function formatDateTime(value: string | number | Date, locale: Locale, now: Date = new Date()): string {
  const d = toDate(value);
  if (istDateKey(d) === istDateKey(now)) return formatTime(d, locale);
  return `${formatDateShort(d, locale, now)} ${formatTime(d, locale)}`;
}

export type RelativeDay = 'tonight' | 'today' | 'tomorrow' | 'weekday' | 'date';

/**
 * Relative day word (design.md 18.3): "tonight" is 18:00 today to 06:00 tomorrow, then "today",
 * "tomorrow", the weekday name up to 6 days ahead, then the date.
 */
export function relativeDay(value: string | number | Date, now: Date = new Date()): RelativeDay {
  const d = toDate(value);
  const diff = daysBetween(istDateKey(now), istDateKey(d));
  const { hour } = istParts(d);
  if ((diff === 0 && hour >= 18) || (diff === 1 && hour < 6)) return 'tonight';
  if (diff === 0) return 'today';
  if (diff === 1) return 'tomorrow';
  if (diff > 1 && diff <= 6) return 'weekday';
  return 'date';
}

export function countdown(target: string | number | Date, now: Date = new Date()): { totalMinutes: number; hours: number; minutes: number } {
  const totalMinutes = Math.max(0, Math.round((toDate(target).getTime() - now.getTime()) / 60_000));
  return { totalMinutes, hours: Math.floor(totalMinutes / 60), minutes: totalMinutes % 60 };
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/* ---------------- Area, distance, coordinates ---------------- */

export type AreaUnit = 'hectare' | 'acre';
export const SQM_PER_HECTARE = 10_000;
export const SQM_PER_ACRE = 4046.8564224;

export function areaFromSqm(sqm: number, unit: AreaUnit): number {
  return sqm / (unit === 'acre' ? SQM_PER_ACRE : SQM_PER_HECTARE);
}
export function areaToSqm(value: number, unit: AreaUnit): number {
  return value * (unit === 'acre' ? SQM_PER_ACRE : SQM_PER_HECTARE);
}

export function formatCoordinate(value: number, locale: Locale): string {
  return formatFixed(value, locale, 4);
}

/** Phone digits for tel: links. */
export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, '')}`;
}

/** Spelled-out digits for accessible names of phone numbers (design.md 12.11). */
export function spellDigits(phone: string): string {
  return phone.replace(/[^\d+]/g, '').split('').join(' ');
}

/** Group a 10-digit Indian mobile as "98765 43210". */
export function groupPhone(digits: string): string {
  const d = digits.replace(/\D/g, '').slice(0, 10);
  return d.length > 5 ? `${d.slice(0, 5)} ${d.slice(5)}` : d;
}

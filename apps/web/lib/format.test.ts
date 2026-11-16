import { describe, expect, it } from 'vitest';
import {
  MINUS, NNBSP, dayPart, formatDateShort, formatNumber, formatPercent, formatRupees, formatTemp, formatTime, istDateKey,
  naturalFrequency, relativeDay,
} from './format';
import { intlLocale } from './locales';

describe('Western digits in every locale (design.md 7.5, 18.3)', () => {
  it('uses the -u-nu-latn extension', () => {
    expect(intlLocale('mr')).toBe('mr-IN-u-nu-latn');
    expect(intlLocale('hi')).toBe('hi-IN-u-nu-latn');
  });
  it('formats Marathi numbers with Western digits and Indian grouping', () => {
    expect(formatNumber(1234567.5, 'mr', 1)).toBe('12,34,567.5');
    expect(formatNumber(1234567.5, 'mr', 1)).not.toMatch(/[०-९]/);
    expect(new Intl.NumberFormat('mr-IN').format(1)).not.toBe('1'); // plain mr-IN would give Devanagari digits
  });
  it('formats rupees, temperatures and percentages', () => {
    expect(formatRupees(4520, 'mr')).toBe('₹4,520');
    expect(formatTemp(3.2, 'en')).toBe(`3.2${NNBSP}°C`);
    expect(formatTemp(-0.5, 'en')).toBe(`${MINUS}0.5${NNBSP}°C`);
    expect(formatTemp(0, 'en', 'fahrenheit')).toBe(`32.0${NNBSP}°F`);
    expect(formatPercent(0.82, 'mr')).toBe('82%');
    expect(formatPercent(1, 'en')).toBe('99%');
    expect(formatPercent(0.001, 'en')).toBeNull();
    expect(naturalFrequency(0.82)).toBe(8);
  });
  it('writes Marathi month names with Western digits', () => {
    const d = formatDateShort('2026-01-17', 'mr', new Date('2026-01-17T08:00:00+05:30'));
    expect(d).toMatch(/^17 /);
    expect(d).not.toMatch(/[०-९]/);
  });
});

describe('day-part time words (design.md 18.3)', () => {
  it('maps the bands', () => {
    expect(dayPart(4)).toBe('predawn');
    expect(dayPart(9)).toBe('morning');
    expect(dayPart(14)).toBe('afternoon');
    expect(dayPart(18)).toBe('evening');
    expect(dayPart(21)).toBe('night');
    expect(dayPart(2)).toBe('night');
  });
  it('uses 24-hour time in English and 12-hour with a day-part word in mr and hi', () => {
    expect(formatTime('2026-01-17T21:30:00+05:30', 'en')).toBe('21:30');
    expect(formatTime('2026-01-17T21:30:00+05:30', 'mr')).toBe('रात्री 9:30');
    expect(formatTime('2026-01-18T05:40:00+05:30', 'mr')).toBe('पहाटे 5:40');
    expect(formatTime('2026-01-17T09:30:00+05:30', 'mr')).toBe('सकाळी 9:30');
    expect(formatTime('2026-01-17T14:20:00+05:30', 'mr')).toBe('दुपारी 2:20');
    expect(formatTime('2026-01-17T18:04:00+05:30', 'mr')).toBe('संध्याकाळी 6:04');
    expect(formatTime('2026-01-17T21:30:00+05:30', 'hi')).toBe('रात 9:30');
    expect(formatTime('2026-01-18T05:40:00+05:30', 'hi')).toBe('तड़के 5:40');
    expect(formatTime('2026-01-17T12:05:00+05:30', 'hi')).toBe('दोपहर 12:05');
  });
  it('works in IST whatever the server time zone', () => {
    expect(istDateKey('2026-01-17T20:00:00Z')).toBe('2026-01-18');
  });
  it('names tonight, today and tomorrow', () => {
    const now = new Date('2026-01-17T16:20:00+05:30');
    expect(relativeDay('2026-01-17T21:30:00+05:30', now)).toBe('tonight');
    expect(relativeDay('2026-01-18T05:40:00+05:30', now)).toBe('tonight');
    expect(relativeDay('2026-01-17T10:00:00+05:30', now)).toBe('today');
    expect(relativeDay('2026-01-18T10:00:00+05:30', now)).toBe('tomorrow');
    expect(relativeDay('2026-01-20T10:00:00+05:30', now)).toBe('weekday');
  });
});

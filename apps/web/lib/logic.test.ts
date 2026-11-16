import { describe, expect, it } from 'vitest';
import type { Abstention, Decision } from '@fasalalert/shared/api';
import { formatMessage, argumentNames } from './icu';
import { createTranslator } from './i18n';
import { isValidPhone, normalisePhone, safeNext } from './phone';
import { cardModel, imdTerm, isPinned, rankDistricts, sortHome, transportLevel, trendRead } from './risk';
import { actByText, chancePhrase } from './view';

const now = new Date('2026-01-17T16:20:00+05:30');
const fresh = '2026-01-17T15:04:11+05:30';
function decision(over: Partial<Decision> = {}): Decision {
  return {
    field_id: 1, decision_date: '2026-01-17', headline: 'h', action_text: 'Irrigate the basin before 21:30 tonight. Wet soil holds the heat.',
    action_by: '2026-01-17T21:30:00+05:30', confidence: 0.82, abstain_reason: null,
    risks: [{ kind: 'frost', level: 'high', probability: 0.82, tmin_c: 3.2, band_low_c: 2.8, band_high_c: 3.6, threshold_c: 4, window_start: '2026-01-18T05:00:00+05:30', window_end: '2026-01-18T07:00:00+05:30', lead_hours: 13, model_version: 'frost-test', evidence: { forecast_source: 'test-forecast', forecast_fetched_at: fresh } }],
    market: null, transport: null, recommendation: null, advisory: null, sources: [], model_versions: {}, ...over,
  };
}

describe('ICU subset', () => {
  it('formats plural, select and nested arguments', () => {
    expect(formatMessage('{count, plural, one {# attempt left} other {# attempts left}}', { count: 1 }, 'en-IN-u-nu-latn')).toBe('1 attempt left');
    expect(formatMessage('{count, plural, one {# attempt left} other {# attempts left}}', { count: 3 }, 'en-IN-u-nu-latn')).toBe('3 attempts left');
    expect(formatMessage('Hi{has, select, yes {, {name}} other {}}.', { has: 'yes', name: 'Sunita' }, 'en')).toBe('Hi, Sunita.');
    expect(argumentNames('{a} {b, select, x {{c}} other {}}')).toEqual(['a', 'b', 'c']);
  });
  it('uses Western digits for numbers in Marathi messages', () => {
    const t = createTranslator('mr');
    expect(t('signin.wrongCode', { count: 3 })).toMatch(/3/);
  });
});

describe('risk logic', () => {
  it('uses the IMD probability terms', () => {
    expect(imdTerm(0.1)).toBe('unlikely');
    expect(imdTerm(0.3)).toBe('likely');
    expect(imdTerm(0.6)).toBe('veryLikely');
    expect(imdTerm(0.82)).toBe('mostLikely');
  });
  it('bins transport probabilities with the design defaults (Q10)', () => {
    expect([0.08, 0.22, 0.41, 0.68, 0.85].map(transportLevel)).toEqual(['none', 'low', 'medium', 'high', 'critical']);
  });
  it('maps decisions to card states', () => {
    expect(cardModel(decision(), now).state).toBe('actionable');
    expect(cardModel(decision({ risks: [] }), now).state).toBe('no-risk');
    const stale = decision({ risks: [{ ...decision().risks[0]!, evidence: { forecast_fetched_at: '2026-01-17T08:00:00+05:30' } }] });
    expect(cardModel(stale, now).state).toBe('stale');
    const ab: Abstention = { field_id: 1, decision_date: '2026-01-17', headline: 'x', action_text: 'y', confidence: 0, abstain_reason: 'missing_field_input', risks: [], kvk: null };
    expect(cardModel(ab, now).state).toBe('abstain');
    expect(cardModel({ ...ab, abstain_reason: 'data_stale', last_update: '2026-01-17T14:20:00+05:30' }, now)).toMatchObject({ state: 'stale', lastUpdatedAt: '2026-01-17T14:20:00+05:30' });
    expect(cardModel(null, now).state).toBe('stale');
  });
  it('pins today frost decisions and sorts by urgency (design.md 10.4)', () => {
    expect(isPinned(decision(), now)).toBe(true);
    const items = sortHome([
      { fieldId: 2, fieldName: 'B', decision: decision({ field_id: 2, risks: [] }) },
      { fieldId: 3, fieldName: 'C', decision: { field_id: 3, decision_date: '2026-01-17', headline: '', action_text: '', confidence: 0, abstain_reason: 'no_retrieval_above_threshold', risks: [], kvk: null } },
      { fieldId: 1, fieldName: 'A', decision: decision() },
    ], now);
    expect(items.map((i) => i.fieldId)).toEqual([1, 3, 2]);
  });
  it('ranks districts excluding no data', () => {
    const rows = [{ code: 'a', level: 'nodata' as const, probability: null }, { code: 'b', level: 'high' as const, probability: 0.6 }, { code: 'c', level: 'high' as const, probability: 0.9 }, { code: 'd', level: 'low' as const, probability: 0.3 }];
    expect(rankDistricts(rows).map((r) => r.code)).toEqual(['c', 'b', 'd']);
  });
  it('reads the price trend from numbers only', () => {
    expect(trendRead(4520, 4310, 4790, 5120)).toEqual({ direction: 'up', wide: false });
    expect(trendRead(4520, 4000, 4300, 4600)?.direction).toBe('down');
  });
  it('writes chance phrases in words only and act-by text with day words', () => {
    const t = createTranslator('en');
    expect(chancePhrase(t, 'frost', 0.82, '2026-01-18T05:00:00+05:30', now, 'en')).toBe('Frost most likely tonight.');
    expect(actByText(t, '2026-01-17T21:30:00+05:30', now, 'en')).toBe('Act by 21:30 today');
    const mr = createTranslator('mr');
    expect(actByText(mr, '2026-01-17T21:30:00+05:30', now, 'mr')).toContain('रात्री 9:30');
  });
});

describe('phone helpers', () => {
  it('normalises pasted numbers', () => {
    expect(normalisePhone('+91 98765-43210')).toBe('9876543210');
    expect(normalisePhone('09876543210')).toBe('9876543210');
    expect(isValidPhone('9876543210')).toBe(true);
    expect(isValidPhone('5876543210')).toBe(false);
  });
  it('rejects open redirects', () => {
    expect(safeNext('/mr/home')).toBe('/mr/home');
    expect(safeNext('//evil.example')).toBeNull();
    expect(safeNext('https://evil.example')).toBeNull();
  });
});

/** Regression tests for the redesign's routing and list logic (docs/UX_QA_AUDIT.md). */
import { describe, expect, it } from 'vitest';
import { postSignInTarget } from './auth-flow';
import { filterDistricts, levelCounts, type DistrictRow } from './districts';
import { filterFields, type FieldCardData } from './fields';
import { destinationFor, shellFor } from './nav';

describe('navigation model (NAV-01, NAV-03)', () => {
  it('maps every app path to its destination; a field page belongs to My Fields', () => {
    expect(destinationFor('/mr/home')).toBe('home');
    expect(destinationFor('/mr/fields')).toBe('fields');
    expect(destinationFor('/mr/fields/new')).toBe('fields');
    expect(destinationFor('/mr/field/12')).toBe('fields');
    expect(destinationFor('/en/ask?field_id=3')).toBe('ask');
    expect(destinationFor('/en/market')).toBe('market');
    expect(destinationFor('/en/alert')).toBe('alerts');
    expect(destinationFor('/hi/map')).toBe('map');
    expect(destinationFor('/hi/settings/calibration')).toBe('settings');
    expect(destinationFor('/hi/signin')).toBeNull();
  });
  it('uses the focused layout for sign in, onboarding, add field and offline, the public header when signed out', () => {
    for (const p of ['/en/signin', '/en/onboarding', '/en/fields/new', '/en/offline']) expect(shellFor(p, true)).toBe('focus');
    expect(shellFor('/en/fields', true)).toBe('app');
    expect(shellFor('/en/map', true)).toBe('app');
    expect(shellFor('/en/map', false)).toBe('public');
  });
});

describe('post sign-in destination (FLOW-02)', () => {
  it('sends a user without fields to onboarding, even with a ?next=', () => {
    expect(postSignInTarget({ hasFields: false, next: null, locale: 'mr' })).toBe('/mr/onboarding');
    expect(postSignInTarget({ hasFields: false, next: '/mr/ask', locale: 'mr' })).toBe('/mr/onboarding');
  });
  it('sends a returning user to a safe ?next= or Home, never back to onboarding or sign in', () => {
    expect(postSignInTarget({ hasFields: true, next: null, locale: 'en' })).toBe('/en/home');
    expect(postSignInTarget({ hasFields: true, next: '/en/field/4?edit=sowing', locale: 'en' })).toBe('/en/field/4?edit=sowing');
    expect(postSignInTarget({ hasFields: true, next: '/en/onboarding', locale: 'en' })).toBe('/en/home');
    expect(postSignInTarget({ hasFields: true, next: '/en/signin', locale: 'en' })).toBe('/en/home');
    expect(postSignInTarget({ hasFields: true, next: '/', locale: 'en' })).toBe('/en/home');
    expect(postSignInTarget({ hasFields: true, next: '//evil.example', locale: 'en' })).toBe('/en/home');
    expect(postSignInTarget({ hasFields: true, next: 'https://evil.example', locale: 'en' })).toBe('/en/home');
  });
});

const d = (code: string, level: DistrictRow['level'], en: string, mr: string, p: number | null = null): DistrictRow => ({ code, level, probability: p, name: { en, mr, hi: en } });
const DISTRICTS = [d('a', 'none', 'Pune', 'पुणे'), d('b', 'high', 'Nashik', 'नाशिक', 0.7), d('c', 'medium', 'Ahilyanagar', 'अहिल्यानगर', 0.4), d('d', 'nodata', 'Latur', 'लातूर'), d('e', 'high', 'Akola', 'अकोला', 0.9)];

describe('district list (MAP-03)', () => {
  it('sorts by severity, then chance, then name', () => {
    expect(filterDistricts(DISTRICTS, { query: '', level: 'all', sort: 'severity', locale: 'en' }).map((r) => r.code)).toEqual(['e', 'b', 'c', 'a', 'd']);
  });
  it('searches names in any language and filters by level', () => {
    expect(filterDistricts(DISTRICTS, { query: 'नाशि', level: 'all', sort: 'name', locale: 'mr' }).map((r) => r.code)).toEqual(['b']);
    expect(filterDistricts(DISTRICTS, { query: 'PUNE', level: 'all', sort: 'name', locale: 'en' }).map((r) => r.code)).toEqual(['a']);
    expect(filterDistricts(DISTRICTS, { query: '', level: 'atRisk', sort: 'name', locale: 'en' }).map((r) => r.code)).toEqual(['c', 'e', 'b']);
    expect(filterDistricts(DISTRICTS, { query: '', level: 'nodata', sort: 'name', locale: 'en' }).map((r) => r.code)).toEqual(['d']);
    expect(levelCounts(DISTRICTS)).toMatchObject({ high: 2, medium: 1, none: 1, nodata: 1, low: 0, critical: 0 });
  });
});

const f = (id: number, name: string, level: FieldCardData['level'], status: FieldCardData['status'], crop: FieldCardData['crop'] = 'grape'): FieldCardData => ({
  id, name, crop, cropText: crop, variety: null, location: 'Niphad, Nashik', stage: null, level, status, headline: null, decisionDate: null,
});
const FIELDS = [f(1, 'North plot', 'none', 'decision'), f(2, 'Cotton river plot', 'high', 'decision', 'cotton'), f(3, 'Old orchard', 'nodata', 'abstain', 'mango'), f(4, 'New plot', 'nodata', 'pending')];

describe('My Fields list (FIELDS-01)', () => {
  it('shows every field: no cap on the number', () => {
    const many = Array.from({ length: 40 }, (_, i) => f(i + 1, `Plot ${i + 1}`, 'none', 'decision'));
    expect(filterFields(many, { query: '', crop: 'all', risk: 'all', sort: 'name', locale: 'en' })).toHaveLength(40);
  });
  it('filters by crop, status and text, and sorts by risk or newest', () => {
    expect(filterFields(FIELDS, { query: '', crop: 'all', risk: 'all', sort: 'risk', locale: 'en' })[0]!.id).toBe(2);
    expect(filterFields(FIELDS, { query: '', crop: 'all', risk: 'all', sort: 'newest', locale: 'en' }).map((x) => x.id)).toEqual([4, 3, 2, 1]);
    expect(filterFields(FIELDS, { query: '', crop: 'cotton', risk: 'all', sort: 'name', locale: 'en' }).map((x) => x.id)).toEqual([2]);
    expect(filterFields(FIELDS, { query: '', crop: 'all', risk: 'atRisk', sort: 'name', locale: 'en' }).map((x) => x.id)).toEqual([2]);
    expect(filterFields(FIELDS, { query: '', crop: 'all', risk: 'noRisk', sort: 'name', locale: 'en' }).map((x) => x.id)).toEqual([1]);
    expect(filterFields(FIELDS, { query: '', crop: 'all', risk: 'attention', sort: 'name', locale: 'en' }).map((x) => x.id).sort()).toEqual([3, 4]);
    expect(filterFields(FIELDS, { query: 'niphad', crop: 'all', risk: 'all', sort: 'name', locale: 'en' })).toHaveLength(4);
    expect(filterFields(FIELDS, { query: 'orchard', crop: 'all', risk: 'all', sort: 'name', locale: 'en' }).map((x) => x.id)).toEqual([3]);
  });
});

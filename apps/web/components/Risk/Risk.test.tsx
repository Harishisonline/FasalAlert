import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Abstention, Decision } from '@fasalalert/shared/api';
import { ctx, renderWithI18n } from '@/test/utils';
import { AbstainNotice } from './AbstainNotice';
import { DecisionCard } from './DecisionCard';
import { ProbabilityMeter } from './ProbabilityMeter';
import { RiskBadge } from './RiskBadge';
import { SourceLine } from './SourceLine';

const c = ctx('en');
const field = { id: 7, name: 'Test field', crop: 'mango' as const, stageLabel: 'Flowering' };
const fixture: Decision = {
  field_id: 7, decision_date: '2026-01-17', headline: 'Frost risk HIGH', action_text: 'Irrigate the basin before 21:30 tonight. Wet soil holds the heat.',
  action_by: '2026-01-17T21:30:00+05:30', confidence: 0.82, abstain_reason: null,
  risks: [{ kind: 'frost', level: 'high', probability: 0.82, tmin_c: 3.2, band_low_c: 2.8, band_high_c: 3.6, threshold_c: 4, window_start: '2026-01-18T05:00:00+05:30', window_end: '2026-01-18T07:00:00+05:30', lead_hours: 13, model_version: 'frost-fixture', evidence: { forecast_source: 'fixture-forecast', forecast_fetched_at: '2026-01-17T15:30:00+05:30' } }],
  market: null, transport: null, recommendation: null,
  advisory: { text: 'Fixture advisory text.', source: 'Fixture institute bulletin', source_url: 'https://example.org/advisory', institution: 'Fixture institute', year: 2019, verified: true, similarity: 0.8 },
  sources: [], model_versions: { frost: 'frost-fixture' },
};

describe('RiskBadge', () => {
  it('says the level in words with a hidden prefix, not colour alone', () => {
    renderWithI18n(<RiskBadge level="high" kind="frost" t={c.t} />);
    const badge = screen.getByText('High').closest('span[data-level]')!;
    expect(badge.getAttribute('data-level')).toBe('high');
    expect(badge.textContent).toContain('Risk:');
    expect(badge.textContent).toContain('Frost');
  });
  it('adds the IMD action word only at lg', () => {
    const { rerender } = renderWithI18n(<RiskBadge level="medium" size="md" showAction t={c.t} />);
    expect(screen.queryByText('Be prepared')).toBeNull();
    rerender(<RiskBadge level="medium" size="lg" showAction t={c.t} />);
    expect(screen.getByText('Be prepared')).toBeTruthy();
  });
  it('renders no station data with its own label', () => {
    renderWithI18n(<RiskBadge level="nodata" t={c.t} />);
    expect(screen.getByText('No station data')).toBeTruthy();
  });
});

describe('ProbabilityMeter', () => {
  it('fills round(p x 10) cells and names the IMD term and natural frequency', () => {
    renderWithI18n(<ProbabilityMeter label="Chance of frost damage" value={0.82} level="high" t={c.t} locale="en" />);
    const img = screen.getByRole('img');
    expect(img.getAttribute('aria-label')).toBe('Chance of frost damage: 82%, about 8 in 10, Most likely.');
    expect(img.querySelectorAll('[data-filled]').length).toBe(8);
  });
  it('draws no band unless an interval is supplied (Q26)', () => {
    const { container, rerender } = renderWithI18n(<ProbabilityMeter label="x" value={0.5} level="medium" t={c.t} locale="en" />);
    expect(container.querySelector('[style*="width"]')).toBeNull();
    rerender(<ProbabilityMeter label="x" value={0.5} level="medium" interval={{ low: 0.4, high: 0.6 }} t={c.t} locale="en" />);
    expect(container.querySelector('[style*="width"]')).not.toBeNull();
  });
  it('says as likely as not near 50 percent and has an unavailable state', () => {
    const { rerender } = renderWithI18n(<ProbabilityMeter label="x" value={0.5} level="medium" t={c.t} locale="en" />);
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('as likely as not');
    rerender(<ProbabilityMeter label="x" value={null} level="medium" t={c.t} locale="en" />);
    expect(screen.getByText('Chance unavailable')).toBeTruthy();
  });
});

describe('SourceLine', () => {
  it('shows source, time and a safe external link', () => {
    renderWithI18n(<SourceLine sources={[{ label: 'Fixture forecast', at: '2026-01-17T15:04:00+05:30', kind: 'forecast', url: 'https://example.org/f' }]} t={c.t} locale="en" now={c.now} />);
    expect(screen.getByText('Forecast: Fixture forecast · issued 15:04')).toBeTruthy();
    const link = screen.getByRole('link');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(link.getAttribute('aria-label')).toContain('Open source: Fixture forecast');
  });
  it('marks verified advisories and synthetic data', () => {
    renderWithI18n(<SourceLine sources={[{ label: 'Inst', kind: 'advisory', verified: true }, { label: 'seed', kind: 'synthetic' }]} t={c.t} locale="en" now={c.now} />);
    expect(screen.getByText(/Verified/)).toBeTruthy();
    expect(screen.getByText('Sample data')).toBeTruthy();
    expect(screen.getByText('Synthetic sample, not real prices')).toBeTruthy();
  });
  it('drops links that are not http(s)', () => {
    renderWithI18n(<SourceLine sources={[{ label: 'x', kind: 'model', url: 'javascript:alert(1)' }]} t={c.t} locale="en" now={c.now} />);
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('AbstainNotice', () => {
  it('uses amber status styling, the reason copy and a KVK call link', () => {
    renderWithI18n(<AbstainNotice reason="no_retrieval_above_threshold" kvk={{ name: 'KVK Fixture', phone: '+91-20-0000000' }} t={c.t} locale="en" now={c.now} />);
    const notice = screen.getByText('No verified advice for this').closest('[role="status"]') as HTMLElement;
    expect(notice).not.toBeNull();
    const call = within(notice).getByRole('link');
    expect(call.getAttribute('href')).toBe('tel:+91200000000');
    expect(call.getAttribute('aria-label')).toContain('KVK Fixture');
  });
  it('falls back to the Kisan Call Centre and states the stale time', () => {
    renderWithI18n(<AbstainNotice reason="data_stale" lastUpdatedAt="2026-01-17T14:20:00+05:30" t={c.t} locale="en" now={c.now} />);
    expect(screen.getByText('The last update was at 14:20. I will not advise on old data.')).toBeTruthy();
    expect(screen.getByRole('link').getAttribute('href')).toBe('tel:18001801551');
  });
});

describe('DecisionCard states (design.md 14.1)', () => {
  it('actionable: action sentence, act-by, chance in words, stretched link, Why this', () => {
    renderWithI18n(<DecisionCard variant="compact" field={field} decision={fixture} ctx={c} href="/en/field/7" pinned />);
    expect(screen.getByText('Irrigate the basin before 21:30 tonight.')).toBeTruthy();
    expect(screen.getByText('Act by 21:30 today')).toBeTruthy();
    expect(screen.getByText('Frost most likely tonight.')).toBeTruthy();
    // Home cards use words only: the percentage lives inside the collapsed "Why this?" region.
    expect(screen.getByText('82%').closest('[hidden]')).not.toBeNull();
    expect(screen.getByRole('link', { name: 'Test field' }).getAttribute('href')).toBe('/en/field/7');
    expect(screen.getByRole('button', { name: /Why this\?/ }).getAttribute('aria-expanded')).toBe('false');
    expect(screen.getByText('Today')).toBeTruthy();
    expect(screen.getByRole('article').getAttribute('data-pinned')).toBe('true');
  });
  it('full: headline, full action text, meter and verified advisory', () => {
    renderWithI18n(<DecisionCard variant="full" field={field} decision={fixture} ctx={c} />);
    expect(screen.getByText('Frost risk HIGH')).toBeTruthy();
    expect(screen.getByText(fixture.action_text)).toBeTruthy();
    expect(screen.getAllByRole('img')[0]!.getAttribute('aria-label')).toContain('82%');
    expect(screen.getByText('Fixture advisory text.')).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Test field' })).toBeNull();
  });
  it('no-risk', () => {
    renderWithI18n(<DecisionCard variant="compact" field={field} decision={{ ...fixture, risks: [] }} ctx={c} />);
    expect(screen.getByText('No weather risk for your mango today.')).toBeTruthy();
  });
  it('abstain: amber notice replaces the action', () => {
    const ab: Abstention = { field_id: 7, decision_date: '2026-01-17', headline: 'x', action_text: 'y', confidence: 0, abstain_reason: 'missing_field_input', risks: [], kvk: null };
    renderWithI18n(<DecisionCard variant="compact" field={field} decision={ab} ctx={c} />);
    expect(screen.getByText('I need one more detail')).toBeTruthy();
    expect(screen.getByRole('article').getAttribute('data-spine')).toBe('abstain');
  });
  it('stale: withholds the decision and shows the last update', () => {
    const stale = { ...fixture, risks: [{ ...fixture.risks[0]!, evidence: { forecast_fetched_at: '2026-01-17T08:00:00+05:30' } }] };
    renderWithI18n(<DecisionCard variant="compact" field={field} decision={stale} ctx={c} />);
    expect(screen.getByText('Risk unavailable. Last update 08:00.')).toBeTruthy();
    expect(screen.queryByText(/Irrigate/)).toBeNull();
  });
  it('raw: model outputs without a recommendation', () => {
    renderWithI18n(<DecisionCard variant="compact" field={field} decision={null} state="raw" rawRisks={fixture.risks} ctx={c} />);
    expect(screen.getByText(/Lowest forecast 3.2/)).toBeTruthy();
    expect(screen.queryByText(/Irrigate/)).toBeNull();
  });
  it('loading: a skeleton with a busy region', () => {
    const { container } = renderWithI18n(<DecisionCard variant="compact" field={field} decision={null} state="loading" ctx={c} />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });
  it('offline: always shows the last known label', () => {
    renderWithI18n(<DecisionCard variant="offline" field={field} decision={fixture} ctx={c} renderedAt="2026-01-17T06:10:00+05:30" />);
    expect(screen.getByText('Last known · 06:10')).toBeTruthy();
  });
  it('renders Marathi with Western digits', () => {
    const mr = ctx('mr');
    renderWithI18n(<DecisionCard variant="compact" field={field} decision={fixture} ctx={mr} />, 'mr');
    const article = screen.getByRole('article');
    expect(article.textContent).toContain('9:30');
    expect(article.textContent).not.toMatch(/[०-९]/);
  });
});
